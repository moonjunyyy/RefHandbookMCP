import { Child } from './dom';
import { prefs } from './frame';
import { lang } from './i18n';
export declare const main: () => HTMLElement;
export declare class ApiError extends Error {
    status: number;
    code: string;
    constructor(status: number, code: string, message: string);
}
export type Json = any;
/** One service's API at its prefix: api('/agents/api/v1').get('/runs'). */
export declare function api(prefix: string): {
    get: (path: string) => Promise<any>;
    post: (path: string, body?: unknown) => Promise<any>;
    put: (path: string, body: unknown) => Promise<any>;
    patch: (path: string, body: unknown) => Promise<any>;
    del: (path: string) => Promise<any>;
};
export declare const site: {
    get: (path: string) => Promise<any>;
    post: (path: string, body?: unknown) => Promise<any>;
    put: (path: string, body: unknown) => Promise<any>;
    patch: (path: string, body: unknown) => Promise<any>;
    del: (path: string) => Promise<any>;
};
export declare const agents: {
    get: (path: string) => Promise<any>;
    post: (path: string, body?: unknown) => Promise<any>;
    put: (path: string, body: unknown) => Promise<any>;
    patch: (path: string, body: unknown) => Promise<any>;
    del: (path: string) => Promise<any>;
};
/** The account portal's API: under the portal's root, which the frame says (/account). */
export declare const account: () => {
    get: (path: string) => Promise<any>;
    post: (path: string, body?: unknown) => Promise<any>;
    put: (path: string, body: unknown) => Promise<any>;
    patch: (path: string, body: unknown) => Promise<any>;
    del: (path: string) => Promise<any>;
};
export declare function message(e: unknown): string;
/** The header: the site's name (home), the apps the person has on, and their name — a menu with what is
 * theirs (the account and its pages, the apps catalog, the settings) and the way out. */
export declare function header(): void;
export declare function title(text: string): void;
/** The head of a page: its name, and its tabs when it has them. Nothing else: a page that needs a sentence
 * to be understood is a page to rename (docs/frame.md §5 R3). */
export declare function pageHead(heading: Child, tabs?: {
    href: string;
    label: string;
}[]): HTMLElement;
export declare function section(heading: Child, ...body: Child[]): HTMLElement;
export declare function empty(text: string): HTMLElement;
/** One line of help, shown when asked for: the only place an explanation lives (§5 R3). */
export declare function help(text: Child): HTMLElement;
/** What a thing says of itself under its name (its id, its state, its numbers): data, not an explanation. */
export declare function meta(...children: Child[]): HTMLElement;
export declare function tag(text: string, kind?: string): HTMLElement;
/** A result from elsewhere than where it was asked (saved, failed), one at a time, gone on its own; with
 * one action when there is one (undo). The result of an action in place is shown in place, not here. */
export declare function flash(kind: 'ok' | 'error', text: string, action?: {
    label: string;
    run: () => void;
}): void;
/** A message for the page about to be shown (after go()): the router shows it once that page is drawn. */
export declare function flashNext(kind: 'ok' | 'error', text: string): void;
export declare function showPending(): void;
/** Run an action: the button waits while it runs; a refusal is shown; what succeeded shows in place. */
export declare function act<T>(button: HTMLButtonElement | null, fn: () => Promise<T>): Promise<T | undefined>;
/** A button: one verb, and the action it runs (held while it runs). kind: '' | 'secondary' | 'danger' | 'link'. */
export declare function button(text: string, fn: (b: HTMLButtonElement) => void | Promise<unknown>, kind?: string): HTMLButtonElement;
/** A switch: on or off, kept at once; it springs back when the keeping fails. */
export declare function toggle(label: Child, on: boolean, fn: (on: boolean) => Promise<unknown>, attrs?: Record<string, unknown>): HTMLLabelElement;
/** One choice of several, kept at once. */
export declare function select(name: string, choices: [string, string][], value: string, fn: (v: string) => Promise<unknown>): HTMLSelectElement;
/** One of several, as a row of chips (a filter, a view): the chosen one is pressed. */
export declare function choice(choices: [string, Child][], value: string, fn: (v: string) => void, attrs?: Record<string, unknown>): HTMLElement;
/** A form that, when submitted, runs `fn` with its button held. */
export declare function form(attrs: Record<string, unknown>, fn: (f: HTMLFormElement, b: HTMLButtonElement | null) => Promise<void>, ...children: Child[]): HTMLFormElement;
/** A question (or a form) in a dialog: true when confirmed. `danger`: the confirming button is the red one;
 * `confirmWith`: a word the person must type (the name of what is being destroyed); `justClose`: the sheet
 * applies as the person goes (switches), so its one button closes it. */
export declare function dialog(heading: string, body: Child, opts?: {
    ok?: string;
    cancel?: string;
    danger?: boolean;
    confirmWith?: string;
    justClose?: boolean;
}): Promise<boolean>;
export interface Key {
    key: string;
    label: string;
    run: () => void | Promise<unknown>;
    when?: () => boolean;
}
/** The page's shortcuts: `key` as KeyboardEvent.key ('t', '/', 'ArrowLeft', 'Escape'; 'Shift+?'-style modifiers
 * as 'Alt+ArrowLeft'); a letter is not taken while typing, Escape and the arrows with Alt are. Called by a page when
 * it draws; the next page replaces the set. ? (Shift+/) shows the list. */
export declare function keys(list: Key[]): void;
/** The list of the page's keys, as declared — nothing is written here that the page did not declare. */
export declare function keysDialog(): Promise<boolean>;
export interface MenuItem {
    label: Child;
    detail?: Child;
    run: () => void | Promise<unknown>;
    danger?: boolean;
    disabled?: boolean;
    kbd?: string;
}
export interface MenuSection {
    title?: string;
    items: MenuItem[];
}
export type MenuAt = {
    x: number;
    y: number;
} | HTMLElement;
export declare function closeMenu(): void;
/** The actions of a thing, where it is: a list under the pointer (a right-click), or under its ⋯ button.
 * One line per item — a bold keyword and a dim detail; ↑↓ move, Enter runs, Esc and a click outside close;
 * the focus goes back to where it came from. A menu with one item is still a menu: the place is the point. */
export declare function menu(at: MenuAt, sections: MenuSection[], opts?: {
    label?: string;
}): HTMLElement;
/** A thing that has a menu: the right-click, and Shift+F10 (or the menu key) while it has the focus, open the
 * same one. `build` says what the menu holds now; null for nothing. */
export declare function onMenu(el: HTMLElement, build: () => MenuSection[] | null, opts?: {
    label?: string;
}): HTMLElement;
/** The ⋯ button of a row or a head: the same menu, under it. */
export declare function menuButton(build: () => MenuSection[], label?: string): HTMLButtonElement;
/** Go to a page of the pages app without a reload. */
export declare function go(path: string): void;
/** A move: a link. Inside the pages app it goes without a reload (an app's page reloads: it is another app). */
export declare function link(href: string, ...children: Child[]): HTMLAnchorElement;
/** The first thing to do on a page that has nothing yet: the one link that looks like a button. */
export declare function primaryLink(href: string, text: string): HTMLAnchorElement;
export declare const when: (ts: number | null | undefined) => string;
export declare const num: (n: number | null | undefined) => string;
export { lang, prefs };
