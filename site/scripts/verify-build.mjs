import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const dist = path.join(root, 'dist');
const indexPath = path.join(dist, 'index.html');
const financialPath = path.join(dist, 'api/v3/financial-database/index.json');
const infrastructurePath = path.join(dist, 'api/v1/ai-infrastructure/index.json');

if (!fs.existsSync(indexPath)) throw new Error('GitHub Pages root index.html is missing');
if (!fs.existsSync(financialPath)) throw new Error('Financial Database v3 JSON is missing from the Pages artifact');
if (!fs.existsSync(infrastructurePath)) throw new Error('AI Infrastructure JSON is missing from the Pages artifact');

const html = fs.readFileSync(indexPath, 'utf8');
const normalizedHtml = html.toUpperCase();
const financial = JSON.parse(fs.readFileSync(financialPath, 'utf8'));
const infrastructure = JSON.parse(fs.readFileSync(infrastructurePath, 'utf8'));
const expectedSha = process.env.PUBLIC_BUILD_SHA;

if (!html.includes('<title>AI Infrastructure / 半導体業績データ</title>')) {
  throw new Error('Pages daily AI infrastructure root title is missing');
}
for (const text of ['Today — 最新の確認済み事実。', '次に、市況を見る。', '企業の利益と耐久力を見る。', '必要なら、根拠まで降りる。']) {
  if (!html.includes(text)) throw new Error(`Pages root reading order is incomplete: ${text}`);
}
for (const text of ['前回の比較可能actualからの変化', 'Compute', 'Network', 'Memory', 'Power', 'vs previous actual']) {
  if (!html.includes(text)) throw new Error(`Pages comparable-change surface is incomplete: ${text}`);
}
if (!html.includes('data-change-state=')) {
  throw new Error('Pages comparable-change state is not machine-readable');
}
for (const token of ['#F7F5EF', '#FFFFFF', '#17233F', '#667085', '#D9D6CE', '#2563EB']) {
  if (!normalizedHtml.includes(token)) throw new Error(`Pages root is missing design foundation token ${token}`);
}
if (!html.includes('min-height:44px') && !html.includes('min-height: 44px')) {
  throw new Error('Pages root is missing the 44px interaction target contract');
}
if (!html.includes('focus-visible')) {
  throw new Error('Pages root is missing visible keyboard focus');
}
if (!html.includes('/api/v1/ai-infrastructure/index.json')) {
  throw new Error('Pages root does not expose the canonical AI infrastructure API');
}
if (expectedSha && !html.includes(`data-build-sha="${expectedSha}"`)) {
  throw new Error(`Pages root does not expose build SHA ${expectedSha}`);
}
if (!html.includes(`data-financial-api-hash="${financial.content_hash}"`)) {
  throw new Error('Pages root and Financial Database v3 hashes do not match');
}
if (!html.includes(`data-ai-infrastructure-schema="${infrastructure.schema_version}"`)) {
  throw new Error('Pages root and AI infrastructure schema do not match');
}
if (infrastructure.schema_version !== 'ai-infrastructure-view.v2') {
  throw new Error(`Unexpected AI infrastructure schema: ${infrastructure.schema_version}`);
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

console.log(`pages_root_contract=PASS ai_schema=${infrastructure.schema_version} nand_periods=${financial.views.nand_kpi_comparisons.length} hash=${financial.content_hash}`);
