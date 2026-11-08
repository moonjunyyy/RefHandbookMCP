import { t } from './i18n';

let hasDraft: () => boolean = () => false;

export function watchDraft(node: HTMLElement, dirty: () => boolean): void {
  hasDraft = () => node.isConnected && dirty();
}

export function canLeave(): boolean {
  return !hasDraft() || window.confirm(t('저장하지 않은 변경을 버리고 이동할까요?'));
}

window.addEventListener('beforeunload', event => {
  if (!hasDraft()) return;
  event.preventDefault();
  event.returnValue = '';
});
