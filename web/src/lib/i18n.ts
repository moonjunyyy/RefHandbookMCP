// The pages' languages (the server pages' are portal/i18n.py, with the same rules). Korean is the
// source: a text is written in Korean and is its own key; each other language has a catalog
// (src/i18n/<lang>/), falling back to the Korean. A text with values names them {name}:
// t('블럭 {n}개', { n }). A table built at load marks its texts n_('…') and shows t(TABLE[x]). tests/portal/test_i18n.py checks every t('…') has its English, and that no
// Korean is left outside t().

import { EN } from '../i18n/en';

export const LANGS: [string, string][] = [['ko', '한국어'], ['en', 'English']];  // i18n: data (each in its own)
const CATALOGS: Record<string, Record<string, string>> = { en: EN };
const LOCALES: Record<string, string> = { ko: 'ko-KR', en: 'en-US' };

let lang = 'ko';

/** The language to show: the person's setting, or for 'auto' the browser's first one we have. */
export function setLang(pref: string): void {
  const known = (x: string) => LANGS.some(([code]) => code === x);
  const fromBrowser = (navigator.languages ?? [navigator.language]).map(x => x.toLowerCase().split('-')[0]).find(known);
  lang = known(pref) ? pref : fromBrowser ?? 'ko';
  document.documentElement.lang = lang;
}

export const currentLang = () => lang;
export const locale = () => LOCALES[lang] ?? 'ko-KR';

/** A text kept as it is (a table built before the language is known), translated where it is shown:
 * t(TABLE[x]). Marked, so the catalog test finds it. */
export const n_ = (text: string) => text;

/** `text` (Korean) in the page's language, its {values} filled in. */
export function t(text: string, values?: Record<string, string | number>): string {
  const out = (lang === 'ko' ? undefined : CATALOGS[lang]?.[text]) ?? text;
  return values ? out.replace(/\{(\w+)\}/g, (m, k: string) => (k in values ? String(values[k]) : m)) : out;
}
