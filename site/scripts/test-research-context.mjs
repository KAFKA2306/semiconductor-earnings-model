import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const siteRoot = path.resolve(scriptDir, '..');
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'research-context-'));
const dist = path.join(fixture, 'dist');

const write = (relativePath, content) => {
  const file = path.join(dist, relativePath);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, typeof content === 'string' ? content : `${JSON.stringify(content, null, 2)}\n`);
};

for (const page of ['earnings', 'resilience', 'model']) {
  write(`${page}/index.html`, `<!doctype html><html><head><title>${page}</title></head><body><main><article>NVDA NVIDIA 2025-01-26</article></main></body></html>`);
}
write('api/v2/semiconductor-research/index.json', {
  peer_groups: [{ id: 'semiconductor', label_ja: '半導体メーカー' }],
  companies: [{ id: 'nvidia', ticker: 'NVDA', name: 'NVIDIA', peer_group: 'semiconductor', latest_annual_period: '2025-01-26' }],
});
write('api/v1/semiconductor-profit/index.json', {
  companies: [{ id: 'nvidia', ticker: 'NVDA', name: 'NVIDIA', quarters: [{ period_end: '2025-04-27' }] }],
});
write('api/v1/demand/index.json', {
  companies: [{ id: 'microsoft', ticker: 'MSFT', name: 'Microsoft', role: 'hyperscaler', quarters: [{ period_end: '2025-03-31' }] }],
});
write('api/v1/index.json', { companies: [] });
write('assets/research-context.css', fs.readFileSync(path.join(siteRoot, 'public/assets/research-context.css'), 'utf8'));
write('assets/research-context.js', fs.readFileSync(path.join(siteRoot, 'public/assets/research-context.js'), 'utf8'));

const enhance = spawnSync(process.execPath, [path.join(scriptDir, 'enhance-research-context.mjs')], {
  cwd: fixture,
  encoding: 'utf8',
});
assert.equal(enhance.status, 0, enhance.stderr || enhance.stdout);
assert.match(enhance.stdout, /research_context=PASS/);

const manifest = JSON.parse(fs.readFileSync(path.join(dist, 'research-context-manifest.json'), 'utf8'));
assert.equal(manifest.schema_version, 'research-context.v1');
assert.equal(manifest.company_count, 2);
assert.equal(manifest.period_count, 3);
assert.deepEqual(manifest.pages, ['earnings', 'resilience', 'model']);

for (const page of manifest.pages) {
  const html = fs.readFileSync(path.join(dist, page, 'index.html'), 'utf8');
  assert.match(html, new RegExp(`data-research-page="${page}"`));
  assert.match(html, /research-context\.css/);
  assert.match(html, /research-context\.js/);
  const match = html.match(/<script type="application\/json" id="research-context-config">([^<]+)<\/script>/);
  assert.ok(match);
  const config = JSON.parse(match[1]);
  assert.equal(config.page, page);
  assert.equal(config.companies.length, 2);
  assert.deepEqual(config.periods, ['2025-04-27', '2025-03-31', '2025-01-26']);
  assert.ok(config.evidence[page].length >= 4);
}

console.log(`research_context_fixture=PASS ${enhance.stdout.trim()}`);
