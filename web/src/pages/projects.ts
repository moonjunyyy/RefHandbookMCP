// Projects: groups people make themselves (docs/projects.md). The list (mine, the listed ones, a new
// one), a project (its members, how one joins, what an owner manages), and an invitation link. The
// operations are the portal API's (/account/api/v1/projects).

import { account, act, empty, flash, flashNext, form, frame, go, h, link, main, pageHead, replace, section, tag, values, when } from '/auth/static/site.js';
import type { Json } from '/auth/static/site.js';
import { n_, t } from '../lib/i18n';

const api = () => account();
const P = '/projects';

const POLICIES: Record<string, string> = {
  open: n_('누구나 바로 들어옴'), request: n_('신청하면 소유자가 승인'), invite: n_('초대 링크로만'),
};

const policySelect = (current = 'request') =>
  h('select', { name: 'join_policy' }, Object.entries(POLICIES).map(([k, v]) =>
    h('option', { value: k, selected: k === current }, t(v))));

function state(p: Json): HTMLElement[] {
  return [
    p.archived && tag(t('보관됨'), 'bad'),
    p.role === 'owner' ? tag(t('소유자'), 'ok') : p.member ? tag(t('구성원')) : p.requested ? tag(t('신청 중'), 'warn') : null,
    !p.listed && tag(t('숨김')),
  ].filter(Boolean) as HTMLElement[];
}

function row(p: Json): HTMLElement {
  return h('tr', null,
    h('td', null, link(`${P}/${p.cn}`, h('b', null, p.title), ' ', h('code', { class: 'muted small' }, p.cn))),
    h('td', { class: 'wrap' }, p.description),
    h('td', null, t(POLICIES[p.join_policy] ?? p.join_policy)),
    h('td', null, String(p.members.length)),
    h('td', null, state(p)));
}

function table(list: Json[]): HTMLElement {
  return h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null, [t('프로젝트'), t('설명'), t('가입'), t('구성원'), t('상태')].map(x => h('th', null, x)))),
    h('tbody', null, list.map(row))));
}

// ── the list ────────────────────────────────────────────────────────────

export async function projects(): Promise<void> {
  const d = await api().get(P);
  const list = d.projects as Json[];
  const mine = list.filter(p => p.member), others = list.filter(p => !p.member);
  replace(main(),
    pageHead(t('프로젝트')),
    section(t('내 프로젝트 ({n})', { n: mine.length }), mine.length ? table(mine) : empty(t('아직 들어 있는 프로젝트가 없습니다.'))),
    section(t('다른 프로젝트 ({n})', { n: others.length }), others.length ? table(others) : empty(t('들어갈 수 있는 다른 프로젝트가 없습니다.'))),
    d.may_create && section(t('새 프로젝트'), form({}, async (f, b) => {
      const v = values(f);
      const r = await act(b, () => api().post(P, v));
      if (r) { flashNext('ok', t('프로젝트를 만들었습니다.')); go(`${P}/${r.cn}`); }
    },
      h('div', { class: 'cols' },
        h('label', null, t('이름 (그룹·공유 이름)'), h('input', { name: 'name', required: true, pattern: '[a-z][a-z0-9_-]{1,31}',
          autocomplete: 'off', placeholder: 'chain-image' })),
        h('label', null, t('제목'), h('input', { name: 'title', maxlength: 64, placeholder: t('사람이 읽는 이름') }))),
      h('label', null, t('설명'), h('textarea', { name: 'description', rows: 2, maxlength: 500 })),
      h('div', { class: 'cols' },
        h('label', null, t('가입'), policySelect()),
        h('label', { class: 'check' }, h('input', { name: 'listed', type: 'checkbox', checked: true }), ' ', t('목록에 보이기'))),
      h('p', { class: 'muted small' }, t('이름은 영문 소문자로 시작하는 2–32자이고 나중에 바꿀 수 없습니다. 만든 사람이 첫 소유자입니다.')),
      h('div', { class: 'actions' }, h('button', null, t('만들기'))))));
}

// ── one project ─────────────────────────────────────────────────────────

export async function project(cn: string): Promise<void> {
  const p = await api().get(`${P}/${encodeURIComponent(cn)}`);
  const reload = () => project(cn);
  const may = p.may as Record<string, boolean>;
  const path = `${P}/${cn}`;
  const members = h('ul', { class: 'groups' }, p.members.map((uid: string) => h('li', null,
    h('code', null, uid), p.owners.includes(uid) && [' ', tag(t('소유자'), 'ok')],
    may.manage && !p.archived && [
      p.owners.includes(uid)
        ? h('button', { class: 'link', onclick: async (e: Event) => {
          if (await act(e.target as HTMLButtonElement, () => api().del(`${path}/owners/${uid}`))) reload();
        } }, t('소유자 해임'))
        : h('button', { class: 'link', onclick: async (e: Event) => {
          if (await act(e.target as HTMLButtonElement, () => api().put(`${path}/owners/${uid}`, {}))) reload();
        } }, t('소유자로')),
      h('button', { class: 'link danger-text', onclick: async (e: Event) => {
        if (await act(e.target as HTMLButtonElement, () => api().del(`${path}/members/${uid}`))) reload();
      } }, t('빼기'))])));
  const joining = [
    may.join && form({ class: 'inline' }, async (f, b) => {
      const r = await act(b, () => api().post(`${path}/join`, values(f)));
      if (r) { flash('ok', r.member ? t('프로젝트에 들어왔습니다.') : t('가입을 신청했습니다. 소유자가 승인하면 들어갑니다.')); reload(); }
    }, p.join_policy === 'request' && h('input', { name: 'note', maxlength: 200, placeholder: t('소유자에게 한마디 (선택)') }),
      h('button', null, p.join_policy === 'open' ? t('들어가기') : t('가입 신청'))),
    p.requested && h('button', { class: 'secondary', onclick: async (e: Event) => {
      if (await act(e.target as HTMLButtonElement, () => api().post(`${path}/withdraw`))) reload();
    } }, t('신청 거두기')),
    may.leave && h('button', { class: 'secondary danger-text', onclick: async (e: Event) => {
      if (await act(e.target as HTMLButtonElement, () => api().post(`${path}/leave`))) reload();
    } }, t('나가기')),
    !p.member && !may.join && !p.requested && p.join_policy === 'invite' && h('p', { class: 'muted small' }, t('초대 링크로만 들어갈 수 있습니다.')),
  ].filter(Boolean);
  replace(main(),
    pageHead(p.title), h('p', { class: 'muted' }, [h('code', null, p.cn), ' · gid ', String(p.gid), ' · ', state(p)]),
    h('div', { class: 'grid' },
      section(t('프로젝트'), h('dl', null,
        h('dt', null, t('설명')), h('dd', null, p.description || '-'),
        h('dt', null, t('가입')), h('dd', null, t(POLICIES[p.join_policy] ?? p.join_policy)),
        h('dt', null, t('만든 사람')), h('dd', null, h('code', null, p.created_by), ' · ', when(p.created)),
        h('dt', null, t('소유자')), h('dd', null, p.owners.map((o: string) => h('code', null, o, ' '))),
        p.archived && [h('dt', null, t('보관')), h('dd', null, when(p.archived))]),
        h('div', { class: 'actions' }, joining)),
      section(t('구성원 ({n})', { n: p.members.length }), members,
        may.manage && !p.archived && form({ class: 'row' }, async (f, b) => {
          const uid = String(values(f).uid).trim();
          if (await act(b, () => api().put(`${path}/members/${encodeURIComponent(uid)}`, {}))) reload();
        }, h('input', { name: 'uid', required: true, placeholder: t('사용자명'), pattern: '[a-z][a-z0-9_-]{1,31}', autocomplete: 'off' }),
          h('button', { class: 'secondary' }, t('구성원 넣기')))),
      may.manage && section(t('가입 신청 ({n})', { n: (p.requests ?? []).length }),
        (p.requests ?? []).length ? (p.requests as Json[]).map(r => h('div', { class: 'item' },
          h('div', { class: 'item-head' }, h('code', null, r.uid), h('span', { class: 'muted small' }, when(r.created))),
          r.note && h('p', null, r.note),
          h('div', { class: 'actions' },
            h('button', { onclick: async (e: Event) => {
              if (await act(e.target as HTMLButtonElement, () => api().post(`${path}/requests/${r.id}/approve`))) reload();
            } }, t('승인')),
            h('button', { class: 'secondary', onclick: async (e: Event) => {
              if (await act(e.target as HTMLButtonElement, () => api().post(`${path}/requests/${r.id}/reject`))) reload();
            } }, t('거절'))))) : empty(t('기다리는 신청이 없습니다.'))),
      may.manage && section(t('초대 링크'),
        !p.archived && form({ class: 'inline' }, async (f, b) => {
          const r = await act(b, () => api().post(`${path}/invites`, values(f)));
          if (r) replace(main(), pageHead(p.title), section(t('링크를 만들었습니다'),
            h('p', null, t('이 링크는 지금 한 번만 보입니다. 받은 사람이 로그인한 채 열면 바로 구성원이 됩니다.')),
            h('p', { class: 'secret' }, h('code', null, r.link)),
            h('div', { class: 'actions' },
              h('button', { type: 'button', class: 'secondary', onclick: () => navigator.clipboard?.writeText(r.link).then(() => flash('ok', t('복사했습니다.'))) }, t('복사')),
              link(path, t('프로젝트로')))));
        }, h('input', { name: 'note', maxlength: 120, placeholder: t('누구에게 줄 링크인지') }), h('button', { class: 'secondary' }, t('링크 만들기'))),
        (p.invites ?? []).length ? h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, [t('메모'), t('만든 사람'), t('기한'), ''].map(x => h('th', null, x)))),
          h('tbody', null, (p.invites as Json[]).map(i => h('tr', null, h('td', { class: 'wrap' }, i.note || '-'), h('td', null, i.created_by),
            h('td', null, when(i.expires)), h('td', null, h('button', { class: 'secondary', onclick: async (e: Event) => {
              if (await act(e.target as HTMLButtonElement, () => api().post(`${path}/invites/${i.id}/revoke`))) reload();
            } }, t('거두기')))))))) : empty(t('살아 있는 링크가 없습니다.'))),
      may.manage && section(t('설정'),
        !p.archived && form({}, async (f, b) => {
          const v = values(f);
          if (await act(b, () => api().patch(path, v))) reload();
        },
          h('label', null, t('제목'), h('input', { name: 'title', value: p.title, maxlength: 64, required: true })),
          h('label', null, t('설명'), h('textarea', { name: 'description', rows: 2, maxlength: 500 }, p.description)),
          h('div', { class: 'cols' },
            h('label', null, t('가입'), policySelect(p.join_policy)),
            h('label', { class: 'check' }, h('input', { name: 'listed', type: 'checkbox', checked: p.listed }), ' ', t('목록에 보이기'))),
          h('div', { class: 'actions' }, h('button', null, t('저장')))),
        h('div', { class: 'actions' },
          may.archive && h('button', { class: 'danger', onclick: async (e: Event) => {
            if (await act(e.target as HTMLButtonElement, () => api().post(`${path}/archive`))) reload();
          } }, t('프로젝트 보관')),
          may.restore && h('button', { onclick: async (e: Event) => {
            if (await act(e.target as HTMLButtonElement, () => api().post(`${path}/restore`))) reload();
          } }, t('되살리기'))),
        h('p', { class: 'muted small' }, t('보관하면 그룹과 구성원은 그대로 남고(파일은 그대로 읽힙니다), 바꾸거나 들어올 수는 없습니다.')),
        may.delete && h('details', { class: 'panel' }, h('summary', null, h('span', { class: 'danger-text' }, t('프로젝트 삭제…'))),
          form({}, async (f, b) => {
            const c = String(values(f).confirm);
            if (await act(b, () => api().del(`${path}?confirm=${encodeURIComponent(c)}`))) {
              flashNext('ok', t('{cn}을(를) 지웠습니다. 그 프로젝트의 파일은 그대로입니다.', { cn }));
              go(P);
            }
          },
            h('p', { class: 'muted small' }, t('그룹과 모든 구성원 소속, 신청과 초대 링크를 지웁니다. 되돌릴 수 없습니다. 파일은 그대로 남습니다.')),
            h('label', null, t('확인하려면 이름을 입력하세요:'), ' ', h('code', null, cn),
              h('input', { name: 'confirm', autocomplete: 'off', required: true, pattern: cn })),
            h('div', { class: 'actions' }, h('button', { class: 'danger' }, t('{cn} 삭제', { cn }))))))),
    h('p', null, link(P, t('프로젝트 목록으로'))));
}

// ── an invitation link ──────────────────────────────────────────────────

export async function join(token: string): Promise<void> {
  replace(main(), pageHead(t('프로젝트 초대')),
    section(t('들어가기'), h('p', null, t('계정: '), h('code', null, frame.uid ?? '-')),
      h('div', { class: 'actions' }, h('button', { onclick: async (e: Event) => {
        const r = await act(e.target as HTMLButtonElement, () => api().post(`${P}/join`, { token }));
        if (r) { flashNext('ok', t('{title}에 들어왔습니다.', { title: r.title })); go(`${P}/${r.cn}`); }
      } }, t('이 프로젝트에 들어가기')), link(P, t('프로젝트 목록')))));
}
