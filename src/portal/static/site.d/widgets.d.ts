import { Child } from './dom';
import { Card, Param, Placement, Size, Widget, frame, prefs } from './frame';
import { t } from './i18n';
import { api, go } from './parts';
export interface WidgetContext {
    frame: typeof frame;
    prefs: typeof prefs;
    t: typeof t;
    lang: string;
    theme: string;
    go: typeof go;
    api: typeof api;
    card: Card;
    widget: Widget;
    size: Size;
    params: Record<string, string>;
}
export type WidgetModule = {
    default: (host: HTMLElement, ctx: WidgetContext) => void | (() => void) | Promise<void | (() => void)>;
};
/** The widget every app has: a launcher — its mark and name, the way in; an app with more than one page lists
 * them. What the app is and its address are the store's to say (/app/<id>), not the main page's. */
export declare function launcher(c: Card): HTMLElement;
export declare const LAUNCHER = "launcher";
/** The widgets an app offers: the launcher first, then the ones it declared. */
export declare function widgetsOf(c: Card): Widget[];
/** A cell's place on the grid for a size: the spans, as inline style (no class per size — the sizes are the
 * site's declaration, docs/frame.md §4). */
export declare function spanStyle(sizeId: string | undefined): string;
/** A place's settings: the widget's declared defaults under what the person kept for this place; a kept value
 * that is no longer one of the declared choices gives way to the default. */
export declare function paramsOf(w: Widget, p?: Placement): Record<string, string>;
/** What a setting may be: its declared choices, or the word for no filter and then the person's own objects, read
 * from the setting's path (askers at the same moment share one read). */
export declare function choicesOf(d: Param): Promise<{
    value: string;
    label: string;
}[]>;
/** Draw a widget into its cell: the module when there is one, the launcher otherwise or on failure. `size`: the
 * cell's (the person's own, else the widget's declared one); `p`: the place, for its title and its settings. */
export declare function mount(cell: HTMLElement, c: Card, w: Widget, size?: Size, p?: Placement): Promise<void>;
/** How many list rows a cell holds: its rows × --cell-items (theme.css, beside --cell). */
export declare function fit(ctx: {
    size: Size;
}): number;
/** A day as the services name it (YYYY-MM-DD, local time). */
export declare const dayKey: (d: Date) => string;
/** A time as how long ago (or how soon), in the page's language: '3시간 전', '어제', '2일 후'. */
export declare function ago(when: Date | number, now?: number): string;
/** A row of a widget's list. lead: what comes first (a time, a check); mark: the colour of what it belongs to (a dot);
 * sub: a second line; aside: at the end (a date, a count, a tag); state: past (muted), now, next (pointed out). */
export interface Item {
    text: Child;
    href?: string;
    title?: string;
    lead?: Child;
    mark?: string;
    sub?: Child;
    aside?: Child;
    state?: 'past' | 'now' | 'next';
}
/** Items under a title (a day, a due, a folder), with an aside (their count). */
export interface ItemGroup {
    title: Child;
    items: Item[];
    aside?: Child;
}
/** The title a group of rows goes under (a day, a due, a folder), with its count. */
export declare function groupHead(title: Child, aside?: Child): HTMLElement;
/** A widget's list, one item a row — or its groups, each under its title. `none`: what an empty list says;
 * `more`: the rest that did not fit, as a link. */
export declare function items(list: Item[] | ItemGroup[], none: string, more?: {
    href: string;
    n: number;
}): HTMLElement;
/** A list inside a widget: the simple form (a link and an aside per row). */
export declare function widgetList(list: {
    href: string;
    text: Child;
    aside?: Child;
}[], none: string): HTMLElement;
/** A number that sums a widget up, with its word; a tone (warn, bad, ok) when it asks for attention. */
export interface Stat {
    n: number | string;
    label: string;
    tone?: '' | 'ok' | 'warn' | 'bad';
    href?: string;
}
/** The numbers at the head of a widget: what it holds at a glance. */
export declare function stats(list: Stat[]): HTMLElement;
/** How much of a whole is done: a bar, its words beside it. */
export declare function meter(value: number, max: number, label: string): HTMLElement;
/** A day of a strip or a month: its count, the colours of what falls on it, where it leads. */
export interface Day {
    date: Date;
    n: number;
    marks?: string[];
    href?: string;
}
/** A run of days (a week ahead): each its weekday, its date and its count as dots in the colours of what falls on it. */
export declare function dayStrip(days: Day[], today?: Date): HTMLElement;
/** A month: its days on a grid of weeks (Monday first, as the calendar draws them), each at the level of its
 * count, today ringed, the picked one marked; ‹ › move the month, a day is picked in place, and the month's name is
 * a button when `open` is given (a year of months: the name opens the month). */
export interface Month {
    year: number;
    month: number;
    counts: Map<string, number>;
    today?: Date;
    picked?: string;
    pick?: (key: string) => void;
    move?: (by: number) => void;
    open?: () => void;
}
export declare function monthGrid(m: Month): HTMLElement;
/** Counts by label, as bars against the largest (a vault's tags). */
export interface Bar {
    label: Child;
    n: number;
    href?: string;
}
export declare function bars(list: Bar[], none: string): HTMLElement;
/** A run of days' counts as columns (what was done each day), the last today; its words for a reader. */
export declare function activity(days: {
    date: Date;
    n: number;
}[], label: string): HTMLElement;
export declare const openWord: () => string;
