// Kontrola zbudowanej strony (SPEC 10, testy obowiązkowe):
//  1. w tekście HTML nie ma „NaN”, „undefined”, „null”, „[object Object]”,
//  2. każda kwota (.kwota) jest wewnątrz .kzd, który ma link .dowod,
//  3. linki wewnętrzne prowadzą do istniejących plików.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const DIST = path.resolve(process.argv[2] ?? 'dist');
const bledy = [];
const pliki = [];
(function chodz(k) {
  for (const n of readdirSync(k)) {
    const p = path.join(k, n);
    if (statSync(p).isDirectory()) chodz(p); else if (n.endsWith('.html')) pliki.push(p);
  }
})(DIST);

const bezSkryptow = (h) => h.replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<style[\s\S]*?<\/style>/gi, '');
const tekst = (h) => bezSkryptow(h).replace(/<[^>]+>/g, ' ');

// prosty parser znaczników do kontroli zagnieżdżeń
function sprawdzKwoty(html, plik) {
  const stos = [];
  const SAMOZAMYKAJACE = new Set(['br', 'img', 'input', 'meta', 'link', 'hr', 'source', 'path', 'circle', 'rect', 'line', 'stop', 'ellipse']);
  const re = /<\/?([a-zA-Z][a-zA-Z0-9-]*)([^>]*?)(\/?)>/g;
  let m;
  const kzd = []; // {maDowod, kwoty}
  const h = bezSkryptow(html);
  while ((m = re.exec(h))) {
    const [caly, tag, attrs, selfclose] = m;
    const t = tag.toLowerCase();
    const zamyk = caly.startsWith('</');
    const klasy = (/class="([^"]*)"/.exec(attrs)?.[1] ?? '').split(/\s+/);
    if (zamyk) {
      while (stos.length) {
        const e = stos.pop();
        if (e.kzd) { const z = kzd.pop(); if (z.kwoty > 0 && !z.maDowod) bledy.push(`${plik}: kwota bez linku do dowodu`); }
        if (e.tag === t) break;
      }
      continue;
    }
    if (SAMOZAMYKAJACE.has(t) || selfclose) continue;
    const el = { tag: t, kzd: klasy.includes('kzd') };
    if (el.kzd) kzd.push({ maDowod: false, kwoty: 0 });
    if (klasy.includes('kwota')) {
      if (!kzd.length) bledy.push(`${plik}: kwota poza blokiem z dowodem: ${h.slice(m.index, m.index + 80)}`);
      else kzd[kzd.length - 1].kwoty++;
    }
    if (t === 'a' && klasy.includes('dowod') && kzd.length) {
      kzd[kzd.length - 1].maDowod = /href="[^"]+"/.test(attrs);
    }
    stos.push(el);
  }
}

for (const p of pliki) {
  const rel = path.relative(DIST, p);
  const html = readFileSync(p, 'utf8');
  const t = tekst(html);
  if (t.includes('[object Object]')) bledy.push(`${rel}: w treści występuje „[object Object]”`);
  if (t.includes('Invalid Date')) bledy.push(`${rel}: w treści występuje „Invalid Date”`);
  for (const zly of ['NaN', 'undefined', 'null']) {
    if (new RegExp(String.raw`(^|[^\p{L}_])${zly}($|[^\p{L}_])`, 'u').test(t)) bledy.push(`${rel}: w treści występuje „${zly}”`);
  }
  sprawdzKwoty(html, rel);
  for (const [, href] of html.matchAll(/href="(\/[^"#?]*)/g)) {
    const cel = path.join(DIST, decodeURIComponent(href));
    const ok = existsSync(cel) && (statSync(cel).isFile() || existsSync(path.join(cel, 'index.html')));
    if (!ok) bledy.push(`${rel}: martwy link wewnętrzny ${href}`);
  }
}

if (bledy.length) {
  console.error(`Kontrola HTML: ${bledy.length} błędów\n  - ${[...new Set(bledy)].join('\n  - ')}`);
  process.exit(1);
}
console.log(`Kontrola HTML: ${pliki.length} stron poprawnych (brak NaN/undefined/null, każda kwota z dowodem, linki wewnętrzne działają).`);
