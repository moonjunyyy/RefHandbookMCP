// The person's settings (/settings), kept with their account (docs/frame.md §2): the language, the theme, the
// page to open after signing in, and the look (§1.3: the colour, the corners, the type, the text size, the main
// page's columns, an image under the page — the choices the site file declares; the body's, the headings' and the
// code's font from the open fonts the site ships, each shown in its own face) — each chosen in place and kept
// at once, with its default beside it when it is not the default. The apps are added in the store (/apps) and
// the main page is arranged on the main page: neither is a setting.

import { DEFAULTS, IMAGE, LANGS, button, choice, editedColors, flash, frame, h, lookTokens, main, normalizeHex, onApps, pageHead, prefs, previewFonts, primaryLink, replace, savePrefs, section, select } from '/auth/static/site.js';
import type { FontKind, LookChoice, LookKind, LookPrefs, Prefs } from '/auth/static/site.js';
import { t } from '../lib/i18n';
import { paletteEditor } from '../lib/palette-editor';

/** The languages to choose from: the browser's, or one of the site's (each named in its own). */
const languages = (): [string, string][] => [['auto', t('브라우저 언어 따르기')], ...LANGS];
const themes = (): [string, string][] => [['auto', t('기기 설정 따르기')], ['light', t('밝게')], ['dark', t('어둡게')]];

/** The token each font of the look redeclares (theme.css: --sans, --serif, --mono), and theme.css's own value of it. */
const FONT_TOKEN: Record<FontKind, string> = { type: 'sans', heading: 'serif', mono: 'mono' };
/** A line set in a font, to see it by: the letters a reader meets (Korean, Latin, figures), a line of code. */
const SPECIMEN: Record<FontKind, string> = {
  type: '다람쥐 헌 쳇바퀴에 타고파 · The quick brown fox 0123',  // i18n: data (a specimen, the same in every language)
  heading: '오늘의 노트 — Notes of the Day',  // i18n: data
  mono: 'const 합 = xs.reduce((a, b) => a + b, 0) // 0O 1lI',  // i18n: data
};

/** Where one may start: the main page, the catalog, each app that is on (and its pages the site links). */
function starts(): [string, string][] {
  const out: [string, string][] = [['/', t('홈')], ['/apps', t('앱')]];
  for (const c of onApps()) {
    for (const l of [{ label: c.title, href: c.href }, ...c.links]) {
      if (l.href && l.href.startsWith('/') && !out.some(([href]) => href === l.href)) {
        out.push([l.href, l.label === c.title ? c.title : `${c.title} · ${l.label}`]);
      }
    }
  }
  if (!out.some(([href]) => href === prefs.start)) out.push([prefs.start, prefs.start]);
  return out;
}

export async function settings(): Promise<void> {
  drawSettings();
}

function drawSettings(draft?: string, focus?: string, draftHex?: string): void {
  if (!frame.uid) {
    replace(main(), pageHead(t('설정')), h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/settings`, t('로그인'))));
    return;
  }
  const controls = h('div', { class: 'settings-controls' });
  const status = h('p', { class: 'muted small settings-status', role: 'status' });
  const save = async (change: Partial<Prefs> | (() => Promise<Partial<Prefs>>), target: string, after?: () => void, resetImage = false) => {
    if (controls.inert) return;
    controls.inert = true;
    status.textContent = t('저장 중…');
    try {
      const next = typeof change === 'function' ? await change() : change;
      if (next.look && next.look.palette !== prefs.look.palette && next.look.colors
        && (['light', 'dark'] as const).some(s => next.look?.colors?.[s] && !editedColors(frame.look, next.look, s))) {
        throw new Error('palette-contrast');
      }
      await savePrefs(next);
      if (!controls.isConnected) return;
      if (after) { after(); return; }
      const imageChanged = next.look && next.look.image !== initialImage;
      drawSettings(imageChanged || resetImage ? undefined : image.value, target);
    } catch (error) {
      if (!controls.isConnected) return;
      drawSettings(image.value, target, target === '#accent-hex' ? hex.value : undefined);
      flash('error', error instanceof Error && error.message === 'background-image'
        ? t('배경 이미지를 불러올 수 없습니다. 주소를 확인하세요.')
        : error instanceof Error && error.message === 'palette-contrast'
          ? t('이 프리셋은 직접 편집한 배경색과 함께 쓰기 어렵습니다. 테마별 색상에서 배경을 조정하세요.')
          : t('설정을 저장하지 못했습니다. 다시 시도하세요.'));
    }
  };
  const value = (name: keyof typeof DEFAULTS & ('lang' | 'theme' | 'start'), label: string, choices: [string, string][],
                 after?: () => void) =>
    h('div', { class: 'value' },
      h('label', { for: name }, label),
      select(name, choices, prefs[name], v => save({ [name]: v }, '#' + name, after)),
      prefs[name] !== DEFAULTS[name]
        ? button(t('기본값'), () => save({ [name]: DEFAULTS[name] }, '#' + name, after), 'link')
        : h('span'));
  const lookChange = (change: LookPrefs): Partial<Prefs> => {
    const look = { ...prefs.look, ...change };
    for (const k of Object.keys(look) as (keyof LookPrefs)[]) if (look[k] === undefined || look[k] === '' || (k === 'columns' && look[k] === 0)) delete look[k];
    return { look };
  };
  const focusLook = (kind: string) => '[data-look=' + kind + '] [aria-pressed=true]';
  const keepLook = (kind: string, change: LookPrefs) => save(lookChange(change), focusLook(kind));
  const swatch = (c: LookChoice) => {
    const dot = h('span', { class: 'swatch', 'aria-hidden': 'true' });
    if (c.light?.accent && c.dark?.accent) {
      dot.style.setProperty('--swatch-light', c.light.accent);
      dot.style.setProperty('--swatch-dark', c.dark.accent);
    }
    return [dot, c.label];
  };
  /** A kind of the look: its choices as chips (the first is theme.css's own), and the way back to it. */
  const lookValue = (kind: LookKind, label: string) => {
    const choices = frame.look[kind] ?? [];
    if (choices.length < 2) return false;
    const custom = (kind === 'palette' && prefs.look.accent !== undefined) || (kind === 'corner' && prefs.look.radius !== undefined);
    const cur = custom ? '' : choices.find(c => c.id === prefs.look[kind])?.id ?? choices[0].id;
    return h('div', { class: 'value' }, h('span', { class: 'label' }, label),
      choice(choices.map(c => [c.id, kind === 'palette' ? swatch(c) : c.label]), cur,
             v => void keepLook(kind, { [kind]: v === choices[0].id ? undefined : v,
               ...(kind === 'palette' ? { accent: undefined } : kind === 'corner' ? { radius: undefined } : {}) }), { 'aria-label': label, 'data-look': kind }),
      cur !== choices[0].id ? button(t('기본값'), () => keepLook(kind, { [kind]: undefined,
        ...(kind === 'palette' ? { accent: undefined } : kind === 'corner' ? { radius: undefined } : {}) }), 'link') : h('span'));
  };
  const cols = frame.look.columns ?? [];
  const initialImage = prefs.look.image;
  const image = h('input', { id: 'image', type: 'text', inputmode: 'url', name: 'image', value: draft ?? initialImage ?? '',
    placeholder: 'https://…', 'aria-describedby': 'image-help', 'aria-label': t('배경 이미지 주소') });
  const putImage = async () => {
    const v = image.value.trim();
    if (v && !IMAGE.test(v)) { flash('error', t('https:// 로 시작하는 주소나 이 사이트의 /… 주소를 적으세요.')); image.focus(); return; }
    await save(async () => {
      if (v && v !== initialImage) {
        const probe = new Image();
        probe.src = v;
        try { await probe.decode(); } catch { throw new Error('background-image'); }
      }
      return lookChange({ image: v || undefined });
    }, '#image');
  };
  image.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); void putImage(); } });
  const preview = h('div', { class: 'look-preview' },
    h('div', { class: 'look-sample' },
      h('strong', null, t('모양 미리보기')),
      h('span', { class: 'muted small' }, t('색, 글꼴, 글자 크기와 모서리가 사이트 전체에 적용됩니다.')),
      h('span', { class: 'look-sample-accent' }, t('강조 색'))));
  const updatePreview = (change: LookPrefs) => {
    const tokens = lookTokens(frame.look, { ...prefs.look, ...change });
    const scheme = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const palette = scheme === 'dark' ? tokens.dark : tokens.light;
    for (const [key, value] of Object.entries({ ...palette, ...tokens.both })) preview.style.setProperty('--' + key, value);
  };
  const resetCustom = (key: keyof LookPrefs, id: string) =>
    prefs.look[key] !== undefined ? button(t('기본값'), () => save(lookChange({ [key]: undefined }), '#' + id), 'link') : h('span');
  const dark = document.documentElement.dataset.theme === 'dark'
    || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
  const preset = frame.look.palette.find(c => c.id === prefs.look.palette);
  const schemeAccent = (dark ? preset?.dark : preset?.light)?.accent;
  const defaultAccent = getComputedStyle(document.documentElement).getPropertyValue(dark ? '--dark-accent' : '--light-accent');
  const selectedAccent = normalizeHex(prefs.look.accent ?? schemeAccent ?? '') ?? normalizeHex(defaultAccent) ?? '#' + '0'.repeat(6);
  const picker = h('input', { id: 'accent-picker', type: 'color', value: selectedAccent, 'aria-label': t('강조 색상 선택') });
  const hex = h('input', { id: 'accent-hex', type: 'text', maxlength: 7, value: draftHex ?? selectedAccent, spellcheck: false, 'aria-label': t('HEX 색상') });
  const putHex = async () => {
    const accent = normalizeHex(hex.value);
    if (!accent) { flash('error', t('유효한 HEX 색상을 입력하세요.')); hex.focus(); return; }
    return save(lookChange({ accent }), '#accent-hex');
  };
  picker.addEventListener('input', () => { hex.value = picker.value; updatePreview({ accent: picker.value }); });
  picker.addEventListener('change', () => void save(lookChange({ accent: picker.value }), '#accent-picker'));
  hex.addEventListener('input', () => {
    const accent = normalizeHex(hex.value);
    if (accent) { picker.value = accent; updatePreview({ accent }); }
  });
  hex.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); putHex(); } });
  const slider = (key: 'radius' | 'imageBlur' | 'imageDim', label: string, unit: string, max: number, initial: number) => {
    const input = h('input', { id: key, type: 'range', min: 0, max, step: 1, value: initial });
    const readout = h('output', { for: key }, input.value + unit);
    input.addEventListener('input', () => {
      readout.value = input.value + unit;
      updatePreview({ [key]: input.valueAsNumber });
    });
    input.addEventListener('change', () => void save(lookChange({ [key]: input.valueAsNumber }), '#' + key));
    return h('div', { class: 'value' }, h('label', { for: key }, label),
      h('div', { class: 'inline-field look-slider' }, input, readout), resetCustom(key, key));
  };
  // a font's face is fetched only when its row comes into view (the open fonts are many and each is its own download)
  const inView = 'IntersectionObserver' in window ? new IntersectionObserver(seen => {
    for (const e of seen) if (e.isIntersecting) { previewFonts((e.target as HTMLElement).dataset.fonts?.split(' ').filter(Boolean)); inView?.unobserve(e.target); }
  }, { rootMargin: '160px' }) : null;
  /** A font of the look (the body's, the headings', the code's): its choices grouped by what they are, each row set
   * in its own face, chosen at once; the way back to theme.css's own beside it. */
  const fontValue = (kind: FontKind, label: string) => {
    const choices = frame.look[kind] ?? [];
    if (choices.length < 2) return false;
    const cur = choices.find(c => c.id === prefs.look[kind])?.id ?? choices[0].id;
    const row = (c: LookChoice, i: number) => {
      const sample = h('span', { class: 'font-sample', 'aria-hidden': 'true' }, SPECIMEN[kind]);
      sample.style.setProperty('font-family', c.tokens?.[FONT_TOKEN[kind]] ?? `var(--${FONT_TOKEN[kind]}-default)`);
      const el = h('button', { type: 'button', class: 'font-choice', 'aria-pressed': String(c.id === cur), 'data-fonts': (c.fonts ?? []).join(' '),
                               onclick: () => void keepLook(kind, { [kind]: i === 0 ? undefined : c.id }) },
        h('span', { class: 'font-name' }, c.label), sample);
      if (c.fonts?.length) { if (inView) inView.observe(el); else previewFonts(c.fonts); }
      return el;
    };
    const groups = [...new Set(choices.map(c => c.group ?? ''))];
    return h('div', { class: 'value font-value' }, h('span', { class: 'label' }, label),
      h('div', { class: 'font-list', role: 'group', 'aria-label': label, 'data-look': kind },
        groups.map(g => h('div', { class: 'font-group' },
          groups.length > 1 && h('p', { class: 'font-group-title small muted' }, frame.look.groups[g] ?? g),
          choices.map((c, i) => [c, i] as const).filter(([c]) => (c.group ?? '') === g).map(([c, i]) => row(c, i))))),
      cur !== choices[0].id ? button(t('기본값'), () => keepLook(kind, { [kind]: undefined }), 'link') : h('span'));
  };
  const appearance = section(t('모양'), preview,
    value('theme', t('테마'), themes()),
    lookValue('palette', t('색')),
    h('div', { class: 'value' }, h('label', { for: 'accent-picker' }, t('공통 강조색')),
      h('div', { class: 'inline-field look-color' }, picker, hex, button(t('적용'), putHex, 'secondary')),
      resetCustom('accent', 'accent-hex')),
    paletteEditor(dark ? 'dark' : 'light', async colors => {
      if (controls.inert) return;
      controls.inert = true;
      try {
        await savePrefs(lookChange({ colors }));
        if (controls.isConnected) drawSettings(image.value, '#palette-editor summary');
      } finally {
        controls.inert = false;
      }
    }),
    lookValue('corner', t('모서리')),
    slider('radius', t('모서리 둥글기'), '%', 100, prefs.look.radius
      ?? Math.round((Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue('--radius'), 10) || 0) / .24)),
    fontValue('type', t('본문 글꼴')),
    fontValue('heading', t('제목 글꼴')),
    fontValue('mono', t('코드 글꼴')),
    lookValue('size', t('글자 크기')),
    h('div', { class: 'value' }, h('label', { for: 'image' }, t('배경 이미지')),
      h('div', null, h('div', { class: 'inline-field' }, image, button(t('적용'), putImage, 'secondary')),
        h('small', { id: 'image-help', class: 'muted' }, t('이 사이트의 경로 또는 HTTPS 이미지 주소'))),
      initialImage ? button(t('기본값'), () => save(lookChange({ image: undefined }), '#image'), 'link') : h('span')),
    initialImage && slider('imageBlur', t('배경 흐림'), 'px', 30, prefs.look.imageBlur ?? 0),
    initialImage && slider('imageDim', t('배경 어둡기'), '%', 100, prefs.look.imageDim ?? 25),
    h('div', { class: 'settings-footer' },
      button(t('모양 초기화'), () => save({ theme: DEFAULTS.theme, look: prefs.look.columns ? { columns: prefs.look.columns } : {} }, '#theme', undefined, true), 'secondary')));
  const layout = cols.length > 1 && section(t('홈 배치'),
    h('div', { class: 'value' }, h('span', { class: 'label' }, t('홈 칸 수')),
      choice(cols.map(n => [String(n), n ? t('{n}칸', { n }) : t('자동')]), String(cols.includes(prefs.look.columns ?? 0) ? prefs.look.columns ?? 0 : 0),
        v => void keepLook('columns', { columns: Number(v) || undefined }), { 'aria-label': t('홈 칸 수'), 'data-look': 'columns' }),
      prefs.look.columns ? button(t('기본값'), () => keepLook('columns', { columns: undefined }), 'link') : h('span')),
    h('a', { href: '/' }, t('홈에서 배치 확인')));
  controls.append(appearance);
  if (layout) controls.append(layout);
  controls.append(section(t('일반'),
    value('lang', t('언어'), languages(), () => location.reload()),
    value('start', t('시작 페이지'), starts())));
  replace(main(), pageHead(t('설정')), status, controls);
  for (const field of controls.querySelectorAll('select')) field.id = field.name;
  if (focus) controls.querySelector<HTMLElement>(focus)?.focus();
}
