// Hidden developer-facing panel for the latest Hyperlite debug payload.
export function DebugPanel({ debug }) {
  return (
    <details className="debug-panel">
      <summary>Debug</summary>
      <div className="debug-panel-body">
        {!debug ? (
          <p className="panel-note">No debug payload yet.</p>
        ) : (
          <>
            <DebugBlock title="Raw LLM Response" value={debug.raw_llm_response || ""} />
            <DebugBlock title="Parsed Tags" value={debug.parsed_tags || {}} />
            <DebugBlock title="Applied Changes" value={debug.applied_changes || []} />
            <DebugBlock
              title="Malformed / Skipped Tags"
              value={debug.malformed_or_skipped_tags || []}
            />
          </>
        )}
      </div>
    </details>
  );
}

function DebugBlock({ title, value }) {
  return (
    <section className="debug-event">
      <strong>{title}</strong>
      <pre>{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}
