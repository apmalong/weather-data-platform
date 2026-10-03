"""Load NOAA files into the warehouse's raw schema, as published (ELT: typing happens in dbt).

- Reference files (stations, inventory, countries, states) are snapshots: a changed file replaces
  its table. Fixed-width columns are cut at the readme's positions (formats.FIXED_WIDTH).
- The readme is stored whole and its element catalog is parsed into raw.element_catalog.
- Observations are merged per station with row-level change detection. Each row is fingerprinted;
  new, changed and vanished rows are applied and logged to raw.observation_changes. NOAA revises
  past values and backfills gaps (v3.35 reloaded 17 months of Canadian data at once), so loading
  "dates after the last one" would silently miss changes.
- Rows that can't be loaded are kept, not just counted: lines the CSV reader rejects, rows for
  another station and duplicates go to raw.rejected_rows with the reason.
"""

import time
from pathlib import Path

from wx.ingest.noaa import formats
from wx.observe import ops

RAW_DDL = """
create schema if not exists raw;
create table if not exists raw.observations (
    station_id varchar, obs_date varchar, element varchar, value varchar, mflag varchar,
    qflag varchar, sflag varchar, obs_time varchar,
    _row_hash varchar, _source_file varchar, _first_loaded_at timestamp, _last_changed_at timestamp,
    _run_id varchar,
    primary key (station_id, obs_date, element));
create table if not exists raw.observation_changes (
    run_id varchar, station_id varchar, obs_date varchar, element varchar, change varchar,
    old_value varchar, new_value varchar, old_flags varchar, new_flags varchar, changed_at timestamp);
create table if not exists raw.rejected_rows (
    run_id varchar, source_file varchar, station_id varchar, line_number bigint, line varchar,
    reason varchar, rejected_at timestamp);
"""

_FLAGS = "concat_ws('|', coalesce(mflag, ''), coalesce(qflag, ''), coalesce(sflag, ''), coalesce(obs_time, ''))"


def ensure_schema(conn) -> None:
    conn.execute(RAW_DDL)


def _record(conn, run_id, dataset, path, sha256, read, rejected, inserted=0, updated=0, deleted=0, started=0.0):
    conn.execute(
        "insert into ops.loads values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            run_id,
            dataset,
            str(path),
            sha256,
            read,
            rejected,
            inserted,
            updated,
            deleted,
            time.time() - started,
            ops.now(),
        ],
    )


@ops.atomic
def load_fixed_width(conn, run_id: str, dataset: str, path: Path, sha256: str) -> int:
    """Replace raw.<dataset> with the file's rows, cut at the readme's column positions."""
    started = time.time()
    columns = formats.FIXED_WIDTH[dataset]
    cuts = ", ".join(f"nullif(trim(substr(line, {c.start}, {c.end - c.start + 1})), '') as {c.name}" for c in columns)
    key = columns[0]
    conn.execute(
        """
        create or replace temp table _lines as
        select line from (select unnest(string_split(replace(content, chr(13), ''), chr(10))) as line
                          from read_text(?)) where trim(line) <> ''""",
        [str(path)],
    )
    conn.execute(
        f"""
        create or replace table raw.{dataset} as
        select {cuts}, ? as _source_file, ? as _sha256, ? as _loaded_at, ? as _run_id
        from _lines where length(trim(substr(line, {key.start}, {key.end - key.start + 1}))) > 0""",
        [path.name, sha256, ops.now(), run_id],
    )
    read = conn.execute("select count(*) from _lines").fetchone()[0]
    loaded = conn.execute(f"select count(*) from raw.{dataset}").fetchone()[0]
    _record(conn, run_id, dataset, path, sha256, read, read - loaded, inserted=loaded, started=started)
    return loaded


@ops.atomic
def load_text(conn, run_id: str, name: str, path: Path, sha256: str) -> None:
    """Keep a whole text file (readme, status log) in raw.documents."""
    conn.execute(
        "create table if not exists raw.documents (name varchar, content varchar, _sha256 varchar, "
        "_loaded_at timestamp, _run_id varchar)"
    )
    conn.execute("delete from raw.documents where name = ?", [name])
    conn.execute(
        "insert into raw.documents values (?, ?, ?, ?, ?)",
        [name, path.read_text(encoding="utf-8", errors="replace"), sha256, ops.now(), run_id],
    )
    _record(conn, run_id, name, path, sha256, 1, 0, inserted=1)


@ops.atomic
def load_element_catalog(conn, run_id: str, readme: str) -> int:
    catalog = formats.element_catalog(readme)
    conn.execute(
        "create or replace table raw.element_catalog (code varchar, description varchar, unit varchar, "
        "scale double, core boolean, _loaded_at timestamp, _run_id varchar)"
    )
    conn.executemany(
        "insert into raw.element_catalog values (?, ?, ?, ?, ?, ?, ?)",
        [[e.code, e.description, e.unit, e.scale, e.core, ops.now(), run_id] for e in catalog],
    )
    return len(catalog)


@ops.atomic
def load_observations(conn, run_id: str, station_id: str, path: Path, sha256: str) -> dict:
    """Merge one station's file into raw.observations; returns counts of read, rejected and changes."""
    started = time.time()
    columns = ", ".join(f"'{name}': 'VARCHAR'" for name in formats.OBSERVATION_COLUMNS)
    # DuckDB keeps the rejects tables for the whole connection, so clear them: otherwise one station's
    # rejected lines would be counted again for every station loaded after it.
    conn.execute("drop table if exists _rejects; drop table if exists _rejects_scan")
    conn.execute(
        f"""
        create or replace temp table _incoming_all as
        select * from read_csv(?, header = false, columns = {{{columns}}}, ignore_errors = true,
                               store_rejects = true, rejects_table = '_rejects', rejects_scan = '_rejects_scan')
        """,
        [str(path)],
    )
    now = ops.now()
    # The reader logs one error per missing column, so a short line has several entries: keep one per
    # line, with the first error as the reason.
    conn.execute(
        """
        insert into raw.rejected_rows
        select ?, ?, ?, line, csv_line, arg_min(error_type || ': ' || error_message, coalesce(column_idx, 0)), ?
        from _rejects group by line, csv_line""",
        [run_id, path.name, station_id, now],
    )
    rejected = conn.execute("select count(distinct line) from _rejects").fetchone()[0]
    # A file's rows must belong to its station, and a station/date/element must appear once.
    conn.execute(
        f"""
        create or replace temp table _incoming as
        select *, md5(concat_ws('|', coalesce(value, ''), {_FLAGS})) as _row_hash
        from _incoming_all where station_id = ?
        qualify row_number() over (partition by obs_date, element order by value) = 1""",
        [station_id],
    )
    read = conn.execute("select count(*) from _incoming_all").fetchone()[0]
    kept = conn.execute("select count(*) from _incoming").fetchone()[0]
    foreign = conn.execute(
        "select count(*) from _incoming_all where station_id is distinct from ?", [station_id]
    ).fetchone()[0]
    duplicates = read - foreign - kept
    line = "concat_ws(',', " + ", ".join(f"coalesce({c}, '')" for c in formats.OBSERVATION_COLUMNS) + ")"
    conn.execute(
        f"""
        insert into raw.rejected_rows
        select ?, ?, ?, null, {line}, 'row for another station (' || coalesce(station_id, 'none') || ')', ?
        from _incoming_all where station_id is distinct from ?""",
        [run_id, path.name, station_id, now, station_id],
    )
    conn.execute(
        f"""
        insert into raw.rejected_rows
        select ?, ?, ?, null, {line}, 'duplicate of ' || obs_date || ' ' || element || ' (another row was kept)', ?
        from _incoming_all where station_id = ?
        qualify row_number() over (partition by obs_date, element order by value) > 1""",
        [run_id, path.name, station_id, now, station_id],
    )
    ops.check(conn, run_id, "load", "rows_belong_to_station", station_id, foreign == 0, foreign, 0)
    ops.check(conn, run_id, "load", "unique_station_date_element", station_id, duplicates == 0, duplicates, 0)
    ops.check(conn, run_id, "load", "parseable_rows", station_id, rejected == 0, rejected, 0, severity="warn")

    conn.execute(
        """
        create or replace temp table _changes as
        select coalesce(i.station_id, o.station_id) as station_id, coalesce(i.obs_date, o.obs_date) as obs_date,
               coalesce(i.element, o.element) as element,
               case when o.station_id is null then 'insert' when i.station_id is null then 'delete' else 'update' end
                   as change,
               o.value as old_value, i.value as new_value,
               case when o.station_id is not null then concat_ws('|', coalesce(o.mflag, ''), coalesce(o.qflag, ''),
                   coalesce(o.sflag, ''), coalesce(o.obs_time, '')) end as old_flags,
               case when i.station_id is not null then concat_ws('|', coalesce(i.mflag, ''), coalesce(i.qflag, ''),
                   coalesce(i.sflag, ''), coalesce(i.obs_time, '')) end as new_flags
        from _incoming i
        full join (select * from raw.observations where station_id = ?) o
            on o.station_id = i.station_id and o.obs_date = i.obs_date and o.element = i.element
        where o._row_hash is distinct from i._row_hash""",
        [station_id],
    )
    conn.execute("insert into raw.observation_changes select ?, *, ? from _changes", [run_id, now])
    conn.execute("""delete from raw.observations o
                    where exists (select 1 from _changes c
                                  where c.station_id = o.station_id and c.obs_date = o.obs_date
                                    and c.element = o.element and c.change in ('update', 'delete'))""")
    conn.execute(
        """
        insert into raw.observations
        select i.station_id, i.obs_date, i.element, i.value, i.mflag, i.qflag, i.sflag, i.obs_time, i._row_hash,
               ?, coalesce(f.first_loaded, ?), ?, ?
        from _incoming i
        join _changes c on c.station_id = i.station_id and c.obs_date = i.obs_date and c.element = i.element
        left join (select station_id, obs_date, element, min(changed_at) as first_loaded
                   from raw.observation_changes where change = 'insert' group by all) f
               on f.station_id = i.station_id and f.obs_date = i.obs_date and f.element = i.element
        where c.change in ('insert', 'update')""",
        [path.name, now, now, run_id],
    )
    counts = dict(conn.execute("select change, count(*) from _changes group by 1").fetchall())
    result = {
        "read": read,
        "rejected": rejected,
        "inserted": counts.get("insert", 0),
        "updated": counts.get("update", 0),
        "deleted": counts.get("delete", 0),
    }
    _record(
        conn,
        run_id,
        "observations",
        path,
        sha256,
        read,
        rejected + foreign + duplicates,
        result["inserted"],
        result["updated"],
        result["deleted"],
        started,
    )
    return result
