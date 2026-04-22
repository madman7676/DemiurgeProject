// Hidden developer-facing panel for inspecting gameplay decision events.
export function DebugPanel({ decisionHistory }) {
  return (
    <details className="debug-panel">
      <summary>Debug Decisions</summary>
      <div className="debug-panel-body">
        {decisionHistory.length === 0 ? (
          <p className="panel-note">No decision events recorded yet.</p>
        ) : (
          decisionHistory.map((cycle) => (
            <section key={`debug-cycle-${cycle.turn}`} className="debug-cycle">
              <h3>Turn {cycle.turn}</h3>
              <p className="debug-input">{cycle.raw_player_input}</p>
              <div className="debug-event-list">
                {cycle.events.map((event, index) => (
                  <article
                    key={`debug-event-${cycle.turn}-${index}`}
                    className="debug-event"
                  >
                    <strong>{event.source}</strong>
                    <p>{event.message}</p>
                    {event.details && Object.keys(event.details).length > 0 ? (
                      <pre>{JSON.stringify(event.details, null, 2)}</pre>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </details>
  );
}
