export function HistoryPanel({ history }) {
  const turns = Array.isArray(history) ? history.slice(-6).reverse() : [];

  return (
    <details className="panel" open>
      <summary>Recent History</summary>
      {turns.length === 0 ? (
        <p className="panel-note">No turns yet.</p>
      ) : (
        <ol className="history-list">
          {turns.map((turn, index) => (
            <li key={`${turn.user_input}-${index}`}>
              <strong>{turn.user_input}</strong>
              <p>{turn.narrator_response_clean}</p>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}
