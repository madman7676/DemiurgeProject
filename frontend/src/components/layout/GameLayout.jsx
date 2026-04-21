import { ChatUI } from "../chat/ChatUI";
import { InventoryPanel } from "../state_panels/InventoryPanel";
import { SkillsPanel } from "../state_panels/SkillsPanel";
import { StatsPanel } from "../state_panels/StatsPanel";
import { TimePanel } from "../state_panels/TimePanel";

// Layout keeps chat and player state views separate from game logic.
export function GameLayout() {
  return (
    <main className="game-layout">
      <section className="panel">
        <ChatUI />
      </section>

      <aside className="state-panel-grid">
        <InventoryPanel />
        <StatsPanel />
        <SkillsPanel />
        <TimePanel />
      </aside>
    </main>
  );
}

