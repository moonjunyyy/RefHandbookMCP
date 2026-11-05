// The person's settings (/settings), kept with their account (docs/frame.md §2): the language, the theme, the
// page to open after signing in, and the look (§1.3: the colour, the corners, the type, the text size, the main
// page's columns, an image under the page — the choices the site file declares) — each chosen in place and kept
// at once, with its default beside it when it is not the default. The apps are added in the store (/apps) and
// the main page is arranged on the main page: neither is a setting.

import { DEFAULTS, IMAGE, LANGS, applyLook, button, choice, flash, frame, h, main, onApps, pageHead, prefs, primaryLink, replace, savePrefs, section, select } from '/auth/static/site.js';
import type { LookChoice, LookKind, LookPrefs, Prefs } from '/auth/static/site.js';
import { t } from '../lib/i18n';

/** The languages to choose from: the browser's, or one of the site's (each named in its own). */
const languages = (): [string, string][] => [['auto', t('브라우저 언어 따르기')], ...LANGS];
const themes = (): [string, string][] => [['auto', t('기기 설정 따르기')], ['light', t('밝게')], ['dark', t('어둡게')]];

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
  if (!frame.uid) {
    replace(main(), pageHead(t('설정')), h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/settings`, t('로그인'))));
    return;
  }
  const value = (name: keyof typeof DEFAULTS & ('lang' | 'theme' | 'start'), label: string, choices: [string, string][],
                 after?: () => void) =>
    h('div', { class: 'value' },
      h('label', { for: name }, label),
      select(name, choices, prefs[name], async v => { await savePrefs({ [name]: v } as Partial<Prefs>); after?.(); void settings(); }),
      prefs[name] !== DEFAULTS[name]
        ? button(t('기본값'), async () => { await savePrefs({ [name]: DEFAULTS[name] } as Partial<Prefs>); after?.(); void settings(); }, 'link')
        : h('span'));
  /** Keep a change of the look and put it on at once. */
  const keepLook = async (change: LookPrefs) => {
    const look: LookPrefs = { ...prefs.look, ...change };
    for (const k of Object.keys(look) as (keyof LookPrefs)[]) if (look[k] === undefined || look[k] === '' || look[k] === 0) delete look[k];
    await savePrefs({ look });
    applyLook();
    void settings();
  };
  const reset = (change: LookPrefs) => button(t('기본값'), () => keepLook(change), 'link');
  const swatch = (c: LookChoice) => {
    const s = h('span', { class: 'swatch', 'aria-hidden': 'true' });
    const dark = document.documentElement.getAttribute('data-theme') === 'dark'
      || (!document.documentElement.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
    const accent = (dark ? c.dark : c.light)?.accent;
    if (accent) s.style.setProperty('background', accent);  // the CSSOM: the pages' CSP takes no inline style
    else s.classList.add('own');  // theme.css's own accent
    return [s, c.label];
  };
  /** A kind of the look: its choices as chips (the first is theme.css's own), and the way back to it. */
  const lookValue = (kind: LookKind, label: string) => {
    const choices = frame.look[kind] ?? [];
    if (choices.length < 2) return false;
    const cur = choices.some(c => c.id === prefs.look[kind]) ? prefs.look[kind]! : choices[0].id;
    return h('div', { class: 'value' }, h('span', { class: 'label' }, label),
      choice(choices.map(c => [c.id, kind === 'palette' ? swatch(c) : c.label]), cur,
             v => void keepLook({ [kind]: v === choices[0].id ? undefined : v }), { 'aria-label': label, 'data-look': kind }),
      cur !== choices[0].id ? reset({ [kind]: undefined }) : h('span'));
  };
  const cols = frame.look.columns ?? [];
  const image = h('input', { type: 'url', name: 'image', value: prefs.look.image ?? '', placeholder: 'https://…', 'aria-label': t('배경 이미지 주소') });
  const putImage = async () => {
    const v = image.value.trim();
    if (v && !IMAGE.test(v)) { flash('error', t('https:// 로 시작하는 주소나 이 사이트의 /… 주소를 적으세요.')); return; }
    await keepLook({ image: v || undefined });
  };
  image.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); void putImage(); } });
  replace(main(),
    pageHead(t('설정')),
    section('',
      value('lang', t('언어'), languages(), () => location.reload()),
      value('theme', t('테마'), themes()),
      value('start', t('시작 페이지'), starts())),
    section(t('모양'),
      lookValue('palette', t('색')),
      lookValue('corner', t('모서리')),
      lookValue('type', t('글꼴')),
      lookValue('size', t('글자 크기')),
      cols.length > 1 && h('div', { class: 'value' }, h('span', { class: 'label' }, t('홈 칸 수')),
        choice(cols.map(n => [String(n), n ? t('{n}칸', { n }) : t('자동')]), String(cols.includes(prefs.look.columns ?? 0) ? prefs.look.columns ?? 0 : 0),
               v => void keepLook({ columns: Number(v) || undefined }), { 'aria-label': t('홈 칸 수'), 'data-look': 'columns' }),
        prefs.look.columns ? reset({ columns: undefined }) : h('span')),
      h('div', { class: 'value' }, h('label', { for: 'image' }, t('배경 이미지')),
        h('div', { class: 'inline-field' }, image, button(t('적용'), putImage, 'secondary')),
        prefs.look.image ? reset({ image: undefined }) : h('span'))));
  image.id = 'image';
  (main().querySelectorAll('select') as NodeListOf<HTMLSelectElement>).forEach(s => { s.id = s.name; });
}
