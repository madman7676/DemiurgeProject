import { getDisplayCurrencies } from "./currencyPanelUtils";

export function CurrenciesPanel({ currencies }) {
  const visibleCurrencies = getDisplayCurrencies(currencies);

  return (
    <section className="panel currencies-panel">
      <h2>Currencies</h2>
      {visibleCurrencies.length === 0 ? (
        <p className="panel-note">No currencies.</p>
      ) : (
        <ul className="currency-chip-list">
          {visibleCurrencies.map((currency) => (
            <li key={currency.id}>
              <span
                className="currency-chip"
                title={currency.name || currency.id}
                aria-label={currency.name || currency.id}
                data-tooltip={currency.name || currency.id}
                tabIndex={0}
              >
                <span aria-hidden="true">{currency.icon || "$"}</span>
                <strong>{currency.amount || 0}</strong>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
