import { dialog, flash, h } from '/auth/static/site.js';
import { t } from './i18n';

export async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const field = h('textarea', { readonly: true, autofocus: true, rows: 2,
      onfocus: () => field.select() }, value);
    await dialog(t('직접 복사'), h('label', null, t('자동 복사가 차단됐습니다. 선택된 텍스트를 복사하세요.'), field), { justClose: true });
    return;
  }
  flash('ok', t('복사했습니다.'));
}
