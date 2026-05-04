export function LocationPanel({ location }) {
  return (
    <section className="panel">
      <h2>Current Location</h2>
      {location ? (
        <p className="location-line">
          <span className="item-icon">{location.icon || "⌂"}</span>
          <span>{location.name || location.id}</span>
        </p>
      ) : (
        <p className="panel-note">Unknown location.</p>
      )}
    </section>
  );
}
