// Opcjonalna warstwa odwzorowania sejfu Obsidian, bez modyfikowania kontraktu strony.
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
const source = join(process.cwd(), 'data', 'eksport', 'socjal.json');
let cache;
export function socjal() {
  if (cache === undefined) cache = existsSync(source) ? JSON.parse(readFileSync(source, 'utf8')) : null;
  return cache;
}
export const kartaSocjal = (id) => socjal()?.karty?.[id] ?? null;
