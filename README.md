# DemiurgeProject

Minimal web text adventure powered by a local Ollama LLM.

The backend is a tag-driven Lite loop:

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
    test_lite_pipeline.py
```

## GameState Shape

```text
scene:
  location: { id, name, icon }
  entities: [{ id, class, name, visibility, icon, last_seen_turn }]
  last_response
player:
  inventory: [{ id, name, icon }]
  currencies: [{ id, name, icon, amount }]
  skills: [{ id, name, icon }]
history:
  [{ user_input, narrator_response_clean, parsed_entities, applied_changes }]
debug:
  raw_llm_response
  parsed_tags
  applied_changes
  malformed_or_skipped_tags
```

## Tags

```text
[[entity:item|rusty_knife_01|rusty knife|available|K]]
[[entity:currency|gold|золото|available|G]]
[[entity:place|market_lane|ринковий провулок|available|P]]

[[player_change|add_item:rusty_knife_01]]
[[player_change|add_currency:gold:10]]
[[player_change|set_location:market_lane]]
```

Entity tags from the latest response replace the current visible scene entities.
Location changes only through `set_location`.

## Local Setup

```powershell
pip install -r backend/requirements.txt
python -m backend.main
npm install --prefix frontend
npm run dev --prefix frontend
```
