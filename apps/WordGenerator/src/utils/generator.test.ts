import { describe, expect, it } from 'vitest';
import { KeywordItem } from '../types';
import { attachJosa } from './grammar';
import {
  generateKeywords,
  generateStoryPrompt,
  keywordUsedIn,
  replaceSingleKeyword,
  synthesizeKeyword,
} from './generator';

const kw = (korean: string, extra: Partial<KeywordItem> = {}): KeywordItem => ({
  id: korean, korean, category: 'object', categoryKo: '', descriptionKo: '', ...extra,
});

describe('generateKeywords', () => {
  it('never repeats a keyword or its noun within a set', () => {
    for (let run = 0; run < 50; run++) {
      const set = generateKeywords({ count: 20, mode: 'character_heavy', combinationStyle: 'mixed' });
      const texts = set.map(k => k.korean);
      const nouns = set.map(k => k.components?.object).filter(Boolean);
      expect(new Set(texts).size).toBe(texts.length);
      expect(new Set(nouns).size).toBe(nouns.length);
    }
  });

  it('keeps every locked keyword, in place, even when the count goes down', () => {
    const first = generateKeywords({ count: 6, mode: 'balanced' });
    const locked = first.map((k, i) => (i === 1 || i === 5 ? { ...k, isLocked: true } : k));
    const next = generateKeywords({ count: 3, mode: 'balanced', existingKeywords: locked });
    expect(next).toHaveLength(3);
    expect(next[1]).toBe(locked[1]); // still in its slot
    expect(next).toContain(locked[5]); // its slot is gone, but it is not
    const fewer = generateKeywords({ count: 1, mode: 'balanced', existingKeywords: locked });
    expect(fewer).toHaveLength(2); // never below what is locked
  });

  it('draws a replacement from the same domain that repeats nothing', () => {
    const set = generateKeywords({ count: 8, mode: 'balanced', combinationStyle: 'modifier_object' });
    const old = set[0];
    const fresh = replaceSingleKeyword(old, set, 'modifier_object');
    expect(fresh.category).toBe(old.category);
    expect(set.map(k => k.korean)).not.toContain(fresh.korean);
  });
});

describe('synthesizeKeyword', () => {
  it('puts the right object particle on the noun', () => {
    for (let i = 0; i < 200; i++) {
      const k = synthesizeKeyword({ style: 'object_predicate', domain: 'physical', index: i });
      const noun = k.components!.object!;
      expect(k.korean.startsWith(attachJosa(noun, '을/를') + ' ')).toBe(true);
    }
  });

  it('puts a place before its verb with 에서, or 에 at an edge', () => {
    for (let i = 0; i < 200; i++) {
      const k = synthesizeKeyword({ style: 'object_predicate', domain: 'spatial', index: i });
      const place = k.components!.object!;
      expect(k.korean.startsWith(`${place}에서 `) || k.korean.startsWith(`${place}에 `)).toBe(true);
    }
  });
});

describe('generateStoryPrompt', () => {
  it('chooses each particle by the last syllable, not "을(를)"', () => {
    expect(generateStoryPrompt([kw('비밀')])).toBe('[비밀]을 둘러싼 미스터리와 인간 내면의 갈등을 다룬 이야기.');
    expect(generateStoryPrompt([kw('편지')])).toBe('[편지]를 둘러싼 미스터리와 인간 내면의 갈등을 다룬 이야기.');
    expect(generateStoryPrompt([kw('폐허'), kw('달빛')])).toMatch(/^\[폐허\]와 \[달빛\] 사이에서/);
    expect(generateStoryPrompt([kw('달빛'), kw('폐허')])).toMatch(/^\[달빛\]과 \[폐허\] 사이에서/);
    expect(generateStoryPrompt([kw('a'), kw('b'), kw('은시계를 불태우다')])).toContain('[은시계를 불태우다]를 향해');
  });
});

describe('keywordUsedIn', () => {
  it('counts a phrase by what it is about, not by its first word', () => {
    const watch = kw('오래된 은시계', { components: { modifier: '오래된', object: '은시계' } });
    expect(keywordUsedIn('그는 은시계를 꺼냈다', watch)).toBe(true);
    expect(keywordUsedIn('오래된 집이었다', watch)).toBe(false);
    const burn = kw('불태우다', { partType: 'predicate' });
    expect(keywordUsedIn('편지를 불태우고 떠났다', burn)).toBe(true);
  });
});
