// Inventory display for the Hyperlite player state.
export function InventoryPanel({ inventory }) {
  return (
    <section className="panel">
      <h2>Inventory</h2>
      {inventory.length === 0 ? (
        <p>No items.</p>
      ) : (
        <ul className="data-list icon-list">
          {inventory.map((item) => (
            <li key={item.id}>
              <span className="item-icon">{item.icon || "•"}</span>
              <span>{item.name || item.id}</span>
              <strong className="stack-amount">x{item.quantity || 0}</strong>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
