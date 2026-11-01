// The person's settings (/settings), kept with their account (docs/frame.md §2): three values — the
// language, the theme, the page to open after signing in — each chosen in place and kept at once, with
// its default beside it when it is not the default. The apps are turned on in the catalog (/apps) and the
// main page is arranged on the main page: neither is a setting.

import { DEFAULTS, LANGS, button, frame, h, main, onApps, pageHead, prefs, primaryLink, replace, savePrefs, section, select } from '/auth/static/site.js';
import type { Prefs } from '/auth/static/site.js';
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
  replace(main(),
    pageHead(t('설정')),
    section('',
      value('lang', t('언어'), languages(), () => location.reload()),
      value('theme', t('테마'), themes()),
      value('start', t('시작 페이지'), starts())));
  (main().querySelectorAll('select') as NodeListOf<HTMLSelectElement>).forEach(s => { s.id = s.name; });
}
