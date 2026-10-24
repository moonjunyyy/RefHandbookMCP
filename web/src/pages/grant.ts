// The grant form (a new run, a preset): the routing policy as rows of key, model and roles, each
// key offering its own models; then the limits, the pruning levels, the sandbox policy and effort.

import { Json } from '../lib/api';
import { h, replace } from '../lib/dom';

export interface Key { ref: string; provider: string; label: string; format: string; models: string[];
                       models_listed: boolean; status: string }
export interface Options { roles: string[]; context: string[]; handoff: string[]; retention: string[];
                           efforts: string[]; policies: string[]; defaults: Json; max_routes: number }
interface Route { key: string; model: string; roles: string[] }

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

/** The form's parts and a way to read the grant back out of it. `routes: false`: no routing (a flow's
 * routing is its blocks' keys and models), only the limits and levels. */
export function grantForm(keys: Key[], opts: Options, initial?: Json, { routes: withRoutes = true } = {}):
    { el: HTMLElement; grant: () => Json } {
  const g = { ...opts.defaults, ...(initial ?? {}) };
  const byRef = new Map(keys.map(k => [k.ref, k]));
  let routes: Route[] = (initial?.routes as Route[] | undefined)?.map(r => ({ ...r, roles: [...r.roles] })) ??
    (keys.length ? [{ key: keys[0].ref, model: keys[0].models[0] ?? '', roles: [...opts.roles] }] : []);

  const body = h('tbody');
  const add = h('button', { type: 'button', class: 'secondary' }, '경로 추가');
  add.addEventListener('click', () => {
    const k = keys[0];
    routes.push({ key: k?.ref ?? '', model: k?.models[0] ?? '', roles: ['worker'] });
    draw();
  });

  const modelField = (r: Route) => modelPicker(byRef.get(r.key)?.models ?? [], r.model, m => { r.model = m; });

  function draw(): void {
    replace(body, routes.map((r, i) => h('tr', null,
      h('td', { class: 'num' }, String(i + 1)),
      h('td', null, h('select', { onchange: (e: Event) => {
        r.key = (e.target as HTMLSelectElement).value;
        r.model = byRef.get(r.key)?.models[0] ?? '';  // the models are the key's own
        draw();
      } }, keys.map(k => h('option', { value: k.ref, selected: k.ref === r.key }, keyLabel(k))))),
      h('td', null, modelField(r)),
      h('td', { class: 'roles' }, opts.roles.map(role => h('label', { class: 'check' },
        h('input', { type: 'checkbox', checked: r.roles.includes(role), onchange: (e: Event) => {
          const on = (e.target as HTMLInputElement).checked;
          r.roles = on ? [...r.roles, role] : r.roles.filter(x => x !== role);
        } }), ' ', roleName(role)))),
      h('td', { class: 'row-tools' },
        h('button', { type: 'button', class: 'link', title: '위로', disabled: i === 0,
                      onclick: () => { [routes[i - 1], routes[i]] = [routes[i], routes[i - 1]]; draw(); } }, '↑'),
        h('button', { type: 'button', class: 'link', title: '아래로', disabled: i === routes.length - 1,
                      onclick: () => { [routes[i + 1], routes[i]] = [routes[i], routes[i + 1]]; draw(); } }, '↓'),
        h('button', { type: 'button', class: 'link danger-text', title: '빼기', disabled: routes.length === 1,
                      onclick: () => { routes = routes.filter((_, j) => j !== i); draw(); } }, '✕')))));
    add.disabled = routes.length >= opts.max_routes || !keys.length;
  }
  draw();

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
    withRoutes && [h('h3', null, '라우팅'),
    h('p', { class: 'muted small' }, '역할마다 위에서부터 첫 경로로 시작하고, 키가 거부되거나 제공자가 계속 실패하면 같은 역할의 ' +
      '다음 경로로 넘어갑니다. 모델 목록은 고른 키의 것입니다. 워커에 싼 모델을 두면 비용이 줄어듭니다.'),
    keys.length
      ? h('div', { class: 'table-wrap' }, h('table', { class: 'routes' },
          h('thead', null, h('tr', null, h('th', null, '순서'), h('th', null, '키'), h('th', null, '모델'),
            h('th', null, '역할'), h('th', null, ''))), body))
      : h('p', { class: 'flash error' }, '먼저 API 키를 등록하세요.'),
    h('div', { class: 'actions' }, add)],
    h('h3', null, '한도'),
    h('div', { class: 'fields' }, LIMITS.map(([, label], i) => h('label', null, label, limitInputs[i]))),
    h('h3', null, '정리 · 실행 환경'),
    h('div', { class: 'fields' },
      h('label', null, '문맥', selects.context), h('label', null, '전달', selects.handoff),
      h('label', null, '보관', selects.retention), h('label', null, '샌드박스 정책', selects.policy),
      h('label', null, 'effort', selects.effort)));

  function grant(): Json {
    const out: Json = withRoutes ? { routes: routes.map(r => ({ key: r.key, model: r.model.trim(), roles: r.roles })) } : {};
    LIMITS.forEach(([k], i) => { if (limitInputs[i].value !== '') out[k] = Number(limitInputs[i].value); });
    for (const [k, sel] of Object.entries(selects)) out[k] = (sel as HTMLSelectElement).value;
    return out;
  }
  return { el, grant };
}
