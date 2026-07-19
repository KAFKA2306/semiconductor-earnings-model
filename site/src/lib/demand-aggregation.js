export const DEMAND_COHORTS = [
  { id: 'hyperscalers', label: 'Hyperscalers', roles: ['hyperscaler'] },
  { id: 'ai-cloud', label: 'AI cloud', roles: ['ai-cloud'] },
  { id: 'data-center', label: 'Data-center operators', roles: ['data-center-operator'] },
  { id: 'other-cloud', label: 'Other cloud', roles: ['cloud-provider'] },
];

const tagLabel = (tag) => ({
  PaymentsToAcquireProductiveAssets: 'Productive assets',
  PaymentsToAcquirePropertyPlantAndEquipment: 'Property, plant & equipment',
}[tag] || tag);

export const buildDemandAggregation = (demandApi) => {
  const companies = demandApi.companies.filter((company) => company.quarters.length > 0);
  const periodCounts = companies.reduce((counts, company) => {
    const period = company.quarters[0]?.period_end;
    if (period) counts.set(period, (counts.get(period) || 0) + 1);
    return counts;
  }, new Map());
  const commonPeriod = [...periodCounts.entries()].sort((a, b) => b[1] - a[1] || b[0].localeCompare(a[0]))[0]?.[0] || null;
  const commonCompanies = companies.filter((company) => company.quarters[0]?.period_end === commonPeriod);
  const byTag = (rows) => {
    const tags = new Map();
    for (const company of rows) {
      const quarter = company.quarters[0];
      const tag = quarter.capital_expenditures.fact_tag;
      const previous = tags.get(tag) || { tag, label: tagLabel(tag), total: 0, companies: [], ocf: 0 };
      previous.total += Number(quarter.capital_expenditures.value_usd);
      previous.ocf += Number(quarter.operating_cash_flow.value_usd);
      previous.companies.push(company.name);
      tags.set(tag, previous);
    }
    return [...tags.values()].sort((a, b) => b.total - a.total || a.tag.localeCompare(b.tag));
  };
  const cohortDrafts = DEMAND_COHORTS.map((cohort) => {
    const rows = commonCompanies.filter((company) => cohort.roles.includes(company.role));
    const tags = byTag(rows).map((entry) => ({ ...entry, fcf: entry.ocf - entry.total }));
    const ocf = rows.reduce((sum, company) => sum + Number(company.quarters[0].operating_cash_flow.value_usd), 0);
    return {
      ...cohort,
      rows,
      tags,
      ocf,
      comparableBurden: tags.length === 1 ? tags[0].total / ocf : null,
    };
  }).filter((cohort) => cohort.rows.length > 0);
  const tagTotals = byTag(commonCompanies).map((entry) => ({ ...entry, fcf: entry.ocf - entry.total }));
  const tagIndex = new Map(tagTotals.map((tag, index) => [tag.tag, index]));
  const cohorts = cohortDrafts.map((cohort) => ({
    ...cohort,
    tags: cohort.tags.map((tag) => ({ ...tag, colorIndex: tagIndex.get(tag.tag) ?? 0 })),
  }));
  const scale = Math.max(...[commonCompanies.reduce((sum, company) => sum + Number(company.quarters[0].operating_cash_flow.value_usd), 0), ...tagTotals.map((entry) => entry.total)], 1);
  return {
    companies,
    commonPeriod,
    commonCompanies,
    cohorts,
    tagTotals,
    totalOcf: commonCompanies.reduce((sum, company) => sum + Number(company.quarters[0].operating_cash_flow.value_usd), 0),
    scale,
    ready: commonCompanies.length > 0 && tagTotals.length > 0,
  };
};
