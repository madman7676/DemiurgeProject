# DemiurgeProject

Minimal starter structure for a web-based text adventure game powered by a local LLM.

This repository intentionally focuses on project layout only. Gameplay logic, combat rules, action resolution, and content generation are not implemented yet.

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

