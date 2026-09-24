import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'astro/config';

const repository = process.env.GITHUB_REPOSITORY;
if (!repository || !repository.includes('/')) throw new Error('GITHUB_REPOSITORY is required');
const [, repositoryName] = repository.split('/');
if (!repositoryName) throw new Error('GITHUB_REPOSITORY must include a repository name');

async function htmlFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    const target = new URL(entry.name + (entry.isDirectory() ? '/' : ''), directory);
    if (entry.isDirectory()) return htmlFiles(target);
    return entry.isFile() && entry.name.endsWith('.html') ? [fileURLToPath(target)] : [];
  }));
  return files.flat();
}

const accessibilitySystem = {
  name: 'kafka-accessibility-system',
  hooks: {
    'astro:build:done': async ({ dir }) => {
      const outputDirectory = new URL('.', dir);
      const accessibilityStylesheet = `/${repositoryName}/accessibility.css`;
      for (const file of await htmlFiles(outputDirectory)) {
        let html = await fs.readFile(file, 'utf8');
        if (!html.includes(accessibilityStylesheet)) {
          html = html.replace('</head>', `<link rel="stylesheet" href="${accessibilityStylesheet}"></head>`);
        }
        if (html.includes('<main') && !html.includes('id="main-content"')) {
          html = html.replace('<main', '<main id="main-content"');
        }
        if (html.includes('<main') && !html.includes('class="skip-link"')) {
          const bodyPattern = /<body([^>]*)>/;
          if (!bodyPattern.test(html)) throw new Error(`Missing body element in ${file}`);
          html = html.replace(bodyPattern, '<body$1><a class="skip-link" href="#main-content">本文へ移動</a>');
        }
        await fs.writeFile(file, html);
      }
    },
  },
};

export default defineConfig({
  base: `/${repositoryName}/`,
  trailingSlash: 'always',
  integrations: [accessibilitySystem],
});
