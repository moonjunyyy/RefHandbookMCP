// The app catalog (/apps) and an app's page (/app/<id>) — a store (docs/apps-vault-calendar.md §1): every
// app of the site says its name, its one line and its tags on a card, and a switch turns it on — on, and it
// is in the person's header and on their main page; off, and it is only here. Nothing is on until they turn
// it on (docs/frame.md §2–§3). A search and a row of chips (all · mine · the tags) narrow the cards; the
// order is the site file's. The app's page says more: what it does, the widgets it offers the main page,
// its links. Seeing the catalog marks every app seen (its "new" tag goes).

import { choice, frame, h, main, onApps, pageHead, prefs, primaryLink, replace, savePrefs, section, tag, title, toggle, widgetsOf, link } from '/auth/static/site.js';
import type { Card } from '/auth/static/site.js';
import { t } from '../lib/i18n';

const ALL = '';
const MINE = 'mine';

/** Turn an app on or off: it enters (leaves) the person's apps and, when they arranged their main page by
 * hand, its launcher enters (its widgets leave) that arrangement. */
export async function setOn(c: Card, on: boolean): Promise<void> {
  const apps = on ? [...prefs.apps.filter(x => x !== c.id), c.id] : prefs.apps.filter(x => x !== c.id);
  let home = prefs.home;
  if (home.length) home = on ? [...home, { app: c.id, widget: 'launcher' }] : home.filter(p => p.app !== c.id);
  await savePrefs({ apps, home });
}

const fresh = (c: Card) => prefs.seen.length > 0 && !prefs.seen.includes(c.id);

/** The one switch of an app: on or off, kept at once. */
function onOff(c: Card, after: () => void): HTMLElement | false {
  const on = prefs.apps.includes(c.id);
  return !!frame.uid && toggle(on ? t('켬') : t('끔'), on, async v => { await setOn(c, v); after(); }, { 'aria-label': t('{app} 켜기', { app: c.title }) });
}

/** The catalog: a search, the chips, the cards. Also the main page when nothing is on yet. */
export function catalog(query = '', chip = ALL): HTMLElement {
  const all = frame.cards.filter(c => c.optional);
  const tags = [...new Set(all.flatMap(c => c.tags))];
  const grid = h('div', { class: 'store' });
  const search = h('input', { type: 'search', value: query, placeholder: t('앱 찾기'), 'aria-label': t('앱 찾기'), autofocus: true,
                              oninput: () => { draw(); remember(); } });
  const chips = choice([[ALL, t('전체')], ...(frame.uid ? [[MINE, t('내 앱')] as [string, string]] : []), ...tags.map(x => [x, x] as [string, string])],
                       chip, v => { chip = v; draw(); remember(); }, { 'aria-label': t('앱의 갈래') });

  function remember(): void {
    const q = new URLSearchParams();
    if (search.value) q.set('q', search.value);
    if (chip) q.set('tag', chip);
    history.replaceState(null, '', q.toString() ? `${location.pathname}?${q}` : location.pathname);
  }

  function card(c: Card): HTMLElement {
    const on = prefs.apps.includes(c.id);
    return h('article', { class: `store-card${on ? ' on' : ''}`, 'data-app': c.id },
      h('span', { class: 'app-icon big', 'aria-hidden': 'true' }, c.icon || c.title.slice(0, 1)),
      h('div', { class: 'store-text' },
        h('h3', null, link(`/app/${c.id}`, c.title), fresh(c) && [' ', tag(t('새 앱'), 'ok')]),
        c.description && h('p', { class: 'desc' }, c.description),
        c.tags.length > 0 && h('p', { class: 'tags' }, c.tags.map(x => tag(x)))),
      h('div', { class: 'app-tools' }, onOff(c, draw)));
  }

  function draw(): void {
    const q = search.value.trim().toLowerCase();
    let list = chip === MINE ? onApps() : chip ? all.filter(c => c.tags.includes(chip)) : all;
    if (q) list = list.filter(c => `${c.title} ${c.description} ${c.about} ${c.tags.join(' ')} ${c.links.map(l => l.label).join(' ')}`.toLowerCase().includes(q));
    replace(grid, list.length ? list.map(card) : h('p', { class: 'empty muted' }, q || chip ? t('찾는 앱이 없습니다.') : t('쓸 수 있는 앱이 없습니다.')));
  }

  draw();
  return h('div', { class: 'catalog' }, search, chips, grid);
}

export async function apps(): Promise<void> {
  const params = new URLSearchParams(location.search);
  title(t('앱'));
  replace(main(), pageHead(t('앱')), catalog(params.get('q') ?? '', params.get('tag') ?? ALL),
    !frame.uid && h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/apps`, t('로그인'))));
  (main().querySelector('input[type=search]') as HTMLInputElement | null)?.focus();
  markSeen();
}

function markSeen(): void {
  if (!frame.uid) return;
  const ids = frame.cards.filter(c => c.optional).map(c => c.id);
  if (ids.some(id => !prefs.seen.includes(id))) void savePrefs({ seen: ids }).catch(() => undefined);
}

/** An app's page: its name and line, the switch, what it does, what it puts on the main page, its links. */
export async function app(id: string): Promise<void> {
  const c = frame.cards.find(x => x.id === id && x.optional);
  if (!c) {
    title(t('없는 앱'));
    replace(main(), pageHead(t('없는 앱')), section('', h('p', null, link('/apps', t('앱')))));
    return;
  }
  title(c.title);
  const head = h('div', { class: 'page-head store-head' });
  const open = h('p', { class: 'actions' });

  function draw(): void {
    const on = prefs.apps.includes(c!.id);
    replace(head,
      h('span', { class: 'app-icon big', 'aria-hidden': 'true' }, c!.icon || c!.title.slice(0, 1)),
      h('div', { class: 'store-text' }, h('h1', null, c!.title, fresh(c!) && [' ', tag(t('새 앱'), 'ok')]),
        c!.description && h('p', { class: 'desc' }, c!.description), c!.tags.length > 0 && h('p', { class: 'tags' }, c!.tags.map(x => tag(x)))),
      h('div', { class: 'app-tools' }, onOff(c!, draw)));
    replace(open, on && c!.href && primaryLink(c!.href, t('열기')));
  }
  draw();
  const widgets = widgetsOf(c);
  replace(main(), head, open,
    c.about && h('p', { class: 'about' }, c.about),
    section(t('홈에 올릴 수 있는 위젯'), h('ul', { class: 'plain' }, widgets.map(w => h('li', null, w.title, ' ', h('span', { class: 'muted small' }, w.size))))),
    c.links.length > 0 && section(t('링크'), h('ul', { class: 'plain' }, c.links.map(l => h('li', null, link(l.href, l.label))))),
    c.code && section(t('연결 주소'), h('p', null, h('code', { class: 'address' }, c.code))));
  markSeen();
}
