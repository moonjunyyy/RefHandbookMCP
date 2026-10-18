import { BalanceMode, CategoryType, CombinationStyle, KeywordItem, OutputFormat, SemanticDomain } from '../types';
import { BALANCE_MODES, CATEGORY_NAMES, DOMAINS, WORD_PARTS, categoryOf, keysOf, verbKindOf } from '../data/labels';
import { MAX_DRAWS_PER_KEYWORD } from '../config';
import { wordPoolManager } from './wordPoolManager';
import { attachJosa, placeParticle } from './grammar';

type Random = () => number;

function pick<T>(arr: T[], random: Random): T | undefined {
  return arr.length ? arr[Math.floor(random() * arr.length)] : undefined;
}

const DOMAIN_KEYS = keysOf(DOMAINS);

/** The domain a keyword was drawn from, to draw its replacement from the same one. */
export function domainOf(category: CategoryType): SemanticDomain {
  return DOMAIN_KEYS.find(d => DOMAINS[d].category === category || DOMAINS[d].alsoFor?.includes(category))
    ?? DOMAIN_KEYS[DOMAIN_KEYS.length - 1];
}

/** "<object>을/를 <verb>", or "<place>에서 <verb>" when the domain's verbs take a place. */
function withPredicate(domain: SemanticDomain, noun: string, random: Random): { text: string; verb: string } {
  const verb = pick(wordPoolManager.words('predicate', domain), random) ?? '';
  return verbKindOf(domain) === 'spatial'
    ? { text: `${noun}${placeParticle(noun)} ${verb}`, verb }
    : { text: `${attachJosa(noun, '을/를')} ${verb}`, verb };
}

function keywordId(): string {
  return `kw-${crypto.randomUUID()}`;
}

/** One keyword in `style`, from `domain`. `index` alternates the mixed and discrete styles. */
export function synthesizeKeyword(options: {
  style: CombinationStyle;
  domain?: SemanticDomain;
  index: number;
  random?: Random;
}): KeywordItem {
  const { style, index, random = Math.random } = options;
  const domain = options.domain ?? pick(DOMAIN_KEYS, random)!;
  const modifier = pick(wordPoolManager.words('modifier', domain), random) ?? '';
  const object = pick(wordPoolManager.words('object', domain), random) ?? '';
  const category = DOMAINS[domain].category;
  const id = keywordId();
  const tag = (part: keyof typeof WORD_PARTS, word: string) => `[${WORD_PARTS[part].label}] ${word}`;

  const phrase = (): KeywordItem => ({
    id, korean: `${modifier} ${object}`, category, categoryKo: CATEGORY_NAMES[category],
    descriptionKo: `${tag('modifier', modifier)} + ${tag('object', object)}`, components: { modifier, object },
  });
  const action = (noun: string, withModifier: boolean): KeywordItem => {
    const { text, verb } = withPredicate(domain, noun, random);
    return {
      id, korean: text, category: categoryOf('predicate'), categoryKo: CATEGORY_NAMES[categoryOf('predicate')],
      descriptionKo: [...(withModifier ? [tag('modifier', modifier)] : []), tag('object', object),
                      tag('predicate', verb)].join(' + '),
      components: { ...(withModifier ? { modifier } : {}), object, predicate: verb },
    };
  };
  // a bare word: its part is its category's name on the card
  const bare = (part: keyof typeof WORD_PARTS, word: string, cat: CategoryType): KeywordItem => ({
    id, korean: word, category: cat, categoryKo: WORD_PARTS[part].label,
    descriptionKo: `${WORD_PARTS[part].label} 원형`, partType: part,
  });

  switch (style) {
    case 'modifier_object':
      return phrase();
    case 'object_predicate':
      return action(object, false);
    case 'full_clause':
      return action(`${modifier} ${object}`, true);
    case 'discrete_parts': {
      // modifier, noun, verb in turn: one cycle per part of speech
      const parts = keysOf(WORD_PARTS);
      const part = parts[index % parts.length];
      if (part === 'modifier') return bare('modifier', modifier, category);
      if (part === 'object') return bare('object', object, category);
      const verb = pick(wordPoolManager.verbs('transitive'), random) ?? '';
      return bare('predicate', verb, categoryOf('predicate'));
    }
    default: // mixed: phrases and actions in turn
      return index % 2 === 0 ? phrase() : action(object, false);
  }
}

function preferredDomain(mode: BalanceMode, i: number): SemanticDomain | undefined {
  const m = BALANCE_MODES[mode];
  if (m.random) return undefined;
  if (m.focus && i % (m.focusEvery ?? 1) === 0) return m.focus;
  return DOMAIN_KEYS[i % DOMAIN_KEYS.length];
}

/** The noun a keyword is about, so a set does not use the same one twice. */
function coreNoun(k: KeywordItem): string {
  return k.components?.object ?? k.korean;
}

/**
 * Draw one keyword that repeats nothing in `taken` (its text or its noun), trying up to
 * MAX_DRAWS_PER_KEYWORD times before settling for a repeat (a tiny custom pool may have nothing else).
 */
function fresh(draw: () => KeywordItem, taken: Set<string>): KeywordItem {
  let item = draw();
  for (let tries = 0; tries < MAX_DRAWS_PER_KEYWORD && (taken.has(item.korean) || taken.has(coreNoun(item))); tries++) {
    item = draw();
  }
  taken.add(item.korean);
  taken.add(coreNoun(item));
  return item;
}

/**
 * `count` keywords. Locked keywords of `existingKeywords` stay where they are, all of them (a set
 * never shrinks below what is locked), and nothing in the set repeats a keyword or its noun.
 */
export function generateKeywords(options: {
  count: number;
  mode: BalanceMode;
  combinationStyle?: CombinationStyle;
  existingKeywords?: KeywordItem[];
  random?: Random;
}): KeywordItem[] {
  const { mode, combinationStyle = 'mixed', existingKeywords = [], random = Math.random } = options;
  const locked = existingKeywords.filter(k => k.isLocked);
  const count = Math.max(options.count, locked.length);
  const taken = new Set<string>();
  locked.forEach(k => { taken.add(k.korean); taken.add(coreNoun(k)); });

  // Locked keywords keep their slot when it is still in the set; the rest go to the first free ones.
  const slots: (KeywordItem | undefined)[] = Array(count).fill(undefined);
  const homeless: KeywordItem[] = [];
  existingKeywords.forEach((k, i) => {
    if (!k.isLocked) return;
    if (i < count) slots[i] = k;
    else homeless.push(k);
  });
  for (let i = 0; i < count && homeless.length; i++) {
    if (!slots[i]) slots[i] = homeless.shift();
  }

  let drawn = 0;
  return slots.map(slot => {
    if (slot) return slot;
    const i = drawn++;
    return fresh(() => synthesizeKeyword({
      style: combinationStyle, domain: preferredDomain(mode, i), index: i, random,
    }), taken);
  });
}

/** A new keyword in place of `old`: from the same domain, repeating nothing else in the set. */
export function replaceSingleKeyword(
  old: KeywordItem,
  currentKeywords: KeywordItem[],
  style: CombinationStyle = 'mixed',
  random: Random = Math.random,
): KeywordItem {
  const taken = new Set<string>([old.korean, coreNoun(old)]);
  currentKeywords.forEach(k => { taken.add(k.korean); taken.add(coreNoun(k)); });
  const item = fresh(() => synthesizeKeyword({
    style, domain: domainOf(old.category), index: Math.floor(random() * 1000), random,
  }), taken);
  return { ...item, isLocked: false };
}

export function formatKeywords(keywords: KeywordItem[], format: OutputFormat): string {
  const ws = keywords.map(k => k.korean.trim()).filter(Boolean);
  switch (format) {
    case 'comma_quote': return ws.map(w => `"${w}"`).join(', ');
    case 'newlines': return ws.join('\n');
    case 'numbered': return ws.map((w, i) => `${i + 1}. ${w}`).join('\n');
    case 'hashtags': return ws.map(w => `#${w.replace(/\s+/g, '')}`).join(' ');
    case 'markdown_checklist': return ws.map(w => `- [ ] ${w}`).join('\n');
    default: return ws.join(', ');
  }
}

/**
 * A one-line plot hook from the first keywords. The particles follow each phrase's last syllable
 * ("[은시계]를", "[폐허]와"), not "을(를)".
 */
export function generateStoryPrompt(keywords: KeywordItem[]): string {
  if (keywords.length === 0) return '키워드를 생성하면 소설 플롯 아이디어가 즉시 제안됩니다.';
  const [a, b, c] = keywords.map(k => k.korean.trim());
  const br = (s: string) => `[${s}]`;
  // the particle goes on the bracketed phrase, chosen by the phrase's own last syllable
  const josa = (s: string, type: '을/를' | '과/와') => attachJosa(s, type).slice(s.length);
  if (c !== undefined) {
    return `${br(a)}에서 시작하여 ${br(b)}에 부딪힌 주인공이 결국 ${br(c)}${josa(c, '을/를')} 향해 파국과 결단으로 치닫는 서사.`;
  }
  if (b !== undefined) {
    return `${br(a)}${josa(a, '과/와')} ${br(b)} 사이에서 운명의 기로에 선 인물의 이야기.`;
  }
  return `${br(a)}${josa(a, '을/를')} 둘러싼 미스터리와 인간 내면의 갈등을 다룬 이야기.`;
}

/**
 * Whether a draft uses a keyword: the whole phrase, else the noun it is about ("은시계" for "은시계를
 * 불태우다"); a bare verb counts by its stem ("불태우" for "불태우다"), a bare modifier only as written.
 */
export function keywordUsedIn(text: string, k: KeywordItem): boolean {
  const phrase = k.korean.trim();
  if (!phrase) return false;
  if (text.includes(phrase)) return true;
  if (k.components?.object) return text.includes(k.components.object);
  if (k.partType === 'predicate' && phrase.endsWith('다') && phrase.length > 2) return text.includes(phrase.slice(0, -1));
  return false;
}
