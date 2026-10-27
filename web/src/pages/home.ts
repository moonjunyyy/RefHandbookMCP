// The main page: who is signed in, and their apps as they arranged them (lib/prefs.ts): in their order,
// without those they hid, new ones pointed out. Right after signing in it opens their start page.

import { Card, frame } from '../lib/api';
import { h, replace } from '../lib/dom';
import { arranged, prefs, savePrefs, unseen } from '../lib/prefs';
import { buttonLink, link, main, title } from '../lib/ui';

/** An app's card: its mark and name (opening it), what it is, its address to connect to, its links. */
export function appCard(c: Card): HTMLElement {
  return h('section', { class: 'card service' },
    h('h2', null, c.icon && h('span', { class: 'app-icon', 'aria-hidden': 'true' }, c.icon),
      c.href ? h('a', { href: c.href }, c.title) : c.title),
    c.description && h('p', { class: 'muted' }, c.description),
    c.code && h('p', null, h('code', { class: 'address' }, c.code)),
    c.links.length > 0 && h('div', { class: 'links' }, c.links.map(l => h('a', { href: l.href }, l.label))));
}

export async function home(): Promise<void> {
  const params = new URLSearchParams(location.search);
  if (params.has('start')) {  // just signed in: their start page, if they chose one of the site's
    history.replaceState(null, '', '/');
    if (frame.uid && prefs.start.startsWith('/') && !prefs.start.startsWith('//') && prefs.start !== '/') {
      location.replace(prefs.start);
      return;
    }
  }
  title('');
  const cards = arranged(frame.cards);
  const fresh = prefs.seen.length ? unseen(frame.cards) : [];
  if (frame.uid && !prefs.seen.length) {  // a first visit: nothing is "new"; what comes later will be
    void savePrefs({ seen: frame.cards.map(c => c.id) }).catch(() => undefined);
  }
  const hero = frame.uid
    ? h('section', { class: 'hero' },
        h('h1', null, `안녕하세요, ${frame.uid} 님`),
        h('p', { class: 'lead' }, '계정 하나로 아래 서비스를 모두 씁니다.'),
        h('div', { class: 'actions' },
          h('a', { class: 'button', href: `${frame.portal}/` }, '내 계정'),
          buttonLink('/settings', '설정', true)))
    : h('section', { class: 'hero' },
        h('h1', null, frame.title),
        h('p', { class: 'lead' }, '계정 하나로 이 사이트의 서비스를 모두 씁니다.'),
        h('div', { class: 'actions' },
          h('a', { class: 'button', href: `${frame.signin}/login` }, '로그인'),
          h('a', { class: 'button secondary', href: `${frame.portal}/request` }, '계정 신청')),
        h('p', { class: 'muted small' }, '초대 링크를 받았다면 그 링크를 열어 바로 가입하세요. 임시 비밀번호를 받았거나 비밀번호가 ' +
          '만료되었다면 ', h('a', { href: `${frame.signin}/expired` }, '여기서 바꾸세요'), '.'));
  replace(main(), hero,
    fresh.length > 0 && h('p', { class: 'flash info' }, `새 앱: ${fresh.map(c => c.title).join(', ')} `, link('/apps', '앱 목록에서 보기')),
    h('div', { class: 'section-head' }, h('h2', { class: 'section' }, frame.uid ? '내 앱' : '서비스'),
      frame.uid && h('span', { class: 'small' }, link('/apps', `모든 앱 (${frame.cards.length})`), ' · ', link('/settings#home', '홈 화면 편집'))),
    cards.length ? h('div', { class: 'grid' }, cards.map(appCard))
      : h('p', { class: 'muted' }, '홈에 표시할 앱을 모두 숨겼습니다. ', link('/apps', '앱 목록'), '에서 다시 고르세요.'));
}
