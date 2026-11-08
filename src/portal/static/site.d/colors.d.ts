export declare const COLOR_ROLES: readonly ["bg", "card", "soft", "text", "muted", "line", "accent", "link", "ok", "warn", "bad"];
export type ColorRole = (typeof COLOR_ROLES)[number];
export type ThemeColors = Partial<Record<ColorRole, string>>;
export type ColorScheme = 'light' | 'dark';
export declare function normalizeHex(value: unknown): string | undefined;
export declare function paletteTokens(colors: Record<ColorRole, string>): Record<string, string> | undefined;
