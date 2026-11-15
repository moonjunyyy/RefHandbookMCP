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
  "건너뛰기": "Skip",
  "다음": "Next",
  "사용 안내": "Usage guide",
  "시작하기": "Get started",
  "안내 완료 상태를 저장하지 못했습니다. 다시 시도하거나 Escape로 닫을 수 있습니다.": "Could not save guide completion. Retry or press Escape to close.",
  "이전": "Back",
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
  "열기": "Open",
  "메뉴": "Menu",
  "더 보기": "More",
  "닫기": "Close",
  "이 페이지의 키": "Keys on this page",
  "이 목록": "this list",
  // the widgets' parts (frame/widgets.ts)
  "{n}개 더": "{n} more",
  "{n}개": "{n}",
  "이전 달": "Previous month",
  "다음 달": "Next month"
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
const COLOR_ROLES = ["bg", "card", "soft", "text", "muted", "line", "accent", "link", "ok", "warn", "bad"];
function normalizeHex(value) {
  if (typeof value !== "string") return void 0;
  const hex2 = value.trim().replace(/^#/, "").toLowerCase();
  if (/^[0-9a-f]{3}$/.test(hex2)) return "#" + [...hex2].map((c) => c + c).join("");
  return /^[0-9a-f]{6}$/.test(hex2) ? "#" + hex2 : void 0;
}
const parseRgb = (hex2) => [1, 3, 5].map((i) => parseInt(hex2.slice(i, i + 2), 16));
const hex = (color) => "#" + color.map((c) => c.toString(16).padStart(2, "0")).join("");
const luma = (color) => color.reduce((sum, channel, i) => {
  const c = channel / 255;
  return sum + [0.2126, 0.7152, 0.0722][i] * (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
}, 0);
const contrast = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
const gray = (n) => [n, n, n];
const mix = (a, b, t2) => a.map((n, i) => Math.round(n + (b[i] - n) * t2));
function readable(value, surfaces, ratio = 4.5) {
  const source = parseRgb(value);
  const fits = (color) => surfaces.every((surface) => contrast(luma(color), surface) >= ratio);
  if (fits(source)) return value;
  for (let step = 1; step <= 255; step++) {
    for (const end of [0, 255]) {
      const candidate = mix(source, gray(end), step / 255);
      if (fits(candidate)) return hex(candidate);
    }
  }
  for (let n = 0; n <= 255; n++) {
    if (fits(gray(n))) return hex(gray(n));
  }
  return void 0;
}
function paletteTokens(colors) {
  const { bg, card, soft, line, accent } = colors;
  const tint = hex(mix(parseRgb(card), parseRgb(accent), 0.08));
  const surfaces = [bg, card, soft].map((c) => luma(parseRgb(c)));
  const tinted = [...surfaces, luma(parseRgb(tint))];
  const tintedText = readable(colors.text, tinted);
  const text = tintedText ?? readable(colors.text, surfaces);
  if (!text) return void 0;
  const accentSoft = tintedText ? tint : card;
  const inks = tintedText ? tinted : surfaces;
  const inkFor = (color) => readable(color, inks) ?? text;
  const muted = inkFor(colors.muted);
  const link2 = inkFor(colors.link);
  const ok = inkFor(colors.ok);
  const warn = inkFor(colors.warn);
  const bad = inkFor(colors.bad);
  const hover = inkFor(hex(mix(parseRgb(link2), parseRgb(text), 0.22)));
  const inkOn = (fill) => luma(parseRgb(fill)) >= Math.sqrt(0.0525) - 0.05 ? 0 : 255;
  const ink = inkOn(accent);
  return {
    bg,
    card,
    soft,
    line,
    text,
    muted,
    ok,
    warn,
    bad,
    "bad-text": hex(gray(inkOn(bad))),
    accent: link2,
    "accent-hover": hover,
    "accent-text": hex(gray(inkOn(link2))),
    "accent-soft": accentSoft,
    "accent-fill": accent,
    "accent-fill-hover": hex(mix(parseRgb(accent), gray(255 - ink), 0.14)),
    "accent-fill-text": hex(gray(ink))
  };
}
const LOOK_KINDS = ["palette", "corner", "type", "heading", "mono", "size"];
const FONT_KINDS = ["type", "heading", "mono"];
const THEMES = ["auto", "light", "dark"];
const DEFAULTS = { lang: "auto", theme: "auto", start: "/", apps: [], home: [], seen: [], look: {} };
const frame = {
  uid: null,
  title: "",
  signin: "/auth",
  portal: "/account",
  lang: "ko",
  theme: "auto",
  frame: 0,
  cards: [],
  menu: [],
  sizes: [],
  look: { palette: [], corner: [], type: [], heading: [], mono: [], size: [], columns: [], fonts: "", groups: {} }
};
const IMAGE = /^(https:\/\/|\/(?!\/))[^\s"'()\\<>;{}]{1,500}$/;
const LOOK = "look";
function lookColors(look, p, scheme) {
  const style = getComputedStyle(document.documentElement);
  const preset = look.palette.find((c) => c.id === p.palette)?.[scheme];
  const overrides = p.colors?.[scheme];
  const legacy = normalizeHex(p.accent);
  const result = Object.fromEntries(COLOR_ROLES.map((role) => {
    const token = role === "link" ? "accent" : role;
    const base = preset?.[token] ?? style.getPropertyValue("--" + scheme + "-" + token);
    return [role, normalizeHex(overrides?.[role]) ?? (role === "accent" || role === "link" ? legacy : void 0) ?? normalizeHex(base) ?? normalizeHex(style.getPropertyValue("--" + token)) ?? "#" + (scheme === "dark" ? "f" : "0").repeat(6)];
  }));
  return result;
}
function editedColors(look, p, scheme) {
  return paletteTokens(lookColors(look, p, scheme));
}
const inRange = (value, max) => typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= max;
const fontSheet = (id, look = frame.look) => `${look.fonts}${id}.css`;
function previewFonts(ids = []) {
  for (const id of ids) {
    const href = fontSheet(id);
    if (!frame.look.fonts || document.head.querySelector(`link[data-font-preview="${CSS.escape(id)}"]`)) continue;
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    l.dataset.fontPreview = id;
    document.head.append(l);
  }
}
function lookTokens(look, p) {
  const pick = (k) => look[k]?.find((c) => c.id === p[k]);
  const pal = pick("palette");
  const both = {
    ...pick("corner")?.tokens,
    ...pick("type")?.tokens,
    ...pick("heading")?.tokens,
    ...pick("mono")?.tokens,
    ...pick("size")?.tokens
  };
  const fonts = look.fonts ? [...new Set(FONT_KINDS.flatMap((k) => (pick(k) ?? look[k]?.[0])?.fonts ?? []))].map((id) => fontSheet(id, look)) : [];
  if (p.columns && look.columns.includes(p.columns)) {
    const gap = p.columns - 1;
    both["home-grid"] = "repeat(auto-fill, minmax(min(100%, max(12rem, calc((100% - " + gap + " * var(--gap)) / " + p.columns + "))), 1fr))";
  }
  if (inRange(p.radius, 100)) {
    both.radius = Math.round(p.radius * 0.24) + "px";
    both["radius-s"] = Math.round(p.radius * 0.1) + "px";
  }
  if (p.image && IMAGE.test(p.image)) {
    both["page-image"] = 'url("' + p.image + '")';
    both["page-blur"] = (inRange(p.imageBlur, 30) ? p.imageBlur : 0) + "px";
    both["page-dim"] = (inRange(p.imageDim, 100) ? p.imageDim : 25) + "%";
    both["page-surface"] = "var(--bg)";
  }
  const custom = (scheme) => {
    const own = p.colors?.[scheme];
    if (!normalizeHex(p.accent) && !COLOR_ROLES.some((role) => normalizeHex(own?.[role]))) return {};
    return editedColors(look, p, scheme) ?? {};
  };
  return { light: { ...pal?.light, ...custom("light") }, dark: { ...pal?.dark, ...custom("dark") }, both, fonts };
}
function applyLook() {
  const t2 = lookTokens(frame.look, prefs.look ?? {});
  try {
    localStorage.setItem(LOOK, JSON.stringify(t2));
  } catch {
  }
  putLook(t2);
}
function putLook(t2) {
  const el = document.documentElement;
  for (const name of Array.from(el.style)) if (name.startsWith("--")) el.style.removeProperty(name);
  const set = el.getAttribute("data-theme");
  const dark = set ? set === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  for (const [k, v] of Object.entries({ ...dark ? t2.dark : t2.light, ...t2.both })) el.style.setProperty(`--${k}`, v);
  const kept = Array.from(document.head.querySelectorAll("link[data-look-font]"));
  for (const l of kept) if (!t2.fonts.includes(l.getAttribute("href") ?? "")) l.remove();
  for (const href of t2.fonts) {
    if (kept.some((l2) => l2.getAttribute("href") === href && l2.isConnected)) continue;
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    l.setAttribute("data-look-font", "");
    document.head.append(l);
  }
}
let schemeWatched = false;
function sizeOf(id) {
  return frame.sizes.find((s) => s.id === id) ?? frame.sizes[0] ?? { id: "1x1", cols: 1, rows: 1 };
}
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
  applyLook();
  if (!schemeWatched) {
    schemeWatched = true;
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyLook());
  }
}
function fromStored(raw, cards) {
  const p = { ...DEFAULTS, ...raw, apps: [...DEFAULTS.apps] };
  if ("apps" in raw) p.apps = Array.isArray(raw.apps) ? raw.apps : [];
  if (!Array.isArray(p.home)) p.home = [];
  p.guides = Array.isArray(p.guides) ? p.guides.filter((x) => typeof x === "string") : [];
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
  if (!p.look || typeof p.look !== "object" || Array.isArray(p.look)) p.look = {};
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
  frame.cards = (frame.cards ?? []).map((c) => ({ description: "", about: "", tags: [], code: [], icon: "", href: "", optional: true, default: false, links: [], widgets: [], ...c })).map((c) => typeof c.code === "string" ? { ...c, code: c.code ? [{ label: "", value: c.code }] : [] } : c);
  frame.menu ??= [];
  frame.sizes = Array.isArray(frame.sizes) && frame.sizes.length ? frame.sizes : [{ id: "1x1", cols: 1, rows: 1 }];
  const given = frame.look ?? {};
  frame.look = {
    palette: given.palette ?? [],
    corner: given.corner ?? [],
    type: given.type ?? [],
    heading: given.heading ?? [],
    mono: given.mono ?? [],
    size: given.size ?? [],
    columns: given.columns ?? [],
    fonts: given.fonts ?? "",
    groups: given.groups ?? {}
  };
  DEFAULTS.apps = frame.cards.filter((c) => c.default && c.optional).map((c) => c.id);
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
let preferenceWrite = Promise.resolve();
function savePrefs(update) {
  const write = preferenceWrite.then(async () => {
    const change = typeof update === "function" ? update() : update;
    const next = { ...prefs, ...change };
    if (frame.uid) {
      const r = await fetch(STORE, {
        method: "PUT",
        credentials: "same-origin",
        body: JSON.stringify(next),
        headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" }
      });
      if (!r.ok) throw new Error(`prefs: ${r.status}`);
      try {
        localStorage.setItem(KNOWN, "1");
      } catch {
      }
    }
    Object.assign(prefs, next);
    if ("lang" in change) setLang(prefs.lang);
    remember();
  });
  preferenceWrite = write.catch(() => void 0);
  return write;
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
  const why = typeof e === "string" ? e : e?.message;
  throw new ApiError(r.status, e?.code ?? "http", why || t("요청이 실패했습니다 ({status})", { status: r.status }));
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
function hoverMenu(d) {
  let timer = 0;
  const close = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      d.open = false;
    }, 120);
  };
  const open = () => {
    window.clearTimeout(timer);
    for (const o of document.querySelectorAll("header nav details[open]")) if (o !== d) o.open = false;
    d.open = true;
  };
  d.addEventListener("mouseenter", open);
  d.addEventListener("mouseleave", close);
  d.addEventListener("focusin", open);
  d.addEventListener("focusout", (ev) => {
    if (!d.contains(ev.relatedTarget)) close();
  });
  d.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && d.open) {
      d.open = false;
      d.querySelector("summary a, summary")?.focus();
    }
  });
  return d;
}
let pageHelp = null;
function setHelp(open) {
  pageHelp = open;
  header();
}
function chrome() {
  let top = document.getElementById("nav")?.closest("header");
  if (!top) {
    top = h("header", null, h("a", { class: "brand", href: "/", id: "brand" }), h("nav", { id: "nav" }));
    document.body.prepend(top);
  }
  header();
  return top;
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
      onApps().map((c) => {
        const top = h(
          "a",
          { href: c.href, "aria-current": current(c.href) ? "page" : null },
          c.icon && h("span", { class: "app-icon", "aria-hidden": "true" }, c.icon),
          c.title
        );
        const pages = c.links.filter((l, i, all) => l.href && all.findIndex((x) => x.href === l.href) === i);
        return pages.length > 1 && pages.some((l) => l.href !== c.href) ? hoverMenu(h(
          "details",
          { class: "nav-menu" },
          h("summary", null, top),
          h("div", null, pages.map((l) => h("a", { href: l.href, "aria-current": current(l.href) && location.pathname.replace(/\/$/, "") === l.href.replace(/\/$/, "") ? "page" : null }, l.label)))
        )) : top;
      }),
      hoverMenu(h(
        "details",
        { class: "me" },
        h("summary", { title: t("내 메뉴") }, h("code", null, frame.uid)),
        h(
          "div",
          null,
          own.flatMap((c) => [h("a", { href: c.href }, c.title), ...c.links.filter((l) => l.href !== c.href).map((l) => h("a", { href: l.href }, l.label))]),
          h("a", { href: "/apps" }, t("앱")),
          h("a", { href: "/settings" }, t("설정")),
          pageHelp && h("button", { type: "button", onclick: () => pageHelp?.() }, t("사용 안내")),
          h("hr"),
          h("a", { href: `${frame.signin}/logout` }, t("로그아웃"))
        )
      ))
    ],
    !frame.uid && h("a", { href: `${frame.signin}/login?next=${encodeURIComponent(location.pathname)}` }, t("로그인"))
  );
  if (!closing) {
    closing = true;
    document.addEventListener("click", (ev) => {
      for (const d of nav.querySelectorAll("details[open]")) if (!d.contains(ev.target)) d.removeAttribute("open");
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") for (const d of nav.querySelectorAll("details[open]")) d.removeAttribute("open");
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
function meta(...children) {
  return h("p", { class: "meta" }, ...children);
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
    const okBtn = h(
      "button",
      { type: "submit", class: opts.danger ? "danger" : opts.justClose ? "secondary" : null, disabled: !!opts.confirmWith },
      opts.ok ?? (opts.justClose ? t("닫기") : t("확인"))
    );
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
          !opts.justClose && h("button", { type: "button", class: "secondary", onclick: () => d.close("") }, opts.cancel ?? t("취소")),
          okBtn
        )
      )
    );
    d.addEventListener("close", () => {
      resolve(d.returnValue === "ok");
      d.remove();
    });
    d.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" || ev.isComposing) return;
      const el = ev.target;
      if (el.tagName === "TEXTAREA" || el.tagName === "BUTTON" || el.tagName === "A" || el.closest(".menu")) return;
      if (el.closest("form") !== d.firstElementChild) return;
      ev.preventDefault();
      if (!okBtn.disabled) okBtn.click();
    });
    document.body.appendChild(d);
    d.showModal();
    if (!d.querySelector("input, select, textarea") && !okBtn.disabled) okBtn.focus();
  });
}
let pageKeys = [];
let keysInstalled = false;
function typing(el) {
  const e = el;
  if (e instanceof HTMLInputElement) return !["checkbox", "radio", "button", "submit", "reset"].includes(e.type);
  return !!e && (["TEXTAREA", "SELECT"].includes(e.tagName) || e.isContentEditable);
}
function keys(list) {
  pageKeys = list;
  if (keysInstalled) return;
  keysInstalled = true;
  document.addEventListener("keydown", (ev) => {
    if (ev.defaultPrevented || ev.isComposing || document.querySelector("dialog[open]") || openMenu) return;
    const combo = `${ev.altKey ? "Alt+" : ""}${ev.ctrlKey || ev.metaKey ? "Ctrl+" : ""}${ev.key}`;
    if (ev.key === "?" && !typing(ev.target)) {
      ev.preventDefault();
      void keysDialog();
      return;
    }
    const hit = pageKeys.find((k) => k.key === combo && (!k.when || k.when()));
    if (!hit) return;
    if (typing(ev.target) && !(ev.key === "Escape" || ev.altKey || ev.ctrlKey || ev.metaKey)) return;
    ev.preventDefault();
    void act(null, async () => hit.run());
  });
}
const KEY_WORDS = { ArrowLeft: "←", ArrowRight: "→", ArrowUp: "↑", ArrowDown: "↓", Escape: "Esc", " ": "Space" };
function keysDialog() {
  const word = (k) => k.split("+").map((p) => KEY_WORDS[p] ?? p).join(" + ");
  const rows = pageKeys.filter((k) => !k.when || k.when()).map((k) => h("li", null, h("kbd", null, word(k.key)), h("span", null, k.label)));
  return dialog(t("이 페이지의 키"), h("ul", { class: "keys" }, rows, h("li", null, h("kbd", null, "?"), h("span", null, t("이 목록")))), { justClose: true });
}
let openMenu = null;
function closeMenu() {
  openMenu?.remove();
  openMenu = null;
}
function menu(at, sections, opts = {}) {
  closeMenu();
  const back = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const el = h(
    "div",
    { class: "menu", role: "menu", "aria-label": opts.label ?? t("메뉴") },
    sections.filter((s) => s.items.length).map((s, i) => [
      i > 0 && h("hr"),
      s.title && h("div", { class: "menu-title" }, s.title),
      s.items.map((it) => h(
        "button",
        {
          type: "button",
          role: "menuitem",
          class: `menu-item${it.danger ? " danger" : ""}`,
          disabled: it.disabled || null,
          onclick: () => {
            done();
            void act(null, async () => it.run());
          }
        },
        h("strong", null, it.label),
        it.detail && h("span", { class: "detail" }, it.detail),
        it.kbd && h("kbd", null, it.kbd)
      ))
    ])
  );
  const done = () => {
    if (openMenu === el) {
      el.remove();
      openMenu = null;
      back?.focus();
    }
  };
  const items2 = () => Array.from(el.querySelectorAll(".menu-item:not(:disabled)"));
  el.addEventListener("keydown", (ev) => {
    const list = items2();
    const i = list.indexOf(document.activeElement);
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      list[(i + (ev.key === "ArrowDown" ? 1 : list.length - 1)) % list.length]?.focus();
    } else if (ev.key === "Home") {
      ev.preventDefault();
      list[0]?.focus();
    } else if (ev.key === "End") {
      ev.preventDefault();
      list[list.length - 1]?.focus();
    } else if (ev.key === "Escape" || ev.key === "Tab") {
      ev.preventDefault();
      done();
    }
  });
  document.body.appendChild(el);
  openMenu = el;
  const r = at instanceof HTMLElement ? at.getBoundingClientRect() : null;
  const pt = at instanceof HTMLElement ? { x: 0, y: 0 } : at;
  let x = r ? r.left : pt.x, y = r ? r.bottom + 4 : pt.y;
  const w = el.offsetWidth, hgt = el.offsetHeight;
  if (x + w > innerWidth - 8) x = Math.max(8, (r ? r.right : pt.x) - w);
  if (y + hgt > innerHeight - 8) y = Math.max(8, (r ? r.top - 4 : pt.y) - hgt);
  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
  const outside = (ev) => {
    if (!el.contains(ev.target)) {
      done();
      off();
    }
  };
  const off = () => {
    document.removeEventListener("pointerdown", outside, true);
    window.removeEventListener("resize", done);
    window.removeEventListener("scroll", done, true);
  };
  setTimeout(() => {
    if (openMenu === el) {
      document.addEventListener("pointerdown", outside, true);
      window.addEventListener("resize", done);
      window.addEventListener("scroll", done, true);
    }
  });
  items2()[0]?.focus();
  return el;
}
function onMenu(el, build, opts = {}) {
  el.addEventListener("contextmenu", (ev) => {
    const sections = build();
    if (!sections) return;
    ev.preventDefault();
    ev.stopPropagation();
    menu({ x: ev.clientX, y: ev.clientY }, sections, opts);
  });
  el.addEventListener("keydown", (ev) => {
    if (ev.shiftKey && ev.key === "F10" || ev.key === "ContextMenu") {
      const sections = build();
      if (!sections) return;
      ev.preventDefault();
      ev.stopPropagation();
      menu(el, sections, opts);
    }
  });
  return el;
}
function menuButton(build, label = t("더 보기")) {
  const b = h("button", {
    type: "button",
    class: "more",
    "aria-label": label,
    title: label,
    "aria-haspopup": "menu",
    onclick: (ev) => {
      ev.stopPropagation();
      menu(b, build(), { label });
    }
  }, "⋯");
  return b;
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
  const pages = c.links.filter((l, i, all) => l.href && all.findIndex((x) => x.href === l.href) === i);
  const more = pages.length > 1 && pages.some((l) => l.href !== c.href);
  return h(
    "div",
    { class: `launcher${more ? "" : " single"}` },
    h(
      "h2",
      null,
      c.icon && h("span", { class: "app-icon big", "aria-hidden": "true" }, c.icon),
      c.href ? h("a", { href: c.href }, c.title) : c.title
    ),
    more && h("div", { class: "links" }, pages.map((l) => h("a", { href: l.href }, l.label)))
  );
}
const LAUNCHER = "launcher";
function widgetsOf(c) {
  return [{ id: LAUNCHER, title: c.title, description: c.description, href: "", size: sizeOf(void 0).id }, ...c.widgets];
}
function spanStyle(sizeId) {
  const s = sizeOf(sizeId);
  return `grid-column: span ${s.cols}; grid-row: span ${s.rows};`;
}
async function mount(cell, c, w, size = sizeOf(w.size)) {
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
    await mod.default(body, { frame, prefs, t, lang: lang(), theme: frame.theme, go, api, card: c, widget: w, size });
  } catch (e) {
    console.warn("widget", c.id, w.id, e);
    replace(body, launcher(c));
  }
}
function fit(ctx) {
  const per = Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--cell-items"), 10);
  return ctx.size.rows * (per > 0 ? per : 1);
}
const pad = (n) => String(n).padStart(2, "0");
const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
function ago(when2, now = Date.now()) {
  const ms = (when2 instanceof Date ? when2.getTime() : when2) - now;
  const units = [["year", 31536e6], ["month", 2592e6], ["week", 6048e5], ["day", 864e5], ["hour", 36e5], ["minute", 6e4]];
  const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
  for (const [unit, size] of units) if (Math.abs(ms) >= size) return rtf.format(Math.round(ms / size), unit);
  return rtf.format(0, "minute");
}
function mark(el, colour) {
  if (colour && CSS.supports("color", colour)) el.style.setProperty("--mark", colour);
  return el;
}
function itemRow(i) {
  return h(
    "li",
    { class: "item", "data-state": i.state ?? null },
    i.lead !== void 0 && i.lead !== null && h("span", { class: "item-lead" }, i.lead),
    i.mark !== void 0 && mark(h("span", { class: "item-mark", "aria-hidden": "true" }), i.mark),
    h(
      "span",
      { class: "item-main" },
      i.href ? h("a", { class: "item-text", href: i.href, title: i.title ?? null }, i.text) : h("span", { class: "item-text", title: i.title ?? null }, i.text),
      i.sub !== void 0 && i.sub !== null && i.sub !== "" && h("span", { class: "item-sub" }, i.sub)
    ),
    i.aside !== void 0 && i.aside !== null && i.aside !== "" && h("span", { class: "item-aside" }, i.aside)
  );
}
const isGroups = (x) => x.length > 0 && "items" in x[0];
function groupHead(title2, aside) {
  return h("p", { class: "items-group" }, h("span", null, title2), aside !== void 0 && aside !== null && h("span", { class: "items-count" }, aside));
}
function items(list, none, more) {
  const groups = isGroups(list) ? list.filter((g) => g.items.length) : [];
  if (!groups.length && (isGroups(list) || !list.length)) return h("p", { class: "items-none muted small" }, none);
  return h(
    "div",
    { class: "items" },
    groups.length ? groups.map((g) => [groupHead(g.title, g.aside), h("ul", { class: "items-list" }, g.items.map(itemRow))]) : h("ul", { class: "items-list" }, list.map(itemRow)),
    more && more.n > 0 && h("a", { class: "items-more small", href: more.href }, t("{n}개 더", { n: more.n }))
  );
}
function widgetList(list, none) {
  return items(list.map((i) => ({ href: i.href, text: i.text, aside: i.aside })), none);
}
function stats(list) {
  return h("div", { class: "stats" }, list.map((s) => {
    const body = [h("b", { class: "stat-n" }, String(s.n)), h("span", { class: "stat-label" }, s.label)];
    return s.href ? h("a", { class: "stat", href: s.href, "data-tone": s.tone || null }, body) : h("span", { class: "stat", "data-tone": s.tone || null }, body);
  }));
}
function meter(value, max, label) {
  const bar = h("span", { class: "meter-bar" });
  bar.style.setProperty("--v", String(max > 0 ? Math.min(1, value / max) : 0));
  return h(
    "div",
    { class: "meter" },
    h("span", { class: "meter-track", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": max, "aria-valuenow": value, "aria-label": label }, bar),
    h("span", { class: "meter-label small muted" }, label)
  );
}
const LEVELS = 3;
const level = (n, max) => n <= 0 || max <= 0 ? 0 : Math.max(1, Math.ceil(LEVELS * n / max));
function dayStrip(days, today = /* @__PURE__ */ new Date()) {
  const max = Math.max(0, ...days.map((d) => d.n));
  const now = dayKey(today);
  return h("ol", { class: "day-strip" }, days.map((d) => {
    const label = `${d.date.toLocaleDateString(locale(), { month: "long", day: "numeric", weekday: "long" })} · ${t("{n}개", { n: d.n })}`;
    const dots = h(
      "span",
      { class: "day-dots", "aria-hidden": "true" },
      [...new Set(d.marks?.length ? d.marks : d.n ? [""] : [])].slice(0, LEVELS).map((c) => mark(h("span", { class: "day-dot" }), c || void 0))
    );
    const inner = [
      h("span", { class: "day-wd" }, d.date.toLocaleDateString(locale(), { weekday: "narrow" })),
      h("span", { class: "day-num" }, String(d.date.getDate())),
      dots
    ];
    return h(
      "li",
      { class: "day", "data-today": dayKey(d.date) === now ? "" : null, "data-level": level(d.n, max) },
      d.href ? h("a", { href: d.href, "aria-label": label, title: label }, inner) : h("span", { "aria-label": label, title: label }, inner)
    );
  }));
}
function monthGrid(m) {
  const first = new Date(m.year, m.month, 1);
  const start = new Date(first);
  start.setDate(1 - (first.getDay() + 6) % 7);
  const days = [...Array(42)].map((_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
  const weeks = days[35].getMonth() === m.month ? 6 : 5;
  const max = Math.max(0, ...m.counts.values());
  const now = dayKey(m.today ?? /* @__PURE__ */ new Date());
  const names = days.slice(0, 7).map((d) => d.toLocaleDateString(locale(), { weekday: "narrow" }));
  const nav = (by, text, label) => m.move && h("button", { type: "button", class: "month-nav", "aria-label": label, onclick: () => m.move?.(by) }, text);
  return h(
    "div",
    { class: "month" },
    h(
      "div",
      { class: "month-head" },
      nav(-1, "‹", t("이전 달")),
      h("span", { class: "month-title" }, first.toLocaleDateString(locale(), { year: "numeric", month: "long" })),
      nav(1, "›", t("다음 달"))
    ),
    h(
      "div",
      { class: "month-grid", role: "grid" },
      names.map((n) => h("span", { class: "month-wd", "aria-hidden": "true" }, n)),
      days.slice(0, weeks * 7).map((d) => {
        const k = dayKey(d);
        const n = m.counts.get(k) ?? 0;
        return h("button", {
          type: "button",
          class: "month-day",
          "data-level": level(n, max),
          "data-today": k === now ? "" : null,
          "data-out": d.getMonth() !== m.month ? "" : null,
          "aria-pressed": m.picked ? String(k === m.picked) : null,
          "aria-label": `${d.toLocaleDateString(locale(), { month: "long", day: "numeric", weekday: "short" })} · ${t("{n}개", { n })}`,
          onclick: () => m.pick?.(k)
        }, String(d.getDate()));
      })
    )
  );
}
function bars(list, none) {
  if (!list.length) return h("p", { class: "items-none muted small" }, none);
  const max = Math.max(...list.map((b) => b.n));
  return h("ul", { class: "bars" }, list.map((b) => {
    const fill = h("span", { class: "bar-fill" });
    fill.style.setProperty("--v", String(max > 0 ? b.n / max : 0));
    const inner = [h("span", { class: "bar-label" }, b.label), h("span", { class: "bar-track", "aria-hidden": "true" }, fill), h("span", { class: "bar-n" }, String(b.n))];
    return h("li", null, b.href ? h("a", { href: b.href }, inner) : h("span", null, inner));
  }));
}
function activity(days, label) {
  const max = Math.max(0, ...days.map((d) => d.n));
  return h("div", { class: "activity", role: "img", "aria-label": label }, days.map((d) => {
    const col = h("span", { class: "act", "data-level": level(d.n, max), title: `${d.date.toLocaleDateString(locale(), { month: "numeric", day: "numeric" })} · ${d.n}` });
    col.style.setProperty("--v", String(max > 0 ? d.n / max : 0));
    return col;
  }));
}
const openWord = () => t("열기");
function guide(id, title2, steps, _host) {
  if (!steps.length || !frame.uid) return () => void 0;
  let sheet;
  let target = null;
  let previous = null;
  const clearTarget = () => {
    target?.classList.remove("guide-target");
    target = null;
  };
  function close() {
    clearTarget();
    sheet?.close();
    sheet?.remove();
    sheet = void 0;
    const back = previous?.isConnected && previous.closest("details:not([open])")?.querySelector("summary") || previous;
    if (back?.isConnected) back.focus({ preventScroll: true });
  }
  function open() {
    if (sheet) return;
    previous = document.activeElement;
    let index = 0;
    const heading = h("h2", { id: "guide-heading" });
    const text = h("p", { id: "guide-text" });
    const count = h("p", { class: "muted small", "aria-live": "polite" });
    const error = h("p", { class: "guide-error", role: "alert" });
    const back = h("button", { type: "button", class: "secondary", onclick: () => {
      index--;
      draw();
    } }, t("이전"));
    const next = h("button", { type: "button", onclick: () => {
      if (index < steps.length - 1) {
        index++;
        draw();
      } else void finish();
    } });
    const skip = h("button", { type: "button", class: "secondary", onclick: () => {
      void finish();
    } }, t("건너뛰기"));
    async function finish() {
      back.disabled = next.disabled = skip.disabled = true;
      try {
        await savePrefs(() => ({ guides: [.../* @__PURE__ */ new Set([...prefs.guides ?? [], id])] }));
        close();
      } catch {
        error.textContent = t("안내 완료 상태를 저장하지 못했습니다. 다시 시도하거나 Escape로 닫을 수 있습니다.");
        next.disabled = skip.disabled = false;
        back.disabled = index === 0;
      }
    }
    function draw() {
      clearTarget();
      const step = steps[index];
      heading.textContent = `${title2} · ${step.title}`;
      text.textContent = step.text;
      count.textContent = `${index + 1} / ${steps.length}`;
      back.disabled = index === 0;
      next.textContent = index < steps.length - 1 ? t("다음") : t("시작하기");
      target = step.target ? document.querySelector(step.target) : null;
      target?.classList.add("guide-target");
      if (target) target.scrollIntoView({ block: "center", behavior: "instant" });
      next.focus();
    }
    sheet = h(
      "dialog",
      { class: "site-guide", "aria-labelledby": "guide-heading", "aria-describedby": "guide-text" },
      count,
      heading,
      text,
      error,
      h("div", { class: "actions" }, skip, back, next)
    );
    sheet.addEventListener("keydown", (ev) => {
      ev.stopPropagation();
      if (ev.key !== "Tab") return;
      const controls = Array.from(sheet.querySelectorAll("button:not(:disabled)"));
      const first = controls[0], last = controls[controls.length - 1];
      if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
      }
    });
    sheet.addEventListener("cancel", (ev) => {
      ev.preventDefault();
      close();
    });
    document.body.append(sheet);
    sheet.showModal();
    draw();
  }
  setHelp(open);
  if (!(prefs.guides ?? []).includes(id)) open();
  return () => {
    close();
    setHelp(null);
  };
}
const version = 1;
export {
  ApiError,
  COLOR_ROLES,
  DEFAULTS,
  FONT_KINDS,
  IMAGE,
  LANGS,
  LAUNCHER,
  LOOK_KINDS,
  THEMES,
  account,
  act,
  activity,
  agents,
  ago,
  api,
  append,
  applyLook,
  applyTheme,
  bars,
  button,
  choice,
  chrome,
  closeMenu,
  dayKey,
  dayStrip,
  dialog,
  editedColors,
  empty,
  fit,
  flash,
  flashNext,
  fontSheet,
  form,
  frame,
  go,
  groupHead,
  guide,
  h,
  header,
  help,
  items,
  keys,
  keysDialog,
  lang,
  launcher,
  link,
  load,
  locale,
  lookColors,
  lookTokens,
  main,
  menu,
  menuButton,
  message,
  meta,
  meter,
  monthGrid,
  mount,
  n_,
  normalizeHex,
  num,
  onApps,
  onMenu,
  openWord,
  ownCard,
  pageHead,
  prefs,
  previewFonts,
  primaryLink,
  replace,
  resolveLang,
  savePrefs,
  section,
  select,
  setLang,
  showPending,
  site,
  sizeOf,
  spanStyle,
  stats,
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
