import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const dist = path.join(root, 'dist');
const indexPath = path.join(dist, 'index.html');
const componentPath = path.join(root, 'src/components/ResearchWorkbench.astro');
const cssPath = path.join(dist, 'assets/bi-workbench.css');
const jsPath = path.join(dist, 'assets/bi-workbench.js');
const statePath = path.join(dist, 'assets/workspace-state.js');
const chartEnginePath = path.join(dist, 'assets/chart-engine.js');
const financialPath = path.join(dist, 'api/v3/financial-database/index.json');
const infrastructurePath = path.join(dist, 'api/v1/ai-infrastructure/index.json');

for (const file of [indexPath, componentPath, cssPath, jsPath, statePath, chartEnginePath, financialPath, infrastructurePath]) {
  if (!fs.existsSync(file)) throw new Error('Required Pages artifact is missing: ' + path.relative(root, file));
}

const html = fs.readFileSync(indexPath, 'utf8');
const component = fs.readFileSync(componentPath, 'utf8');
const css = fs.readFileSync(cssPath, 'utf8');
const js = fs.readFileSync(jsPath, 'utf8');
const workspaceState = fs.readFileSync(statePath, 'utf8');
const chartEngine = fs.readFileSync(chartEnginePath, 'utf8');
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
  'data-open-mobile-nav',
  'data-mobile-nav-dialog',
  'data-open-workspaces',
  'data-save-workspace',
  'data-workspace-dialog',
  'data-watchlist-filter',
  'data-add-watchlist',
  'data-linked-strip',
  'data-chart-panel',
  'assets/chart-engine.js',
  'data-export-json',
  'data-export-full',
  'Full canonical JSON',
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
  '.wb-mobile-nav',
  '.wb-linked-strip',
  '[data-sort-dir=asc]',
  '[data-sort-dir=desc]',
  '.wb-chart-panel',
  '.wb-bar-chart',
  '.wb-pastel-line',
  '.wb-pie',
  '.wb-col-resizer',
  '.wb-pinned',
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
  "ev.key==='/'",
  'data-inspector-tab',
  'applyInspectorTab',
  'renderSortState',
  'aria-sort',
  'renderLinkedStrip',
  'renderChart',
  'openChartMenu',
  'TABLE_LAYOUT_KEY',
  'WORKSPACE_KEY',
  'WATCHLIST_KEY',
  'saveWorkspace',
  'renderSavedWorkspaces',
  'workspaceApi.restore',
  'exportFullCanonical',
  'addSelectedToWatchlist',
  'watchlistOnly',
  'moveColumn',
  'ensureColumnResizers',
  'workspaceApi.setActive',
  'openInspector',
]) {
  if (!js.includes(marker)) throw new Error('BI interaction contract is missing: ' + marker);
}

for (const marker of [
  'SemiconChartEngine',
  'pieAllowed',
  "view==='projects'",
  "view==='financials'",
  "type:'line'",
  "type:'bar'",
  "model.type='pie'",
]) {
  if (!chartEngine.includes(marker)) throw new Error('Chart engine contract is missing: ' + marker);
}
for (const marker of [
  'workspace-state.v1',
  'active: {rowId:null, entityId:null, projectId:null, recordId:null}',
  'selected: new Set()',
  'filter:',
  'toggleSelected',
  'setInspectorTab',
  'snapshot',
  'restore',
  'watchlist:new Set()',
  'widgets:',
]) {
  if (!workspaceState.includes(marker)) throw new Error('WorkspaceState contract is missing: ' + marker);
}
for (const marker of [
  "NULL ≠ 0",
  "Actual ≠ Guidance",
  "site/public/api/v2/projects/index.json",
  "site/public/api/v2/entities/index.json",
  "site/public/api/v2/events/index.json",
  "site/public/api/v3/financial-database/index.json",
  "linkedByEntity",
  "change_type",
  "classifyCanonicalChange",
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
