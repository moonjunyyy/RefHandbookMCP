// The main page: who is signed in, and the site's services as this person may see them.

import { frame } from '../lib/api';
import { h, replace } from '../lib/dom';
import { main, title } from '../lib/ui';

export async function home(): Promise<void> {
  title('');
  const hero = frame.uid
    ? h('section', { class: 'hero' },
        h('h1', null, `안녕하세요, ${frame.uid} 님`),
        h('p', { class: 'lead' }, '계정 하나로 아래 서비스를 모두 씁니다.'),
        h('div', { class: 'actions' },
          h('a', { class: 'button', href: `${frame.portal}/` }, '내 계정'),
          h('a', { class: 'button secondary', href: `${frame.portal}/#password` }, '비밀번호 변경')))
    : h('section', { class: 'hero' },
        h('h1', null, frame.title),
        h('p', { class: 'lead' }, '계정 하나로 이 사이트의 서비스를 모두 씁니다.'),
        h('div', { class: 'actions' },
          h('a', { class: 'button', href: `${frame.signin}/login` }, '로그인'),
          h('a', { class: 'button secondary', href: `${frame.portal}/request` }, '계정 신청')),
        h('p', { class: 'muted small' }, '초대 링크를 받았다면 그 링크를 열어 바로 가입하세요. 임시 비밀번호를 받았거나 비밀번호가 ' +
          '만료되었다면 ', h('a', { href: `${frame.signin}/expired` }, '여기서 바꾸세요'), '.'));
  replace(main(), hero,
    frame.cards.length > 0 && h('h2', { class: 'section' }, '서비스'),
    h('div', { class: 'grid' }, frame.cards.map(c => h('section', { class: 'card service' },
      h('h2', null, c.title),
      c.description && h('p', { class: 'muted' }, c.description),
      c.code && h('p', null, h('code', { class: 'address' }, c.code)),
      c.links.length > 0 && h('div', { class: 'links' }, c.links.map(l => h('a', { href: l.href }, l.label)))))));
}
