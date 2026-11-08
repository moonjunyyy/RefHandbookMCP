// theme.js — before the first paint: the person's theme from the site cookie onto <html data-theme>, and their
// look (docs/frame.md §1.3: the tokens site.js last applied, kept in this browser) onto <html> as custom properties and
// the stylesheets of its open fonts into <head>,
// so a page never flashes the other scheme or theme.css's own look (docs/frame.md §1). site.js then keeps both
// with the account.
(function () {
  var root = document.documentElement;
  var m = /(?:^|; )theme=(light|dark)(?:;|$)/.exec(document.cookie);
  if (m) root.setAttribute('data-theme', m[1]);
  try {
    var t = JSON.parse(localStorage.getItem('look') || 'null');
    if (!t) return;
    if (t.both && /^repeat\(\d+, minmax\(0, 1fr\)\)$/.test(t.both['home-grid'] || '')) delete t.both['home-grid'];
    var dark = m ? m[1] === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    var all = [dark ? t.dark : t.light, t.both];
    for (var i = 0; i < all.length; i++) for (var k in all[i] || {}) root.style.setProperty('--' + k, all[i][k]);
    // the chosen open fonts' stylesheets (an address of this site), so the text is set in them from the start
    var fonts = t.fonts || [];
    for (var j = 0; j < fonts.length; j++) {
      if (!/^\/(?!\/)[^\s"'<>]*\.css$/.test(fonts[j])) continue;
      var l = document.createElement('link');
      l.rel = 'stylesheet'; l.href = fonts[j]; l.setAttribute('data-look-font', '');
      document.head.appendChild(l);
    }
  } catch (e) { /* storage off, or nothing kept: theme.css as it is */ }
})();
