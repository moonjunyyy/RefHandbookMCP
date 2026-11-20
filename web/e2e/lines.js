// Where a line may end: not inside a word of Hangul. The site's own words (names, labels,
// headings, descriptions) are never broken inside a word: one that does not fit is cut with an ellipsis or given
// room. A person's own text (a note, an event, a to-do) may break a word, and only one wider than its block.
// It runs in the page and returns [where, word] for each text that breaks the rule (one per text node); code,
// addresses and values (pre, code, dd) break anywhere by design and are not looked at.
module.exports = () => {
  const hits = [];
  const HANGUL = /[가-힣]/;
  const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
  const where = (el) => { const parts = []; for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) parts.unshift(e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/)[0] : '')); return parts.join('>'); };
  const blockOf = (el) => { let e = el; while (e && getComputedStyle(e).display.startsWith('inline')) e = e.parentElement; return e || el; };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const s = node.textContent, el = node.parentElement;
    if (!HANGUL.test(s) || !el || !vis(el) || el.closest('pre, code, dd, script, style, textarea, .katex')) continue;
    const rg = document.createRange();
    let last = null;
    for (let i = 0; i < s.length; i++) {
      if (/\s/.test(s[i])) { last = null; continue; }
      rg.setStart(node, i); rg.setEnd(node, i + 1);
      const b = rg.getClientRects()[0];
      if (!b || !b.width) continue;
      if (last && b.top >= last.bottom - 1 && HANGUL.test(s[i]) && HANGUL.test(s[i - 1])) {
        let a = i, z = i; while (a > 0 && !/\s/.test(s[a - 1])) a--; while (z < s.length && !/\s/.test(s[z])) z++;
        rg.setStart(node, a); rg.setEnd(node, z);
        const wordW = [...rg.getClientRects()].reduce((w, q) => w + q.width, 0);
        const box = blockOf(el), cs = getComputedStyle(box);
        const room = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        if (wordW <= room + 1 || !el.closest('.note-body, .note-head, .peek, .cal-ev, ul.tasks, .day-list')) { hits.push([where(el), s.slice(a, z).slice(0, 20)]); break; }
      }
      last = b;
    }
  }
  return hits;
};
