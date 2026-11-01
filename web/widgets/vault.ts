// The notes' widgets on the main page (docs/apps-vault-calendar.md §4.4): `recent` (the notes last
// changed) and `home` (the vault's Home note, rendered). One module for both (ctx.widget.id); the first
// vault of the person's, as the page opens it. The Home widget renders markdown without the page's
// mathematics (that module is heavier than a widget should be): formulas show as written.

import { api, h, replace, widgetList } from '/auth/static/site.js';
import type { WidgetContext } from '/auth/static/site.js';
import { t } from '../src/lib/i18n';
import MarkdownIt from 'markdown-it';

const vaults = api('/vault/api/v1');
const href = (vid: string, path: string) => `/vault/${vid}/${path.split('/').map(encodeURIComponent).join('/')}`;

export default async function widget(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  replace(host, h('p', { class: 'muted small' }, '…'));
  const listed = await vaults.get('/vaults');
  const v = (listed.vaults as { id: string; name: string; status: string }[]).find(x => x.status === 'ok');
  if (!v) { replace(host, h('p', { class: 'muted small' }, h('a', { href: '/vault' }, t('볼트 추가')))); return; }
  const base = api(`/vault/api/v1/vaults/${v.id}`);
  if (ctx.widget.id === 'home') {
    try {
      const note = await base.get('/file?path=Home.md');
      const md = new MarkdownIt({ html: false, linkify: true });
      const body = h('div', { class: 'note-body small' });
      body.innerHTML = md.render(String(note.text).replace(/^---\n[\s\S]*?\n---\n/, '').replace(/!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]/g,
        (_m, target: string, alias?: string) => `[${alias ?? target}](${href(v.id, target.trim().endsWith('.md') ? target.trim() : `${target.trim()}.md`)})`));
      replace(host, body);
    } catch {
      replace(host, h('p', { class: 'muted small' }, h('a', { href: `/vault/${v.id}` }, t('Home 노트가 없습니다.'))));
    }
    return;
  }
  const r = await base.get('/recent?n=5');
  replace(host, widgetList((r.notes as { path: string; title: string; mtime: number }[]).map(n =>
    ({ href: href(v.id, n.path), text: n.title, aside: new Date(n.mtime * 1000).toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }) })), t('노트가 없습니다.')));
}
