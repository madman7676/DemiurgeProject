export function LocalCuriositiesPanel({ entities }) {
  const sceneEntities = Array.isArray(entities) ? entities : [];

  return (
    <details className="curiosities-panel panel" open>
      <summary>Local Curiosities</summary>
      <div className="curiosities-body">
        {sceneEntities.length === 0 ? (
          <p className="panel-note">No scene entities in the latest response.</p>
        ) : (
          <ul className="curiosity-list">
            {sceneEntities.map((entity) => (
              <li key={entity.id}>
                <span className="curiosity-name">
                  <span className="item-icon">{entity.icon || "•"}</span>
                  {entity.name || entity.id}
                </span>
                <span className="curiosity-meta">
                  {entity.class} · {entity.visibility}
                  {Number.isInteger(entity.last_seen_turn)
                    ? ` · turn ${entity.last_seen_turn}`
                    : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
