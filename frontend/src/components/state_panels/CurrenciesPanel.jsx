export function CurrenciesPanel({ currencies }) {
  return (
    <section className="panel">
      <h2>Currencies</h2>
      {currencies.length === 0 ? (
        <p>No currencies.</p>
      ) : (
        <ul className="currency-list">
          {currencies.map((currency) => (
            <li key={currency.id} title={currency.name || currency.id}>
              <span>{currency.icon || "$"}</span>
              <strong>{currency.amount || 0}</strong>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
