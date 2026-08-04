import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const dist = path.join(root, 'dist');
const manifestPath = path.join(dist, 'research-context-manifest.json');
const cssPath = path.join(dist, 'assets/research-context.css');
const jsPath = path.join(dist, 'assets/research-context.js');

for (const file of [manifestPath, cssPath, jsPath]) {
  if (!fs.existsSync(file)) throw new Error(`Research context artifact is missing: ${path.relative(dist, file)}`);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
if (manifest.schema_version !== 'research-context.v1') throw new Error('Research context schema is invalid');
if (manifest.pages?.length !== 3) throw new Error('Research context must cover three product views');

const requiredHtmlMarkers = [
  'data-research-page=',
  'id="research-context-config"',
  '../assets/research-context.css',
  '../assets/research-context.js',
];
for (const page of ['earnings', 'resilience', 'model']) {
  const htmlPath = path.join(dist, page, 'index.html');
  const html = fs.readFileSync(htmlPath, 'utf8');
  for (const marker of requiredHtmlMarkers) {
    if (!html.includes(marker)) throw new Error(`${page} is missing ${marker}`);
  }
  const configMatch = html.match(/<script type="application\/json" id="research-context-config">([^<]+)<\/script>/);
  if (!configMatch) throw new Error(`${page} context config is missing`);
  const config = JSON.parse(configMatch[1]);
  if (config.page !== page) throw new Error(`${page} context config has wrong page id`);
  if (!Array.isArray(config.companies) || !Array.isArray(config.periods) || !Array.isArray(config.peers)) {
    throw new Error(`${page} context arrays are invalid`);
  }
  if (!config.evidence?.[page]?.length) throw new Error(`${page} evidence routes are missing`);
}

const js = fs.readFileSync(jsPath, 'utf8');
for (const marker of [
  "new URLSearchParams(location.search)",
  "params.set('company'",
  "params.set('compare'",
  "params.set('period'",
  "params.set('valueType'",
  'function applyContextHighlight()',
  'function openEvidence(',
  'research-value-actual',
  'research-value-guidance',
  'research-value-consensus',
  'research-value-estimate',
  'research-value-scenario',
]) {
  if (!js.includes(marker)) throw new Error(`Research context JS is missing ${marker}`);
}

const css = fs.readFileSync(cssPath, 'utf8');
for (const marker of [
  '.research-context-shell',
  '.research-evidence-dialog',
  '.research-value-actual',
  '.research-value-guidance',
  '.research-value-consensus',
  '.research-value-estimate',
  '.research-value-scenario',
  'min-height: 40px',
  '@media (max-width: 920px)',
  '@media (prefers-reduced-motion: reduce)',
]) {
  if (!css.includes(marker)) throw new Error(`Research context CSS is missing ${marker}`);
}

console.log(`research_context_contract=PASS companies=${manifest.company_count} periods=${manifest.period_count}`);
