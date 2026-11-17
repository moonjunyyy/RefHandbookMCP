// The store (/apps) and an app's page (/app/<id>) (docs/apps-vault-calendar.md §1). The apps the person added
// come first, as tiles that open them (each tile's ⋯ and right-click: the app's page, remove); below them the
// store — every app not added yet as a card (its mark, name, one line, tags) with one action, 추가. Nothing is
// added until they add it (docs/frame.md §2–§3); an added app is in their header and on their main page. A
// search and the tag chips narrow both; the store's order is the site file's, the tiles' the order they were
// added. The app's page says more — what it does, the widgets it offers the main page, its links — and its one
// action is 추가, or 열기 with 빼기 beside it. Seeing the store marks every app seen (its "new" tag goes).

import { button, cellsOf, choice, frame, go, h, link, main, menuButton, onApps, onMenu, pageHead, prefs, primaryLink, replace, savePrefs, section, sizeOf, tag, title, widgetsOf } from '/auth/static/site.js';
import type { Address, Card, MenuSection } from '/auth/static/site.js';
import { t } from '../lib/i18n';
import { copyText } from '../lib/clipboard';

const ALL = '';

/** Add an app or take it out: it enters (leaves) the person's apps and, when they arranged their main page by
 * hand, its launcher enters (its widgets leave) that arrangement. */
export async function setOn(c: Card, on: boolean): Promise<void> {
  await savePrefs(() => {
    const apps = on ? [...prefs.apps.filter(x => x !== c.id), c.id] : prefs.apps.filter(x => x !== c.id);
    let home = prefs.home;
    if (home.length || prefs.homeCustomized) home = on ? [...home.filter(p => p.app !== c.id || p.widget !== 'launcher'), { app: c.id, widget: 'launcher' }]
      : home.filter(p => p.app !== c.id);
    return { apps, home };
  });
}

const fresh = (c: Card) => prefs.seen.length > 0 && !prefs.seen.includes(c.id);
const mark = (c: Card, big = true) => h('span', { class: `app-icon${big ? ' big' : ''}`, 'aria-hidden': 'true' }, c.icon || c.title.slice(0, 1));
const added = (c: Card) => prefs.apps.includes(c.id);

/** The store: a search, the chips, the person's apps, the apps to add. */
export function catalog(query = '', chip = ALL): HTMLElement {
  const all = frame.cards.filter(c => c.optional);
  const tags = [...new Set(all.flatMap(c => c.tags))];
  const mine = h('div');
  const rest = h('div');
  const search = h('input', { type: 'search', value: query, placeholder: t('앱 찾기'), 'aria-label': t('앱 찾기'), autofocus: true,
                              oninput: () => { draw(); remember(); } });
  const chips = tags.length > 0 && choice([[ALL, t('전체')], ...tags.map(x => [x, x] as [string, string])],
                                          chip, v => { chip = v; draw(); remember(); }, { 'aria-label': t('앱의 갈래') });

  function remember(): void {
    const q = new URLSearchParams();
    if (search.value) q.set('q', search.value);
    if (chip) q.set('tag', chip);
    history.replaceState(null, '', q.toString() ? `${location.pathname}?${q}` : location.pathname);
  }

  const shown = (c: Card) => {
    const q = search.value.trim().toLowerCase();
    return (!chip || c.tags.includes(chip))
      && (!q || `${c.title} ${c.description} ${c.about} ${c.tags.join(' ')} ${c.links.map(l => l.label).join(' ')}`.toLowerCase().includes(q));
  };

  /** An added app: its mark and name open it; its menu has its page and the way out. */
  function tile(c: Card): HTMLElement {
    const sections = (): MenuSection[] => [{ title: c.title, items: [
      { label: t('앱 정보'), run: () => go(`/app/${c.id}`) },
      { label: t('빼기'), danger: true, run: async () => { await setOn(c, false); draw(); } } ] }];
    const el = h('div', { class: 'my-app', 'data-app': c.id },
      h('a', { href: c.href || `/app/${c.id}` }, mark(c), h('span', { class: 'my-app-name' }, c.title)),
      menuButton(sections, t('{app} 메뉴', { app: c.title })));
    onMenu(el, sections);
    return el;
  }

  /** An app not added yet: what it is, and 추가. */
  function card(c: Card): HTMLElement {
    return h('article', { class: 'store-card', 'data-app': c.id },
      mark(c),
      h('div', { class: 'store-text' },
        h('h3', null, link(`/app/${c.id}`, c.title), fresh(c) && [' ', tag(t('새 앱'), 'ok')]),
        c.description && h('p', { class: 'desc' }, c.description),
        c.tags.length > 0 && h('p', { class: 'tags' }, c.tags.map(x => tag(x)))),
      !!frame.uid && h('div', { class: 'app-tools' }, add(c)));
  }
  function add(c: Card): HTMLButtonElement {
    const b = button(t('추가'), async () => { await setOn(c, true); draw(); }, 'secondary');
    b.setAttribute('aria-label', t('{app} 추가', { app: c.title }));
    return b;
  }

  function draw(): void {
    const yours = frame.uid ? onApps().filter(shown) : [];
    const others = all.filter(c => !(frame.uid && added(c)) && shown(c));
    const narrowed = !!(search.value.trim() || chip);
    replace(mine, yours.length > 0 && section(t('내 앱'), h('div', { class: 'my-apps' }, yours.map(tile))));
    replace(rest, section(frame.uid ? t('추가할 수 있는 앱') : '',
      others.length ? h('div', { class: 'store' }, others.map(card))
        : h('p', { class: 'empty muted' }, narrowed ? t('찾는 앱이 없습니다.') : all.length ? t('모든 앱을 추가했습니다.') : t('쓸 수 있는 앱이 없습니다.'))));
  }

  draw();
  return h('div', { class: 'catalog' }, search, chips, mine, rest);
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

/** An app's page: its mark, name and line, its one action (추가 — or 열기, with 빼기 beside it), what it does,
 * what it puts on the main page, its links. */
export async function app(id: string): Promise<void> {
  const c = frame.cards.find(x => x.id === id && x.optional);
  if (!c) {
    title(t('없는 앱'));
    replace(main(), pageHead(t('없는 앱')), section('', h('p', null, link('/apps', t('앱')))));
    return;
  }
  title(c.title);
  const head = h('div', { class: 'page-head store-head' });
  const acts = h('p', { class: 'actions' });

  function draw(): void {
    replace(head, mark(c!),
      h('div', { class: 'store-text' }, h('h1', null, c!.title, fresh(c!) && [' ', tag(t('새 앱'), 'ok')]),
        c!.description && h('p', { class: 'desc' }, c!.description), c!.tags.length > 0 && h('p', { class: 'tags' }, c!.tags.map(x => tag(x)))));
    replace(acts,
      !frame.uid ? primaryLink(`${frame.signin}/login?next=/app/${c!.id}`, t('로그인'))
      : added(c!) ? [c!.href && c!.href.replace(/\/$/, '') !== `/app/${c!.id}` && primaryLink(c!.href, t('열기')), button(t('빼기'), async () => { await setOn(c!, false); draw(); }, 'secondary')]
      : button(t('추가'), async () => { await setOn(c!, true); draw(); }, 'primary'));
  }
  draw();
  const widgets = widgetsOf(c);
  replace(main(), head, acts,
    c.about && h('p', { class: 'about' }, c.about),
    section(t('홈에 올릴 수 있는 위젯'), h('ul', { class: 'plain' }, widgets.map(w => h('li', null, w.title, ' ', h('span', { class: 'muted small' }, `${cellsOf(sizeOf(w.size)).cols}×${cellsOf(sizeOf(w.size)).rows}`))))),
    c.links.length > 0 && section(t('링크'), h('ul', { class: 'plain' }, c.links.map(l => h('li', null, link(l.href, l.label))))),
    c.code.length > 0 && section(t('연결 주소'), h('ul', { class: 'plain addresses' }, c.code.map(address))));
  markSeen();
}

/** One way to connect: which client it is for, the address (a link too when it is a URI the system opens,
 * smb:// say), and a copy button. {user} in it is the person looking. */
function address(a: Address): HTMLElement {
  const value = a.value.split('{user}').join(frame.uid || '{user}');
  const uri = /^[a-z][a-z0-9+.-]*:\/\//i.test(value) && !/^(javascript|data|vbscript):/i.test(value);
  const code = h('code', { class: 'address' }, value);
  return h('li', null, a.label && [h('span', { class: 'muted small' }, a.label), ' '],
    uri ? h('a', { href: value }, code) : code, ' ',
    button(t('복사'), () => copyText(value), 'secondary'));
}
