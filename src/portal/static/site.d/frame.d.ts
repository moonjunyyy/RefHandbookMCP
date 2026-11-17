import type { ColorRole, ColorScheme, ThemeColors } from './colors';
/** A widget's room on the grid, in the grid's units: one of the sizes the site declares (`frame.sizes`, from
 * portal/site.py SIZES); `frame.grid` units make a cell's side. */
export interface Size {
    id: string;
    cols: number;
    rows: number;
}
/** A setting a widget declares ([[app.widget.param]]): one of `choices`, or one of the person's own objects read
 * `from` a path of the site (`list` in its answer; an item's `value` and `label`) with `all`, the word for no filter. */
export interface Param {
    id: string;
    label: string;
    default: string;
    choices?: {
        value: string;
        label: string;
    }[];
    from?: {
        path: string;
        list: string;
        value: string;
        label: string;
    };
    all?: string;
}
export interface Widget {
    id: string;
    title: string;
    description: string;
    href: string;
    size: string;
    params?: Param[];
}
/** One way to connect to an app (site.toml's `code`): its value may name the person looking as {user}. */
export interface Address {
    label: string;
    value: string;
}
export interface Card {
    id: string;
    title: string;
    description: string;
    about: string;
    tags: string[];
    code: Address[];
    icon: string;
    href: string;
    optional: boolean;
    default: boolean;
    links: {
        label: string;
        href: string;
    }[];
    widgets: Widget[];
}
/** One choice of the person's look (docs/frame.md §1.3), as the site file declares it: the tokens it redeclares —
 * a palette for each theme, the others once. The first choice of a kind is theme.css's own (nothing redeclared).
 * A font choice also names the open fonts it needs (`fonts`: ids, their stylesheets at `Look.fonts`) and the
 * group the settings page lists it under (`group`: a word of `Look.groups`). */
export interface LookChoice {
    id: string;
    label: string;
    tokens?: Record<string, string>;
    light?: Record<string, string>;
    dark?: Record<string, string>;
    fonts?: string[];
    group?: string;
}
export interface Look {
    palette: LookChoice[];
    corner: LookChoice[];
    type: LookChoice[];
    heading: LookChoice[];
    mono: LookChoice[];
    size: LookChoice[];
    columns: number[];
    fonts: string;
    groups: Record<string, string>;
}
export declare const LOOK_KINDS: readonly ["palette", "corner", "type", "heading", "mono", "size"];
export type LookKind = (typeof LOOK_KINDS)[number];
/** The look's fonts: the body's (--sans), the headings' (--serif), the code's (--mono). */
export declare const FONT_KINDS: readonly ["type", "heading", "mono"];
export type FontKind = (typeof FONT_KINDS)[number];
/** What the person picked: a choice of each kind (its id), the main page's columns (0: as many as fit), an image. */
export interface LookPrefs {
    palette?: string;
    corner?: string;
    type?: string;
    heading?: string;
    mono?: string;
    size?: string;
    columns?: number;
    image?: string;
    accent?: string;
    colors?: Partial<Record<ColorScheme, ThemeColors>>;
    radius?: number;
    imageBlur?: number;
    imageDim?: number;
}
export interface Frame {
    uid: string | null;
    title: string;
    signin: string;
    portal: string;
    lang: string;
    theme: string;
    frame: number;
    cards: Card[];
    menu: {
        label: string;
        href: string;
    }[];
    sizes: Size[];
    grid: number;
    look: Look;
}
export declare const THEMES: readonly ["auto", "light", "dark"];
export type Theme = (typeof THEMES)[number];
/** A place a person gave a widget: its size and title (their own, else the widget's) and its settings (the
 * widget's declared parameters, as they set them here). The same widget may have several places. */
export interface Placement {
    app: string;
    widget: string;
    size?: string;
    title?: string;
    params?: Record<string, string>;
}
export interface Prefs {
    lang: string;
    theme: Theme;
    start: string;
    apps: string[];
    home: Placement[];
    seen: string[];
    guides?: string[];
    homeCustomized?: boolean;
    look: LookPrefs;
}
/** The settings an account starts with. `apps`: the apps the site file marks `default = true` (docs/frame.md §2
 * R13) — filled from the frame once it is loaded; a kept `apps`, an empty one too, is the person's own choice. */
export declare const DEFAULTS: Prefs;
export declare const frame: Frame;
/** An image under the page: an address of this site or an https one, nothing that could leave the url("…"). */
export declare const IMAGE: RegExp;
/** Base colors are the actual theme's tokens, with the selected preset applied. */
export declare function lookColors(look: Look, p: LookPrefs, scheme: ColorScheme): Record<ColorRole, string>;
/** The result of applying one scheme's editor, or undefined for incompatible surfaces. */
export declare function editedColors(look: Look, p: LookPrefs, scheme: ColorScheme): Record<string, string> | undefined;
/** Where an open font's stylesheet is (web/fonts.json builds it; the site file says where it is served). */
export declare const fontSheet: (id: string, look?: Look) => string;
/** The open fonts' stylesheets, for showing choices in their own faces (the settings page): linked once each,
 * apart from the look's own (applyLook keeps those). */
export declare function previewFonts(ids?: string[]): void;
export interface LookTokens {
    light: Record<string, string>;
    dark: Record<string, string>;
    both: Record<string, string>;
    fonts: string[];
}
/** The tokens the person's look redeclares, by theme: the palette's for each, the rest for both (a heading chosen
 * wins over what a body font says of --serif); and the stylesheets of the open fonts its choices need — a kind
 * not chosen is its first choice, theme.css's own, which names the open font theme.css puts first. */
export declare function lookTokens(look: Look, p: LookPrefs): LookTokens;
/** The look onto <html> as custom properties (the CSSOM, which the pages' CSP allows; an inline style outranks the
 * theme's selectors), the palette of the theme in force; and into this browser for the next first paint. */
export declare function applyLook(): void;
/** The size a placement has: its own, else its widget's; unknown ids fall back to the first declared size. */
/** A size in whole cells — what a widget's module is told and what a person reads (2×1). */
export declare function cellsOf(s: Size): Size;
/** Whether a size is one unit of the grid: room for an app's mark and a name under it, nothing else. */
export declare const isUnit: (s: Size) => boolean;
export declare function sizeOf(id: string | undefined): Size;
export declare const prefs: Prefs;
/** The person's theme onto the document, and into the site cookie theme.js reads before the first paint. */
export declare function applyTheme(theme: string): void;
/** The frame and the person's settings, applied: call once, before drawing anything. Never throws for a
 * signed-out person or an unreachable store (what this browser last had, else the defaults). */
export declare function load(): Promise<Frame>;
/** Save changes in order. Apply only accepted settings to the page and its first-paint cache. */
export declare function savePrefs(update: Partial<Prefs> | (() => Partial<Prefs>)): Promise<void>;
/** The apps the person has on, as cards, in their order (apps that cannot be turned off are not here:
 * they live in the person's own menu). */
export declare const onApps: () => Card[];
/** The app of the page being shown, when the page is an app's (served under /apps/<id>/). */
export declare function ownCard(base?: string): Card | undefined;
