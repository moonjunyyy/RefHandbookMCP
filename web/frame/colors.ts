export const COLOR_ROLES = ['bg', 'card', 'soft', 'text', 'muted', 'line', 'accent', 'link', 'ok', 'warn', 'bad'] as const;
export type ColorRole = (typeof COLOR_ROLES)[number];
export type ThemeColors = Partial<Record<ColorRole, string>>;
export type ColorScheme = 'light' | 'dark';

export function normalizeHex(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const hex = value.trim().replace(/^#/, '').toLowerCase();
  if (/^[0-9a-f]{3}$/.test(hex)) return '#' + [...hex].map(c => c + c).join('');
  return /^[0-9a-f]{6}$/.test(hex) ? '#' + hex : undefined;
}

const parseRgb = (hex: string) => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
const hex = (color: number[]) => '#' + color.map(c => c.toString(16).padStart(2, '0')).join('');
const luma = (color: number[]) => color.reduce((sum, channel, i) => {
  const c = channel / 255;
  return sum + [0.2126, 0.7152, 0.0722][i] * (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
}, 0);
const contrast = (a: number, b: number) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
const gray = (n: number) => [n, n, n];
const mix = (a: number[], b: number[], t: number) => a.map((n, i) => Math.round(n + (b[i] - n) * t));

/** The closest readable tint or shade of the requested foreground. Search both directions:
 * for opposing surfaces the valid interval can be narrow and between the endpoints. */
function readable(value: string, surfaces: number[], ratio = 4.5): string | undefined {
  const source = parseRgb(value);
  const fits = (color: number[]) => surfaces.every(surface => contrast(luma(color), surface) >= ratio);
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
  return undefined;
}

export function paletteTokens(colors: Record<ColorRole, string>): Record<string, string> | undefined {
  const { bg, card, soft, line, accent } = colors;
  const tint = hex(mix(parseRgb(card), parseRgb(accent), .08));
  const surfaces = [bg, card, soft].map(c => luma(parseRgb(c)));
  const tinted = [...surfaces, luma(parseRgb(tint))];
  const tintedText = readable(colors.text, tinted);
  const text = tintedText ?? readable(colors.text, surfaces);
  if (!text) return undefined;
  const accentSoft = tintedText ? tint : card;
  const inks = tintedText ? tinted : surfaces;
  const inkFor = (color: string) => readable(color, inks) ?? text;
  const muted = inkFor(colors.muted);
  const link = inkFor(colors.link);
  const ok = inkFor(colors.ok);
  const warn = inkFor(colors.warn);
  const bad = inkFor(colors.bad);
  const hover = inkFor(hex(mix(parseRgb(link), parseRgb(text), .22)));

  const inkOn = (fill: string) => luma(parseRgb(fill)) >= Math.sqrt(.0525) - .05 ? 0 : 255;
  const ink = inkOn(accent);
  return { bg, card, soft, line, text, muted, ok, warn, bad, 'bad-text': hex(gray(inkOn(bad))),
    accent: link, 'accent-hover': hover, 'accent-text': hex(gray(inkOn(link))), 'accent-soft': accentSoft,
    'accent-fill': accent, 'accent-fill-hover': hex(mix(parseRgb(accent), gray(255 - ink), .14)), 'accent-fill-text': hex(gray(ink)) };
}
