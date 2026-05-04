import { useEffect, useState } from "react";
import { fetchSession, sendPlayerMessageStream } from "../../api/gameApi";
import { ChatUI } from "../chat/ChatUI";
import { DebugPanel } from "../debug/DebugPanel";
import { CurrenciesPanel } from "../state_panels/CurrenciesPanel";
import { HistoryPanel } from "../state_panels/HistoryPanel";
import { InventoryPanel } from "../state_panels/InventoryPanel";
import { LocalCuriositiesPanel } from "../state_panels/LocalCuriositiesPanel";
import { LocationPanel } from "../state_panels/LocationPanel";
import { SkillsPanel } from "../state_panels/SkillsPanel";

// Layout keeps chat and Lite state views separate from transport logic.
export function GameLayout() {
  const [visibleState, setVisibleState] = useState(null);
  const [messages, setMessages] = useState([]);
  const [history, setHistory] = useState([]);
  const [debug, setDebug] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const [currentPipelineStep, setCurrentPipelineStep] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadSession() {
      try {
        const response = await fetchSession();
        setVisibleState(response.visible_state);
        setMessages(response.recent_messages || []);
        setHistory(response.history || []);
        setDebug(response.debug || null);
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
      ...currentMessages.map((message) => {
        if (message.role !== "assistant" || !message.change_summary) {
          return message;
        }
        const { change_summary, ...rest } = message;
        return rest;
      }),
      { role: "player", text: message },
      { role: "assistant", text: "" },
    ]);

    try {
      const response = await sendPlayerMessageStream(message, {
        onStatus: (step) => {
          setCurrentPipelineStep(step);
        },
        onPipelineUpdate: (update) => {
          if (update.debug) {
            setDebug(update.debug);
          }
        },
        onNarrationDelta: (chunk) => {
          setCurrentPipelineStep("");
          setMessages((currentMessages) => patchLastAssistantMessage(currentMessages, chunk));
        },
      });
      setVisibleState(response.visible_state);
      setMessages(response.recent_messages || []);
      setHistory(response.history || []);
      setDebug(response.debug || null);
    } catch (sendError) {
      setError(sendError.message);
      setMessages((currentMessages) => currentMessages.slice(0, -2));
    } finally {
      setIsSending(false);
      setCurrentPipelineStep("");
    }
  }

  const scene = visibleState?.scene || {};
  const player = visibleState?.player || {};

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
        <LocationPanel location={scene.location} />
        <LocalCuriositiesPanel entities={scene.entities || []} />
        <InventoryPanel inventory={player.inventory || []} />
        <CurrenciesPanel currencies={player.currencies || []} />
        <SkillsPanel skills={player.skills || []} />
        <HistoryPanel history={history} />
        <DebugPanel debug={debug} />
      </aside>
    </main>
  );
}

function patchLastAssistantMessage(messages, chunk) {
  const updatedMessages = [...messages];
  for (let index = updatedMessages.length - 1; index >= 0; index -= 1) {
    if (updatedMessages[index].role === "assistant") {
      updatedMessages[index] = {
        ...updatedMessages[index],
        text: `${updatedMessages[index].text}${chunk}`,
      };
      break;
    }
  }
  return updatedMessages;
}
