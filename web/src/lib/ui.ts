// The parts every page is made of, in the site's stylesheet's terms: the frame, a page head, a section
// card, a flash, buttons that call the API and show what happened.

import { ApiError, frame } from './api';
import { Child, h, replace } from './dom';
import { locale, t } from './i18n';

export const main = () => document.getElementById('main') as HTMLElement;

/** The header: the site's name (home), the menu, who is signed in. */
export function header(): void {
  document.getElementById('brand')!.textContent = frame.title;
  const nav = document.getElementById('nav') as HTMLElement;
  replace(nav,
    frame.uid && [
      h('a', { href: '/' }, t('홈')),
      h('a', { href: '/apps' }, t('앱')),
      h('a', { href: `${frame.portal}/` }, t('내 계정')),
      frame.menu.map(m => h('a', { href: m.href }, m.label)),
      h('a', { href: '/settings', title: t('설정') }, h('code', null, frame.uid)),
      h('a', { href: `${frame.signin}/logout` }, t('로그아웃')),
    ],
    !frame.uid && [h('a', { href: '/apps' }, t('앱')),
      h('a', { href: `${frame.signin}/login?next=${encodeURIComponent(location.pathname)}` }, t('로그인'))]);
}

export function title(text: string): void {
  document.title = text ? `${text} · ${frame.title}` : frame.title;
}

export function pageHead(heading: string, intro: Child, tabs?: { href: string; label: string }[]): HTMLElement {
  title(heading);
  return h('div', { class: 'page-head' },
    h('h1', null, heading),
    intro && h('p', { class: 'muted' }, intro),
    tabs && h('nav', { class: 'chips' }, tabs.map(t =>
      h('a', { class: `chip${current(t.href, tabs.map(x => x.href)) ? ' warn' : ''}`, href: t.href }, t.label))));
}

/** Whether a tab is the current page's: its own path, or the longest tab path the page is under. */
function current(href: string, all: string[]): boolean {
  const path = location.pathname.replace(/\/$/, '');
  const norm = (x: string) => x.replace(/\/$/, '');
  const under = all.filter(x => path === norm(x) || path.startsWith(norm(x) + '/'));
  const best = under.sort((a, b) => norm(b).length - norm(a).length)[0];
  return best !== undefined && norm(best) === norm(href);
}

export function section(heading: Child, ...body: Child[]): HTMLElement {
  return h('section', { class: 'card section' }, h('h2', null, heading), ...body);
}

export function empty(text: string): HTMLElement {
  return h('p', { class: 'empty muted' }, text);
}

/** The page's message line (one at a time, at the top of the page). */
export function flash(kind: 'ok' | 'error', text: string): void {
  const m = main();
  m.querySelector(':scope > .flash')?.remove();
  const f = h('p', { class: `flash ${kind}` }, text);
  const head = m.querySelector(':scope > .page-head');
  if (head) head.after(f); else m.prepend(f);
  f.scrollIntoView({ block: 'nearest' });
}

let pending: ['ok' | 'error', string] | null = null;

/** A message for the page about to be shown (after go()): the router shows it once that page is drawn. */
export function flashNext(kind: 'ok' | 'error', text: string): void {
  pending = [kind, text];
}

export function showPending(): void {
  if (pending) flash(...pending);
  pending = null;
}

export function message(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
}

/** Run an action: the button waits while it runs; a refusal is shown, a success too (if given). */
export async function act<T>(button: HTMLButtonElement | null, fn: () => Promise<T>, ok?: string | ((r: T) => string)):
    Promise<T | undefined> {
  if (button) button.disabled = true;
  try {
    const r = await fn();
    if (ok) flash('ok', typeof ok === 'function' ? ok(r) : ok);
    return r;
  } catch (e) {
    flash('error', message(e));
    return undefined;
  } finally {
    if (button) button.disabled = false;
  }
}

/** A form that, when submitted, runs `fn` with its button held. */
export function form(attrs: Record<string, unknown>, fn: (f: HTMLFormElement, b: HTMLButtonElement | null) => Promise<void>,
                     ...children: Child[]): HTMLFormElement {
  const f = h('form', { ...attrs }, ...children);
  f.addEventListener('submit', ev => {
    ev.preventDefault();
    const b = (ev as SubmitEvent).submitter as HTMLButtonElement | null;
    void fn(f, b);
  });
  return f;
}

export const when = (t: number | null | undefined): string =>
  t ? new Date(t * 1000).toLocaleString(locale(), { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-';
export const num = (n: number | null | undefined): string => (n ? n.toLocaleString(locale()) : '-');

/** Go to a page of the app without a reload (links inside the app). */
export function go(path: string): void {
  history.pushState(null, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function link(href: string, ...children: Child[]): HTMLAnchorElement {
  return h('a', { href, onclick: (ev: MouseEvent) => {
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;
    ev.preventDefault();
    go(href);
  } }, ...children);
}

/** A link inside the app that looks like a button (secondary: the outlined one). */
export function buttonLink(href: string, text: string, secondary = false): HTMLAnchorElement {
  const a = link(href, text);
  a.className = secondary ? 'button secondary' : 'button';
  return a;
}

export function tag(text: string, kind = ''): HTMLElement {
  return h('span', { class: `tag ${kind}`.trim() }, text);
}
