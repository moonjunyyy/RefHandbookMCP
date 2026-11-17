// What every page starts from (docs/frame.md §1–§2): the frame (/auth/api/v1/me: who is signed in, the
// site's name, the apps and their widgets as this person may see them) and the person's own settings
// (/apps/site/api/store/prefs: language, theme, start page, the apps they turned on, their home). One
// load() for all of them; the language and the theme are applied at once and kept as site cookies so the
// server pages and the next first paint agree with the account.

import { setLang } from './i18n';
import { COLOR_ROLES, normalizeHex, paletteTokens } from './colors';
import type { ColorRole, ColorScheme, ThemeColors } from './colors';

/** A widget's cells on the grid: one of the sizes the site declares (`frame.sizes`, from portal/site.py SIZES). */
export interface Size { id: string; cols: number; rows: number }
/** A setting a widget declares ([[app.widget.param]]): one of `choices`, or one of the person's own objects read
 * `from` a path of the site (`list` in its answer; an item's `value` and `label`) with `all`, the word for no filter. */
export interface Param { id: string; label: string; default: string; choices?: { value: string; label: string }[];
                         from?: { path: string; list: string; value: string; label: string }; all?: string }
export interface Widget { id: string; title: string; description: string; href: string; size: string; params?: Param[] }

/** One way to connect to an app (site.toml's `code`): its value may name the person looking as {user}. */
export interface Address { label: string; value: string }
export interface Card { id: string; title: string; description: string; about: string; tags: string[]; code: Address[]; icon: string;
                        href: string; optional: boolean; default: boolean; links: { label: string; href: string }[]; widgets: Widget[] }
/** One choice of the person's look (docs/frame.md §1.3), as the site file declares it: the tokens it redeclares —
 * a palette for each theme, the others once. The first choice of a kind is theme.css's own (nothing redeclared).
 * A font choice also names the open fonts it needs (`fonts`: ids, their stylesheets at `Look.fonts`) and the
 * group the settings page lists it under (`group`: a word of `Look.groups`). */
export interface LookChoice { id: string; label: string; tokens?: Record<string, string>; light?: Record<string, string>; dark?: Record<string, string>;
                              fonts?: string[]; group?: string }
export interface Look { palette: LookChoice[]; corner: LookChoice[]; type: LookChoice[]; heading: LookChoice[]; mono: LookChoice[]; size: LookChoice[];
                        columns: number[]; fonts: string; groups: Record<string, string> }
export const LOOK_KINDS = ['palette', 'corner', 'type', 'heading', 'mono', 'size'] as const;
export type LookKind = (typeof LOOK_KINDS)[number];
/** The look's fonts: the body's (--sans), the headings' (--serif), the code's (--mono). */
export const FONT_KINDS = ['type', 'heading', 'mono'] as const;
export type FontKind = (typeof FONT_KINDS)[number];
/** What the person picked: a choice of each kind (its id), the main page's columns (0: as many as fit), an image. */
export interface LookPrefs { palette?: string; corner?: string; type?: string; heading?: string; mono?: string; size?: string; columns?: number; image?: string;
  accent?: string; colors?: Partial<Record<ColorScheme, ThemeColors>>; radius?: number; imageBlur?: number; imageDim?: number;
}
export interface Frame { uid: string | null; title: string; signin: string; portal: string; lang: string;
                         theme: string; frame: number; cards: Card[]; menu: { label: string; href: string }[]; sizes: Size[]; look: Look }

export const THEMES = ['auto', 'light', 'dark'] as const;
export type Theme = (typeof THEMES)[number];

/** A place a person gave a widget: its size and title (their own, else the widget's) and its settings (the
 * widget's declared parameters, as they set them here). The same widget may have several places. */
export interface Placement { app: string; widget: string; size?: string; title?: string; params?: Record<string, string> }
export interface Prefs {
  lang: string;        // 'auto' (the browser's), or a language the site has
  theme: Theme;        // 'auto' (the OS's), 'light' or 'dark'
  start: string;       // '/' (the main page) or an address of the site to open after signing in
  apps: string[];      // the apps the person turned on, in their order; a new account starts with the apps the site file marks default
  home: Placement[];   // the main page's widgets, in their order; [] = each app's first widget, as turned on
  seen: string[];      // app ids the person has been shown: any other is new to them
  guides?: string[]; // completed/skipped guide versions, separate from catalog discovery
  homeCustomized?: boolean;  // an explicitly empty home is different from the initial launchers
  look: LookPrefs;     // the person's look over theme.css (docs/frame.md §1.3); {} = theme.css as it is
}

/** The settings an account starts with. `apps`: the apps the site file marks `default = true` (docs/frame.md §2
 * R13) — filled from the frame once it is loaded; a kept `apps`, an empty one too, is the person's own choice. */
export const DEFAULTS: Prefs = { lang: 'auto', theme: 'auto', start: '/', apps: [], home: [], seen: [], look: {} };
export const frame: Frame = { uid: null, title: '', signin: '/auth', portal: '/account', lang: 'ko', theme: 'auto', frame: 0,
                              cards: [], menu: [], sizes: [], look: { palette: [], corner: [], type: [], heading: [], mono: [], size: [], columns: [], fonts: '', groups: {} } };

/** An image under the page: an address of this site or an https one, nothing that could leave the url("…"). */
export const IMAGE = /^(https:\/\/|\/(?!\/))[^\s"'()\\<>;{}]{1,500}$/;
const LOOK = 'look';  // this browser's copy of the tokens, for theme.js to put on before the first paint

/** Base colors are the actual theme's tokens, with the selected preset applied. */
export function lookColors(look: Look, p: LookPrefs, scheme: ColorScheme): Record<ColorRole, string> {
  const style = getComputedStyle(document.documentElement);
  const preset = look.palette.find(c => c.id === p.palette)?.[scheme];
  const overrides = p.colors?.[scheme];
  const legacy = normalizeHex(p.accent);
  const result = Object.fromEntries(COLOR_ROLES.map(role => {
    const token = role === 'link' ? 'accent' : role;
    const base = preset?.[token] ?? style.getPropertyValue('--' + scheme + '-' + token);
    return [role, normalizeHex(overrides?.[role]) ?? ((role === 'accent' || role === 'link') ? legacy : undefined)
      ?? normalizeHex(base) ?? normalizeHex(style.getPropertyValue('--' + token)) ?? '#' + (scheme === 'dark' ? 'f' : '0').repeat(6)];
  }));
  return result as Record<ColorRole, string>;
}

/** The result of applying one scheme's editor, or undefined for incompatible surfaces. */
export function editedColors(look: Look, p: LookPrefs, scheme: ColorScheme): Record<string, string> | undefined {
  return paletteTokens(lookColors(look, p, scheme));
}

const inRange = (value: number | undefined, max: number): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= max;

/** Where an open font's stylesheet is (web/fonts.json builds it; the site file says where it is served). */
export const fontSheet = (id: string, look: Look = frame.look): string => `${look.fonts}${id}.css`;

/** The open fonts' stylesheets, for showing choices in their own faces (the settings page): linked once each,
 * apart from the look's own (applyLook keeps those). */
export function previewFonts(ids: string[] = []): void {
  for (const id of ids) {
    const href = fontSheet(id);
    if (!frame.look.fonts || document.head.querySelector(`link[data-font-preview="${CSS.escape(id)}"]`)) continue;
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = href; l.dataset.fontPreview = id;
    document.head.append(l);
  }
}

export interface LookTokens { light: Record<string, string>; dark: Record<string, string>; both: Record<string, string>; fonts: string[] }

/** The tokens the person's look redeclares, by theme: the palette's for each, the rest for both (a heading chosen
 * wins over what a body font says of --serif); and the stylesheets of the open fonts its choices need — a kind
 * not chosen is its first choice, theme.css's own, which names the open font theme.css puts first. */
export function lookTokens(look: Look, p: LookPrefs): LookTokens {
  const pick = (k: LookKind) => look[k]?.find(c => c.id === p[k]);
  const pal = pick('palette');
  const both: Record<string, string> = { ...pick('corner')?.tokens, ...pick('type')?.tokens, ...pick('heading')?.tokens, ...pick('mono')?.tokens,
                                         ...pick('size')?.tokens };
  const fonts = look.fonts ? [...new Set(FONT_KINDS.flatMap(k => (pick(k) ?? look[k]?.[0])?.fonts ?? []))].map(id => fontSheet(id, look)) : [];
  if (p.columns && look.columns.includes(p.columns)) {
    const gap = p.columns - 1;
    both['home-grid'] = 'repeat(auto-fill, minmax(min(100%, max(12rem, calc((100% - ' + gap
      + ' * var(--gap)) / ' + p.columns + '))), 1fr))';
  }
  if (inRange(p.radius, 100)) {
    both.radius = Math.round(p.radius * .24) + 'px';
    both['radius-s'] = Math.round(p.radius * .10) + 'px';
  }
  if (p.image && IMAGE.test(p.image)) {
    both['page-image'] = 'url("' + p.image + '")';
    both['page-blur'] = (inRange(p.imageBlur, 30) ? p.imageBlur : 0) + 'px';
    both['page-dim'] = (inRange(p.imageDim, 100) ? p.imageDim : 25) + '%';
    both['page-surface'] = 'var(--bg)';
  }
  const custom = (scheme: ColorScheme) => {
    const own = p.colors?.[scheme];
    if (!normalizeHex(p.accent) && !COLOR_ROLES.some(role => normalizeHex(own?.[role]))) return {};
    return editedColors(look, p, scheme) ?? {};
  };
  return { light: { ...pal?.light, ...custom('light') }, dark: { ...pal?.dark, ...custom('dark') }, both, fonts };
}

/** The look onto <html> as custom properties (the CSSOM, which the pages' CSP allows; an inline style outranks the
 * theme's selectors), the palette of the theme in force; and into this browser for the next first paint. */
export function applyLook(): void {
  const t = lookTokens(frame.look, prefs.look ?? {});
  try { localStorage.setItem(LOOK, JSON.stringify(t)); } catch { /* storage may be off */ }
  putLook(t);
}
function putLook(t: LookTokens): void {
  const el = document.documentElement;
  for (const name of Array.from(el.style)) if (name.startsWith('--')) el.style.removeProperty(name);
  const set = el.getAttribute('data-theme');
  const dark = set ? set === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  for (const [k, v] of Object.entries({ ...(dark ? t.dark : t.light), ...t.both })) el.style.setProperty(`--${k}`, v);
  // the chosen fonts' stylesheets in <head> (theme.js put the last ones on before the first paint): the ones no longer chosen go
  const kept = Array.from(document.head.querySelectorAll<HTMLLinkElement>('link[data-look-font]'));
  for (const l of kept) if (!t.fonts.includes(l.getAttribute('href') ?? '')) l.remove();
  for (const href of t.fonts) {
    if (kept.some(l => l.getAttribute('href') === href && l.isConnected)) continue;
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = href; l.setAttribute('data-look-font', '');
    document.head.append(l);
  }
}
let schemeWatched = false;
/** The size a placement has: its own, else its widget's; unknown ids fall back to the first declared size. */
export function sizeOf(id: string | undefined): Size {
  return frame.sizes.find(s => s.id === id) ?? frame.sizes[0] ?? { id: '1x1', cols: 1, rows: 1 };
}
export const prefs: Prefs = { ...DEFAULTS };

const STORE = '/apps/site/api/store/prefs';
const LOCAL = 'prefs';
const KNOWN = 'prefs-known';  // this browser has seen the account's settings in the store

/** The person's theme onto the document, and into the site cookie theme.js reads before the first paint. */
export function applyTheme(theme: string): void {
  const v: Theme = (THEMES as readonly string[]).includes(theme) ? (theme as Theme) : 'auto';
  if (v === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', v);
  document.cookie = `theme=${v}; path=/; max-age=31536000; samesite=lax`;
  frame.theme = v;
  applyLook();  // the palette follows the theme in force
  if (!schemeWatched) { schemeWatched = true; matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyLook()); }
}

/** What is kept from an older account: `hidden`/`order` (every app shown unless hidden) become `apps`
 * (nothing on unless turned on) — the apps that were shown, in their order. The stored data is not rewritten.
 * An account with nothing kept starts with the site's default apps; a kept `apps` is kept even when it is empty. */
function fromStored(raw: Record<string, unknown>, cards: Card[]): Prefs {
  const p: Prefs = { ...DEFAULTS, ...raw, apps: [...DEFAULTS.apps] } as Prefs;
  if ('apps' in raw) p.apps = Array.isArray(raw.apps) ? (raw.apps as string[]) : [];
  if (!Array.isArray(p.home)) p.home = [];
  p.guides = Array.isArray(p.guides) ? p.guides.filter((x): x is string => typeof x === 'string') : [];
  if (!('apps' in raw) && (Array.isArray(raw.order) || Array.isArray(raw.hidden))) {
    const hidden = new Set((raw.hidden as string[]) ?? []);
    const order = (raw.order as string[]) ?? [];
    const ids = cards.filter(c => c.optional).map(c => c.id);
    const rank = (id: string) => { const i = order.indexOf(id); return i < 0 ? order.length + ids.indexOf(id) : i; };
    p.apps = ids.filter(id => !hidden.has(id)).sort((a, b) => rank(a) - rank(b));
  }
  if (!(THEMES as readonly string[]).includes(p.theme)) p.theme = 'auto';
  if (!p.look || typeof p.look !== 'object' || Array.isArray(p.look)) p.look = {};
  return p;
}

function remember(): void {
  try { localStorage.setItem(LOCAL, JSON.stringify(prefs)); } catch { /* storage may be off */ }
  document.cookie = `lang=${prefs.lang}; path=/; max-age=31536000; samesite=lax`;
  applyTheme(prefs.theme);
}

/** The frame and the person's settings, applied: call once, before drawing anything. Never throws for a
 * signed-out person or an unreachable store (what this browser last had, else the defaults). */
export async function load(): Promise<Frame> {
  try {
    const r = await fetch('/auth/api/v1/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (r.ok) Object.assign(frame, await r.json());
  } catch { /* the frame stays as it is: a page still draws */ }
  // an answer from an older sign-in (or a test's) may lack the newer fields: every card is whole here
  frame.cards = (frame.cards ?? []).map(c => ({ description: '', about: '', tags: [], code: [], icon: '', href: '', optional: true, default: false, links: [], widgets: [], ...(c as Partial<Card>) } as Card))
    .map(c => typeof (c.code as unknown) === 'string' ? { ...c, code: (c.code as unknown as string) ? [{ label: '', value: c.code as unknown as string }] : [] } : c);
  frame.menu ??= [];
  frame.sizes = Array.isArray(frame.sizes) && frame.sizes.length ? frame.sizes : [{ id: '1x1', cols: 1, rows: 1 }];
  const given: Partial<Look> = frame.look ?? {};  // an older sign-in's answer has no look: theme.css as it is
  frame.look = { palette: given.palette ?? [], corner: given.corner ?? [], type: given.type ?? [], heading: given.heading ?? [], mono: given.mono ?? [],
                 size: given.size ?? [], columns: given.columns ?? [], fonts: given.fonts ?? '', groups: given.groups ?? {} };
  DEFAULTS.apps = frame.cards.filter(c => c.default && c.optional).map(c => c.id);  // R13: the site file says which
  let raw: Record<string, unknown> = {};
  try { raw = JSON.parse(localStorage.getItem(LOCAL) ?? '{}'); } catch { /* none kept here */ }
  if (frame.uid) {
    try {
      // a key never saved answers 404, which the browser reports as an error: so a browser that has not
      // seen the account's settings yet asks the store's list first, and only once
      let known = localStorage.getItem(KNOWN) === '1';
      if (!known) {
        const r = await fetch(STORE.replace(/\/prefs$/, ''), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        known = r.ok && ((await r.json()) as { keys: { key: string }[] }).keys.some(k => k.key === 'prefs');
      }
      if (known) {
        const r = await fetch(STORE, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        if (r.ok) { raw = await r.json(); localStorage.setItem(KNOWN, '1'); }
        else if (r.status === 404) raw = {};  // deleted meanwhile: the defaults
      } else {
        raw = {};  // never saved: the defaults
      }
    } catch { /* the store is not reachable: what this browser had */ }
  }
  Object.assign(prefs, fromStored(raw, frame.cards));
  setLang(prefs.lang);
  remember();
  return frame;
}

let preferenceWrite: Promise<void> = Promise.resolve();

/** Save changes in order. Apply only accepted settings to the page and its first-paint cache. */
export function savePrefs(update: Partial<Prefs> | (() => Partial<Prefs>)): Promise<void> {
  const write = preferenceWrite.then(async () => {
    const change = typeof update === 'function' ? update() : update;
    const next = { ...prefs, ...change };
    if (frame.uid) {
      const r = await fetch(STORE, { method: 'PUT', credentials: 'same-origin', body: JSON.stringify(next),
                                   headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' } });
      if (!r.ok) throw new Error(`prefs: ${r.status}`);
      try { localStorage.setItem(KNOWN, '1'); } catch { /* storage may be off */ }
    }
    Object.assign(prefs, next);
    if ('lang' in change) setLang(prefs.lang);
    remember();
  });
  preferenceWrite = write.catch(() => undefined);
  return write;
}

/** The apps the person has on, as cards, in their order (apps that cannot be turned off are not here:
 * they live in the person's own menu). */
export const onApps = (): Card[] =>
  prefs.apps.map(id => frame.cards.find(c => c.id === id && c.optional)).filter((c): c is Card => !!c);

/** The app of the page being shown, when the page is an app's (served under /apps/<id>/). */
export function ownCard(base: string = document.baseURI): Card | undefined {
  const m = /\/apps\/([^/]+)\//.exec(new URL(base).pathname);
  return m ? frame.cards.find(c => c.id === m[1]) : undefined;
}
