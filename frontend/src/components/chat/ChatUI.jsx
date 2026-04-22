import { useState } from "react";

// Minimal chat surface for exploration-mode requests and responses.
export function ChatUI({ messages, onSendMessage, isSending, error }) {
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
      <p className="chat-subtitle">Exploration mode prototype</p>

      <div className="message-list">
        {messages.length === 0 ? (
          <p className="empty-state">
            Send a message to process the first exploration turn.
          </p>
        ) : (
          messages.map((message, index) => (
            <article
              key={`${message.role}-${index}`}
              className={`message-bubble message-bubble-${message.role}`}
            >
              <strong>{message.role === "player" ? "You" : "Narrator"}</strong>
              <p>{message.text}</p>
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
