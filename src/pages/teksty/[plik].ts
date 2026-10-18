import type { APIRoute } from 'astro';
import { readFileSync } from 'node:fs';
import { dane } from '../../lib/model.mjs';
import { eliSlug } from '../../lib/format.mjs';

export function getStaticPaths() {
  const d = dane();
  return d.akty.flatMap((a: any) => a.pliki.filter((p: any) => p.tekst_naprawiony).map((p: any) => ({
    params: { plik: `${eliSlug(a.eli)}-${p.rodzaj}-do-kopiowania.txt` },
    props: { bajty: readFileSync(`${d.katalog}/${p.tekst_naprawiony.plik}`) },
  })));
}
export const GET: APIRoute = ({ props }) => new Response(props.bajty, {
  headers: { 'Content-Type': 'text/plain; charset=utf-8' },
});
