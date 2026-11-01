export type Child = Node | string | number | null | undefined | false | Child[];
type Attrs = Record<string, unknown>;
export declare function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Attrs | null, ...children: Child[]): HTMLElementTagNameMap[K];
export declare function append(parent: Node, children: Child[]): void;
export declare function replace(parent: Element, ...children: Child[]): void;
export declare function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs?: Attrs | null, ...children: Child[]): SVGElementTagNameMap[K];
/** The values of a form's named fields (a checkbox: true or false). */
export declare function values(form: HTMLFormElement): Record<string, string | boolean>;
export {};
