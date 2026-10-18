import { WORD_PARTS, keysOf } from '../data/labels';
import type { PoolStats } from './wordPoolManager';

/** Numbers as the screens show them (5,019). */
export function num(n: number): string {
  return n.toLocaleString('ko-KR');
}

/** "수식어 1,714 · 목적어·체언 2,006 · 술어·용언 1,299", in the order of WORD_PARTS. */
export function partBreakdown(stats: PoolStats, sep = ' · '): string {
  return keysOf(WORD_PARTS).map(p => `${WORD_PARTS[p].label} ${num(stats.byPart[p])}`).join(sep);
}

/** What separates items in a pasted list: commas (also full-width and 、), semicolons, line breaks. */
export const LIST_SEPARATORS = /[,，、;\n\r]+/;

/** A pasted list as its items: trimmed, outer quotes dropped, blanks left out. */
export function splitList(text: string): string[] {
  return text.split(LIST_SEPARATORS).map(s => s.trim().replace(/^["'“”‘’]+|["'“”‘’]+$/g, '').trim()).filter(Boolean);
}
