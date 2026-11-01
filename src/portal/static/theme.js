// theme.js — before the first paint: the person's theme from the site cookie onto <html data-theme>, so a
// page never flashes the other scheme (docs/frame.md §1). site.js then keeps it with the account.
(function () {
  var m = /(?:^|; )theme=(light|dark)(?:;|$)/.exec(document.cookie);
  if (m) document.documentElement.setAttribute('data-theme', m[1]);
})();
