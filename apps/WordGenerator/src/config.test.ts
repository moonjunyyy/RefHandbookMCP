import { describe, expect, it } from 'vitest';
import { KEYWORD_COUNT, QUICK_COUNTS, clampCount } from './config';

describe('keyword count limits', () => {
  it('keeps every count within min..max', () => {
    expect(clampCount(KEYWORD_COUNT.max + 50)).toBe(KEYWORD_COUNT.max);
    expect(clampCount(KEYWORD_COUNT.min - 5)).toBe(KEYWORD_COUNT.min);
    expect(clampCount(7.6)).toBe(Math.min(KEYWORD_COUNT.max, 8));
    expect(clampCount(Number.NaN)).toBe(KEYWORD_COUNT.initial);
  });

  it('offers only quick counts the slider can reach, and starts within range', () => {
    expect(QUICK_COUNTS.every(n => n >= KEYWORD_COUNT.min && n <= KEYWORD_COUNT.max)).toBe(true);
    expect(clampCount(KEYWORD_COUNT.initial)).toBe(KEYWORD_COUNT.initial);
  });
});
