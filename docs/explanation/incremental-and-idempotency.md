# Incremental loading and idempotency

## Why not load "dates after the last load"?

NOAA revises the past: it corrects values, adds quality flags later, backfills gaps, and sometimes
reloads whole histories (v3.35 reloaded 17 months of Canadian data at once). It publishes each
station's entire history as one file and offers no "changes since" feed. Loading only new dates would
silently miss all of that.

## Read in full, write only what changed

- **Files:** every download is fingerprinted (SHA-256). An unchanged file isn't read again. NOAA's
  `Last-Modified` header can't be trusted for this: on 2 October its files showed a new time with
  byte-for-byte identical contents.
- **Rows:** a changed file is read in full and compared row by row, by a hash of value and flags, with
  what's stored. Only inserts, updates and deletes are applied, and each is logged in
  `raw.observation_changes`. That log is what tells you NOAA changed something, and when.
- **Facts:** `fct_observations` is incremental and reprocesses only rows in the change log, rows of an
  element whose rule changed in config (tracked by a `policy_hash`), and stations or elements newly in
  scope. TMAX and TMIN are assessed as a pair, so a change to one reprocesses the other. Removed rows
  become tombstones (`removed_at_source`) rather than disappearing.

Verified on a copy of the warehouse: four simulated NOAA changes rewrote exactly four rows; changing
TMAX's upper bound rewrote only TMAX's 33,080 rows; an incremental build after a revision and a
removal matched a full rebuild of the same data exactly.

## All or nothing

Writes that span several statements run in one transaction: a station file's merge, a reference file
with its load record, the run-scope tables, a narrative with its validation. Without that, a merge
interrupted between its delete and its insert would lose rows and log changes that never happened.
A test interrupts a merge at its last step: with the transaction nothing changes; without it, raw went
from 2 rows to 1 and the change log gained 2 entries for changes that never happened.

## Running again changes nothing

| Command | Running it again with the same inputs |
|---|---|
| `wx ingest` | Same data: unchanged files are skipped; a forced reload of the same file changes nothing |
| `wx transform` | Same data: nothing to reprocess; a full rebuild equals an incremental one |
| `wx narrate` | Same narratives: cached by their exact facts, model and prompt version; no model calls |
| `wx report`, `wx health` | Same contents, a new timestamp |

What does change: the run logs grow (by design); the window moves with the date; and if the narrative
cache is cleared, Gemini writes different text for the same facts. An interrupted run leaves every
table as it was before the step that failed, and the next run carries on.

Related: [ingest reference](../reference/app/ingest.md), [reset and rebuild](../how-to/reset-and-rebuild.md).
