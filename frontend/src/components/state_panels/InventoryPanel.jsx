// Inventory display for the current visible player state.
export function InventoryPanel({ inventory }) {
  return (
    <section className="panel">
      <h2>Inventory</h2>
      {inventory.length === 0 ? (
        <p>No inventory items visible.</p>
      ) : (
        <ul className="data-list">
          {inventory.map((item) => (
            <li key={item.item_id}>
              {item.name} x{item.quantity}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
