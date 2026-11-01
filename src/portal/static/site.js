function h(tag2, attrs, ...children) {
  const el = document.createElement(tag2);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === void 0 || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") {
      el.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (k === "value" && "value" in el) {
      el.value = String(v);
    } else if (k === "checked" && el instanceof HTMLInputElement) {
      el.checked = Boolean(v);
    } else {
      el.setAttribute(k, v === true ? "" : String(v));
    }
  }
  append(el, children);
  return el;
}
function append(parent, children) {
  for (const c of children) {
    if (c === null || c === void 0 || c === false) continue;
    if (Array.isArray(c)) append(parent, c);
    else parent.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}
function replace(parent, ...children) {
  parent.replaceChildren();
  append(parent, children);
}
function svg(tag2, attrs, ...children) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag2);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === void 0 || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, String(v));
  }
  append(el, children);
  return el;
}
function values(form2) {
  const out = {};
  for (const el of Array.from(form2.elements)) {
    const f = el;
    if (!f.name) continue;
    out[f.name] = f.type === "checkbox" ? f.checked : f.value;
  }
  return out;
}
const EN = {
  "서버에 닿지 않습니다. 잠시 뒤 다시 시도하세요.": "The server is not reachable. Try again in a moment.",
  "요청이 실패했습니다 ({status})": "The request failed ({status})",
  "내 메뉴": "My menu",
  "앱": "Apps",
  "설정": "Settings",
  "로그아웃": "Sign out",
  "로그인": "Sign in",
  "도움말": "Help",
  "확인": "OK",
  "취소": "Cancel",
  "열기": "Open"
};
const LANGS = [["ko", "한국어"], ["en", "English"]];
const CATALOGS = { en: EN };
const LOCALES = { ko: "ko-KR", en: "en-US" };
let current$1 = "ko";
function resolveLang(pref) {
  const known = (x) => LANGS.some(([code]) => code === x);
  const fromBrowser = (navigator.languages ?? [navigator.language]).map((x) => x.toLowerCase().split("-")[0]).find(known);
  return known(pref) ? pref : fromBrowser ?? "ko";
}
function setLang(pref) {
  current$1 = resolveLang(pref);
  document.documentElement.lang = current$1;
  return current$1;
}
const lang = () => current$1;
const locale = () => LOCALES[current$1] ?? "ko-KR";
const n_ = (text) => text;
function t(text, values2) {
  const out = (current$1 === "ko" ? void 0 : CATALOGS[current$1]?.[text]) ?? text;
  return values2 ? out.replace(/\{(\w+)\}/g, (m, k) => k in values2 ? String(values2[k]) : m) : out;
}
const THEMES = ["auto", "light", "dark"];
const DEFAULTS = { lang: "auto", theme: "auto", start: "/", apps: [], home: [], seen: [] };
const frame = {
  uid: null,
  title: "",
  signin: "/auth",
  portal: "/account",
  lang: "ko",
  theme: "auto",
  frame: 0,
  cards: [],
  menu: []
};
const prefs = { ...DEFAULTS };
const STORE = "/apps/site/api/store/prefs";
const LOCAL = "prefs";
const KNOWN = "prefs-known";
function applyTheme(theme) {
  const v = THEMES.includes(theme) ? theme : "auto";
  if (v === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", v);
  document.cookie = `theme=${v}; path=/; max-age=31536000; samesite=lax`;
  frame.theme = v;
}
function fromStored(raw, cards) {
  const p = { ...DEFAULTS, ...raw };
  if (!Array.isArray(p.apps)) p.apps = [];
  if (!Array.isArray(p.home)) p.home = [];
  if (!("apps" in raw) && (Array.isArray(raw.order) || Array.isArray(raw.hidden))) {
    const hidden = new Set(raw.hidden ?? []);
    const order = raw.order ?? [];
    const ids = cards.filter((c) => c.optional).map((c) => c.id);
    const rank = (id) => {
      const i = order.indexOf(id);
      return i < 0 ? order.length + ids.indexOf(id) : i;
    };
    p.apps = ids.filter((id) => !hidden.has(id)).sort((a, b) => rank(a) - rank(b));
  }
  if (!THEMES.includes(p.theme)) p.theme = "auto";
  return p;
}
function remember() {
  try {
    localStorage.setItem(LOCAL, JSON.stringify(prefs));
  } catch {
  }
  document.cookie = `lang=${prefs.lang}; path=/; max-age=31536000; samesite=lax`;
  applyTheme(prefs.theme);
}
async function load() {
  try {
    const r = await fetch("/auth/api/v1/me", { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (r.ok) Object.assign(frame, await r.json());
  } catch {
  }
  frame.cards = (frame.cards ?? []).map((c) => ({ description: "", about: "", tags: [], code: "", icon: "", href: "", optional: true, links: [], widgets: [], ...c }));
  frame.menu ??= [];
  let raw = {};
  try {
    raw = JSON.parse(localStorage.getItem(LOCAL) ?? "{}");
  } catch {
  }
  if (frame.uid) {
    try {
      let known = localStorage.getItem(KNOWN) === "1";
      if (!known) {
        const r = await fetch(STORE.replace(/\/prefs$/, ""), { credentials: "same-origin", headers: { Accept: "application/json" } });
        known = r.ok && (await r.json()).keys.some((k) => k.key === "prefs");
      }
      if (known) {
        const r = await fetch(STORE, { credentials: "same-origin", headers: { Accept: "application/json" } });
        if (r.ok) {
          raw = await r.json();
          localStorage.setItem(KNOWN, "1");
        } else if (r.status === 404) raw = {};
      } else {
        raw = {};
      }
    } catch {
    }
  }
  Object.assign(prefs, fromStored(raw, frame.cards));
  setLang(prefs.lang);
  remember();
  return frame;
}
async function savePrefs(change) {
  Object.assign(prefs, change);
  if ("lang" in change) setLang(prefs.lang);
  remember();
  if (!frame.uid) return;
  const r = await fetch(STORE, {
    method: "PUT",
    credentials: "same-origin",
    body: JSON.stringify(prefs),
    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" }
  });
  if (!r.ok) throw new Error(`prefs: ${r.status}`);
  try {
    localStorage.setItem(KNOWN, "1");
  } catch {
  }
}
const onApps = () => prefs.apps.map((id) => frame.cards.find((c) => c.id === id && c.optional)).filter((c) => !!c);
function ownCard(base = document.baseURI) {
  const m = /\/apps\/([^/]+)\//.exec(new URL(base).pathname);
  return m ? frame.cards.find((c) => c.id === m[1]) : void 0;
}
const main = () => document.getElementById("main");
class ApiError extends Error {
  constructor(status, code, message2) {
    super(message2);
    this.status = status;
    this.code = code;
  }
  status;
  code;
}
async function call(method, url, body) {
  const headers = { Accept: "application/json" };
  if (method !== "GET") headers["X-Requested-With"] = "fetch";
  if (body !== void 0) headers["Content-Type"] = "application/json";
  let r;
  try {
    r = await fetch(url, {
      method,
      headers,
      body: body === void 0 ? void 0 : JSON.stringify(body),
      credentials: "same-origin"
    });
  } catch {
    throw new ApiError(0, "network", t("서버에 닿지 않습니다. 잠시 뒤 다시 시도하세요."));
  }
  const text = await r.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
  }
  if (r.ok) return data;
  if (r.status === 401) {
    location.assign(`${frame.signin}/login?next=${encodeURIComponent(location.pathname + location.search)}`);
  }
  const e = data?.error;
  throw new ApiError(r.status, e?.code ?? "http", e?.message ?? t("요청이 실패했습니다 ({status})", { status: r.status }));
}
function api(prefix) {
  return {
    get: (path) => call("GET", prefix + path),
    post: (path, body = {}) => call("POST", prefix + path, body),
    put: (path, body) => call("PUT", prefix + path, body),
    patch: (path, body) => call("PATCH", prefix + path, body),
    del: (path) => call("DELETE", prefix + path)
  };
}
const site = api("/auth/api/v1");
const agents = api("/agents/api/v1");
const account = () => api(`${frame.portal}/api/v1`);
function message(e) {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
}
function current(href) {
  const path = location.pathname.replace(/\/$/, "") || "/";
  const h2 = href.replace(/\/$/, "") || "/";
  return h2 === "/" ? path === "/" : path === h2 || path.startsWith(h2 + "/");
}
function header() {
  const brand = document.getElementById("brand");
  if (brand) brand.textContent = frame.title;
  const nav = document.getElementById("nav");
  if (!nav) return;
  const own = frame.cards.filter((c) => !c.optional);
  replace(
    nav,
    frame.uid && [
      onApps().map((c) => h(
        "a",
        { href: c.href, "aria-current": current(c.href) ? "page" : null },
        c.icon && h("span", { class: "app-icon", "aria-hidden": "true" }, c.icon),
        c.title
      )),
      h(
        "details",
        { class: "me" },
        h("summary", { title: t("내 메뉴") }, h("code", null, frame.uid)),
        h(
          "div",
          null,
          own.flatMap((c) => [h("a", { href: c.href }, c.title), ...c.links.filter((l) => l.href !== c.href).map((l) => h("a", { href: l.href }, l.label))]),
          h("a", { href: "/apps" }, t("앱")),
          h("a", { href: "/settings" }, t("설정")),
          h("hr"),
          h("a", { href: `${frame.signin}/logout` }, t("로그아웃"))
        )
      )
    ],
    !frame.uid && [
      h("a", { href: "/apps" }, t("앱")),
      h("a", { href: `${frame.signin}/login?next=${encodeURIComponent(location.pathname)}` }, t("로그인"))
    ]
  );
  if (!closing) {
    closing = true;
    document.addEventListener("click", (ev) => {
      const me = nav.querySelector("details.me[open]");
      if (me && !me.contains(ev.target)) me.removeAttribute("open");
    });
  }
}
let closing = false;
function title(text) {
  document.title = text ? `${text} · ${frame.title}` : frame.title;
}
function pageHead(heading, tabs) {
  if (typeof heading === "string") title(heading);
  return h(
    "div",
    { class: "page-head" },
    h("h1", null, heading),
    tabs && h("nav", { class: "chips" }, tabs.map((tab) => h("a", { class: `chip${tabCurrent(tab.href, tabs.map((x) => x.href)) ? " warn" : ""}`, href: tab.href }, tab.label)))
  );
}
function tabCurrent(href, all) {
  const path = location.pathname.replace(/\/$/, "");
  const norm = (x) => x.replace(/\/$/, "");
  const under = all.filter((x) => path === norm(x) || path.startsWith(norm(x) + "/"));
  const best = under.sort((a, b) => norm(b).length - norm(a).length)[0];
  return best !== void 0 && norm(best) === norm(href);
}
function section(heading, ...body) {
  return h("section", { class: "card section" }, heading && h("h2", null, heading), ...body);
}
function empty(text) {
  return h("p", { class: "empty muted" }, text);
}
function help(text) {
  return h("details", { class: "help" }, h("summary", { title: t("도움말") }, "i"), h("p", null, text));
}
function tag(text, kind = "") {
  return h("span", { class: `tag ${kind}`.trim() }, text);
}
let toastTimer;
function flash(kind, text, action) {
  document.querySelector(".toast")?.remove();
  window.clearTimeout(toastTimer);
  const el = h(
    "p",
    { class: `flash toast ${kind}`, role: kind === "error" ? "alert" : "status" },
    text,
    action && h("button", { type: "button", class: "link", onclick: () => {
      action.run();
      el.remove();
    } }, action.label)
  );
  el.addEventListener("click", (ev) => {
    if (ev.target.tagName !== "BUTTON") el.remove();
  });
  document.body.appendChild(el);
  toastTimer = window.setTimeout(() => el.remove(), kind === "error" || action ? 12e3 : 4e3);
}
let pending = null;
function flashNext(kind, text) {
  pending = [kind, text];
}
function showPending() {
  if (pending) flash(...pending);
  pending = null;
}
async function act(button2, fn) {
  if (button2) button2.disabled = true;
  try {
    return await fn();
  } catch (e) {
    flash("error", message(e));
    return void 0;
  } finally {
    if (button2) button2.disabled = false;
  }
}
function button(text, fn, kind = "") {
  const b = h("button", { type: "button", class: kind || null }, text);
  b.addEventListener("click", () => void act(b, async () => fn(b)));
  return b;
}
function toggle(label, on, fn, attrs = {}) {
  const input = h("input", { type: "checkbox", checked: on, ...attrs });
  input.addEventListener("change", () => {
    const want = input.checked;
    input.disabled = true;
    fn(want).catch((e) => {
      input.checked = !want;
      flash("error", message(e));
    }).finally(() => {
      input.disabled = false;
    });
  });
  return h("label", { class: "switch" }, input, label);
}
function select(name, choices, value, fn) {
  const el = h("select", { name }, choices.map(([v, label]) => h("option", { value: v, selected: v === value }, label)));
  el.addEventListener("change", () => {
    const was = value;
    value = el.value;
    el.disabled = true;
    fn(el.value).catch((e) => {
      el.value = was;
      value = was;
      flash("error", message(e));
    }).finally(() => {
      el.disabled = false;
    });
  });
  return el;
}
function choice(choices, value, fn, attrs = {}) {
  const row = h("div", { class: "chips", role: "group", ...attrs });
  const draw = () => replace(row, choices.map(([v, label]) => h("button", {
    type: "button",
    class: "chip",
    "aria-pressed": v === value ? "true" : "false",
    onclick: () => {
      if (v !== value) {
        value = v;
        draw();
        fn(v);
      }
    }
  }, label)));
  draw();
  return row;
}
function form(attrs, fn, ...children) {
  const f = h("form", { ...attrs }, ...children);
  f.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const b = ev.submitter;
    void fn(f, b);
  });
  return f;
}
function dialog(heading, body, opts = {}) {
  return new Promise((resolve) => {
    const okBtn = h("button", { type: "submit", class: opts.danger ? "danger" : null, disabled: !!opts.confirmWith }, opts.ok ?? t("확인"));
    const typed = opts.confirmWith && h("input", {
      type: "text",
      autocomplete: "off",
      "aria-label": opts.confirmWith,
      oninput: (ev) => {
        okBtn.disabled = ev.target.value.trim() !== opts.confirmWith;
      }
    });
    const d = h(
      "dialog",
      null,
      form(
        { method: "dialog" },
        async () => {
          d.close("ok");
        },
        h("h2", null, heading),
        body,
        typed && h("label", null, typed),
        h(
          "div",
          { class: "actions" },
          h("button", { type: "button", class: "secondary", onclick: () => d.close("") }, opts.cancel ?? t("취소")),
          okBtn
        )
      )
    );
    d.addEventListener("close", () => {
      resolve(d.returnValue === "ok");
      d.remove();
    });
    document.body.appendChild(d);
    d.showModal();
  });
}
function go(path) {
  history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
function link(href, ...children) {
  return h("a", { href, onclick: (ev) => {
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0 || !href.startsWith("/") || href.startsWith("/apps/") || href.startsWith(frame.signin)) return;
    if (location.pathname.startsWith("/apps/")) return;
    ev.preventDefault();
    go(href);
  } }, ...children);
}
function primaryLink(href, text) {
  const a = link(href, text);
  a.className = "primary";
  return a;
}
const when = (ts) => ts ? new Date(ts * 1e3).toLocaleString(locale(), { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "-";
const num = (n) => n ? n.toLocaleString(locale()) : "-";
function launcher(c) {
  return h(
    "div",
    { class: "launcher" },
    h(
      "h2",
      null,
      c.icon && h("span", { class: "app-icon big", "aria-hidden": "true" }, c.icon),
      c.href ? h("a", { href: c.href }, c.title) : c.title
    ),
    c.description && h("p", { class: "muted" }, c.description),
    c.code && h("p", null, h("code", { class: "address" }, c.code)),
    c.links.length > 1 && h("div", { class: "links" }, c.links.map((l) => h("a", { href: l.href }, l.label)))
  );
}
const LAUNCHER = "launcher";
function widgetsOf(c) {
  return [{ id: LAUNCHER, title: c.title, href: "", size: "1x1" }, ...c.widgets];
}
async function mount(cell, c, w) {
  const body = h("div", { class: "widget-body" });
  replace(cell, w.id === LAUNCHER ? null : h(
    "div",
    { class: "widget-head" },
    c.icon && h("span", { class: "app-icon", "aria-hidden": "true" }, c.icon),
    h("a", { href: c.href }, c.title),
    " · ",
    w.title
  ), body);
  if (w.id === LAUNCHER || !w.href) {
    replace(body, launcher(c));
    return;
  }
  try {
    const mod = await import(
      /* @vite-ignore */
      w.href
    );
    if (typeof mod.default !== "function") throw new Error(`${w.href}: no default export`);
    await mod.default(body, { frame, prefs, t, lang: lang(), theme: frame.theme, go, api, card: c, widget: w });
  } catch (e) {
    console.warn("widget", c.id, w.id, e);
    replace(body, launcher(c));
  }
}
function widgetList(items, none) {
  return items.length ? h("ul", { class: "widget-list" }, items.map((i) => h("li", null, h("a", { href: i.href }, i.text), i.aside && [" ", h("span", { class: "muted small" }, i.aside)]))) : h("p", { class: "muted small" }, none);
}
const openWord = () => t("열기");
const version = 1;
export {
  ApiError,
  DEFAULTS,
  LANGS,
  LAUNCHER,
  THEMES,
  account,
  act,
  agents,
  api,
  append,
  applyTheme,
  button,
  choice,
  dialog,
  empty,
  flash,
  flashNext,
  form,
  frame,
  go,
  h,
  header,
  help,
  lang,
  launcher,
  link,
  load,
  locale,
  main,
  message,
  mount,
  n_,
  num,
  onApps,
  openWord,
  ownCard,
  pageHead,
  prefs,
  primaryLink,
  replace,
  resolveLang,
  savePrefs,
  section,
  select,
  setLang,
  showPending,
  site,
  svg,
  t,
  tag,
  title,
  toggle,
  values,
  version,
  when,
  widgetList,
  widgetsOf
};
