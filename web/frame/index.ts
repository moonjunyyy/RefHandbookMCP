// site.js — the frame every page of the site imports at run time (docs/frame.md §1):
//   import { load, header, pageHead, section, button, ... } from '/auth/static/site.js';
// Built from web/frame/ by `npm run build` (web/) into src/portal/static/site.js (+ site.d.ts for the
// types), which the sign-in serves. The exports, the tokens of theme.css and the classes of parts.css are
// the public contract; a change that breaks them ships as /auth/static/v2/ beside this one.

export const version = 1;

export { h, append, replace, svg, values } from './dom';
export type { Child } from './dom';
export { frame, prefs, DEFAULTS, THEMES, load, savePrefs, applyTheme, onApps, ownCard, sizeOf } from './frame';
export type { Card, Widget, Frame, Prefs, Placement, Theme, Size } from './frame';
export { LANGS, setLang, resolveLang, lang, locale, t, n_ } from './i18n';
export { main, api, site, agents, account, ApiError, message, header, title, pageHead, section, empty, help, tag,
         flash, flashNext, showPending, act, button, toggle, select, choice, form, dialog, go, link, primaryLink, when, num, meta,
         menu, onMenu, menuButton, closeMenu, keys, keysDialog } from './parts';
export type { Json, MenuItem, MenuSection, MenuAt, Key } from './parts';
export { launcher, LAUNCHER, widgetsOf, mount, widgetList, openWord, spanStyle } from './widgets';
export type { WidgetContext, WidgetModule } from './widgets';
