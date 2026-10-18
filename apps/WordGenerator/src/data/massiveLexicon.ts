/**
 * The built-in lexicon as one table: modifiers and nouns by domain, verbs by kind (the word lists
 * themselves are in ./lexicon). Sizes are counted, not written down: the 어휘 풀 screens show them.
 */
import { SemanticDomain, VerbKind } from '../types';
import {
  RAW_PHYSICAL_MODIFIERS,
  RAW_CHARACTER_MODIFIERS,
  RAW_SPATIAL_MODIFIERS,
  RAW_THEMATIC_MODIFIERS,
} from './lexicon/modifiers';
import {
  RAW_PHYSICAL_OBJECTS,
  RAW_CHARACTER_OBJECTS,
  RAW_SPATIAL_OBJECTS,
  RAW_THEMATIC_OBJECTS,
} from './lexicon/objects';
import { RAW_TRANSITIVE_VERBS, RAW_SPATIAL_VERBS } from './lexicon/verbs';

export interface Lexicon {
  modifiers: Record<SemanticDomain, string[]>;
  objects: Record<SemanticDomain, string[]>;
  verbs: Record<VerbKind, string[]>;
}

export const BUILTIN_LEXICON: Lexicon = {
  modifiers: {
    physical: RAW_PHYSICAL_MODIFIERS,
    character: RAW_CHARACTER_MODIFIERS,
    spatial: RAW_SPATIAL_MODIFIERS,
    thematic: RAW_THEMATIC_MODIFIERS,
  },
  objects: {
    physical: RAW_PHYSICAL_OBJECTS,
    character: RAW_CHARACTER_OBJECTS,
    spatial: RAW_SPATIAL_OBJECTS,
    thematic: RAW_THEMATIC_OBJECTS,
  },
  verbs: {
    transitive: RAW_TRANSITIVE_VERBS,
    spatial: RAW_SPATIAL_VERBS,
  },
};

/** Trimmed, without blanks or repeats, in the original order. */
export function uniqueList(items: string[]): string[] {
  const seen = new Set<string>();
  const res: string[] = [];
  for (const it of items) {
    const clean = it.trim();
    if (clean && !seen.has(clean)) {
      seen.add(clean);
      res.push(clean);
    }
  }
  return res;
}
