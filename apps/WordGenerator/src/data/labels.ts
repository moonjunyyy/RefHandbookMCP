/**
 * Every option the screens offer and every name they show for it, in one place.
 *
 * Each table is keyed by its type (a Record over the union), so adding a style, a format, a tab or a
 * domain to src/types without giving it a label here is a type error, and the screens list them in
 * the order written below.
 */
import {
  BalanceMode,
  CategoryType,
  CombinationStyle,
  NovelGenre,
  OutputFormat,
  PoolTab,
  SemanticDomain,
  Tab,
  VerbKind,
  WordPartType,
} from '../types';

/** The keys of a label table, in the order they are written. */
export function keysOf<K extends string>(table: Record<K, unknown>): K[] {
  return Object.keys(table) as K[];
}

export const CATEGORY_NAMES: Record<CategoryType, string> = {
  object: '사물·오브제',
  characteristic: '성향·특성',
  setting: '배경·공간',
  action: '사건·행동',
  relationship: '인물·관계',
  motif: '주제·모티프',
  catalyst: '갈등·촉매',
};

/**
 * The lexicon's areas: their names, the keyword category a phrase drawn from one gets, and the
 * other categories whose keywords are redrawn from it (the last domain takes any category left).
 */
export const DOMAINS: Record<SemanticDomain, { label: string; hint: string; category: CategoryType;
                                               alsoFor?: CategoryType[] }> = {
  physical: { label: '사물·물성', hint: 'Physical', category: 'object' },
  character: { label: '인물·심리·성향', hint: 'Character', category: 'characteristic', alsoFor: ['relationship'] },
  spatial: { label: '공간·배경·날씨', hint: 'Spatial', category: 'setting' },
  thematic: { label: '추상·사건·운명', hint: 'Thematic', category: 'motif' },
};

/**
 * Parts of speech: `label` in lists and filters, `short` on badges and breakdowns, `hint` in forms.
 * A phrase or word ending in a verb is an event: `category` (modifiers and nouns take their domain's).
 */
export const WORD_PARTS: Record<WordPartType, { label: string; short: string; hint: string; category?: CategoryType }> = {
  modifier: { label: '수식어', short: '수식', hint: '관형/형용사구' },
  object: { label: '목적어·체언', short: '목적어', hint: '사물/인물/장소 명사' },
  predicate: { label: '술어·용언', short: '술어', hint: '동사', category: 'action' },
};

/** The category of a word of `part` from `domain`. */
export function categoryOf(part: WordPartType, domain?: SemanticDomain): CategoryType {
  return WORD_PARTS[part].category ?? DOMAINS[domain ?? keysOf(DOMAINS)[0]].category;
}

export const VERB_KINDS: Record<VerbKind, string> = {
  transitive: '타동사 (~을/를)',
  spatial: '공간·상태 동사 (~에서/에)',
};

/** A verb added under a domain goes to the kind that domain's phrases use. */
export function verbKindOf(domain: SemanticDomain): VerbKind {
  return domain === 'spatial' ? 'spatial' : 'transitive';
}

export const COMBINATION_STYLES: Record<CombinationStyle, { label: string; example: string }> = {
  mixed: { label: '자연스러운 혼합 구문', example: '[수식어+목적어] & [목적어+술어]' },
  modifier_object: { label: '수식어 + 목적어', example: '오래된 은시계, 서늘한 결벽증' },
  object_predicate: { label: '목적어 + 술어', example: '비밀을 폭로하다, 단검을 숨기다' },
  full_clause: { label: '수식어 + 목적어 + 술어', example: '오래된 은시계를 불태우다' },
  discrete_parts: { label: '단어 원형 분할', example: '오래된 / 은시계 / 불태우다' },
};

/**
 * How a set spreads over the domains: by default it goes round them in turn; `focus` takes every
 * `focusEvery`-th draw (1: all of them) from one domain; `random` picks any domain each time.
 */
export const BALANCE_MODES: Record<BalanceMode, { label: string; focus?: SemanticDomain; focusEvery?: number;
                                                  random?: boolean }> = {
  balanced: { label: '균형 배분' },
  random: { label: '완전 무작위', random: true },
  object_heavy: { label: '사물·소품 위주', focus: 'physical', focusEvery: 2 },
  character_heavy: { label: '인물·성향 위주', focus: 'character' },
  setting_heavy: { label: '배경·분위기 위주', focus: 'spatial' },
};

export const OUTPUT_FORMATS: Record<OutputFormat, string> = {
  comma: '쉼표 구분',
  comma_quote: '"따옴표"',
  newlines: '줄바꿈',
  numbered: '번호',
  hashtags: '#태그',
  markdown_checklist: '체크리스트',
};

export const TABS: Record<Tab, string> = {
  generator: '키워드 생성기',
  draft: '소설 집필실',
  dictionary: '단어 사전',
  saved: '보관함',
};

export const POOL_TABS: Record<PoolTab, string> = {
  single: '단일 어휘 실시간 등록',
  batch: '대량 일괄 등록 (중복 필터링)',
  list: '내 추가 단어',
};

/** Names of the pool's own sources (an extra lexicon is named by its `label` in config). */
export const SOURCE_LABELS: { builtin: string; custom: string } = {
  builtin: '정선 어휘',
  custom: '내 단어',
};

/** Shown for sets saved by the first version, which recorded a genre. */
export const GENRE_NAMES: Record<NovelGenre, string> = {
  all: '전체 장르',
  thriller: '추리 & 스릴러',
  fantasy: '판타지 & 초자연',
  romance: '로맨스 & 드라마',
  historical: '사극 & 시대물',
  modern: '현대문학 & 단편',
  noir: '누아르 & 범죄',
  scifi: 'SF & 디스토피아',
};
