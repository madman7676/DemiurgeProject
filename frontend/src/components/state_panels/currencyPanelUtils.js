export function getDisplayCurrencies(currencies) {
  return Array.isArray(currencies)
    ? currencies.filter((currency) => currency && currency.id)
    : [];
}
