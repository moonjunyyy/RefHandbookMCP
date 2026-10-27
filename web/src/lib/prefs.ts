// Each person's settings for the site's pages, kept with their account (the pages app's own store,
// /apps/site/api/store/prefs; portal/apps.py), so they follow them to any browser: the language, the
// page to open after signing in, and which apps the main page shows, in what order.

import { Card, frame } from './api';
import { t } from './i18n';

export interface Prefs {
  lang: string;      // 'auto' (the browser's), or a language of lib/i18n.ts
  start: string;     // '/' (the main page) or an address of the site to open after signing in
  order: string[];   // app ids, in the order the main page shows them (apps not named come after)
  hidden: string[];  // app ids the main page leaves out (the app list still shows them)
  seen: string[];    // app ids the person has been shown: any other is new to them
}

export const DEFAULTS: Prefs = { lang: 'auto', start: '/', order: [], hidden: [], seen: [] };
export const prefs: Prefs = { ...DEFAULTS };

const URL = '/apps/site/api/store/prefs';
const LOCAL = 'prefs';

/** Read them (signed in: from the account; else, or if that fails, as this browser last had them). */
export async function loadPrefs(): Promise<void> {
  try { Object.assign(prefs, JSON.parse(localStorage.getItem(LOCAL) ?? '{}')); } catch { /* none kept here */ }
  if (!frame.uid) return;
  try {
    const r = await fetch(URL, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (r.ok) Object.assign(prefs, { ...DEFAULTS, ...(await r.json()) });
    else if (r.status === 404) Object.assign(prefs, DEFAULTS);  // never saved: the defaults
  } catch { /* the store is not reachable: what this browser had */ }
  remember();
}

/** Keep them: with the account, and in this browser (for the next first paint). True once kept (so
 * act() can tell a save from a refusal). */
export async function savePrefs(change: Partial<Prefs>): Promise<true> {
  Object.assign(prefs, change);
  remember();
  const r = await fetch(URL, { method: 'PUT', credentials: 'same-origin', body: JSON.stringify(prefs),
                               headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' } });
  if (!r.ok) throw new Error(t('설정을 저장하지 못했습니다 ({status})', { status: r.status }));
  return true;
}

function remember(): void {
  localStorage.setItem(LOCAL, JSON.stringify(prefs));
  // the server pages (sign-in, approvals) read the language from a cookie of the whole site
  document.cookie = `lang=${prefs.lang}; path=/; max-age=31536000; samesite=lax`;
}

/** The apps the main page shows: in the person's order (any app they have not placed: after, as the
 * site lists it), without those they hid. */
export function arranged(cards: Card[], withHidden = false): Card[] {
  const rank = (c: Card) => { const i = prefs.order.indexOf(c.id); return i < 0 ? prefs.order.length + cards.indexOf(c) : i; };
  return [...cards].sort((a, b) => rank(a) - rank(b)).filter(c => withHidden || !prefs.hidden.includes(c.id));
}

/** Apps the person has not been shown yet (new on the site since). */
export const unseen = (cards: Card[]) => cards.filter(c => !prefs.seen.includes(c.id));
