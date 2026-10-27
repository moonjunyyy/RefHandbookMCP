// The app list (/apps): every app of the site the person may use, the ones added later too (the site
// file declares them; the frame lists them), to open, to find by name, and to show on the main page
// or not. Seeing the list marks every app seen (the main page stops calling them new).

import { Card, frame } from '../lib/api';
import { h, replace } from '../lib/dom';
import { arranged, prefs, savePrefs, unseen } from '../lib/prefs';
import { act, buttonLink, empty, link, main, pageHead, section, tag } from '../lib/ui';

export async function apps(): Promise<void> {
  const all = arranged(frame.cards, true);
  const fresh = new Set(prefs.seen.length ? unseen(frame.cards).map(c => c.id) : []);
  const list = h('div', { class: 'app-list' });
  const search = h('input', { type: 'search', placeholder: '앱 이름이나 설명으로 찾기', 'aria-label': '앱 찾기',
                              oninput: () => draw() });

  function row(c: Card): HTMLElement {
    const shown = !prefs.hidden.includes(c.id);
    return h('div', { class: 'app-row' },
      h('span', { class: 'app-icon big', 'aria-hidden': 'true' }, c.icon || c.title.slice(0, 1)),
      h('div', { class: 'app-text' },
        h('div', null, h('b', null, c.title), fresh.has(c.id) && [' ', tag('새 앱', 'ok')], !shown && [' ', tag('홈에서 숨김')]),
        c.description && h('p', { class: 'muted small' }, c.description),
        c.code && h('p', null, h('code', { class: 'address' }, c.code)),
        c.links.length > 1 && h('p', { class: 'small links' }, c.links.map(l => h('a', { href: l.href }, l.label)))),
      h('div', { class: 'app-tools' },
        c.href && h('a', { class: 'button', href: c.href }, '열기'),
        frame.uid && h('button', { class: 'secondary', onclick: async (e: Event) => {
          const hidden = shown ? [...prefs.hidden, c.id] : prefs.hidden.filter(x => x !== c.id);
          if (await act(e.target as HTMLButtonElement, () => savePrefs({ hidden }),
                        shown ? `${c.title}: 홈에서 숨겼습니다.` : `${c.title}: 홈에 표시합니다.`)) draw();
        } }, shown ? '홈에서 숨기기' : '홈에 표시')));
  }

  function draw(): void {
    const q = search.value.trim().toLowerCase();
    const found = all.filter(c => !q || `${c.title} ${c.description} ${c.links.map(l => l.label).join(' ')}`.toLowerCase().includes(q));
    replace(list, found.length ? found.map(row) : empty(q ? '찾는 앱이 없습니다.' : '쓸 수 있는 앱이 없습니다.'));
  }

  replace(main(),
    pageHead('앱', ['이 사이트에서 쓸 수 있는 앱입니다. 새로 생기는 앱도 여기에 나타납니다. 홈 화면의 순서와 시작 페이지는 ',
      link('/settings', '설정'), '에서 정합니다.']),
    section(`앱 (${all.length})`, search, list),
    !frame.uid && h('p', { class: 'muted' }, '로그인하면 홈에 표시할 앱을 고를 수 있습니다. ', buttonLink(`${frame.signin}/login?next=/apps`, '로그인')));
  draw();
  if (frame.uid && (fresh.size || !prefs.seen.length)) void savePrefs({ seen: frame.cards.map(c => c.id) }).catch(() => undefined);
}
