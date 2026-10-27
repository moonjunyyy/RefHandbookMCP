// What a run is given besides its blocks (a preset, a run): the limits, the pruning levels, the sandbox
// policy and effort; and the parts a block's key and model are picked with.

import { Json } from '../lib/api';
import { h } from '../lib/dom';

export interface Key { ref: string; provider: string; label: string; format: string; models: string[];
                       models_listed: boolean; status: string }
export interface Options { roles: string[]; context: string[]; handoff: string[]; retention: string[];
                           efforts: string[]; policies: string[]; defaults: Json; max_routes: number }

const ROLE = { lead: '리드', worker: '워커', verifier: '검증' } as Record<string, string>;
const LEVEL: Record<string, string> = {
  full: '전체', trim: '오래된 출력 정리', digest: '주기적 요약', minimal: '최소',
  refs: 'id만', all: '모두 보관', verified: '검증된 것만', exits: '결과만', purge: '결과 외 삭제',
};
const PROVIDER: Record<string, string> = { anthropic: 'Claude', openai: 'OpenAI', gemini: 'Gemini', custom: 'Custom' };
const LIMITS: [string, string][] = [['max_agents', '동시 에이전트'], ['max_spawns', '총 에이전트 수'],
  ['max_depth', '최대 깊이'], ['max_steps', '에이전트당 턴'], ['max_tokens', '토큰 한도 (0: 없음)']];
const OTHER = '__other__';

export const roleName = (r: string) => ROLE[r] ?? r;
export const providerName = (p: string) => PROVIDER[p] ?? p;

/** A model of a key: the key's own list, or typed (when it lists none, or "직접 입력"). `set` hears each
 * change; a key that lists models starts on its first when nothing is chosen yet. */
export function modelPicker(listed: string[], value: string, set: (model: string) => void): HTMLElement {
  const custom = value !== '' && !listed.includes(value);
  const input = h('input', { value, placeholder: '모델 이름', class: custom || !listed.length ? '' : 'hidden',
                             oninput: (e: Event) => set((e.target as HTMLInputElement).value.trim()) });
  if (!listed.length) return input;  // nothing listed for this key: type it
  const sel = h('select', { onchange: (e: Event) => {
    const v = (e.target as HTMLSelectElement).value;
    if (v === OTHER) { input.classList.remove('hidden'); set(input.value.trim()); input.focus(); }
    else { input.classList.add('hidden'); set(v); }
  } },
    listed.map(m => h('option', { value: m, selected: m === value }, m)),
    h('option', { value: OTHER, selected: custom }, '직접 입력…'));
  if (!value) set(listed[0]);
  return h('div', { class: 'model-pick' }, sel, input);
}

export const keyLabel = (k: Key) => `${k.ref} (${providerName(k.provider)}${k.status !== 'ok' ? ', ' + k.status : ''})`;

/** The limits and levels a run is given (its blocks' keys and models are its routing), and a way to read
 * them back out of the form. */
export function grantForm(opts: Options, initial?: Json):
    { el: HTMLElement; grant: () => Json } {
  const g = { ...opts.defaults, ...(initial ?? {}) };
  const limitInputs = LIMITS.map(([k]) => h('input', { type: 'number', min: 0, name: k, value: g[k] ?? '' }));
  const level = (name: string, choices: string[]) =>
    h('select', { name }, choices.map(c => h('option', { value: c, selected: c === g[name] }, `${LEVEL[c] ?? c} (${c})`)));
  const selects = {
    context: level('context', opts.context), handoff: level('handoff', opts.handoff),
    retention: level('retention', opts.retention),
    policy: h('select', { name: 'policy' }, opts.policies.map(p => h('option', { value: p, selected: p === g.policy }, p))),
    effort: h('select', { name: 'effort' }, opts.efforts.map(e => h('option', { value: e, selected: e === (g.effort ?? '') },
      e || '기본값'))),
  };
  const el = h('div', { class: 'grant' },
    h('h3', null, '한도'),
    h('div', { class: 'fields' }, LIMITS.map(([, label], i) => h('label', null, label, limitInputs[i]))),
    h('h3', null, '정리 · 실행 환경'),
    h('div', { class: 'fields' },
      h('label', null, '문맥', selects.context), h('label', null, '전달', selects.handoff),
      h('label', null, '보관', selects.retention),
      h('label', null, '샌드박스 정책 ', h('a', { class: 'small', href: '/approvals' }, '정책 보기'), selects.policy),
      h('label', null, 'effort', selects.effort)));

  function grant(): Json {
    const out: Json = {};
    LIMITS.forEach(([k], i) => { if (limitInputs[i].value !== '') out[k] = Number(limitInputs[i].value); });
    for (const [k, sel] of Object.entries(selects)) out[k] = (sel as HTMLSelectElement).value;
    return out;
  }
  return { el, grant };
}
