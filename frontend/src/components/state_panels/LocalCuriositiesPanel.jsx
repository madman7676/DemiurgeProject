export function LocalCuriositiesPanel({ scenePool }) {
  const entities = Array.isArray(scenePool) ? scenePool : [];
  const available = entities.filter((entity) => entity.status !== "background");
  const background = entities.filter((entity) => entity.status === "background");

  return (
    <details className="curiosities-panel panel" open>
      <summary>Local Curiosities</summary>
      <div className="curiosities-body">
        {entities.length === 0 ? (
          <p className="panel-note">No curiosities here yet.</p>
        ) : (
          <>
            <CuriosityGroup title="Available" entities={available} />
            <CuriosityGroup title="Background" entities={background} isDimmed />
          </>
        )}
      </div>
    </details>
  );
}

function CuriosityGroup({ title, entities, isDimmed = false }) {
  if (entities.length === 0) {
    return null;
  }

  return (
    <section className={`curiosity-group${isDimmed ? " curiosity-group-dimmed" : ""}`}>
      <h3>{title}</h3>
      <ul className="curiosity-list">
        {entities.map((entity) => (
          <li key={entity.entity_id || `${entity.name}-${entity.status}`}>
            <span className="curiosity-name">{entity.name}</span>
            <span className="curiosity-meta">
              {entity.entity_type || "scene_entity"} · {entity.status || "available"}
              {Number.isInteger(entity.mention_count)
                ? ` · seen ${entity.mention_count}x`
                : ""}
              {Number.isInteger(entity.last_seen_turn)
                ? ` · turn ${entity.last_seen_turn}`
                : ""}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
