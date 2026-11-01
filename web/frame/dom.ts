// A small element builder: h('div', {class: 'card'}, 'text', child, [more]). Children that are
// null, undefined or false are skipped, so a part can be left out with `cond && h(...)`. Text is
// always set as text (never as HTML). Served to every page in site.js (docs/frame.md §1).

export type Child = Node | string | number | null | undefined | false | Child[];
type Attrs = Record<string, unknown>;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Attrs | null, ...children: Child[]):
    HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') {
      el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
    } else if (k === 'value' && 'value' in el) {
      (el as unknown as { value: string }).value = String(v);
    } else if (k === 'checked' && el instanceof HTMLInputElement) {
      el.checked = Boolean(v);
    } else {
      el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  append(el, children);
  return el;
}

export function append(parent: Node, children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(parent, c);
    else parent.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function replace(parent: Element, ...children: Child[]): void {
  parent.replaceChildren();
  append(parent, children);
}

export function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs?: Attrs | null, ...children: Child[]):
    SVGElementTagNameMap[K] {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
    else el.setAttribute(k, String(v));
  }
  append(el, children);
  return el;
}

/** The values of a form's named fields (a checkbox: true or false). */
export function values(form: HTMLFormElement): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (const el of Array.from(form.elements)) {
    const f = el as HTMLInputElement;
    if (!f.name) continue;
    out[f.name] = f.type === 'checkbox' ? f.checked : f.value;
  }
  return out;
}
