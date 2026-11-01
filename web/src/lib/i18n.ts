// The pages' own words in the site's languages. Which language is on, the frame decides
// (/auth/static/site.js: the person's setting, kept with their account); this is only the pages'
// catalog, src/i18n/<lang>/. Korean is the source: a text is written in Korean and is its own key; each
// other language falls back to it. tests/portal/test_i18n.py checks every t('…') has its English, and
// that no Korean is left outside t().

import { lang } from '/auth/static/site.js';
import { EN } from '../i18n/en';

const CATALOGS: Record<string, Record<string, string>> = { en: EN };

/** A text kept as it is (a table built before the language is known), translated where it is shown:
 * t(TABLE[x]). Marked, so the catalog test finds it. */
export const n_ = (text: string) => text;

/** `text` (Korean) in the page's language, its {values} filled in. */
export function t(text: string, values?: Record<string, string | number>): string {
  const l = lang();
  const out = (l === 'ko' ? undefined : CATALOGS[l]?.[text]) ?? text;
  return values ? out.replace(/\{(\w+)\}/g, (m, k: string) => (k in values ? String(values[k]) : m)) : out;
}
