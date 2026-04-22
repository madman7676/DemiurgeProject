// Visible player stats and current location.
export function StatsPanel({ stats, location }) {
  return (
    <section className="panel">
      <h2>Stats</h2>
      {stats.length === 0 ? (
        <p>No stats available.</p>
      ) : (
        <ul className="data-list">
          {stats.map((stat) => (
            <li key={stat.stat_id}>
              {stat.name}: {stat.value}
            </li>
          ))}
        </ul>
      )}
      {location ? (
        <p className="panel-note">
          Location: {location.detail || location.area_id || location.region_id}
        </p>
      ) : null}
    </section>
  );
}
