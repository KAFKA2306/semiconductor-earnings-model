import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const dist = path.join(root, 'dist');

const readJson = (relativePath, fallback = {}) => {
  const file = path.join(dist, relativePath);
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : fallback;
};

const research = readJson('api/v2/semiconductor-research/index.json', { companies: [], peer_groups: [] });
const profit = readJson('api/v1/semiconductor-profit/index.json', { companies: [] });
const demand = readJson('api/v1/demand/index.json', { companies: [] });
const primary = readJson('api/v1/index.json', { companies: [] });

const companyMap = new Map();
const periods = new Set();
const peerMap = new Map([
  ['all', { id: 'all', label: 'すべて' }],
  ['semiconductor', { id: 'semiconductor', label: '半導体メーカー' }],
  ['semiconductor-equipment', { id: 'semiconductor-equipment', label: '半導体製造装置' }],
  ['demand', { id: 'demand', label: '需要・設備投資側' }],
]);

const text = (...values) => values.find(value => typeof value === 'string' && value.trim())?.trim() || '';
const normalizedId = company => text(company.id, company.company_id, company.ticker, company.stock_code, company.cik, company.name, company.company_name);
const normalizedTicker = company => text(company.ticker, company.stock_code, company.symbol, company.id, company.company_id);
const normalizedName = company => text(company.name, company.company_name, company.legal_name, company.name_ja, company.ticker, company.id);
const normalizedPeer = (company, fallbackPeer) => text(company.peer_group, company.role, company.category, fallbackPeer, 'semiconductor');

function addPeriod(value) {
  if (typeof value !== 'string' || !value.trim()) return;
  const match = value.match(/^\d{4}-\d{2}-\d{2}/);
  periods.add(match ? match[0] : value.trim());
}

function addCompany(company, fallbackPeer = 'semiconductor') {
  if (!company || typeof company !== 'object') return;
  const id = normalizedId(company);
  if (!id) return;
  const existing = companyMap.get(id) || {};
  const peer = normalizedPeer(company, fallbackPeer);
  const record = {
    id,
    ticker: normalizedTicker(company) || existing.ticker || id,
    name: normalizedName(company) || existing.name || id,
    peer,
  };
  companyMap.set(id, { ...existing, ...record });
  if (!peerMap.has(peer)) peerMap.set(peer, { id: peer, label: peer.replaceAll('-', ' ') });
  addPeriod(company.latest_annual_period);
  addPeriod(company.latest_quarter_period);
  addPeriod(company.period_end);
  for (const quarter of company.quarters || []) {
    addPeriod(quarter.period_end);
    addPeriod(quarter.filing_date);
  }
  for (const year of company.years || []) addPeriod(year.period_end);
}

for (const company of research.companies || []) addCompany(company, company.role || 'semiconductor');
for (const company of profit.companies || []) addCompany(company, 'semiconductor');
for (const company of demand.companies || []) addCompany(company, 'demand');
for (const company of primary.companies || []) addCompany(company, 'semiconductor');
for (const peer of research.peer_groups || []) {
  const id = text(peer.id, peer.peer_group, peer.name);
  if (id) peerMap.set(id, { id, label: text(peer.label_ja, peer.label, peer.name, id) });
}

const companies = [...companyMap.values()].sort((left, right) => left.ticker.localeCompare(right.ticker, 'en'));
const context = {
  companies,
  periods: [...periods].sort().reverse(),
  peers: [...peerMap.values()],
  base: '../',
  evidence: {
    earnings: [
      { label: '会社別一次fact', href: '#companies' },
      { label: '需要側一次fact', href: '#demand' },
      { label: '半導体利益fact', href: '#profit' },
      { label: 'Primary API v1', href: 'api/v1/index.json' },
      { label: 'Profit API v1', href: 'api/v1/semiconductor-profit/index.json' },
      { label: 'Demand API v1', href: 'api/v1/demand/index.json' },
    ],
    resilience: [
      { label: 'データ品質', href: '#quality' },
      { label: '報告実績', href: '#actuals' },
      { label: '同業比較', href: '#peers' },
      { label: '下振れシナリオ', href: '#scenario' },
      { label: '証拠オントロジー', href: '#ontology' },
      { label: 'Research API v2', href: 'api/v2/semiconductor-research/index.json' },
    ],
    model: [
      { label: '観測入力', href: '#inputs' },
      { label: '集計と比較', href: '#aggregate' },
      { label: '派生式', href: '#formula' },
      { label: '未知変数', href: '#forward' },
      { label: 'Demand API v1', href: 'api/v1/demand/index.json' },
      { label: 'Profit API v1', href: 'api/v1/semiconductor-profit/index.json' },
    ],
  },
};

function safeJson(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026');
}

function enhancePage(page) {
  const file = path.join(dist, page, 'index.html');
  if (!fs.existsSync(file)) throw new Error(`Research page is missing: ${page}/index.html`);
  let html = fs.readFileSync(file, 'utf8');
  const css = '<link rel="stylesheet" href="../assets/research-context.css">';
  const script = '<script src="../assets/research-context.js" defer></script>';
  const config = `<script type="application/json" id="research-context-config">${safeJson({ ...context, page })}</script>`;
  if (!html.includes(css)) html = html.replace('</head>', `  ${css}\n</head>`);
  if (!html.includes('data-research-page=')) html = html.replace('<body', `<body data-research-page="${page}"`);
  if (!html.includes('id="research-context-config"')) html = html.replace('</body>', `  ${config}\n  ${script}\n</body>`);
  fs.writeFileSync(file, html);

  for (const marker of (css, 'id="research-context-config"', 'research-context.js', `data-research-page="${page}"`)) {
    if (!html.includes(marker)) throw new Error(`${page} is missing research context marker: ${marker}`);
  }
}

for (const page of ['earnings', 'resilience', 'model']) enhancePage(page);

const manifest = {
  schema_version: 'research-context.v1',
  generated_at: new Date().toISOString(),
  company_count: companies.length,
  period_count: context.periods.length,
  peer_count: context.peers.length,
  pages: ['earnings', 'resilience', 'model'],
};
fs.writeFileSync(path.join(dist, 'research-context-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`research_context=PASS companies=${manifest.company_count} periods=${manifest.period_count} pages=${manifest.pages.length}`);
