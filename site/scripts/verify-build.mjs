import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const dist = path.join(root, 'dist');
const indexPath = path.join(dist, 'index.html');
const financialPath = path.join(dist, 'api/v3/financial-database/index.json');

if (!fs.existsSync(indexPath)) throw new Error('GitHub Pages root index.html is missing');
if (!fs.existsSync(financialPath)) throw new Error('Financial Database v3 JSON is missing from the Pages artifact');

const html = fs.readFileSync(indexPath, 'utf8');
const financial = JSON.parse(fs.readFileSync(financialPath, 'utf8'));
const expectedSha = process.env.PUBLIC_BUILD_SHA;

if (!html.includes('<title>半導体業績データ</title>')) {
  throw new Error('Pages root landing title is missing');
}
for (const text of ['まず、市況を見る。', '次に、企業を見る。', 'その後、需要を支える資金を見る。', '必要なら、根拠まで降りる。']) {
  if (!html.includes(text)) throw new Error(`Pages root reading order is incomplete: ${text}`);
}
if (expectedSha && !html.includes(`data-build-sha="${expectedSha}"`)) {
  throw new Error(`Pages root does not expose build SHA ${expectedSha}`);
}
if (!html.includes(`data-financial-api-hash="${financial.content_hash}"`)) {
  throw new Error('Pages root and Financial Database v3 hashes do not match');
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

console.log(`pages_root_contract=PASS nand_periods=${financial.views.nand_kpi_comparisons.length} hash=${financial.content_hash}`);
