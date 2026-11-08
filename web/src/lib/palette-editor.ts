import { COLOR_ROLES, button, editedColors, frame, h, lookColors, normalizeHex, prefs, replace, select } from '/auth/static/site.js';
import type { ColorRole, ColorScheme, LookPrefs, ThemeColors } from '/auth/static/site.js';
import { t } from './i18n';

const labels: Record<ColorRole, () => string> = {
  bg: () => t('페이지 배경'), card: () => t('카드 배경'), soft: () => t('보조 배경'),
  text: () => t('본문 글자'), muted: () => t('보조 글자'), line: () => t('테두리'),
  accent: () => t('버튼 강조색'), link: () => t('링크'), ok: () => t('성공 색'),
  warn: () => t('경고 색'), bad: () => t('오류 색'),
};

export function paletteEditor(initial: ColorScheme, save: (colors: LookPrefs['colors']) => Promise<void>): HTMLElement {
  let scheme = initial;
  const stored = prefs.look.colors;
  let draft: NonNullable<LookPrefs['colors']> = { light: { ...stored?.light }, dark: { ...stored?.dark } };
  const box = h('div', { class: 'palette-fields' });
  const preview = h('div', { class: 'palette-preview', 'aria-label': t('팔레트 미리보기') },
    h('div', { class: 'card' }, h('strong', null, t('본문 글자')), ' ', h('span', { class: 'muted' }, t('보조 글자')),
      h('div', { class: 'palette-example-row' },
        h('span', { class: 'palette-link' }, t('링크')), h('span', { class: 'look-sample-accent' }, t('버튼 강조색')),
        h('span', { class: 'tag ok' }, t('성공 색')), h('span', { class: 'tag warn' }, t('경고 색')),
        h('span', { class: 'tag bad' }, t('오류 색')))));
  const status = h('p', { class: 'small', role: 'status' });
  const invalid = new Set<ColorRole>();
  const previewTokens = new Set<string>();
  const apply = button(t('팔레트 저장'), async () => {
    const colors = Object.fromEntries(Object.entries(draft).filter(([, values]) => Object.keys(values).length));
    try { await save(Object.keys(colors).length ? colors : undefined); }
    catch { replace(status, t('설정을 저장하지 못했습니다. 다시 시도하세요.')); }
  });
  const update = () => {
    const look = { ...prefs.look, colors: draft };
    const tokens = editedColors(frame.look, look, scheme);
    const possible = (['light', 'dark'] as const).every(s => s === scheme ? !!tokens : !!editedColors(frame.look, look, s));
    apply.disabled = !possible || invalid.size > 0;
    replace(status, invalid.size > 0 ? t('유효한 HEX 색상을 입력하세요.')
      : !possible ? t('선택한 배경을 함께 쓰면 글자 대비를 맞출 수 없습니다. 배경색들의 밝기를 가깝게 조정하세요.')
      : t('글자와 상태색은 배경과의 대비에 맞춰 조정됩니다.'));
    for (const key of previewTokens) preview.style.removeProperty('--' + key);
    previewTokens.clear();
    if (!tokens) return;
    for (const [key, value] of Object.entries(tokens)) {
      preview.style.setProperty('--' + key, value);
      previewTokens.add(key);
    }
  };
  const draw = () => {
    const values = lookColors(frame.look, { ...prefs.look, colors: draft }, scheme);
    invalid.clear();
    replace(box, COLOR_ROLES.map(role => {
      const id = 'palette-' + role;
      const picker = h('input', { type: 'color', value: values[role], 'aria-label': labels[role]() });
      const field = h('input', { type: 'text', id, value: values[role], maxlength: 7, spellcheck: false });
      const set = (color: string) => { (draft[scheme] as ThemeColors)[role] = color; invalid.delete(role); field.removeAttribute('aria-invalid'); update(); };
      picker.addEventListener('input', () => { field.value = picker.value; set(picker.value); });
      field.addEventListener('input', () => {
        const color = normalizeHex(field.value);
        if (color) { picker.value = color; set(color); }
        else { invalid.add(role); field.setAttribute('aria-invalid', 'true'); update(); }
      });
      return h('div', { class: 'palette-field' }, h('label', { for: id }, labels[role]()), h('div', { class: 'inline-field look-color' }, picker, field));
    }));
    update();
  };
  const mode = select('palette-mode', [['light', t('밝게')], ['dark', t('어둡게')]], scheme,
    async v => { scheme = v === 'dark' ? 'dark' : 'light'; draw(); });
  const editor = h('details', { id: 'palette-editor', class: 'palette-editor' },
    h('summary', null, t('테마별 색상 편집')),
    h('label', null, t('편집할 테마'), mode), preview, box, status,
    h('div', { class: 'actions' }, apply,
      button(t('이 테마 직접 편집 지우기'), () => { draft[scheme] = {}; draw(); }, 'secondary'),
      button(t('취소'), () => {
        draft = { light: { ...stored?.light }, dark: { ...stored?.dark } };
        editor.open = false;
        draw();
      }, 'link')));
  draw();
  return editor;
}
