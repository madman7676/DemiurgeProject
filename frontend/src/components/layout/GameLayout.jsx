import { useEffect, useState } from "react";
import { fetchSession, sendPlayerMessageStream } from "../../api/gameApi";
import { ChatUI } from "../chat/ChatUI";
import { DebugPanel } from "../debug/DebugPanel";
import { InventoryPanel } from "../state_panels/InventoryPanel";
import { LocalCuriositiesPanel } from "../state_panels/LocalCuriositiesPanel";
import { SkillsPanel } from "../state_panels/SkillsPanel";
import { StatsPanel } from "../state_panels/StatsPanel";
import { TimePanel } from "../state_panels/TimePanel";

// Layout keeps chat and player state views separate from game logic.
export function GameLayout() {
  const [visibleState, setVisibleState] = useState(null);
  const [messages, setMessages] = useState([]);
  const [decisionHistory, setDecisionHistory] = useState([]);
  const [isSending, setIsSending] = useState(false);
  const [currentPipelineStep, setCurrentPipelineStep] = useState("");
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
    setCurrentPipelineStep("narrator");
    setMessages((currentMessages) => [
      ...currentMessages,
      { role: "player", text: message },
    ]);

    try {
      setMessages((currentMessages) => [
        ...currentMessages,
        { role: "assistant", text: "" },
      ]);
      const response = await sendPlayerMessageStream(message, {
        onStatus: (step) => {
          setCurrentPipelineStep(step);
        },
        onPipelineUpdate: (update) => {
          if (update.step === "narrator" && update.narrative_text) {
            setMessages((currentMessages) =>
              patchLastAssistantMessage(currentMessages, update.narrative_text),
            );
          }
          if (update.decision_events) {
            setDecisionHistory((currentHistory) =>
              upsertDecisionCycle(currentHistory, {
                turn: update.turn,
                raw_player_input: message,
                events: update.decision_events,
              }),
            );
          } else if (update.event) {
            setDecisionHistory((currentHistory) =>
              appendDecisionEvent(currentHistory, {
                turn: update.turn,
                raw_player_input: message,
                event: update.event,
              }),
            );
          }
        },
        onNarrationDelta: (chunk) => {
          setCurrentPipelineStep("");
          setMessages((currentMessages) => {
            const updatedMessages = [...currentMessages];
            const lastIndex = updatedMessages.length - 1;
            if (lastIndex >= 0 && updatedMessages[lastIndex].role === "assistant") {
              updatedMessages[lastIndex] = {
                ...updatedMessages[lastIndex],
                text: `${updatedMessages[lastIndex].text}${chunk}`,
                change_summary: [],
              };
            }
            return updatedMessages;
          });
        },
      });
      setVisibleState(response.visible_state);
      setMessages(response.recent_messages || []);
      setDecisionHistory(response.decision_history || []);
    } catch (sendError) {
      setError(sendError.message);
      setMessages((currentMessages) => currentMessages.slice(0, -2));
    } finally {
      setIsSending(false);
      setCurrentPipelineStep("");
    }
  }

  return (
    <main className="game-layout">
      <section className="panel">
        <ChatUI
          messages={messages}
          onSendMessage={handleSendMessage}
          isSending={isSending}
          currentPipelineStep={currentPipelineStep}
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
        <LocalCuriositiesPanel scenePool={visibleState?.scene_pool || []} />
        <DebugPanel decisionHistory={decisionHistory} />
      </aside>
    </main>
  );
}

function patchLastAssistantMessage(messages, text) {
  const updatedMessages = [...messages];
  for (let index = updatedMessages.length - 1; index >= 0; index -= 1) {
    if (updatedMessages[index].role === "assistant") {
      updatedMessages[index] = {
        ...updatedMessages[index],
        text,
      };
      break;
    }
  }
  return updatedMessages;
}

function upsertDecisionCycle(history, cycle) {
  if (!cycle.turn) {
    return history;
  }
  const existingIndex = history.findIndex((item) => item.turn === cycle.turn);
  if (existingIndex < 0) {
    return [...history, cycle];
  }
  return history.map((item, index) => (index === existingIndex ? cycle : item));
}

function appendDecisionEvent(history, { turn, raw_player_input, event }) {
  if (!turn || !event) {
    return history;
  }
  const existingIndex = history.findIndex((item) => item.turn === turn);
  if (existingIndex < 0) {
    return [...history, { turn, raw_player_input, events: [event] }];
  }
  return history.map((cycle, index) => {
    if (index !== existingIndex) {
      return cycle;
    }
    return {
      ...cycle,
      events: [...cycle.events, event],
    };
  });
}
