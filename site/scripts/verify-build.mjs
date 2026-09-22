import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const dist = path.join(root, 'dist');
const indexPath = path.join(dist, 'index.html');
const componentPath = path.join(root, 'src/components/ResearchWorkbench.astro');
const cssPath = path.join(dist, 'assets/bi-workbench.css');
const jsPath = path.join(dist, 'assets/bi-workbench.js');
const financialPath = path.join(dist, 'api/v3/financial-database/index.json');
const infrastructurePath = path.join(dist, 'api/v1/ai-infrastructure/index.json');

for (const file of [indexPath, componentPath, cssPath, jsPath, financialPath, infrastructurePath]) {
  if (!fs.existsSync(file)) throw new Error('Required Pages artifact is missing: ' + path.relative(root, file));
}

const html = fs.readFileSync(indexPath, 'utf8');
const component = fs.readFileSync(componentPath, 'utf8');
const css = fs.readFileSync(cssPath, 'utf8');
const js = fs.readFileSync(jsPath, 'utf8');
const financial = JSON.parse(fs.readFileSync(financialPath, 'utf8'));
const infrastructure = JSON.parse(fs.readFileSync(infrastructurePath, 'utf8'));
const expectedSha = process.env.PUBLIC_BUILD_SHA;

if (!html.includes('<title>Projects | Semiconductor Research Workbench</title>')) {
  throw new Error('Screener-first workbench root title is missing');
}
for (const marker of [
  'data-workbench',
  'SEMICON LEDGER',
  'RESEARCH WORKBENCH',
  'data-table-body',
  'data-inspector',
  'data-compare-bar',
  'data-command',
  'data-open-columns',
  'data-open-compare',
  'data-open-views',
  'data-open-export',
  'data-export-json',
  'data-export-meta',
  'data-copy-api',
  'Displayed JSON',
  'Metadata JSON',
  'Save view',
  'Export',
]) {
  if (!html.includes(marker)) throw new Error('Workbench root is missing marker: ' + marker);
}
for (const route of ['companies','financials','capacity','facilities','activity','evidence','quality','earnings','model','resilience']) {
  const file = path.join(dist, route, 'index.html');
  if (!fs.existsSync(file)) throw new Error('Workbench route is missing: ' + route);
  const page = fs.readFileSync(file, 'utf8');
  if (!page.includes('data-workbench')) throw new Error(route + ' is not using shared workbench shell');
}
for (const forbidden of ['AIインフラで、最後に何が変わったか。','headline-card primary','pastel-watercolor.css','research-context.js','research-context.css']) {
  if (html.includes(forbidden)) throw new Error('Legacy marketing UI leaked into root: ' + forbidden);
}
for (const marker of [
  '--wb-rail:',
  '.wb-table',
  '.wb-inspector',
  '.wb-command',
  '.wb-bottom',
  'font-variant-numeric:tabular-nums',
  '@media(max-width:760px)',
]) {
  if (!css.includes(marker)) throw new Error('BI CSS is missing contract marker: ' + marker);
}
for (const marker of [
  "new URLSearchParams(location.search)",
  "params.set('compare'",
  "params.set('cols'",
  "localStorage.getItem('semicon:saved-views')",
  "navigator.clipboard.writeText",
  "exportRows('visible')",
  'openCompare',
  'renderColumnDialog',
  'renderSavedViews',
  'linkedWorkspaceHtml',
  'data-linked-route',
  'exportMetadata',
  'copyApiUrl',
  'Built-in screens',
  'data-column-preset',
  'financialHistoryHtml',
  'wb-history-chart',
  'VIRTUALIZE_AT = 200',
  "dataset.virtualized = 'true'",
  "params.append('f'",
  "params.append('x'",
  'openCellMenu',
  'addCrossFilter',
  "ev.key.toLowerCase()==='k'",
  'openInspector',
]) {
  if (!js.includes(marker)) throw new Error('BI interaction contract is missing: ' + marker);
}
for (const marker of [
  "NULL ≠ 0",
  "Actual ≠ Guidance",
  "site/public/api/v2/projects/index.json",
  "site/public/api/v2/entities/index.json",
  "site/public/api/v2/events/index.json",
  "site/public/api/v3/financial-database/index.json",
  "linkedByEntity",
  "semiconductor-workbench-export.v1",
]) {
  if (!component.includes(marker)) throw new Error('Canonical workbench contract is missing: ' + marker);
}
if (expectedSha && !html.includes('data-build-sha="' + expectedSha + '"')) {
  throw new Error('Pages root does not expose build SHA ' + expectedSha);
}

if (infrastructure.schema_version !== 'ai-infrastructure-view.v2') {
  throw new Error('Unexpected AI infrastructure schema: ' + infrastructure.schema_version);
}
if (infrastructure.observations.some((row) => row.concept_id === 'capital_expenditures' && row.source_tier === 'primary_regulatory')) {
  throw new Error('SEC cash PP&E leaked into the company total-CapEx concept');
}
if (!financial.extensions?.includes('nand-operating-kpis.v1')) {
  throw new Error('NAND operating KPI extension is missing');
}
if ((financial.audit?.counts?.nand_actual_observations ?? 0) < 8) {
  throw new Error('NAND actual observation coverage is below the required baseline');
}
if ((financial.views?.nand_kpi_comparisons?.length ?? 0) < 4) {
  throw new Error('NAND comparison view is incomplete');
}

console.log('pages_root_contract=PASS workbench=screener-first routes=8 cross_filter=PASS ai_schema=' + infrastructure.schema_version + ' hash=' + financial.content_hash);
