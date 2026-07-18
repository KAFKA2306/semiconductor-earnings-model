import { defineConfig } from 'astro/config';

const repository = process.env.GITHUB_REPOSITORY;
if (!repository || !repository.includes('/')) throw new Error('GITHUB_REPOSITORY is required');
const [, repositoryName] = repository.split('/');
if (!repositoryName) throw new Error('GITHUB_REPOSITORY must include a repository name');

export default defineConfig({
  base: `/${repositoryName}/`,
  trailingSlash: 'always',
});
