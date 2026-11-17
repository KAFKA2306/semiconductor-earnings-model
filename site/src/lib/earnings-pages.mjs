import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';

export const earningsApi = 'api/v1/semiconductor-profit/index.json';

export function readEarnings() {
  const cwd = process.cwd();
  const publicDir = basename(cwd) === 'site' ? resolve(cwd, 'public') : resolve(cwd, 'site/public');
  const doc = JSON.parse(readFileSync(resolve(publicDir, earningsApi), 'utf8'));
  if (doc.schema_version !== 'semiconductor-profit-api.v1' || !Array.isArray(doc.companies)) {
    throw new Error('Unexpected semiconductor earnings schema');
  }
  return doc;
}

export const money = new Intl.NumberFormat('ja-JP');
export const hundredMillion = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 2 });
