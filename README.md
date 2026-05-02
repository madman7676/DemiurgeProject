# DemiurgeProject

Minimal web text adventure powered by a local Ollama LLM.

The backend is now a Lite exploration loop:

```text
User input
-> Narrator LLM
-> parse [[...]] tags
-> apply player state changes in code
-> update scene memory in code
-> return narrative and visible state
```

The old multi-agent systems are removed from runtime.

## Structure

```text
DemiurgeProject/
  frontend/
    src/
      api/
      components/
      utils/
  backend/
    main.py
    config.py
    api/
      app.py
      routes.py
    core/
      state.py
      scene_memory.py
      tag_parser.py
    llm/
      client.py
      narrator.py
    tests/
      test_lite_pipeline.py
```

## Backend Pieces

`backend/llm/client.py`
: Small Ollama client.

`backend/llm/narrator.py`
: The single Narrator/GM prompt and call site.

`backend/core/tag_parser.py`
: Extracts `[[...]]` blocks and recognizes `entity:*` and `player_change` tags.

`backend/core/scene_memory.py`
: Stores tagged scene entities in `scene_pool`.

`backend/core/state.py`
: Holds in-memory session state, player inventory, gold, skills, visible state, and chat history.

`backend/api/routes.py`
: Runs the direct Lite turn and applies parsed tag changes.

## Supported Tags

Examples:

```text
[[entity:item|rusty_knife_01|rusty knife|available]]
[[entity:npc|market_guard_01|market guard|available]]
[[player_change|add_item:rusty_knife_01]]
[[player_change|add_gold:10]]
```

The backend intentionally does not validate whether tags are correct. It applies them directly.

## Local Setup

Install backend dependencies:

```powershell
pip install -r backend/requirements.txt
```

Start the backend:

```powershell
python -m backend.main
```

Install and start the frontend:

```powershell
npm install --prefix frontend
npm run dev --prefix frontend
```

Ollama defaults live in `backend/config.py`:

- `MODEL="gemma3:12b"`
- `LLM_URL="http://localhost:11434/api/generate"`
