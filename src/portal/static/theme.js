// theme.js — before the first paint: the person's theme from the site cookie onto <html data-theme>, and their
// look (docs/frame.md §1.3: the tokens site.js last applied, kept in this browser) onto <html> as custom properties,
// so a page never flashes the other scheme or theme.css's own look (docs/frame.md §1). site.js then keeps both
// with the account.
(function () {
  var root = document.documentElement;
  var m = /(?:^|; )theme=(light|dark)(?:;|$)/.exec(document.cookie);
  if (m) root.setAttribute('data-theme', m[1]);
  try {
    var t = JSON.parse(localStorage.getItem('look') || 'null');
    if (!t) return;
    var dark = m ? m[1] === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    var all = [dark ? t.dark : t.light, t.both];
    for (var i = 0; i < all.length; i++) for (var k in all[i] || {}) root.style.setProperty('--' + k, all[i][k]);
  } catch (e) { /* storage off, or nothing kept: theme.css as it is */ }
})();
