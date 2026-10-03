# How to run the tests and style checks

These are what CI runs on every push. Run them before committing:

```bash
uv run pytest                                   # 68 Python tests (app/tests)
uv run black --check app orchestration          # Python formatting
uv run ruff check .                             # Python lint
uv run sqlfluff lint dbt/models dbt/tests       # SQL style (Matt Mazur's guide)
uv run wx transform                             # dbt build: 19 models, 69 data tests, 2 unit tests
```

To fix formatting automatically:

```bash
uv run black app orchestration
uv run ruff check . --fix
uv run sqlfluff fix dbt/models dbt/tests
```

Check `sqlfluff fix` on models with Jinja blocks (such as `fct_observations.sql`): it can't see SQL
inside a `{% if %}` that's off when it renders the model.

The docs build separately, as a website (`.github/workflows/docs.yml`). Preview it, or check it the way
CI does (it fails on a broken link or anchor):

```bash
uv run --group docs mkdocs serve             # http://127.0.0.1:8000, reloads as you edit
uv run --group docs mkdocs build --strict
```

CI then runs the whole pipeline from a clean checkout against live NOAA data (`uv run wx run` with the
mock provider) and uploads the report and health report as artifacts.

The style rules and why: [code style](../explanation/code-style.md).
