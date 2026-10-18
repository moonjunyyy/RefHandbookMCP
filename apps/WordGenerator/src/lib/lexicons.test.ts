import { afterEach, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { lexiconSize, parseLexicon } from './lexicons';
import { BUILTIN_SOURCE, wordPoolManager } from '../utils/wordPoolManager';

const extra = parseLexicon({
  source: '시험사전', publisher: '시험원', url: 'https://example.org', license: 'CC BY-SA 2.0 KR', licenseUrl: '',
  words: {
    objects: { physical: ['새물건', '은시계'], spatial: ['새장소'], nonsense: ['x'] },
    modifiers: { character: ['새로운'] },
    verbs: { transitive: ['새로하다'], spatial: [42, ''] },
  },
})!;

afterEach(() => wordPoolManager.setExtraLexicons([], []));

describe('extra lexicons', () => {
  it('read a file into the pool\'s shape, ignoring what does not fit', () => {
    expect(extra.credit.source).toBe('시험사전');
    expect(extra.lexicon.objects.physical).toEqual(['새물건', '은시계']);
    expect(extra.lexicon.objects.character).toEqual([]);
    expect(extra.lexicon.verbs.spatial).toEqual([]); // not strings: dropped
    expect(lexiconSize(extra.lexicon)).toBe(5);
    expect(parseLexicon({ words: {} })).toBeNull(); // no source or license: refused
    expect(parseLexicon('nonsense')).toBeNull();
  });

  it('add their words when on, and take them back when off', () => {
    const before = wordPoolManager.getStats().total;
    wordPoolManager.setExtraLexicons([{ id: 'test', lexicon: extra.lexicon }], ['test']);
    const entries = wordPoolManager.entries();
    expect(entries.find(e => e.text === '새물건')).toMatchObject({ part: 'object', domain: 'physical', source: 'test' });
    expect(entries.find(e => e.text === '은시계')?.source).toBe(BUILTIN_SOURCE); // built-in words stay built-in
    expect(wordPoolManager.words('predicate', 'physical')).toContain('새로하다');
    expect(wordPoolManager.getStats().total).toBe(before + 4); // 은시계 was there already
    wordPoolManager.setEnabledExtras([]);
    expect(wordPoolManager.getStats().total).toBe(before);
    expect(wordPoolManager.hasWord('새물건')).toBe(false);
  });

  it('ships a krdict file the app can read, with its credit', () => {
    const parsed = parseLexicon(JSON.parse(readFileSync('public/lexicon/krdict.json', 'utf8')));
    expect(parsed?.credit).toMatchObject({ source: '한국어기초사전', publisher: '국립국어원', license: 'CC BY-SA 2.0 KR' });
    expect(lexiconSize(parsed!.lexicon)).toBeGreaterThan(10000);
  });
});
