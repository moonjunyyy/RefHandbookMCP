// The frame's own words (the header, the parts' buttons, the main page's edit mode) in the site's languages.
// Korean is the source and its own key; each other language is a catalog (frame/i18n/<lang>.ts), falling
// back to the Korean. The pages (web/src) and the apps keep catalogs of their own for their own words;
// they ask the frame only which language is on. tests/portal/test_i18n.py holds this file to the same rule.

import { EN } from './i18n/en';

export const LANGS: [string, string][] = [['ko', '한국어'], ['en', 'English']];  // i18n: data (each in its own)
const CATALOGS: Record<string, Record<string, string>> = { en: EN };
const LOCALES: Record<string, string> = { ko: 'ko-KR', en: 'en-US' };

let current = 'ko';

/** The language to show for a setting: itself if we have it, else for 'auto' the browser's first one we have. */
export function resolveLang(pref: string): string {
  const known = (x: string) => LANGS.some(([code]) => code === x);
  const fromBrowser = (navigator.languages ?? [navigator.language]).map(x => x.toLowerCase().split('-')[0]).find(known);
  return known(pref) ? pref : fromBrowser ?? 'ko';
}

export function setLang(pref: string): string {
  current = resolveLang(pref);
  document.documentElement.lang = current;
  return current;
}

export const lang = () => current;
export const locale = () => LOCALES[current] ?? 'ko-KR';

/** A text kept as it is (a table built before the language is known), translated where it is shown. */
export const n_ = (text: string) => text;

/** `text` (Korean) in the page's language, its {values} filled in. */
export function t(text: string, values?: Record<string, string | number>): string {
  const out = (current === 'ko' ? undefined : CATALOGS[current]?.[text]) ?? text;
  return values ? out.replace(/\{(\w+)\}/g, (m, k: string) => (k in values ? String(values[k]) : m)) : out;
}
