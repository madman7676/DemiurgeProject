export function ResourcesPanel({ resources }) {
  return (
    <section className="panel">
      <h2>Resources</h2>
      {resources.length === 0 ? (
        <p>No resources.</p>
      ) : (
        <ul className="resource-list">
          {resources.map((resource) => (
            <li key={resource.id} title={resource.name || resource.id}>
              <span>{resource.icon || "$"}</span>
              <strong>{resource.amount || 0}</strong>
              <span>{resource.name || resource.id}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
