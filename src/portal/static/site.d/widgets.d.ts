import { Child } from './dom';
import { Card, Widget, frame, prefs } from './frame';
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
}
export type WidgetModule = {
    default: (host: HTMLElement, ctx: WidgetContext) => void | (() => void) | Promise<void | (() => void)>;
};
/** The widget every app has: a launcher. */
export declare function launcher(c: Card): HTMLElement;
export declare const LAUNCHER = "launcher";
/** The widgets an app offers: the launcher first, then the ones it declared. */
export declare function widgetsOf(c: Card): Widget[];
/** Draw a widget into its cell: the module when there is one, the launcher otherwise or on failure. */
export declare function mount(cell: HTMLElement, c: Card, w: Widget): Promise<void>;
/** A list inside a widget: the common shape (a title, items with a link each). */
export declare function widgetList(items: {
    href: string;
    text: Child;
    aside?: Child;
}[], none: string): HTMLElement;
export declare const openWord: () => string;
