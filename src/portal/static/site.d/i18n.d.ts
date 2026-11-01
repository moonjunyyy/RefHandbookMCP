export declare const LANGS: [string, string][];
/** The language to show for a setting: itself if we have it, else for 'auto' the browser's first one we have. */
export declare function resolveLang(pref: string): string;
export declare function setLang(pref: string): string;
export declare const lang: () => string;
export declare const locale: () => string;
/** A text kept as it is (a table built before the language is known), translated where it is shown. */
export declare const n_: (text: string) => string;
/** `text` (Korean) in the page's language, its {values} filled in. */
export declare function t(text: string, values?: Record<string, string | number>): string;
