import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { auditEarningsInputs } from '../src/lib/unit-audit.js';

const siteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const readJson = (relativePath) => JSON.parse(fs.readFileSync(path.join(siteRoot, relativePath), 'utf8'));

const result = auditEarningsInputs({
  primaryApi: readJson('public/api/v1/index.json'),
  profitApi: readJson('public/api/v1/semiconductor-profit/index.json'),
  demandApi: readJson('public/api/v1/demand/index.json'),
});

console.log(`unit_audit=PASS checked=${result.checked} required_unit=${result.requiredUnit}`);
