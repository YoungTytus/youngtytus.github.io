import type { APIRoute } from 'astro';
import { dane } from '../lib/model.mjs';
import { socjal } from '../lib/socjal.mjs';
import { eliSlug } from '../lib/format.mjs';

export const GET: APIRoute = ({ site }) => {
  const d = dane();
  const extra = socjal();
  const sciezki = ['/', '/korzysci/', '/akty/', '/metodologia/', '/zmiany/', '/dane/',
    ...(extra ? ['/przepisy/', '/historia/'] : []),
    ...(extra?.artykuly ?? []).map((a: any) => `/przepis/${a.id}/`),
    ...Object.keys(extra?.historia ?? {}).map((h) => `/historia/${h}/`),
    ...d.korzysci.map((k: any) => `/korzysc/${k.id}/`),
    ...d.akty.map((a: any) => `/akt/${eliSlug(a.eli)}/`),
    ...Object.keys(d.slowniki.sytuacje).map((s) => `/sytuacja/${s}/`)];
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${
    sciezki.map((s) => `  <url><loc>${new URL(s, site).href}</loc></url>`).join('\n')}\n</urlset>\n`;
  return new Response(xml, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
};
