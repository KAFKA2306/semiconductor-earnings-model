export class UnitAuditError extends Error {}

export const MONEY_UNITS = Object.freeze({
  USD: { currency: 'USD', factor: 1 },
  USD_million: { currency: 'USD', factor: 1_000_000 },
  USD_billion: { currency: 'USD', factor: 1_000_000_000 },
  JPY: { currency: 'JPY', factor: 1 },
  JPY_million: { currency: 'JPY', factor: 1_000_000 },
  JPY_billion: { currency: 'JPY', factor: 1_000_000_000 },
});

export function monetaryUnit(unit) {
  if (typeof unit !== 'string' || !unit) throw new UnitAuditError('monetary unit is required');
  const spec = MONEY_UNITS[unit];
  if (!spec) throw new UnitAuditError(`unsupported monetary unit: ${unit}`);
  return spec;
}

export function normalizeMonetaryValue(value, unit) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) throw new UnitAuditError(`non-finite monetary value: ${value}`);
  const spec = monetaryUnit(unit);
  return { value: amount * spec.factor, currency: spec.currency, unit: spec.currency };
}

export function convertMonetaryValue(value, unit, targetCurrency, rates = {}) {
  const normalized = normalizeMonetaryValue(value, unit);
  if (normalized.currency === targetCurrency) return { ...normalized, unit: targetCurrency };
  const jpyPerUsd = Number(rates.JPY_per_USD);
  if (!(jpyPerUsd > 0)) throw new UnitAuditError('JPY_per_USD must be a positive explicit rate for USD/JPY conversion');
  if (normalized.currency === 'JPY' && targetCurrency === 'USD') {
    return { value: normalized.value / jpyPerUsd, currency: 'USD', unit: 'USD' };
  }
  if (normalized.currency === 'USD' && targetCurrency === 'JPY') {
    return { value: normalized.value * jpyPerUsd, currency: 'JPY', unit: 'JPY' };
  }
  throw new UnitAuditError(`unsupported currency conversion: ${normalized.currency} -> ${targetCurrency}`);
}

function assertBaseUsdMetric(metric, path, valueKey) {
  if (!metric || typeof metric !== 'object') throw new UnitAuditError(`${path} is missing`);
  if (!(valueKey in metric)) throw new UnitAuditError(`${path}.${valueKey} is missing`);
  const spec = monetaryUnit(metric.unit);
  if (spec.currency !== 'USD' || spec.factor !== 1) {
    throw new UnitAuditError(`${path}.unit=${metric.unit} is not renderer-safe base USD; normalize upstream before HTML generation`);
  }
}

export function auditEarningsInputs({ primaryApi, profitApi, demandApi }) {
  let checked = 0;
  for (const [companyIndex, company] of (primaryApi?.companies || []).entries()) {
    for (const [factIndex, fact] of (company.facts || []).entries()) {
      assertBaseUsdMetric(fact, `primaryApi.companies[${companyIndex}].facts[${factIndex}]`, 'reported_value');
      checked += 1;
    }
  }
  for (const [companyIndex, company] of (profitApi?.companies || []).entries()) {
    for (const [quarterIndex, quarter] of (company.quarters || []).entries()) {
      for (const key of ['revenue', 'operating_income']) {
        assertBaseUsdMetric(quarter[key], `profitApi.companies[${companyIndex}].quarters[${quarterIndex}].${key}`, 'reported_value');
        checked += 1;
      }
    }
  }
  for (const [companyIndex, company] of (demandApi?.companies || []).entries()) {
    for (const [quarterIndex, quarter] of (company.quarters || []).entries()) {
      for (const key of ['operating_cash_flow', 'capital_expenditures']) {
        assertBaseUsdMetric(quarter[key], `demandApi.companies[${companyIndex}].quarters[${quarterIndex}].${key}`, 'value_usd');
        checked += 1;
      }
    }
  }
  return { checked, requiredUnit: 'USD' };
}
