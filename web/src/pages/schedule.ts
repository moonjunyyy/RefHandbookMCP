// A preset's schedules (the presets page and the flow page alike): add one by cron, with the next
// times shown as it is typed; each one turned off or on, or removed.

import { agents, Json } from '../lib/api';
import { h } from '../lib/dom';
import { t } from '../lib/i18n';
import { act, flashNext, form, link, showPending, tag, when } from '../lib/ui';

export const cronHelp = () => [t('예약은 cron 다섯 칸(분 시 일 월 요일, 서버 시간)입니다.'), ' ',
  h('code', null, '0 9 * * mon-fri'), ': ', t('평일 9시'), ', ', h('code', null, '@daily'), ': ', t('매일'), '. ',
  t('앞 실행이 아직 돌고 있으면 그 회차는 건너뜁니다.')];

/** The form that adds a schedule to preset `name`, and the preset's schedules. `redraw`: the page again
 * (the message of what was done is shown on it). */
export function scheduling(name: string, schedules: Json[], redraw: () => Promise<void>):
    { add: HTMLElement; list: HTMLElement | false } {
  const done = async (said: string) => { flashNext('ok', said); await redraw(); showPending(); };
  const preview = h('span', { class: 'muted small' });
  const cron = h('input', { name: 'cron', required: true, placeholder: '0 9 * * mon-fri', class: 'cron', oninput: () => {
    window.clearTimeout(Number(cron.dataset.t));
    cron.dataset.t = String(window.setTimeout(async () => {
      if (!cron.value.trim()) { preview.textContent = ''; return; }
      try {
        const r = await agents.post('/cron', { cron: cron.value });
        preview.textContent = t('다음: {times}', { times: r.next.slice(0, 3).map(when).join(', ') });
      } catch (e) { preview.textContent = (e as Error).message; }
    }, 300));
  } });
  const add = h('div', { class: 'actions' }, form({ class: 'inline' }, async (_f, b) => {
    if (await act(b, () => agents.post(`/presets/${encodeURIComponent(name)}/schedules`, { cron: cron.value }))) {
      await done(t('예약을 추가했습니다.'));
    }
  }, cron, h('button', { class: 'secondary' }, t('예약 추가'))), ' ', preview);
  const list = schedules.length > 0 && h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null, ['cron', t('상태'), t('다음'), t('마지막'), t('메모'), ''].map(x => h('th', null, x)))),
    h('tbody', null, schedules.map((s: Json) => h('tr', null,
      h('td', null, h('code', null, s.cron)), h('td', null, s.enabled ? tag(t('켜짐'), 'ok') : tag(t('꺼짐'))),
      h('td', null, when(s.next_at)),
      h('td', null, when(s.last_at), s.last_run && [' ', link(`/agents/runs/${s.last_run}`, t('실행'))]),
      h('td', { class: 'wrap muted small' }, s.note),
      h('td', null,
        h('button', { class: 'secondary', onclick: async (e: Event) => {
          if (await act(e.target as HTMLButtonElement, () => agents.patch(`/schedules/${s.id}`, { enabled: !s.enabled }))) {
            await done(s.enabled ? t('예약을 껐습니다.') : t('예약을 켰습니다.'));
          }
        } }, s.enabled ? t('끄기') : t('켜기')), ' ',
        h('button', { class: 'secondary', onclick: async (e: Event) => {
          if (await act(e.target as HTMLButtonElement, () => agents.del(`/schedules/${s.id}`))) await done(t('예약을 지웠습니다.'));
        } }, t('삭제'))))))));
  return { add, list };
}
