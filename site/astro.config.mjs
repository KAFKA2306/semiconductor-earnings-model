import { defineConfig } from 'astro/config';

const [, repository = ''] = (process.env.GITHUB_REPOSITORY || '').split('/');
const rawBase = process.env.SITE_BASE?.trim();
const normalizedBase = rawBase
  ? (rawBase === '/' ? '/' : '/' + rawBase.replace(/^\/+|\/+$/g, '') + '/')
  : (repository ? '/' + repository + '/' : '/');

export default defineConfig({
  base: normalizedBase,
  trailingSlash: 'always',
});
