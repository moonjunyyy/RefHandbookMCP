export interface Widget {
    id: string;
    title: string;
    href: string;
    size: '1x1' | '2x1' | '2x2';
}
export interface Card {
    id: string;
    title: string;
    description: string;
    about: string;
    tags: string[];
    code: string;
    icon: string;
    href: string;
    optional: boolean;
    links: {
        label: string;
        href: string;
    }[];
    widgets: Widget[];
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
}
export declare const THEMES: readonly ["auto", "light", "dark"];
export type Theme = (typeof THEMES)[number];
export interface Placement {
    app: string;
    widget: string;
}
export interface Prefs {
    lang: string;
    theme: Theme;
    start: string;
    apps: string[];
    home: Placement[];
    seen: string[];
}
export declare const DEFAULTS: Prefs;
export declare const frame: Frame;
export declare const prefs: Prefs;
/** The person's theme onto the document, and into the site cookie theme.js reads before the first paint. */
export declare function applyTheme(theme: string): void;
/** The frame and the person's settings, applied: call once, before drawing anything. Never throws for a
 * signed-out person or an unreachable store (what this browser last had, else the defaults). */
export declare function load(): Promise<Frame>;
/** Keep a change: with the account, and in this browser. Throws when the account did not take it. */
export declare function savePrefs(change: Partial<Prefs>): Promise<void>;
/** The apps the person has on, as cards, in their order (apps that cannot be turned off are not here:
 * they live in the person's own menu). */
export declare const onApps: () => Card[];
/** The app of the page being shown, when the page is an app's (served under /apps/<id>/). */
export declare function ownCard(base?: string): Card | undefined;
