# DemiurgeProject

Minimal starter structure for a web-based text adventure game powered by a local LLM.

This repository now includes a minimal exploration-mode gameplay loop for one player message. Combat rules, advanced persistence, authentication, and wider gameplay systems are still intentionally not implemented.

## Structure

```text
DemiurgeProject/
  frontend/
    index.html
    package.json
    vite.config.js
    src/
      main.jsx
      App.jsx
      styles.css
      components/
        chat/
          ChatUI.jsx
        layout/
          GameLayout.jsx
        state_panels/
          InventoryPanel.jsx
          StatsPanel.jsx
          SkillsPanel.jsx
          TimePanel.jsx
  backend/
    main.py
    api/
      __init__.py
      app.py
      routes.py
    core/
      game_state/
        __init__.py
        models.py
      world_rules/
        __init__.py
        schema.py
        data/
          world.template.json
      player_state/
        __init__.py
        models.py
      npc_state/
        __init__.py
        models.py
    modules/
      router/
        __init__.py
        prompts/
          README.md
        services/
          router_service.py
        schemas/
          router_contracts.py
      narrator/
        __init__.py
        prompts/
          README.md
        services/
          narrator_service.py
        schemas/
          narrator_contracts.py
      action_evaluation/
        __init__.py
        prompts/
          README.md
        services/
          action_evaluation_service.py
        schemas/
          action_evaluation_contracts.py
      world_evolution/
        __init__.py
        prompts/
          README.md
        services/
          world_evolution_service.py
        schemas/
          world_evolution_contracts.py
      feature_modules/
        __init__.py
        prompts/
          README.md
        services/
          feature_registry.py
        schemas/
          feature_contracts.py
        plugins/
          README.md
      llm_connector/
        __init__.py
        prompts/
          README.md
        services/
          llm_client.py
        schemas/
          llm_contracts.py
```

## Backend Modules

`router`
: Decides which backend modules should process a player action and in what order.

`narrator`
: Converts structured backend results into player-facing narrative text.

`action_evaluation`
: Evaluates whether an action is possible and how likely it is to succeed.

`world_evolution`
: Advances the world state when time thresholds or scheduled changes are reached.

`feature_modules`
: Hosts pluggable gameplay systems such as gacha, reputation, or future combat-related modules.

`llm_connector`
: Centralizes communication with the local LLM so other modules do not duplicate connector logic.

## Core Data Modules

`game_state`
: Stores the overall session state and shared turn-level context.

`world_rules`
: Holds structured world definitions and JSON-based rule data.

`player_state`
: Defines player-facing state such as stats, inventory, and skills.

`npc_state`
: Defines NPC identity, goals, and relationship-oriented state.

## Frontend Areas

`chat UI`
: The primary interaction surface for player input and narrative output.

`state panels`
: Dedicated panels for inventory, stats, skills, and in-game time.

## Extension Notes

- `backend/modules/feature_modules/plugins/` is the intended extension point for future systems.
- Combat is intentionally not implemented, but this structure leaves room for a future combat plugin without flattening the backend.
- Prompt files are kept separate from service logic and schemas so LLM-driven modules remain easy to navigate as they grow.

## Local Setup

### Backend

Create and activate a virtual environment from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install backend dependencies:

```powershell
pip install -r backend/requirements.txt
```

Optional Ollama-related environment overrides are documented in [backend/.env.example](D:/Else/Code/DemiurgeProject/backend/.env.example). The backend already has sensible defaults in [backend/config.py](D:/Else/Code/DemiurgeProject/backend/config.py), so you can start without setting anything if your local Ollama server uses the default URL and model.

Start the backend in development mode:

```powershell
python -m backend.main
```

Or from the repository root:

```powershell
npm run back
```

### Frontend

Install frontend dependencies:

```powershell
npm install --prefix frontend
```

Start the frontend in development mode:

```powershell
npm run dev --prefix frontend
```

Or from the repository root:

```powershell
npm run front
```

### Quick Start

From the repository root, use two terminals:

```powershell
npm run back
npm run front
```

If you want a quick reminder from the root, run:

```powershell
npm run dev:help
```

## Minimal Exploration Flow

1. Start the backend.
2. Start the frontend.
3. Enter a message in the chat UI.
4. The backend processes the message through:
   - `router`
   - `action_evaluation`
   - `time_cost` estimation
   - consequence layer
   - state update layer
   - world evolution hook
   - `narrator`
5. The frontend receives:
   - the structured action result
   - a narrative response
   - updated visible state including canonical game time

## Example End-To-End Message

Player input:
`"I ask Tomas what changed at the station."`

Pipeline summary:
- `router` classifies the action as `talk`
- `action_evaluation` interprets the intent and estimates feasibility
- time cost is computed in minutes and applied to canonical game time
- nearby NPC reactions are generated for local NPCs only
- `narrator` turns the structured result into player-facing text

Ollama configuration defaults live in [backend/config.py](D:/Else/Code/DemiurgeProject/backend/config.py) and target:
- `MODEL="gemma3:12b"`
- `LLM_URL="http://localhost:11434/api/generate"`
