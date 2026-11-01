// The projects' widget on the main page: the person's own projects, each a link (docs/projects.md).
// The list is the account service's (its API under the portal's root).

import { account, h, replace, widgetList } from '/auth/static/site.js';
import type { WidgetContext } from '/auth/static/site.js';
import { t } from '../src/lib/i18n';

export default async function widget(host: HTMLElement, _ctx: WidgetContext): Promise<void> {
  replace(host, h('p', { class: 'muted small' }, '…'));
  const r = await account().get('/projects');
  const mine = (r.projects as { cn: string; title: string; member: boolean; role: string; members: string[] }[]).filter(p => p.member || p.role === 'owner');
  replace(host, widgetList(mine.map(p => ({ href: `/projects/${p.cn}`, text: p.title, aside: t('{n}명', { n: p.members.length }) })), t('프로젝트가 없습니다.')),
    h('p', { class: 'small' }, h('a', { href: '/projects' }, t('프로젝트'))));
}
