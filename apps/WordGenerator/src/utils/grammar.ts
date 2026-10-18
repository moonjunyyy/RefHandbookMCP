/**
 * Hangul Josa (Postposition) attachment and grammar combination engine
 */

/** Nouns of position: a place ending in one takes 에, not 에서, before its verb ("벼랑 끝에 서다"). */
export const POSITION_NOUNS = ['끝', '앞', '위', '아래', '밑', '곁', '옆'];

/** The particle a place takes before a verb: 에 at a position ("문 앞에"), else 에서. */
export function placeParticle(place: string): '에' | '에서' {
  return POSITION_NOUNS.some(n => place.trim().endsWith(n)) ? '에' : '에서';
}

export function hasBatchim(word: string): boolean {
  if (!word) return false;
  // Strip trailing punctuation or whitespace
  const clean = word.trim().replace(/[^가-힣]/g, '');
  if (!clean) return false;
  const lastChar = clean.slice(-1);
  const code = lastChar.charCodeAt(0);
  if (code >= 0xac00 && code <= 0xd7af) {
    return (code - 0xac00) % 28 > 0;
  }
  return false;
}

export function attachJosa(
  word: string,
  josaType: '을/를' | '이/가' | '은/는' | '과/와' | '으로/로' | '에'
): string {
  const has = hasBatchim(word);
  switch (josaType) {
    case '을/를':
      return `${word}${has ? '을' : '를'}`;
    case '이/가':
      return `${word}${has ? '이' : '가'}`;
    case '은/는':
      return `${word}${has ? '은' : '는'}`;
    case '과/와':
      return `${word}${has ? '과' : '와'}`;
    case '으로/로': {
      const clean = word.trim().replace(/[^가-힣]/g, '');
      const lastChar = clean.slice(-1);
      const code = lastChar.charCodeAt(0);
      const jongseong = code >= 0xac00 && code <= 0xd7af ? (code - 0xac00) % 28 : 0;
      // ㄹ 받침 (jongseong === 8) takes '로'
      return `${word}${has && jongseong !== 8 ? '으로' : '로'}`;
    }
    case '에':
      return `${word}에`;
    default:
      return `${word}${has ? '을' : '를'}`;
  }
}

/**
 * Combines Modifier + Object noun
 */
export function combineModifierObject(modifier: string, objectNoun: string): string {
  return `${modifier.trim()} ${objectNoun.trim()}`;
}

/**
 * Combines Object noun + Predicate verb with natural postposition
 */
export function combineObjectPredicate(
  objectNoun: string,
  predicate: string,
  forcedParticle?: '을/를' | '에' | '에서' | '으로' | '와/과'
): string {
  const noun = objectNoun.trim();
  const verb = predicate.trim();

  let particle: string;
  if (forcedParticle === '에') {
    particle = `${noun}에`;
  } else if (forcedParticle === '에서') {
    particle = `${noun}에서`;
  } else if (forcedParticle === '으로') {
    particle = attachJosa(noun, '으로/로');
  } else if (forcedParticle === '와/과') {
    particle = attachJosa(noun, '과/와');
  } else {
    particle = attachJosa(noun, '을/를');
  }

  return `${particle} ${verb}`;
}

/**
 * Combines Modifier + Object + Predicate into a full phrase
 */
export function combineFullClause(
  modifier: string,
  objectNoun: string,
  predicate: string
): string {
  const modObj = combineModifierObject(modifier, objectNoun);
  return combineObjectPredicate(modObj, predicate);
}
