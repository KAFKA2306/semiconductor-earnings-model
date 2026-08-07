import assert from 'node:assert/strict';
import {
  UnitAuditError,
  auditEarningsInputs,
  convertMonetaryValue,
  normalizeMonetaryValue,
} from '../src/lib/unit-audit.js';

assert.deepEqual(normalizeMonetaryValue(2.5, 'USD_million'), {
  value: 2_500_000,
  currency: 'USD',
  unit: 'USD',
});
assert.deepEqual(normalizeMonetaryValue(1.25, 'USD_billion'), {
  value: 1_250_000_000,
  currency: 'USD',
  unit: 'USD',
});
assert.deepEqual(convertMonetaryValue(15_000, 'JPY', 'USD', { JPY_per_USD: 150 }), {
  value: 100,
  currency: 'USD',
  unit: 'USD',
});

const base = {
  primaryApi: { companies: [{ facts: [{ reported_value: 10, unit: 'USD' }] }] },
  profitApi: {
    companies: [{ quarters: [{
      revenue: { reported_value: 20, unit: 'USD' },
      operating_income: { reported_value: 3, unit: 'USD' },
    }] }],
  },
  demandApi: {
    companies: [{ quarters: [{
      operating_cash_flow: { value_usd: 5, unit: 'USD' },
      capital_expenditures: { value_usd: 2, unit: 'USD' },
    }] }],
  },
};

assert.deepEqual(auditEarningsInputs(base), { checked: 5, requiredUnit: 'USD' });

for (const unit of ['USD_million', 'USD_billion', 'JPY']) {
  const fixture = structuredClone(base);
  fixture.profitApi.companies[0].quarters[0].revenue.unit = unit;
  assert.throws(
    () => auditEarningsInputs(fixture),
    (error) => error instanceof UnitAuditError && error.message.includes('not renderer-safe base USD'),
  );
}

const missing = structuredClone(base);
delete missing.demandApi.companies[0].quarters[0].operating_cash_flow.unit;
assert.throws(() => auditEarningsInputs(missing), /monetary unit is required/);
assert.throws(() => convertMonetaryValue(150, 'JPY', 'USD'), /JPY_per_USD/);

console.log('unit audit tests: PASS');
