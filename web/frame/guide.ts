// First-visit guidance, declared by each app. Completion is an account preference, not catalog `seen`.
import { h } from './dom';
import { frame, prefs, savePrefs } from './frame';
import { t } from './i18n';
import { setHelp } from './parts';

export interface GuideStep { title: string; text: string; target?: string }

/** A page's guide: shown once until completed or skipped (kept in the account, so signed in only), and again from
 * '사용 안내' in the person's menu of the site header — the one place for it on every page (parts.ts setHelp).
 * `host` is accepted for the callers of the first version and no longer decides where anything goes. Dispose on
 * navigation. */
export function guide(id: string, title: string, steps: GuideStep[], _host?: HTMLElement): () => void {
  if (!steps.length || !frame.uid) return () => undefined;
  let sheet: HTMLDialogElement | undefined;
  let target: Element | null = null;
  let previous: HTMLElement | null = null;
  const clearTarget = () => { target?.classList.remove('guide-target'); target = null; };
  function close(): void {
    clearTarget();
    sheet?.close(); sheet?.remove(); sheet = undefined;
    // back where the person was: the element they opened it from, or the menu that holds it when the menu has closed
    const back = previous?.isConnected && previous.closest('details:not([open])')?.querySelector('summary') || previous;
    if (back?.isConnected) (back as HTMLElement).focus({ preventScroll: true });
  }
  function open(): void {
    if (sheet) return;
    previous = document.activeElement as HTMLElement | null;
    let index = 0;
    const heading = h('h2', { id: 'guide-heading' });
    const text = h('p', { id: 'guide-text' });
    const count = h('p', { class: 'muted small', 'aria-live': 'polite' });
    const error = h('p', { class: 'guide-error', role: 'alert' });
    const back = h('button', { type: 'button', class: 'secondary', onclick: () => { index--; draw(); } }, t('이전'));
    const next = h('button', { type: 'button', onclick: () => { if (index < steps.length - 1) { index++; draw(); } else void finish(); } });
    const skip = h('button', { type: 'button', class: 'secondary', onclick: () => { void finish(); } }, t('건너뛰기'));
    async function finish(): Promise<void> {
      back.disabled = next.disabled = skip.disabled = true;
      try {
        await savePrefs(() => ({ guides: [...new Set([...(prefs.guides ?? []), id])] }));
        close();
      } catch {
        error.textContent = t('안내 완료 상태를 저장하지 못했습니다. 다시 시도하거나 Escape로 닫을 수 있습니다.');
        next.disabled = skip.disabled = false; back.disabled = index === 0;
      }
    }
    function draw(): void {
      clearTarget();
      const step = steps[index];
      heading.textContent = `${title} · ${step.title}`;
      text.textContent = step.text;
      count.textContent = `${index + 1} / ${steps.length}`;
      back.disabled = index === 0;
      next.textContent = index < steps.length - 1 ? t('다음') : t('시작하기');
      target = step.target ? document.querySelector(step.target) : null;
      target?.classList.add('guide-target');
      if (target) target.scrollIntoView({ block: 'center', behavior: 'instant' });
      next.focus();
    }
    sheet = h('dialog', { class: 'site-guide', 'aria-labelledby': 'guide-heading', 'aria-describedby': 'guide-text' },
      count, heading, text, error, h('div', { class: 'actions' }, skip, back, next));
    // Escape dismisses for this visit only; it is never silently counted as completion.
    sheet.addEventListener('keydown', ev => {
      ev.stopPropagation();
      if (ev.key !== 'Tab') return;
      const controls = Array.from(sheet!.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
      const first = controls[0], last = controls[controls.length - 1];
      if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    });
    sheet.addEventListener('cancel', ev => { ev.preventDefault(); close(); });
    document.body.append(sheet); sheet.showModal(); draw();
  }
  setHelp(open);
  if (!(prefs.guides ?? []).includes(id)) open();
  return () => { close(); setHelp(null); };
}
