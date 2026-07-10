# DemiurgeProject

Minimal web text adventure powered by a local Ollama LLM.

The backend is a Hyperlite loop:

```text
User input
-> Narrator/GM LLM
-> parse [[...]] tags
-> update GameState
-> save bounded history
-> update UI
```

The old multi-agent runtime is removed.

## Backend Structure

```text
backend/
  main.py
  config.py
  api/
    app.py
    routes.py
  core/
    state.py
    tag_parser.py
  llm/
    client.py
    narrator.py
    narrator_prompt.txt
  tests/
    test_hyperlite_pipeline.py
```

## GameState Shape

```text
player:
  inventory: [{ id, name, icon, quantity }]
  resources: [{ id, name, icon, amount }]
  skills: [{ id, name, icon }]
history:
  [{ user_input, narrator_response_for_ui, narrator_response_clean, applied_changes }]
debug:
  raw_llm_response
  narrator_response_for_ui
  llm_diagnostics
  parsed_tags
  applied_changes
  malformed_or_skipped_tags
  warnings
```

## Tags

Only `player_change` tags are parsed. Narrative text is otherwise plain text.

```text
[[player_change|add_item|item_id|name|icon|quantity]]
[[player_change|remove_item|item_id|quantity]]
[[player_change|add_resource|resource_id|name|icon|amount]]
[[player_change|remove_resource|resource_id|amount]]
[[player_change|add_skill|skill_id|name|icon]]
[[player_change|remove_skill|skill_id]]
```

Item stacks merge only by `item_id`. Resource stacks merge only by `resource_id`.
Remove operations clamp at zero and record debug warnings when the requested
quantity or amount is greater than the current stack.

## Local Setup

```powershell
pip install -r backend/requirements.txt
python -m backend.main
npm install --prefix frontend
npm run dev --prefix frontend
```
