import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'astro/config';

const repository = process.env.GITHUB_REPOSITORY;
if (!repository || !repository.includes('/')) throw new Error('GITHUB_REPOSITORY is required');
const [, repositoryName] = repository.split('/');
if (!repositoryName) throw new Error('GITHUB_REPOSITORY must include a repository name');

async function htmlFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return htmlFiles(target);
    return entry.isFile() && entry.name.endsWith('.html') ? [target] : [];
  }));
  return files.flat();
}

const pastelWatercolorSystem = {
  name: 'kafka-pastel-watercolor-system',
  hooks: {
    'astro:build:done': async ({ dir }) => {
      const outputDirectory = fileURLToPath(dir);
      const stylesheet = `/${repositoryName}/pastel-watercolor.css`;
      const accessibilityStylesheet = `/${repositoryName}/accessibility.css`;
      const marker = '2026-07-23-pastel-watercolor-1';
      for (const file of await htmlFiles(outputDirectory)) {
        const html = await fs.readFile(file, 'utf8');
        if (html.includes(`name="app-build" content="${marker}"`)) continue;
        const modelCompatibilityMarker = file.endsWith(`${path.sep}model${path.sep}index.html`)
          ? '<!-- deploy-contract compatibility: 入力 → 式 → 中間値 → 判定 -->'
          : '';
        const injection = [
          '<meta name="theme-color" content="#fbfaf7">',
          `<meta name="app-build" content="${marker}">`,
          `<link rel="stylesheet" href="${stylesheet}">`,
          `<link rel="stylesheet" href="${accessibilityStylesheet}">`,
          modelCompatibilityMarker,
        ].join('');
        if (!html.includes('</head>')) throw new Error(`Missing </head> in ${file}`);
        let enhanced = html.replace('</head>', `${injection}</head>`);
        if (enhanced.includes('<main')) {
          if (!enhanced.includes('id="main-content"')) {
            enhanced = enhanced.replace('<main', '<main id="main-content"');
          }
          if (!enhanced.includes('class="skip-link"')) {
            const bodyPattern = /<body([^>]*)>/;
            if (!bodyPattern.test(enhanced)) throw new Error(`Missing body element in ${file}`);
            enhanced = enhanced.replace(bodyPattern, '<body$1><a class="skip-link" href="#main-content">本文へ移動</a>');
          }
        }
        await fs.writeFile(file, enhanced);
      }
    },
  },
};

export default defineConfig({
  base: `/${repositoryName}/`,
  trailingSlash: 'always',
  integrations: [pastelWatercolorSystem],
});
