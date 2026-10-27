// The account portal's pages: one's own account, and (for helpdesk and admins) the users, the
// account requests and the invitations. The operations are the portal API's (/account/api/v1).

import { account, frame, Json } from '../lib/api';
import { h, replace, values } from '../lib/dom';
import { t } from '../lib/i18n';
import { act, buttonLink, empty, flash, flashNext, form, go, link, main, pageHead, section, tag, when } from '../lib/ui';

interface Me { user: Json; roles: string[]; may: Record<string, boolean>; shells: string[]; requests: boolean; invites: boolean }

let me: Me | null = null;

async function load(): Promise<Me> {
  me = (await account().get('/me')) as Me;
  return me;
}

function tabs(m: Me) {
  const p = frame.portal;
  const out = [{ href: `${p}/`, label: t('내 계정') }];
  if (m.may.view_users) out.push({ href: `${p}/admin/users`, label: t('사용자') });
  if (m.requests && m.may.review_requests) out.push({ href: `${p}/admin/requests`, label: t('사용 신청') });
  if (m.invites && m.may.manage_invites) out.push({ href: `${p}/admin/invites`, label: t('초대 링크') });
  return out.length > 1 ? out : undefined;
}

const shellSelect = (m: Me, current = '') =>
  h('select', { name: 'loginShell' }, m.shells.map(s => h('option', { value: s, selected: s === current }, s)));

/** A one-time password: shown once, with a way to copy it. */
function oneTime(uid: string, password: string, what: string): HTMLElement {
  return section(`${uid}: ${what}`,
    h('p', null, t('이 비밀번호는 지금 한 번만 보입니다. 본인에게 전하고, 처음 로그인할 때 바꾸게 됩니다.')),
    h('p', { class: 'secret' }, h('code', null, password)),
    h('div', { class: 'actions' }, h('button', { type: 'button', class: 'secondary',
      onclick: () => navigator.clipboard?.writeText(password).then(() => flash('ok', t('복사했습니다.'))) }, t('복사'))));
}

// ── one's own account ───────────────────────────────────────────────────

export async function mine(): Promise<void> {
  const m = await load();
  const u = m.user;
  replace(main(),
    pageHead(u.display_name || u.uid, null, tabs(m)),
    h('div', { class: 'grid' },
      section(t('계정'), h('dl', null,
        h('dt', null, t('사용자명')), h('dd', null, h('code', null, u.uid)),
        h('dt', null, 'UID / GID'), h('dd', null, `${u.uid_number} / ${u.gid_number}`),
        h('dt', null, t('홈')), h('dd', null, h('code', null, u.home)),
        h('dt', null, t('그룹')), h('dd', null, u.groups.map((g: string) => tag(g))),
        h('dt', null, t('역할')), h('dd', null, m.roles.filter(r => r !== 'user').join(', ') || t('사용자')))),
      section(t('프로필'), form({}, async (f, b) => {
        const v = values(f);
        await act(b, () => account().patch('/me', v), t('프로필을 저장했습니다.'));
      },
        h('label', null, t('표시 이름'), h('input', { name: 'displayName', value: u.display_name, maxlength: 64 })),
        h('label', null, t('이메일'), h('input', { name: 'mail', type: 'email', value: u.mail })),
        h('label', null, t('로그인 셸'), shellSelect(m, u.login_shell)),
        h('div', { class: 'actions' }, h('button', null, t('저장'))))),
      h('section', { class: 'card section', id: 'password' }, h('h2', null, t('비밀번호 변경')),
        form({}, async (f, b) => {
          const done = await act(b, () => account().post('/me/password', values(f)), t('비밀번호를 바꿨습니다.'));
          if (done) f.reset();
        },
          h('label', null, t('지금 비밀번호'), h('input', { name: 'old', type: 'password', autocomplete: 'current-password', required: true })),
          h('label', null, t('새 비밀번호'), h('input', { name: 'new', type: 'password', minlength: 12, autocomplete: 'new-password', required: true })),
          h('label', null, t('새 비밀번호 확인'), h('input', { name: 'confirm', type: 'password', minlength: 12, autocomplete: 'new-password', required: true })),
          h('div', { class: 'actions' }, h('button', null, t('비밀번호 변경')))),
        h('p', { class: 'muted small' }, t('이 사이트와 SSH에 함께 쓰는 비밀번호입니다.')))));
  if (location.hash === '#password') document.getElementById('password')?.scrollIntoView();
}

// ── users ───────────────────────────────────────────────────────────────

export async function users(): Promise<void> {
  const m = await load();
  const q = new URLSearchParams(location.search).get('q') ?? '';
  const list = (await account().get(`/users?q=${encodeURIComponent(q)}`)) as Json[];
  const p = frame.portal;
  replace(main(),
    pageHead(t('사용자'), t('계정을 찾아 비밀번호 초기화, 잠금 해제, 그룹, 비활성화와 삭제를 합니다.'), tabs(m)),
    section(t('사용자 ({n})', { n: list.length }),
      h('div', { class: 'actions' },
        form({ class: 'search' }, async f => { go(`${p}/admin/users?q=${encodeURIComponent(String(values(f).q))}`); },
          h('input', { name: 'q', value: q, placeholder: t('이름, 사용자명, 이메일') }), h('button', { class: 'secondary' }, t('찾기'))),
        m.may.create_user && buttonLink(`${p}/admin/users/new`, t('새 사용자'))),
      list.length ? h('div', { class: 'table-wrap' }, h('table', null,
        h('thead', null, h('tr', null, [t('사용자명'), t('이름'), t('이메일'), t('그룹'), t('상태')].map(x => h('th', null, x)))),
        h('tbody', null, list.map(u => h('tr', null,
          h('td', null, link(`${p}/admin/users/${u.uid}`, h('code', null, u.uid))),
          h('td', null, u.display_name || u.name), h('td', null, u.mail),
          h('td', { class: 'wrap' }, u.groups.join(', ')),
          h('td', null, u.disabled ? tag(t('비활성'), 'bad') : !u.complete ? tag(t('불완전'), 'warn') : tag(t('활성'), 'ok')))))))
        : empty(t('맞는 사용자가 없습니다.'))));
}

export async function newUser(): Promise<void> {
  const m = await load();
  const p = frame.portal;
  replace(main(),
    pageHead(t('새 사용자'), t('계정과 개인 그룹을 만들고 기본 그룹에 넣습니다. 처음 로그인할 때 바꿀 임시 비밀번호가 한 번 보입니다.'), tabs(m)),
    section(t('계정 만들기'), form({}, async (f, b) => {
      const r = await act(b, () => account().post('/users', values(f)));
      if (r) replace(main(), pageHead(t('새 사용자'), null, tabs(m)), oneTime(r.user.uid, r.password, t('계정을 만들었습니다')),
        h('p', null, link(`${p}/admin/users/${r.user.uid}`, t('계정 보기'))));
    },
      h('div', { class: 'cols' },
        h('label', null, t('사용자명'), h('input', { name: 'uid', required: true, pattern: '[a-z][a-z0-9_-]{1,31}', autocomplete: 'off' })),
        h('label', null, t('이름 (선택)'), h('input', { name: 'name', maxlength: 64 }))),
      h('div', { class: 'cols' },
        h('label', null, t('이메일 (선택)'), h('input', { name: 'mail', type: 'email' })),
        h('label', null, t('로그인 셸'), shellSelect(m))),
      h('div', { class: 'actions' }, h('button', null, t('만들기'))))));
}

export async function user(uid: string): Promise<void> {
  const m = await load();
  const p = frame.portal;
  const d = await account().get(`/users/${encodeURIComponent(uid)}`);
  const u = d.user, may = d.may as Record<string, boolean>;
  const reload = () => user(uid);
  const actions = [
    may.reset_password && h('div', { class: 'item' }, h('div', { class: 'item-head' }, h('b', null, t('비밀번호 초기화'))),
      h('p', { class: 'muted small' }, t('임시 비밀번호를 정합니다. 다음 로그인에서 바꾸게 됩니다.')),
      h('div', { class: 'actions' }, h('button', { onclick: async (e: Event) => {
        const r = await act(e.target as HTMLButtonElement, () => account().post(`/users/${uid}/reset`));
        if (r) replace(main(), pageHead(uid, null, tabs(m)), oneTime(uid, r.password, t('비밀번호를 초기화했습니다')),
          h('p', null, link(`${p}/admin/users/${uid}`, t('계정 보기'))));
      } }, t('초기화')))),
    may.unlock && h('div', { class: 'actions' }, h('button', { class: 'secondary', onclick: async (e: Event) => {
      if (await act(e.target as HTMLButtonElement, () => account().post(`/users/${uid}/unlock`), t('잠금을 풀었습니다.'))) reload();
    } }, t('로그인 실패 잠금 풀기'))),
    may.set_enabled && h('div', { class: 'actions' }, h('button', { class: u.disabled ? 'secondary' : 'danger', onclick: async (e: Event) => {
      if (await act(e.target as HTMLButtonElement, () => account().patch(`/users/${uid}`, { enabled: u.disabled }),
        u.disabled ? t('활성화했습니다.') : t('비활성화했습니다.'))) reload();
    } }, u.disabled ? t('계정 활성화') : t('계정 비활성화'))),
    may.delete_user && h('details', { class: 'panel' }, h('summary', null, h('span', { class: 'danger-text' }, t('계정 삭제…'))),
      form({}, async (f, b) => {
        const c = String(values(f).confirm);
        if (await act(b, () => account().del(`/users/${uid}?confirm=${encodeURIComponent(c)}`))) {
          flashNext('ok', t('{uid}을(를) 삭제했습니다. 그 계정의 파일(홈 디렉터리, 데이터)은 그대로입니다.', { uid }));
          go(`${p}/admin/users`);
        }
      },
        h('p', { class: 'muted small' }, t('계정, 개인 그룹, 모든 그룹 소속을 지웁니다. 되돌릴 수 없습니다. 파일은 그대로 남습니다.')),
        h('label', null, t('확인하려면 사용자명을 입력하세요:'), ' ', h('code', null, uid),
          h('input', { name: 'confirm', autocomplete: 'off', required: true, pattern: uid })),
        h('div', { class: 'actions' }, h('button', { class: 'danger' }, t('{uid} 삭제', { uid }))))),
  ].filter(Boolean);
  replace(main(),
    pageHead(u.display_name || uid, h('code', null, uid), tabs(m)),
    h('div', { class: 'grid' },
      section(t('계정'), h('dl', null,
        h('dt', null, t('이름')), h('dd', null, u.name || '-'), h('dt', null, t('이메일')), h('dd', null, u.mail || '-'),
        h('dt', null, 'UID / GID'), h('dd', null, `${u.uid_number} / ${u.gid_number}`),
        h('dt', null, t('홈')), h('dd', null, h('code', null, u.home)), h('dt', null, t('셸')), h('dd', null, h('code', null, u.login_shell)),
        h('dt', null, t('상태')), h('dd', null, u.disabled ? tag(t('비활성'), 'bad') : !u.complete ? tag(t('불완전'), 'warn') : tag(t('활성'), 'ok')),
        h('dt', null, t('로그인 실패')), h('dd', null, String(u.failed_logins)))),
      section(t('작업'), actions.length ? actions : empty(uid === m.user.uid ? t('자기 계정은 내 계정에서 바꿉니다.') : t('이 계정에 할 수 있는 작업이 없습니다.'))),
      section(t('그룹'),
        h('ul', { class: 'groups' }, u.groups.map((g: string) => h('li', null, tag(g),
          may.manage_groups && g !== uid && h('button', { class: 'link danger-text', onclick: async (e: Event) => {
            if (await act(e.target as HTMLButtonElement, () => account().del(`/users/${uid}/groups/${g}`), t('{group}에서 뺐습니다.', { group: g }))) reload();
          } }, t('빼기'))))),
        may.manage_groups && d.addable_groups.length > 0 && form({ class: 'row' }, async (f, b) => {
          const g = String(values(f).group);
          if (await act(b, () => account().put(`/users/${uid}/groups/${g}`, {}), t('{group}에 넣었습니다.', { group: g }))) reload();
        }, h('select', { name: 'group' }, d.addable_groups.map((g: string) => h('option', null, g))),
          h('button', { class: 'secondary' }, t('그룹에 넣기'))))));
}

// ── requests and invitations ────────────────────────────────────────────

export async function requests(): Promise<void> {
  const m = await load();
  const list = (await account().get('/requests')) as Json[];
  replace(main(),
    pageHead(t('사용 신청'), t('승인하면 계정이 만들어지고 임시 비밀번호가 한 번 보입니다. 신청의 개인정보는 처리하면 바로 지워집니다.'), tabs(m)),
    section(t('대기 중 ({n})', { n: list.length }), list.length ? list.map(r => h('div', { class: 'item' },
      h('div', { class: 'item-head' }, h('b', null, r.uid), h('span', null, r.name), h('span', { class: 'muted small' }, `${r.mail} · ${when(r.created)}`)),
      h('p', null, r.purpose),
      h('div', { class: 'actions' },
        form({ class: 'inline' }, async (f, b) => {
          const out = await act(b, () => account().post(`/requests/${r.id}/approve`, values(f)));
          if (out) replace(main(), pageHead(t('사용 신청'), null, tabs(m)), oneTime(out.user.uid, out.password, t('계정을 만들었습니다')),
            h('p', null, link(`${frame.portal}/admin/requests`, t('다른 신청 보기'))));
        }, shellSelect(m), h('button', null, t('승인'))),
        h('button', { class: 'secondary', onclick: async (e: Event) => {
          if (await act(e.target as HTMLButtonElement, () => account().post(`/requests/${r.id}/reject`), t('{uid} 신청을 거절했습니다.', { uid: r.uid }))) void requests();
        } }, t('거절'))))) : empty(t('대기 중인 신청이 없습니다.'))));
}

export async function invites(): Promise<void> {
  const m = await load();
  const list = (await account().get('/invites')) as Json[];
  replace(main(),
    pageHead(t('초대 링크'), t('링크를 받은 사람이 직접 가입합니다. 링크는 한 번 쓰면 끝나고, 기한이 지나도 끝납니다.'), tabs(m)),
    section(t('새 링크'), form({}, async (f, b) => {
      const r = await act(b, () => account().post('/invites', values(f)));
      if (r) {
        replace(main(), pageHead(t('초대 링크'), null, tabs(m)), section(t('링크를 만들었습니다'),
          h('p', null, t('이 링크는 지금 한 번만 보입니다.')), h('p', { class: 'secret' }, h('code', null, r.link)),
          h('div', { class: 'actions' },
            h('button', { type: 'button', class: 'secondary', onclick: () => navigator.clipboard?.writeText(r.link).then(() => flash('ok', t('복사했습니다.'))) }, t('복사')),
            link(`${frame.portal}/admin/invites`, t('목록으로')))));
      }
    }, h('label', null, t('메모 (선택)'), h('input', { name: 'note', maxlength: 120, placeholder: t('누구에게 줄 링크인지') })),
      h('div', { class: 'actions' }, h('button', null, t('링크 만들기'))))),
    section(t('살아 있는 링크 ({n})', { n: list.length }), list.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, [t('메모'), t('만든 사람'), t('만든 때'), t('기한'), ''].map(x => h('th', null, x)))),
      h('tbody', null, list.map(i => h('tr', null, h('td', { class: 'wrap' }, i.note || '-'), h('td', null, i.created_by),
        h('td', null, when(i.created)), h('td', null, when(i.expires)),
        h('td', null, h('button', { class: 'secondary', onclick: async (e: Event) => {
          if (await act(e.target as HTMLButtonElement, () => account().post(`/invites/${i.id}/revoke`), t('링크를 거뒀습니다.'))) void invites();
        } }, t('거두기')))))))) : empty(t('살아 있는 링크가 없습니다.'))));
}
