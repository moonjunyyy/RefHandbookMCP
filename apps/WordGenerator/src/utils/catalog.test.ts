import { beforeEach, describe, expect, it } from 'vitest';
import { BALANCE_MODES, DOMAINS, WORD_PARTS, categoryOf, keysOf } from '../data/labels';
import { SHORTCUTS, shortcutFor } from '../config';
import { wordPoolManager } from './wordPoolManager';
import { generateKeywords } from './generator';
import { splitList } from './format';

beforeEach(() => wordPoolManager.initializePool([]));

describe('the word pool', () => {
  it('counts what it holds, part by part, with no word twice', () => {
    const stats = wordPoolManager.getStats();
    const entries = wordPoolManager.entries();
    expect(stats.total).toBe(entries.length);
    expect(Object.values(stats.byPart).reduce((a, b) => a + b, 0)).toBe(stats.total);
    for (const part of keysOf(WORD_PARTS)) {
      expect(entries.filter(e => e.part === part)).toHaveLength(stats.byPart[part]);
    }
    expect(new Set(entries.map(e => e.text)).size).toBe(entries.length);
  });

  it("puts a user's word where its part and domain draw from", () => {
    expect(wordPoolManager.addWord('은하수 같은', 'modifier', 'spatial').success).toBe(true);
    expect(wordPoolManager.words('modifier', 'spatial')).toContain('은하수 같은');
    wordPoolManager.addWord('부유하다2', 'predicate', 'spatial'); // a place verb
    wordPoolManager.addWord('훔쳐보다2', 'predicate', 'character'); // an object verb
    expect(wordPoolManager.verbs('spatial')).toContain('부유하다2');
    expect(wordPoolManager.verbs('transitive')).toContain('훔쳐보다2');
    expect(wordPoolManager.addWord('은하수 같은', 'object', 'physical').reason).toBe('duplicate');
  });

  it('takes a pasted list by any separator', () => {
    const res = wordPoolManager.addBatchWords('첫눈, 둘째눈；셋째눈\n"넷째눈"、다섯째눈;', 'object', 'thematic');
    expect(res.addedWords).toEqual(['첫눈', '둘째눈；셋째눈', '넷째눈', '다섯째눈']);
    expect(splitList(' a ,, “b” \r\n c ')).toEqual(['a', 'b', 'c']);
  });

  it('gives a word its domain\'s category, and a verb the event category', () => {
    for (const d of keysOf(DOMAINS)) expect(categoryOf('object', d)).toBe(DOMAINS[d].category);
    expect(categoryOf('predicate', 'physical')).toBe(WORD_PARTS.predicate.category);
  });
});

describe('balance modes', () => {
  it('draw a focused mode from its domain', () => {
    for (const mode of keysOf(BALANCE_MODES)) {
      const { focus, focusEvery = 1 } = BALANCE_MODES[mode];
      if (!focus || focusEvery !== 1) continue;
      const set = generateKeywords({ count: 12, mode, combinationStyle: 'modifier_object' });
      expect(set.every(k => k.category === DOMAINS[focus].category)).toBe(true);
    }
  });
});

describe('shortcuts', () => {
  it('map each listed key to its action, and nothing with a modifier key held', () => {
    for (const s of SHORTCUTS) {
      for (const key of s.keys) expect(shortcutFor({ key, ctrlKey: false, metaKey: false, altKey: false })).toBe(s.action);
    }
    expect(shortcutFor({ key: 'c', ctrlKey: true, metaKey: false, altKey: false })).toBeUndefined();
  });
});
