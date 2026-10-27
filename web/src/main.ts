// The site's pages, over the services' APIs (docs/site.md "APIs and pages"). One app for every page
// path: nginx serves this for /, the portal's pages and the agents' pages; the sign-in, Claude's
// consent and the approvals are server pages of their own.

import { frame, site } from './lib/api';
import { h, replace } from './lib/dom';
import { loadPrefs } from './lib/prefs';
import { flash, header, main, message, pageHead, section, showPending } from './lib/ui';
import * as account from './pages/account';
import * as agents from './pages/agents';
import { presets } from './pages/flows';
import { apps } from './pages/apps';
import { home } from './pages/home';
import { settings } from './pages/settings';

type Page = (...args: string[]) => Promise<void>;

function routes(): [RegExp, Page][] {
  const p = frame.portal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return [
    [/^\/$/, home],
    [/^\/apps\/?$/, apps],
    [/^\/settings\/?$/, settings],
    [new RegExp(`^${p}/?$`), account.mine],
    [new RegExp(`^${p}/admin/users/?$`), account.users],
    [new RegExp(`^${p}/admin/users/new/?$`), account.newUser],
    [new RegExp(`^${p}/admin/users/([^/]+)/?$`), account.user],
    [new RegExp(`^${p}/admin/requests/?$`), account.requests],
    [new RegExp(`^${p}/admin/invites/?$`), account.invites],
    [/^\/agents\/?$/, agents.runs],
    [/^\/agents\/runs\/([^/]+)\/?$/, agents.run],
    [/^\/agents\/presets(?:\/([^/]+))?\/?$/, presets],
    // the flows were a page of their own before every preset was one
    [/^\/agents\/flows(?:\/([^/]+))?\/?$/, async (name?: string) => {
      history.replaceState(null, '', `/agents/presets${name ? '/' + name : ''}${location.search}`);
      return presets(name);
    }],
    [/^\/agents\/keys\/?$/, agents.keys],
    [/^\/agents\/files\/?$/, agents.files],
  ];
}

async function render(): Promise<void> {
  const path = location.pathname;
  for (const [re, page] of routes()) {
    const m = path.match(re);
    if (!m) continue;
    try {
      await page(...m.slice(1).filter((x): x is string => x !== undefined).map(decodeURIComponent));
      showPending();
    } catch (e) {
      replace(main(), pageHead('문제가 생겼습니다', null), section('', h('p', null, message(e))));
    }
    return;
  }
  replace(main(), pageHead('없는 페이지', null), section('', h('p', null, '이 주소에는 페이지가 없습니다. '),
    h('a', { href: '/' }, '홈으로')));
}

async function start(): Promise<void> {
  try {
    Object.assign(frame, await site.get('/me'));
  } catch (e) {
    flash('error', message(e));
  }
  await loadPrefs();
  header();
  window.addEventListener('popstate', () => void render());
  await render();
}

void start();
