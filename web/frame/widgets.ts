// The main page's widgets (docs/frame.md §4): an app's piece, drawn into a cell by the module the app
// declared ([[app.widget]] → me.cards[].widgets[].href). The frame imports the module and hands it the
// cell and a context; the module calls its own app's API. An app with no module, and a module that
// fails, gets the launcher: the app's mark, name and links.

import { Child, h, replace } from './dom';
import { Card, Widget, frame, prefs, sizeOf } from './frame';
import { lang, t } from './i18n';
import { api, go } from './parts';

export interface WidgetContext { frame: typeof frame; prefs: typeof prefs; t: typeof t; lang: string; theme: string;
                                 go: typeof go; api: typeof api; card: Card; widget: Widget }
export type WidgetModule = { default: (host: HTMLElement, ctx: WidgetContext) => void | (() => void) | Promise<void | (() => void)> };

/** The widget every app has: a launcher — its mark and name, the way in; an app with more than one page lists
 * them. What the app is and its address are the store's to say (/app/<id>), not the main page's. */
export function launcher(c: Card): HTMLElement {
  const pages = c.links.filter((l, i, all) => l.href && all.findIndex(x => x.href === l.href) === i);
  const more = pages.length > 1 && pages.some(l => l.href !== c.href);
  return h('div', { class: `launcher${more ? '' : ' single'}` },
    h('h2', null, c.icon && h('span', { class: 'app-icon big', 'aria-hidden': 'true' }, c.icon),
      c.href ? h('a', { href: c.href }, c.title) : c.title),
    more && h('div', { class: 'links' }, pages.map(l => h('a', { href: l.href }, l.label))));
}

export const LAUNCHER = 'launcher';

/** The widgets an app offers: the launcher first, then the ones it declared. */
export function widgetsOf(c: Card): Widget[] {
  return [{ id: LAUNCHER, title: c.title, description: c.description, href: '', size: sizeOf(undefined).id }, ...c.widgets];
}

/** A cell's place on the grid for a size: the spans, as inline style (no class per size — the sizes are the
 * site's declaration, docs/frame.md §4). */
export function spanStyle(sizeId: string | undefined): string {
  const s = sizeOf(sizeId);
  return `grid-column: span ${s.cols}; grid-row: span ${s.rows};`;
}

/** Draw a widget into its cell: the module when there is one, the launcher otherwise or on failure. */
export async function mount(cell: HTMLElement, c: Card, w: Widget): Promise<void> {
  const body = h('div', { class: 'widget-body' });
  replace(cell, w.id === LAUNCHER ? null : h('div', { class: 'widget-head' },
    c.icon && h('span', { class: 'app-icon', 'aria-hidden': 'true' }, c.icon), h('a', { href: c.href }, c.title), ' · ', w.title), body);
  if (w.id === LAUNCHER || !w.href) { replace(body, launcher(c)); return; }
  try {
    const mod = (await import(/* @vite-ignore */ w.href)) as WidgetModule;
    if (typeof mod.default !== 'function') throw new Error(`${w.href}: no default export`);
    await mod.default(body, { frame, prefs, t, lang: lang(), theme: frame.theme, go, api, card: c, widget: w });
  } catch (e) {
    console.warn('widget', c.id, w.id, e);  // the person sees the launcher; the console says why
    replace(body, launcher(c));
  }
}

/** A list inside a widget: the common shape (a title, items with a link each). */
export function widgetList(items: { href: string; text: Child; aside?: Child }[], none: string): HTMLElement {
  return items.length ? h('ul', { class: 'widget-list' }, items.map(i => h('li', null, h('a', { href: i.href }, i.text), i.aside && [' ', h('span', { class: 'muted small' }, i.aside)])))
    : h('p', { class: 'muted small' }, none);
}

export const openWord = () => t('열기');
