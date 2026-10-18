import { BUILTIN_LEXICON, Lexicon, uniqueList } from '../data/massiveLexicon';
import { keysOf, verbKindOf } from '../data/labels';
import { SemanticDomain, VerbKind, WordPartType } from '../types';
import { splitList } from './format';

export type { SemanticDomain } from '../types';

export interface PoolWordItem {
  id: string;
  text: string;
  part: WordPartType;
  domain: SemanticDomain;
  isUserCustom?: boolean;
}

/** Where a word of the pool comes from: the built-in lexicon, an extra one (its id), or the user. */
export const BUILTIN_SOURCE = 'builtin';
export const CUSTOM_SOURCE = 'custom';

/** One word of the pool, for listing (the dictionary). */
export interface PoolEntry {
  text: string;
  part: WordPartType;
  domain?: SemanticDomain;
  verbKind?: VerbKind;
  source: string;
}

export interface PoolStats {
  total: number;
  byPart: Record<WordPartType, number>;
  bySource: Record<string, number>;
  customCount: number;
}

/**
 * Normalizes text for duplicate comparison (trimmed, inner whitespace collapsed)
 */
export function normalizeWord(word: string): string {
  return word.trim().replace(/\s+/g, ' ');
}

function emptyLexicon(): Lexicon {
  const byDomain = () => ({ physical: [], character: [], spatial: [], thematic: [] });
  return { modifiers: byDomain(), objects: byDomain(), verbs: { transitive: [], spatial: [] } };
}

/**
 * The words the generator draws from: the built-in lexicon (data/massiveLexicon.ts) plus the user's
 * own, with no word twice anywhere in it.
 */
class WordPoolManager {
  private pools: Lexicon = emptyLexicon();
  private customWords: PoolWordItem[] = [];
  private wordLookup = new Set<string>();
  private sourceOf = new Map<string, string>();
  private extras: { id: string; lexicon: Lexicon }[] = [];
  private enabledExtras = new Set<string>();

  /** Called with the user's own words whenever they change (the app saves them: lib/storage). */
  public onChange?: (customWords: PoolWordItem[]) => void;

  constructor() {
    this.initializePool();
  }

  /**
   * Extra word lists (lib/lexicons), and which of them to draw from. The built-in lexicon and the
   * user's own words are always in.
   */
  public setExtraLexicons(extras: { id: string; lexicon: Lexicon }[], enabled: Iterable<string>) {
    this.extras = extras;
    this.setEnabledExtras(enabled);
  }

  public setEnabledExtras(enabled: Iterable<string>) {
    this.enabledExtras = new Set(enabled);
    this.initializePool(this.customWords);
  }

  public isExtraEnabled(id: string): boolean {
    return this.enabledExtras.has(id);
  }

  /** The built-in lexicon, the enabled extra ones, then `custom` (the user's own words, as saved). */
  public initializePool(custom: PoolWordItem[] = this.customWords) {
    this.wordLookup.clear();
    this.sourceOf.clear();
    this.pools = emptyLexicon();
    const sources = [{ id: BUILTIN_SOURCE, lexicon: BUILTIN_LEXICON },
                     ...this.extras.filter(x => this.enabledExtras.has(x.id))];
    for (const { id, lexicon } of sources) {
      for (const group of keysOf(lexicon)) {
        const from = lexicon[group] as Record<string, string[]>;
        const target = this.pools[group] as Record<string, string[]>;
        for (const key of Object.keys(target)) {
          for (const word of uniqueList(from[key] ?? [])) {
            const norm = normalizeWord(word);
            if (this.wordLookup.has(norm)) continue; // a word in two lists is drawn from the first
            this.wordLookup.add(norm);
            this.sourceOf.set(norm, id);
            target[key].push(norm);
          }
        }
      }
    }
    // The user's own words, skipping any the lexicon has since gained
    const kept: PoolWordItem[] = [];
    for (const item of Array.isArray(custom) ? custom : []) {
      const norm = normalizeWord(String(item?.text ?? ''));
      if (norm && !this.wordLookup.has(norm)) {
        this.wordLookup.add(norm);
        this.sourceOf.set(norm, CUSTOM_SOURCE);
        kept.push({ ...item, text: norm });
        this.listFor(item.part, item.domain).push(norm);
      }
    }
    this.customWords = kept;
  }

  /** The list a word of `part` in `domain` belongs to (a verb: the kind that domain uses). */
  private listFor(part: WordPartType, domain: SemanticDomain): string[] {
    if (part === 'modifier') return this.pools.modifiers[domain];
    if (part === 'object') return this.pools.objects[domain];
    return this.pools.verbs[verbKindOf(domain)];
  }

  /** The words of `part` the generator draws for `domain`. */
  public words(part: WordPartType, domain: SemanticDomain): string[] {
    return this.listFor(part, domain);
  }

  public verbs(kind: VerbKind): string[] {
    return this.pools.verbs[kind];
  }

  private saveCustomWords() {
    this.onChange?.([...this.customWords]);
  }

  private makeItem(text: string, part: WordPartType, domain: SemanticDomain): PoolWordItem {
    return { id: `custom-${crypto.randomUUID()}`, text, part, domain, isUserCustom: true };
  }

  /**
   * Check if a word already exists anywhere in the pool
   */
  public hasWord(word: string): boolean {
    const norm = normalizeWord(word);
    return !norm ? false : this.wordLookup.has(norm);
  }

  /**
   * Add a single word with deduplication check
   */
  public addWord(
    text: string,
    part: WordPartType,
    domain: SemanticDomain
  ): { success: boolean; reason?: 'empty' | 'duplicate' } {
    const norm = normalizeWord(text);
    if (!norm) return { success: false, reason: 'empty' };
    if (this.wordLookup.has(norm)) return { success: false, reason: 'duplicate' };
    this.wordLookup.add(norm);
    this.sourceOf.set(norm, CUSTOM_SOURCE);
    this.customWords.push(this.makeItem(norm, part, domain));
    this.listFor(part, domain).push(norm);
    this.saveCustomWords();
    return { success: true };
  }

  /**
   * Add batch words with deduplication report
   */
  public addBatchWords(
    rawText: string,
    part: WordPartType,
    domain: SemanticDomain
  ): {
    addedCount: number;
    duplicateCount: number;
    addedWords: string[];
    duplicateWords: string[];
  } {
    const tokens = splitList(rawText).map(normalizeWord).filter(Boolean);

    const addedWords: string[] = [];
    const duplicateWords: string[] = [];
    for (const word of tokens) {
      if (this.wordLookup.has(word)) {
        duplicateWords.push(word);
        continue;
      }
      this.wordLookup.add(word);
      this.sourceOf.set(word, CUSTOM_SOURCE);
      this.customWords.push(this.makeItem(word, part, domain));
      this.listFor(part, domain).push(word);
      addedWords.push(word);
    }
    if (addedWords.length > 0) this.saveCustomWords();
    return { addedCount: addedWords.length, duplicateCount: duplicateWords.length, addedWords, duplicateWords };
  }

  /**
   * Remove a user custom word
   */
  public removeCustomWord(id: string): boolean {
    const idx = this.customWords.findIndex(c => c.id === id);
    if (idx === -1) return false;
    this.customWords.splice(idx, 1);
    this.initializePool(this.customWords); // recompute the lists without it
    this.saveCustomWords();
    return true;
  }

  /**
   * Reset all custom additions
   */
  public resetToDefaults() {
    this.initializePool([]);
    this.saveCustomWords();
  }

  /** Every word, part by part (modifiers and nouns by domain, verbs by kind), for listing. */
  public entries(): PoolEntry[] {
    const out: PoolEntry[] = [];
    const source = (text: string) => this.sourceOf.get(text) ?? BUILTIN_SOURCE;
    for (const domain of keysOf(this.pools.modifiers)) {
      for (const text of this.pools.modifiers[domain]) out.push({ text, part: 'modifier', domain, source: source(text) });
    }
    for (const domain of keysOf(this.pools.objects)) {
      for (const text of this.pools.objects[domain]) out.push({ text, part: 'object', domain, source: source(text) });
    }
    for (const verbKind of keysOf(this.pools.verbs)) {
      for (const text of this.pools.verbs[verbKind]) out.push({ text, part: 'predicate', verbKind, source: source(text) });
    }
    return out;
  }

  public getStats(): PoolStats {
    const sum = (lists: Record<string, string[]>) => Object.values(lists).reduce((n, l) => n + l.length, 0);
    const byPart: Record<WordPartType, number> = {
      modifier: sum(this.pools.modifiers),
      object: sum(this.pools.objects),
      predicate: sum(this.pools.verbs),
    };
    const bySource: Record<string, number> = {};
    for (const s of this.sourceOf.values()) bySource[s] = (bySource[s] ?? 0) + 1;
    return {
      total: Object.values(byPart).reduce((a, b) => a + b, 0),
      byPart,
      bySource,
      customCount: this.customWords.length,
    };
  }

  public getCustomWords(): PoolWordItem[] {
    return [...this.customWords];
  }
}

// Global Singleton Instance
export const wordPoolManager = new WordPoolManager();
