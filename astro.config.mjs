import { defineConfig } from 'astro/config';
export default defineConfig({
  site: process.env.SITE_URL ?? 'https://youngtytus.github.io',
  base: process.env.SITE_BASE ?? '',
  trailingSlash: 'always',
  build: { format: 'directory', inlineStylesheets: 'always' },
  compressHTML: true,
});
