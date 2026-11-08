// site.js — the frame every page of the site imports at run time (docs/frame.md §1):
//   import { load, header, pageHead, section, button, ... } from '/auth/static/site.js';
// Built from web/frame/ by `npm run build` (web/) into src/portal/static/site.js (+ site.d.ts for the
// types), which the sign-in serves. The exports, the tokens of theme.css and the classes of parts.css are
// the public contract; a change that breaks them ships as /auth/static/v2/ beside this one.

export const version = 1;

export { h, append, replace, svg, values } from './dom';
export type { Child } from './dom';
export { frame, prefs, DEFAULTS, THEMES, LOOK_KINDS, FONT_KINDS, IMAGE, load, savePrefs, applyTheme, applyLook, lookTokens, lookColors, editedColors, onApps, ownCard, sizeOf,
         fontSheet, previewFonts } from './frame';
export type { Address, Card, Widget, Frame, Prefs, Placement, Theme, Size, Look, LookChoice, LookKind, LookPrefs, LookTokens, FontKind } from './frame';
export { LANGS, setLang, resolveLang, lang, locale, t, n_ } from './i18n';
export { main, api, site, agents, account, ApiError, message, chrome, header, title, pageHead, section, empty, help, tag,
         flash, flashNext, showPending, act, button, toggle, select, choice, form, dialog, go, link, primaryLink, when, num, meta,
         menu, onMenu, menuButton, closeMenu, keys, keysDialog } from './parts';
export type { Json, MenuItem, MenuSection, MenuAt, Key } from './parts';
export { launcher, LAUNCHER, widgetsOf, mount, widgetList, openWord, spanStyle, fit, dayKey, ago, items, groupHead, stats, meter, dayStrip, monthGrid, bars, activity } from './widgets';
export type { WidgetContext, WidgetModule, Item, ItemGroup, Stat, Day, Month, Bar } from './widgets';

export { COLOR_ROLES, normalizeHex } from './colors';
export type { ColorRole, ColorScheme, ThemeColors } from './colors';

export { guide } from './guide';
export type { GuideStep } from './guide';
