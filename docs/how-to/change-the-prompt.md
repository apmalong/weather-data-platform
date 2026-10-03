# How to change the narrative prompt

Prompts are versioned files in `llm/prompts/`. Change one by adding a version, evaluating it, then
switching to it.

1. Copy the current prompt to a new version and edit the copy:

   ```powershell
   copy llm\prompts\narrative_v3.md llm\prompts\narrative_v4.md
   ```

2. Evaluate it on the 11 hard cases in `llm/evals/cases.yml` (needs `GEMINI_API_KEY`; about two
   requests):

   ```powershell
   uv run wx eval --prompt llm/prompts/narrative_v4.md
   ```

   It prints which cases pass, the warnings and style issues. Compare it with v3 in the report's
   Evaluation tab (`uv run wx report`), case by case.

3. If it's better, make it current in `config/pipeline.yml`:

   ```yaml
   narratives:
     prompt: llm/prompts/narrative_v4.md
   ```

4. Regenerate:

   ```powershell
   uv run wx narrate
   ```

   The new prompt has a new `prompt_version`, so every station-day in the last `narratives.days` is
   regenerated: about 7 requests for 5 cities × 14 days. Narratives from the old version stay in
   `narratives.daily` as history.

To change the model instead, edit `narratives.models` and run `wx eval` first, the same way. Keep the
pinned version names; `-latest` aliases can change behaviour without notice.

What each validation check and eval case tests: [narrative stage reference](../reference/llm/narratives.md).
