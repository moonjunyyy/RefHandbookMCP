/**
 * The numbers and defaults the app enforces or shows, in one place: change them here and the
 * controls, their labels, the clamping and the texts all follow. (Names of options: data/labels.ts.)
 */
import { BalanceMode, CombinationStyle, OutputFormat, SemanticDomain, Tab, WordPartType } from './types';

/** How many keywords a set has. */
export const KEYWORD_COUNT = {
  min: 1,
  max: 100,
  initial: 5,
  /** Shortcut buttons (any outside min..max are left out). */
  quick: [5, 10, 20, 30, 50, 100],
} as const;

export const QUICK_COUNTS: number[] = KEYWORD_COUNT.quick.filter(
  n => n >= KEYWORD_COUNT.min && n <= KEYWORD_COUNT.max,
);

/** A count within min..max (whole numbers; anything not a number becomes the initial count). */
export function clampCount(n: number): number {
  if (!Number.isFinite(n)) return KEYWORD_COUNT.initial;
  return Math.min(KEYWORD_COUNT.max, Math.max(KEYWORD_COUNT.min, Math.round(n)));
}

/** What a fresh visit starts with. */
export const DEFAULTS: {
  style: CombinationStyle;
  mode: BalanceMode;
  format: OutputFormat;
  tab: Tab;
  draftTitle: string;
  /** What the word pool manager's forms start with. */
  newWord: { part: WordPartType; domain: SemanticDomain };
} = {
  style: 'mixed',
  mode: 'balanced',
  format: 'comma',
  tab: 'generator',
  draftTitle: '제목 미정의 단편',
  newWord: { part: 'object', domain: 'physical' },
};

/** How long things stay on screen, and how long the draft waits after typing before it is saved. */
export const TIMING_MS = {
  toast: 2500,
  copied: 2000,
  draftSave: 800,
} as const;

/** The vocabulary dictionary lists this many words at first, and this many more per "더 보기". */
export const DICTIONARY_PAGE = { first: 180, more: 120 } as const;

/** For the draft's "예상 독서 시간". */
export const READING_CHARS_PER_MINUTE = 500;

/** Draws before a set settles for a repeated keyword (only a tiny custom pool runs out). */
export const MAX_DRAWS_PER_KEYWORD = 30;

export type ShortcutAction = 'generate' | 'copy';

/**
 * Keyboard shortcuts (outside text fields, without Ctrl/⌘). `keys` are KeyboardEvent.key values;
 * `label` is how the hint shows them.
 */
export const SHORTCUTS: { action: ShortcutAction; keys: string[]; label: string; description: string }[] = [
  { action: 'generate', keys: [' ', 'r', 'R'], label: 'Space', description: '새로 뽑기' },
  { action: 'copy', keys: ['c', 'C'], label: 'C', description: '복사' },
];

export function shortcutFor(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean }):
    ShortcutAction | undefined {
  if (e.ctrlKey || e.metaKey || e.altKey) return undefined;
  return SHORTCUTS.find(s => s.keys.includes(e.key))?.action;
}

/**
 * Word lists beyond the built-in one, fetched next to the page (public/lexicon) after it loads.
 * Each can be switched off in the controls; `credit` is shown wherever its words are.
 */
export const EXTRA_LEXICONS: {
  id: string;
  file: string;
  label: string;
  enabledByDefault: boolean;
}[] = [
  { id: 'krdict', file: 'lexicon/krdict.json', label: '한국어기초사전', enabledByDefault: true },
];
