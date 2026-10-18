// Pliki eksportu do pobrania: /dane/korzysci.json, /dane/historia_kwot.csv itd.
import type { APIRoute } from 'astro';
import { plikiDanych } from '../../lib/model.mjs';

const TYPY: Record<string, string> = {
  json: 'application/json; charset=utf-8',
  csv: 'text/csv; charset=utf-8',
};

export function getStaticPaths() {
  return plikiDanych().map((p) => ({ params: { plik: p.nazwa }, props: { bajty: p.bajty } }));
}

export const GET: APIRoute = ({ params, props }) => {
  const ext = params.plik!.split('.').pop()!;
  return new Response(props.bajty, { headers: { 'Content-Type': TYPY[ext] ?? 'text/plain; charset=utf-8' } });
};
