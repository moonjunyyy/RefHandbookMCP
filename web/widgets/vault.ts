// The notes' widgets on the main page (docs/apps-vault-calendar.md §4.4), drawn with the frame's parts (docs/frame.md
// §4.2). One module for all (ctx.widget.id); the first vault of the person's, as the page opens it.
//   recent — how many notes changed in the last 7 days and each of the last 14, then the notes last changed (where they
//            are, how long ago), as many as the cell holds.
//   tags   — the vault's tags as bars by how many notes carry them; a tag opens the vault's search for it.
//   home   — the vault's Home note, rendered. The Home widget renders markdown without the page's mathematics (that
//            module is heavier than a widget should be): formulas show as written.

import { activity, api, ago, bars, dayKey, fit, h, items, replace, stats } from '/auth/static/site.js';
import type { WidgetContext } from '/auth/static/site.js';
import { t } from '../src/lib/i18n';
import MarkdownIt from 'markdown-it';

const vaults = api('/vault/api/v1');
const href = (vid: string, path: string) => `/vault/${vid}/${path.split('/').map(encodeURIComponent).join('/')}`;
const DAYS = 14;   // the run of days the activity shows (two weeks: this one and the last)
const RECENT = 100;  // the notes asked for to count them by day (the service's most)

async function recent(host: HTMLElement, ctx: WidgetContext, vid: string): Promise<void> {
  const base = api(`/vault/api/v1/vaults/${vid}`);
  const r = await base.get(`/recent?n=${RECENT}`);
  const notes = r.notes as { path: string; title: string; mtime: number }[];
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = [...Array(DAYS)].map((_, i) => { const d = new Date(today); d.setDate(today.getDate() - (DAYS - 1 - i)); return d; });
  const perDay = new Map<string, number>();
  for (const n of notes) { const k = dayKey(new Date(n.mtime * 1000)); perDay.set(k, (perDay.get(k) ?? 0) + 1); }
  const weekAgo = today.getTime() - 6 * 864e5;
  const thisWeek = notes.filter(n => n.mtime * 1000 >= weekAgo).length;
  const room = fit(ctx);
  replace(host,
    h('div', { class: 'widget-top' }, stats([{ n: thisWeek >= RECENT ? `${RECENT}+` : thisWeek, label: t('7일 동안 고친 노트') }]),
      activity(days.map(d => ({ date: d, n: perDay.get(dayKey(d)) ?? 0 })), t('최근 {n}일 동안 날마다 고친 노트 수', { n: DAYS }))),
    items(notes.slice(0, room).map(n => {
      const folder = n.path.includes('/') ? n.path.slice(0, n.path.lastIndexOf('/')) : '';
      return { href: href(vid, n.path), text: n.title, title: n.path, sub: folder, aside: ago(n.mtime * 1000) };
    }), t('노트가 없습니다.'), notes.length > room ? { href: `/vault/${vid}`, n: notes.length - room } : undefined));
}

async function tags(host: HTMLElement, ctx: WidgetContext, vid: string): Promise<void> {
  const base = api(`/vault/api/v1/vaults/${vid}`);
  const r = await base.get('/tags');
  const all = r.tags as { tag: string; notes: number }[];
  const room = fit(ctx);
  replace(host,
    h('div', { class: 'widget-top' }, stats([{ n: all.length, label: t('태그') }])),
    bars(all.slice(0, room).map(x => ({ label: `#${x.tag}`, n: x.notes, href: `/vault/${vid}?q=${encodeURIComponent(x.tag)}` })), t('태그가 없습니다.')),
    all.length > room && h('a', { class: 'items-more small', href: `/vault/${vid}` }, t('{n}개 더', { n: all.length - room })));
}

async function home(host: HTMLElement, vid: string): Promise<void> {
  const base = api(`/vault/api/v1/vaults/${vid}`);
  try {
    const note = await base.get('/file?path=Home.md');
    const md = new MarkdownIt({ html: false, linkify: true });
    const body = h('div', { class: 'note-body small' });
    body.innerHTML = md.render(String(note.text).replace(/^---\n[\s\S]*?\n---\n/, '').replace(/!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]/g,
      (_m, target: string, alias?: string) => `[${alias ?? target}](${href(vid, target.trim().endsWith('.md') ? target.trim() : `${target.trim()}.md`)})`));
    replace(host, body);
  } catch {
    replace(host, h('p', { class: 'muted small' }, h('a', { href: `/vault/${vid}` }, t('Home 노트가 없습니다.'))));
  }
}

export default async function widget(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  replace(host, h('p', { class: 'muted small' }, '…'));
  const listed = await vaults.get('/vaults');
  const usable = (listed.vaults as { id: string; name: string; status: string }[]).filter(x => x.status === 'ok');
  const v = usable.find(x => x.id === ctx.params?.vault) ?? usable[0];  // the place's vault when it is usable, else the first
  if (!v) { replace(host, h('p', { class: 'muted small' }, h('a', { href: '/vault' }, t('볼트 추가')))); return; }
  if (ctx.widget.id === 'home') { await home(host, v.id); return; }
  if (ctx.widget.id === 'tags') { await tags(host, ctx, v.id); return; }
  await recent(host, ctx, v.id);
}
