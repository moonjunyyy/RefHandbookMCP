// The site's pages, over the services' APIs (docs/site.md "APIs and pages"), on the frame the sign-in
// serves (/auth/static/site.js, docs/frame.md). One app for every page path: nginx serves this for /,
// the portal's pages and the agents' pages; the sign-in, Claude's consent and the approvals are server
// pages of their own.

import { chrome, frame, h, header, keys, load, main, message, pageHead, replace, section, showPending } from '/auth/static/site.js';
import { t } from './lib/i18n';
import { canLeave } from './lib/navigation';
import { closeGuide, pageGuide } from './lib/guides';
import * as account from './pages/account';
import * as agents from './pages/agents';
import { presets } from './pages/flows';
import { app, apps } from './pages/apps';
import { calendar } from './pages/calendar';
import { vault } from './pages/vault';
import { home } from './pages/home';
import * as projects from './pages/projects';
import { settings } from './pages/settings';

type Page = (...args: string[]) => Promise<void>;

function routes(): [RegExp, Page][] {
  const p = frame.portal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return [
    [/^\/$/, home],
    [/^\/apps\/?$/, apps],
    [/^\/app\/([a-z0-9-]+)\/?$/, app],
    [/^\/calendar\/?$/, calendar],
    [/^\/vault\/?$/, vault],
    [/^\/vault\/([a-z0-9]+)\/?(.*)$/, vault],
    [/^\/settings\/?$/, settings],
    [/^\/projects\/?$/, projects.projects],
    [/^\/projects\/join\/([^/]+)\/?$/, projects.join],
    [/^\/projects\/([^/]+)\/?$/, projects.project],
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
  closeGuide();
  const path = location.pathname;
  keys([]);  // a page declares its own keys as it draws (docs/frame.md §5 R14); none carry over
  for (const [re, page] of routes()) {
    const m = path.match(re);
    if (!m) continue;
    try {
      await page(...m.slice(1).filter((x): x is string => x !== undefined).map(decodeURIComponent));
      showPending();
      pageGuide(path);
    } catch (e) {
      replace(main(), pageHead(t('문제가 생겼습니다')), section('', h('p', null, message(e))));
    }
    header();  // the apps the person has on may have changed on this page
    return;
  }
  replace(main(), pageHead(t('없는 페이지')), section('', h('p', null, t('이 주소에는 페이지가 없습니다.')),
    h('a', { href: '/' }, t('홈으로'))));
}

async function start(): Promise<void> {
  await load();
  chrome();
  let accepted = location.href;
  window.addEventListener('popstate', () => {
    if (!canLeave()) { history.pushState(null, '', accepted); return; }
    accepted = location.href;
    void render();
  });
  document.addEventListener('vault-note-navigation', () => { accepted = location.href; });
  await render();
}

void start();
