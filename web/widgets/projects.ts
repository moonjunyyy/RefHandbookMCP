// The projects' widget on the main page (docs/projects.md), drawn with the frame's parts (docs/frame.md §4.2): how
// many projects the person is in and how many they manage, then each — its description, its members' initials,
// the person's role — the archived ones last, muted. The list is the account service's (its API under the
// portal's root).

import { account, fit, h, items, replace, stats } from '/auth/static/site.js';
import type { WidgetContext } from '/auth/static/site.js';
import { t } from '../src/lib/i18n';

interface Project { cn: string; title: string; description: string; member: boolean; role: string; members: string[]; archived: number | null;
                    may?: { manage?: boolean } }
const FACES = 3;  // the members drawn as initials before '+n'

/** The members as initials (the first few), the rest as a number. */
function faces(members: string[]): HTMLElement {
  return h('span', { class: 'faces', role: 'img', title: members.join(', '), 'aria-label': t('{n}명', { n: members.length }) },
    members.slice(0, FACES).map(m => h('span', { class: 'face' }, m.slice(0, 1))),
    members.length > FACES && h('span', { class: 'face' }, `+${members.length - FACES}`));
}

export default async function widget(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  replace(host, h('p', { class: 'muted small' }, '…'));
  const r = await account().get('/projects');
  const mine = (r.projects as Project[]).filter(p => p.member || p.role === 'owner')
    .sort((a, b) => Number(Boolean(a.archived)) - Number(Boolean(b.archived)) || a.title.localeCompare(b.title));
  const manages = mine.filter(p => p.may?.manage || p.role === 'owner').length;
  const room = fit(ctx);
  replace(host,
    h('div', { class: 'widget-top' }, stats([{ n: mine.filter(p => !p.archived).length, label: t('프로젝트') },
                                             ...(manages ? [{ n: manages, label: t('관리') }] : [])])),
    items(mine.slice(0, room).map(p => ({
      href: `/projects/${p.cn}`, text: p.title, title: p.description || p.title,
      sub: [p.role === 'owner' ? t('주인') : '', p.archived ? t('보관됨') : p.description].filter(Boolean).join(' · '),
      aside: faces(p.members), state: p.archived ? 'past' as const : undefined })),
      t('프로젝트가 없습니다.'), mine.length > room ? { href: '/projects', n: mine.length - room } : undefined));
}
