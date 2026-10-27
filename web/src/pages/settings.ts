// The person's settings (/settings), kept with their account (lib/prefs.ts): the language of the pages,
// the page to open after signing in, and the main page's apps (their order, which are shown).

import { frame } from '../lib/api';
import { h, replace } from '../lib/dom';
import { LANGS, t } from '../lib/i18n';
import { arranged, DEFAULTS, prefs, savePrefs } from '../lib/prefs';
import { act, buttonLink, flash, main, pageHead, section } from '../lib/ui';

/** The languages to choose from: the browser's, or one of lib/i18n.ts's (each named in its own). */
const languages = (): [string, string][] => [['auto', t('브라우저 언어 따르기')], ...LANGS];

/** The main page's apps, to order (up, down) and show or hide; each change is kept at once. */
function homeLayout(): HTMLElement {
  const el = h('ol', { class: 'layout' });
  const draw = () => {
    const cards = arranged(frame.cards, true);
    const move = async (i: number, by: number) => {
      const ids = cards.map(c => c.id);
      [ids[i], ids[i + by]] = [ids[i + by], ids[i]];
      if (await act(null, () => savePrefs({ order: ids }))) draw();
    };
    replace(el, cards.map((c, i) => {
      const shown = !prefs.hidden.includes(c.id);
      return h('li', { class: shown ? '' : 'off' },
        h('span', { class: 'app-icon', 'aria-hidden': 'true' }, c.icon || c.title.slice(0, 1)),
        h('span', { class: 'grow' }, c.title),
        h('label', { class: 'check inline' }, h('input', { type: 'checkbox', checked: shown, onchange: async (e: Event) => {
          const on = (e.target as HTMLInputElement).checked;
          const hidden = on ? prefs.hidden.filter(x => x !== c.id) : [...prefs.hidden, c.id];
          if (await act(null, () => savePrefs({ hidden }))) draw();
        } }), t('홈에 표시')),
        h('button', { type: 'button', class: 'link', title: t('위로'), 'aria-label': t('{app} 위로', { app: c.title }), disabled: i === 0,
                      onclick: () => move(i, -1) }, '↑'),
        h('button', { type: 'button', class: 'link', title: t('아래로'), 'aria-label': t('{app} 아래로', { app: c.title }),
                      disabled: i === cards.length - 1, onclick: () => move(i, 1) }, '↓'));
    }));
  };
  draw();
  return el;
}

export async function settings(): Promise<void> {
  if (!frame.uid) {
    replace(main(), pageHead(t('설정'), t('로그인하면 언어, 시작 페이지, 홈 화면을 정할 수 있습니다.')),
      buttonLink(`${frame.signin}/login?next=/settings`, t('로그인')));
    return;
  }
  // where one may start: the main page, the app list, each app (and its pages the site links)
  const starts: [string, string][] = [['/', t('홈')], ['/apps', t('앱 목록')]];
  for (const c of frame.cards) {
    for (const l of [{ label: c.title, href: c.href }, ...c.links]) {
      if (l.href && l.href.startsWith('/') && !starts.some(([h]) => h === l.href)) {
        starts.push([l.href, l.label === c.title ? c.title : `${c.title} · ${l.label}`]);
      }
    }
  }
  if (!starts.some(([href]) => href === prefs.start)) starts.push([prefs.start, prefs.start]);
  const choose = (name: string, choices: [string, string][], value: string, save: (v: string) => Promise<unknown>) =>
    h('select', { name, onchange: async (e: Event) => {
      const v = (e.target as HTMLSelectElement).value;
      if (await act(null, () => save(v), t('저장했습니다.'))) void settings();
    } }, choices.map(([v, label]) => h('option', { value: v, selected: v === value }, label)));

  replace(main(),
    pageHead(t('설정'), t('이 계정의 설정입니다. 어느 브라우저에서 로그인해도 같게 적용됩니다.')),
    section(t('언어'),
      h('label', null, t('화면 언어'), choose('lang', languages(), prefs.lang, v => savePrefs({ lang: v }).then(() => location.reload())))),
    section(t('시작 페이지'),
      h('label', null, t('로그인한 뒤 열 페이지'), choose('start', starts, prefs.start, v => savePrefs({ start: v }))),
      h('p', { class: 'muted small' }, t('다른 페이지를 열다가 로그인한 경우에는 그 페이지로 돌아갑니다. 로고를 누르면 언제든 홈으로 갑니다.'))),
    h('section', { class: 'card section', id: 'home' }, h('h2', null, t('홈 화면')),
      h('p', { class: 'muted small' }, t('홈에 보일 앱과 그 순서입니다. 새로 생기는 앱은 맨 뒤에 보이고, 앱 목록에서 새 앱으로 알려 줍니다.')),
      homeLayout()),
    section(t('초기화'), h('p', { class: 'muted small' }, t('언어·시작 페이지·홈 화면을 처음 상태로 돌립니다.')),
      h('button', { class: 'secondary', onclick: async (e: Event) => {
        if (!confirm(t('설정을 처음 상태로 돌릴까요?'))) return;
        if (await act(e.target as HTMLButtonElement, () => savePrefs({ ...DEFAULTS, seen: prefs.seen }))) {
          await settings();
          flash('ok', t('처음 상태로 돌렸습니다.'));
        }
      } }, t('초기화'))));
  if (location.hash === '#home') document.getElementById('home')?.scrollIntoView();
}
