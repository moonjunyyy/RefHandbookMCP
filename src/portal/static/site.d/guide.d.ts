export interface GuideStep {
    title: string;
    text: string;
    target?: string;
}
/** A page's guide: shown once until completed or skipped (kept in the account, so signed in only), and again from
 * '사용 안내' in the person's menu of the site header — the one place for it on every page (parts.ts setHelp).
 * `host` is accepted for the callers of the first version and no longer decides where anything goes. Dispose on
 * navigation. */
export declare function guide(id: string, title: string, steps: GuideStep[], _host?: HTMLElement): () => void;
