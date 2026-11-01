// Markdown as a vault writes it (docs/apps-vault-calendar.md §4.3): CommonMark through markdown-it, plus
// what Obsidian adds — [[wikilinks]] (with |alias and #heading), ![[embeds]] of images, #tags — and
// mathematics through KaTeX ($…$ inline, $$…$$ displayed). Loaded only by the pages that render notes
// (a dynamic import), so the other pages do not carry it. No raw HTML from a note is let through.

import MarkdownIt from 'markdown-it';
import katex from 'katex';
import 'katex/dist/katex.min.css';

export interface Resolve {
  /** Where a [[target]] goes (a path of the vault's pages) — null: no such note. */
  note: (target: string) => string | null;
  /** The address of an attachment, as a note embeds it. */
  raw: (path: string) => string;
}

const IMAGE = /\.(png|jpe?g|gif|webp|svg|bmp|avif)$/i;
// the inline parser's state, as the installed markdown-it types it (its own export names vary by version)
type InlineRule = Parameters<MarkdownIt['inline']['ruler']['before']>[2];
type StateInline = Parameters<InlineRule>[0];

function wikilinks(md: MarkdownIt, resolve: Resolve): void {
  md.inline.ruler.before('link', 'wikilink', (state: StateInline, silent: boolean): boolean => {
    const src = state.src;
    let pos = state.pos;
    const embed = src.charCodeAt(pos) === 0x21 /* ! */ && src.startsWith('[[', pos + 1);
    if (embed) pos += 1;
    if (!src.startsWith('[[', pos)) return false;
    const end = src.indexOf(']]', pos + 2);
    if (end < 0) return false;
    const inner = src.slice(pos + 2, end);
    if (!inner.trim() || inner.includes('\n')) return false;
    if (!silent) {
      const [target, alias] = inner.split('|', 2);
      const [name, heading] = target.split('#', 2);
      if (embed && IMAGE.test(name)) {
        const img = state.push('image', 'img', 0);
        img.attrs = [['src', resolve.raw(name.trim())], ['alt', (alias ?? name).trim()]];
        img.children = [];
        img.content = (alias ?? name).trim();
      } else {
        const to = resolve.note(name.trim());
        const open = state.push('link_open', 'a', 1);
        open.attrs = [['href', to ? to + (heading ? '#' + encodeURIComponent(heading.trim()) : '') : '#'], ['class', to ? 'wikilink' : 'wikilink missing']];
        const text = state.push('text', '', 0);
        text.content = (alias ?? (heading ? `${name} › ${heading}` : name)).trim();
        state.push('link_close', 'a', -1);
      }
    }
    state.pos = end + 2;
    return true;
  });
}

function tags(md: MarkdownIt): void {
  md.inline.ruler.after('wikilink', 'tag', (state: StateInline, silent: boolean): boolean => {
    const src = state.src;
    const pos = state.pos;
    if (src.charCodeAt(pos) !== 0x23 /* # */) return false;
    const before = pos > 0 ? src[pos - 1] : ' ';
    if (/[\w/#]/.test(before)) return false;
    const m = /^#([\p{L}\p{N}_][\p{L}\p{N}_/-]*)/u.exec(src.slice(pos));
    if (!m) return false;
    if (!silent) {
      const tok = state.push('tag', 'span', 0);
      tok.content = m[1];
    }
    state.pos += m[0].length;
    return true;
  });
  md.renderer.rules.tag = (tokens, i) => `<span class="tag">#${md.utils.escapeHtml(tokens[i].content)}</span>`;
}

function math(md: MarkdownIt): void {
  md.inline.ruler.before('escape', 'math', (state: StateInline, silent: boolean): boolean => {
    const src = state.src;
    const pos = state.pos;
    if (src.charCodeAt(pos) !== 0x24 /* $ */) return false;
    const display = src.startsWith('$$', pos);
    const fence = display ? '$$' : '$';
    const end = src.indexOf(fence, pos + fence.length);
    if (end < 0) return false;
    const body = src.slice(pos + fence.length, end);
    if (!body.trim() || (!display && (body.startsWith(' ') || body.endsWith(' ')))) return false;
    if (!silent) {
      const tok = state.push('math', '', 0);
      tok.content = body;
      tok.meta = { display };
    }
    state.pos = end + fence.length;
    return true;
  });
  md.renderer.rules.math = (tokens, i) =>
    katex.renderToString(tokens[i].content, { displayMode: tokens[i].meta.display, throwOnError: false, output: 'html' });
}

export function renderer(resolve: Resolve): (text: string) => string {
  const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
  wikilinks(md, resolve);
  tags(md);
  math(md);
  // a note's own image, by a relative path: served by the vault, not the site
  const image = md.renderer.rules.image!;
  md.renderer.rules.image = (tokens, i, opts, env, self) => {
    const src = tokens[i].attrGet('src') ?? '';
    if (src && !/^(https?:)?\/\//.test(src) && !src.startsWith('/') && !src.startsWith('data:')) tokens[i].attrSet('src', resolve.raw(decodeURIComponent(src)));
    return image(tokens, i, opts, env, self);
  };
  // a link out of the site opens in a new tab, never with a handle on this one
  const open = md.renderer.rules.link_open ?? ((tokens, i, opts, _env, self) => self.renderToken(tokens, i, opts));
  md.renderer.rules.link_open = (tokens, i, opts, env, self) => {
    const href = tokens[i].attrGet('href') ?? '';
    if (/^https?:\/\//.test(href)) { tokens[i].attrSet('target', '_blank'); tokens[i].attrSet('rel', 'noopener'); }
    return open(tokens, i, opts, env, self);
  };
  return (text: string) => md.render(text.replace(/^---\n[\s\S]*?\n---\n/, ''));  // front matter is not prose
}
