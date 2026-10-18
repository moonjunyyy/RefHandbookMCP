/**
 * Extra word lists (config EXTRA_LEXICONS), fetched next to the page. A list that fails to load or
 * does not have the expected shape is skipped: the built-in lexicon is always there.
 */
import { EXTRA_LEXICONS } from '../config';
import { keysOf, DOMAINS, VERB_KINDS } from '../data/labels';
import { Lexicon } from '../data/massiveLexicon';

/** Where a list's words come from, as its file says (shown as the credit). */
export interface LexiconCredit {
  source: string;
  publisher: string;
  url: string;
  license: string;
  licenseUrl: string;
  dumpCreated?: string;
}

export interface LoadedLexicon {
  id: string;
  label: string;
  credit: LexiconCredit;
  lexicon: Lexicon;
  size: number;
}

function words(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((w): w is string => typeof w === 'string' && w.trim() !== '') : [];
}

/** The file's word lists in the pool's shape; any list missing from it is empty. */
export function parseLexicon(json: unknown): { credit: LexiconCredit; lexicon: Lexicon } | null {
  if (!json || typeof json !== 'object') return null;
  const o = json as Record<string, any>;
  const w = o.words;
  if (!w || typeof w !== 'object' || typeof o.source !== 'string' || typeof o.license !== 'string') return null;
  const byDomain = (group: unknown) =>
    Object.fromEntries(keysOf(DOMAINS).map(d => [d, words((group as any)?.[d])])) as Lexicon['modifiers'];
  const lexicon: Lexicon = {
    modifiers: byDomain(w.modifiers),
    objects: byDomain(w.objects),
    verbs: Object.fromEntries(keysOf(VERB_KINDS).map(k => [k, words(w.verbs?.[k])])) as Lexicon['verbs'],
  };
  const credit: LexiconCredit = {
    source: o.source, publisher: String(o.publisher ?? ''), url: String(o.url ?? ''),
    license: o.license, licenseUrl: String(o.licenseUrl ?? ''), dumpCreated: o.dumpCreated ? String(o.dumpCreated) : undefined,
  };
  return { credit, lexicon };
}

export function lexiconSize(lexicon: Lexicon): number {
  return [lexicon.modifiers, lexicon.objects, lexicon.verbs]
    .reduce((n, group) => n + Object.values(group).reduce((m, list) => m + list.length, 0), 0);
}

/** Every extra list that loads, in the order of EXTRA_LEXICONS. */
export async function loadExtraLexicons(): Promise<LoadedLexicon[]> {
  const loaded = await Promise.all(EXTRA_LEXICONS.map(async ({ id, file, label }) => {
    try {
      const r = await fetch(new URL(file, document.baseURI).toString());
      const parsed = r.ok ? parseLexicon(await r.json()) : null;
      return parsed ? { id, label, ...parsed, size: lexiconSize(parsed.lexicon) } : null;
    } catch {
      return null;
    }
  }));
  return loaded.filter((l): l is LoadedLexicon => l !== null);
}
