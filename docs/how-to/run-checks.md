# How to run the tests and style checks

These are what CI runs on every push. Run them before committing:

```powershell
uv run pytest                                   # 66 Python tests (app/tests)
uv run black --check app orchestration          # Python formatting
uv run ruff check .                             # Python lint
uv run sqlfluff lint dbt/models dbt/tests       # SQL style (Matt Mazur's guide)
uv run wx transform                             # dbt build: 19 models, 69 data tests, 2 unit tests
```

To fix formatting automatically:

```powershell
uv run black app orchestration
uv run ruff check . --fix
uv run sqlfluff fix dbt/models dbt/tests
```

Check `sqlfluff fix` on models with Jinja blocks (such as `fct_observations.sql`): it can't see SQL
inside a `{% if %}` that's off when it renders the model.

CI then runs the whole pipeline from a clean checkout against live NOAA data (`uv run wx run` with the
mock provider) and uploads the report and health report as artifacts.

The style rules and why: [code style](../explanation/code-style.md).
