import { useEffect, useState } from "react";
import { fetchSession, sendPlayerMessage } from "../../api/gameApi";
import { ChatUI } from "../chat/ChatUI";
import { DebugPanel } from "../debug/DebugPanel";
import { InventoryPanel } from "../state_panels/InventoryPanel";
import { SkillsPanel } from "../state_panels/SkillsPanel";
import { StatsPanel } from "../state_panels/StatsPanel";
import { TimePanel } from "../state_panels/TimePanel";

// Layout keeps chat and player state views separate from game logic.
export function GameLayout() {
  const [visibleState, setVisibleState] = useState(null);
  const [messages, setMessages] = useState([]);
  const [decisionHistory, setDecisionHistory] = useState([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadSession() {
      try {
        const response = await fetchSession();
        setVisibleState(response.visible_state);
        setMessages(response.recent_messages || []);
        setDecisionHistory(response.decision_history || []);
      } catch (loadError) {
        setError(loadError.message);
      }
    }

    loadSession();
  }, []);

  async function handleSendMessage(message) {
    setError("");
    setIsSending(true);
    setMessages((currentMessages) => [
      ...currentMessages,
      { role: "player", text: message },
    ]);

    try {
      const response = await sendPlayerMessage(message);
      setVisibleState(response.visible_state);
      setMessages(response.recent_messages || []);
      setDecisionHistory(response.decision_history || []);
    } catch (sendError) {
      setError(sendError.message);
      setMessages((currentMessages) => currentMessages.slice(0, -1));
    } finally {
      setIsSending(false);
    }
  }

  return (
    <main className="game-layout">
      <section className="panel">
        <ChatUI
          messages={messages}
          onSendMessage={handleSendMessage}
          isSending={isSending}
          error={error}
        />
      </section>

      <aside className="state-panel-grid">
        <InventoryPanel inventory={visibleState?.player?.inventory || []} />
        <StatsPanel
          stats={visibleState?.player?.stats || []}
          location={visibleState?.player?.current_location}
        />
        <SkillsPanel skills={visibleState?.player?.skills || []} />
        <TimePanel
          currentTime={visibleState?.current_time}
          nearbyNpcs={visibleState?.nearby_npcs || []}
        />
        <DebugPanel decisionHistory={decisionHistory} />
      </aside>
    </main>
  );
}
