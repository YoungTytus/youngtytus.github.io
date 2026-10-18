// Historia kwot jednej korzyści w CSV (link z karty korzyści).
import type { APIRoute } from 'astro';
import { dane, historiaCsv } from '../../../lib/model.mjs';

export function getStaticPaths() {
  return dane().korzysci.map((k: any) => ({ params: { id: k.id }, props: { k } }));
}

export const GET: APIRoute = ({ props }) =>
  new Response(historiaCsv([props.k]), { headers: { 'Content-Type': 'text/csv; charset=utf-8' } });
