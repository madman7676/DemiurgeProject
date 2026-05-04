import { useState } from "react";
import { renderNarrationWithEntities } from "../../utils/renderNarrationWithEntities";

const PIPELINE_STATUS_LABELS = {
  narrator: "Формується відповідь...",
  lite: "Оновлюється стан...",
};

// Minimal chat surface for Lite exploration requests and responses.
export function ChatUI({
  messages,
  onSendMessage,
  isSending,
  currentPipelineStep,
  error,
}) {
  const [inputValue, setInputValue] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();

    const trimmedValue = inputValue.trim();
    if (!trimmedValue || isSending) {
      return;
    }

    setInputValue("");
    await onSendMessage(trimmedValue);
  }

  return (
    <div className="chat-window">
      <h1>DemiurgeProject</h1>
      <p className="chat-subtitle">Lite tag-driven exploration</p>

      <div className="message-list">
        {messages.length === 0 ? (
          <p className="empty-state">
            Send a message to process the first Lite turn.
          </p>
        ) : (
          messages.map((message, index) => (
            <article
              key={`${message.role}-${index}`}
              className={`message-bubble message-bubble-${message.role}`}
            >
              <strong>{message.role === "player" ? "You" : ""}</strong>
              {renderMessageBody({
                message,
                isPendingAssistant:
                  isSending &&
                  index === messages.length - 1 &&
                  message.role === "assistant" &&
                  !message.text,
                currentPipelineStep,
              })}
            </article>
          ))
        )}
      </div>

      {error ? <p className="error-text">{error}</p> : null}

      <form className="chat-form" onSubmit={handleSubmit}>
        <textarea
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder="Type an exploration action..."
          rows={3}
        />
        <button type="submit" disabled={isSending}>
          {isSending ? "Sending..." : "Send"}
        </button>
      </form>
    </div>
  );
}

function renderMessageBody({ message, isPendingAssistant, currentPipelineStep }) {
  if (message.role === "player") {
    return <p>{message.text}</p>;
  }

  if (isPendingAssistant) {
    const statusText = PIPELINE_STATUS_LABELS[currentPipelineStep] || PIPELINE_STATUS_LABELS.narrator;
    return (
      <p className="pipeline-status">
        <span className="pipeline-loader" aria-hidden="true" />
        <span>{statusText}</span>
      </p>
    );
  }

  return <p>{renderNarrationWithEntities(message.text)}</p>;
}
