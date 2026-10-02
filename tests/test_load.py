import gzip

from wx.noaa import load

STATION = "CAN06158731"


def write(tmp_path, name, rows):
    path = tmp_path / name
    path.write_bytes(gzip.compress(("\n".join(rows) + "\n").encode()))
    return path


def test_first_load_inserts_everything(conn, tmp_path):
    path = write(tmp_path, "v1.csv.gz", [f"{STATION},20260101,TMAX,-52,,,C,", f"{STATION},20260101,PRCP,0,T,,C,"])
    assert load.load_observations(conn, "r1", STATION, path, "sha1") == {
        "read": 2, "rejected": 0, "inserted": 2, "updated": 0, "deleted": 0}


def test_revisions_backfills_and_removals_are_detected(conn, tmp_path):
    v1 = [f"{STATION},20260101,TMAX,-52,,,C,", f"{STATION},20260101,TMIN,-120,,,C,",
          f"{STATION},20260102,TMAX,-30,,,C,"]
    load.load_observations(conn, "r1", STATION, write(tmp_path, "v1.csv.gz", v1), "sha1")
    v2 = [f"{STATION},20260101,TMAX,-55,,,C,",       # value revised
          f"{STATION},20260102,TMAX,-30,,I,C,",      # same value, newly failed a QC check
          f"{STATION},20251215,TMAX,12,,,C,"]        # backfilled earlier date; TMIN 20260101 removed
    counts = load.load_observations(conn, "r2", STATION, write(tmp_path, "v2.csv.gz", v2), "sha2")
    assert counts == {"read": 3, "rejected": 0, "inserted": 1, "updated": 2, "deleted": 1}
    changes = conn.execute("""select obs_date, element, change, old_value, new_value, old_flags, new_flags
                              from raw.observation_changes where run_id = 'r2' order by 1, 2""").fetchall()
    assert changes == [
        ("20251215", "TMAX", "insert", None, "12", None, "||C|"),
        ("20260101", "TMAX", "update", "-52", "-55", "||C|", "||C|"),
        ("20260101", "TMIN", "delete", "-120", None, "||C|", None),
        ("20260102", "TMAX", "update", "-30", "-30", "||C|", "|I|C|"),
    ]
    current = conn.execute("select obs_date, element, value, qflag from raw.observations order by 1, 2").fetchall()
    assert current == [("20251215", "TMAX", "12", None), ("20260101", "TMAX", "-55", None),
                       ("20260102", "TMAX", "-30", "I")]


def test_unchanged_reload_changes_nothing(conn, tmp_path):
    rows = [f"{STATION},20260101,TMAX,-52,,,C,"]
    load.load_observations(conn, "r1", STATION, write(tmp_path, "a.csv.gz", rows), "sha1")
    counts = load.load_observations(conn, "r2", STATION, write(tmp_path, "b.csv.gz", rows), "sha1")
    assert (counts["inserted"], counts["updated"], counts["deleted"]) == (0, 0, 0)


def test_foreign_and_duplicate_rows_fail_checks(conn, tmp_path):
    rows = [f"{STATION},20260101,TMAX,-52,,,C,", f"{STATION},20260101,TMAX,-51,,,C,",
            "CAN07025251,20260101,TMAX,-40,,,C,"]
    counts = load.load_observations(conn, "r1", STATION, write(tmp_path, "v.csv.gz", rows), "sha1")
    assert counts["inserted"] == 1
    failed = dict(conn.execute("select check_name, observed from ops.checks where not passed").fetchall())
    assert failed == {"rows_belong_to_station": "1", "unique_station_date_element": "1"}


def test_other_stations_are_untouched(conn, tmp_path):
    montreal = write(tmp_path, "m.csv.gz", ["CAN07025251,20260101,TMAX,-40,,,C,"])
    toronto = write(tmp_path, "t.csv.gz", [f"{STATION},20260101,TMAX,-52,,,C,"])
    load.load_observations(conn, "r1", "CAN07025251", montreal, "sha1")
    load.load_observations(conn, "r2", STATION, toronto, "sha2")
    assert conn.execute("select count(*) from raw.observations").fetchone()[0] == 2
    assert conn.execute("select count(*) from raw.observation_changes where change = 'delete'").fetchone()[0] == 0
