// The public board's widget on the main page (docs/board.md), drawn with the frame's parts (docs/frame.md §4.2):
// how many notices there are and how many shares, then the notices — the pinned ones first — and what was shared
// last, each opening the board where it is. The board is the handbook's (/board/api/v1).

import { ago, api, fit, h, items, replace, stats, tag } from '/auth/static/site.js';
import type { Item, Json, WidgetContext } from '/auth/static/site.js';
import { n_, t } from '../src/lib/i18n';

const KIND: Record<string, string> = { preset: n_('프리셋'), layer: n_('레이어') };
const P = '/board';
const NOTICES = `${P}?view=notice`;

export default async function widget(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  replace(host, h('p', { class: 'muted small' }, '…'));
  const d = await api('/board/api/v1').get('/');
  const notices = d.notices as Json[];
  const shares = (d.shares as Json[]).filter(s => !s.hidden);
  const room = fit(ctx);
  // the room, split: the notices first; the shares keep half of it when there are both
  const nNotices = Math.min(notices.length, room - Math.min(shares.length, Math.floor(room / 2)));
  const nShares = Math.min(shares.length, room - nNotices);
  const notice = (n: Json): Item => ({ href: NOTICES, text: n.title, title: n.title, sub: ago(n.updated * 1000),
                                       aside: n.pinned ? tag(t('고정'), 'ok') : undefined });
  const share = (s: Json): Item => ({ href: `${P}?view=${s.kind}`, text: s.title, title: s.about || s.title,
                                      sub: [t(KIND[s.kind] ?? s.kind), s.author].join(' · '), aside: ago(s.updated * 1000) });
  const more = notices.length + shares.length - nNotices - nShares;
  replace(host,
    h('div', { class: 'widget-top' }, stats([{ n: notices.length, label: t('공지'), href: NOTICES }, { n: shares.length, label: t('공유'), href: P }])),
    items([{ title: t('공지'), aside: String(notices.length), items: notices.slice(0, nNotices).map(notice) },
           { title: t('새 공유'), aside: String(shares.length), items: shares.slice(0, nShares).map(share) }],
          t('아직 공지도 공유도 없습니다.'), more > 0 ? { href: P, n: more } : undefined));
}
