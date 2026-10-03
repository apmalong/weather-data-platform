# How to reset and rebuild

Pick the smallest reset that does the job. Each asks first; add `--yes` to skip the question.

| To | Run | Cost |
|---|---|---|
| Rebuild every dbt model from raw (after changing model SQL) | `uv run wx transform --full-refresh` | About a minute; nothing lost |
| Regenerate all narratives (new prompt or model) | `uv run wx reset --narratives`, then `uv run wx narrate` | Gemini quota: about 7 requests |
| Start the warehouse over, keeping downloads | `uv run wx reset`, then `uv run wx run` | Loses run history, evaluations and NOAA's change history |
| Start completely over, like a fresh clone | `uv run wx reset --all`, then `uv run wx run` | Also re-downloads NOAA's files |

`wx reset` without `--narratives` removes evaluation history too (`ops.eval_runs`), which the report's
Evaluation tab shows. Re-running evaluations costs quota and gives slightly different text.

If a reset says the warehouse is in use, close `wx --explore`, a DuckDB client or Airflow first.

To experiment without touching your warehouse at all, point `WX_WAREHOUSE` at a copy instead
([CLI reference](../reference/cli.md#environment-variables)).
