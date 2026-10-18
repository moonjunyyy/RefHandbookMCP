export type CategoryType =
  | 'object'         // 사물 (소지품, 오브제, 단서, 유물 등)
  | 'characteristic'  // 성향 & 특성 (성격, 결함, 외형, 분위기, 모순)
  | 'setting'         // 배경 & 공간 (밀실, 자연, 시공간, 날씨)
  | 'action'          // 사건 & 행동 (사건, 비밀, 결정, 조우)
  | 'relationship'    // 인물 & 관계 (조력자, 적대자, 방관자, 애증)
  | 'motif'           // 주제 & 모티프 (죄책감, 구원, 망각, 집착)
  | 'catalyst';       // 갈등 & 촉매 (금기, 5분의 시한, 폭로);

export type NovelGenre =
  | 'all'         // 전체 / 종합
  | 'thriller'    // 추리 & 스릴러
  | 'fantasy'     // 판타지 & 초자연
  | 'romance'     // 로맨스 & 드라마
  | 'historical'  // 사극 & 시대물
  | 'modern'      // 현대문학 & 단편
  | 'noir'        // 누아르 & 범죄
  | 'scifi';       // SF & 디스토피아

/** The four areas of the lexicon; every modifier and noun belongs to one. */
export type SemanticDomain = 'physical' | 'character' | 'spatial' | 'thematic';

/** Verbs come in two kinds: with an object (을/를) and with a place (에서/에). */
export type VerbKind = 'transitive' | 'spatial';

/** The app's screens. */
export type Tab = 'generator' | 'draft' | 'dictionary' | 'saved';

/** The word pool manager's panes. */
export type PoolTab = 'single' | 'batch' | 'list';

export type WordPartType =
  | 'modifier'   // 수식어 (형용사, 관형사, 수식구)
  | 'object'     // 목적어 / 체언 (사물, 개념, 인물, 장소 명사)
  | 'predicate'; // 술어 / 용언 (동사, 상태/행동 서술)

export type CombinationStyle =
  | 'mixed'               // 혼합 구문 (수식어+목적어 & 목적어+술어)
  | 'modifier_object'     // 수식어 + 목적어 (예: 서늘한 은시계, 물에 젖은 유서)
  | 'object_predicate'    // 목적어 + 술어 (예: 비밀을 폭로하다, 죄책감을 씻다)
  | 'full_clause'         // 수식어 + 목적어 + 술어 (예: 오래된 은시계를 불태우다)
  | 'discrete_parts';     // 단어 원형 분할 (수식어, 목적어, 술어 각각 독립 추출)

export interface WordPoolItem {
  id: string;
  text: string;
  part: WordPartType;
  category: CategoryType;
  genres: NovelGenre[];
  english?: string;
  particle?: '을/를' | '에' | '에서' | '으로' | '와/과'; // for natural Korean postposition
}

export interface KeywordItem {
  id: string;
  korean: string;
  category: CategoryType;
  categoryKo: string;
  descriptionKo: string;
  /** Only in sets saved by the first version (it repeated the Korean text, or a placeholder). */
  english?: string;
  /** Only in sets saved by the first version; the lexicon has no genres, so it never chose words. */
  genres?: NovelGenre[];
  isLocked?: boolean;
  components?: {
    modifier?: string;
    object?: string;
    predicate?: string;
  };
  partType?: WordPartType;
}

export type OutputFormat =
  | 'comma'
  | 'comma_quote'
  | 'newlines'
  | 'hashtags'
  | 'markdown_checklist'
  | 'numbered';

export type BalanceMode =
  | 'balanced'       // 균형 배분 (사물, 성향, 배경, 사건 골고루)
  | 'random'         // 완전 무작위
  | 'object_heavy'   // 사물·오브제 중심
  | 'character_heavy'// 인물·성향 중심
  | 'setting_heavy';  // 배경·분위기 중심

export interface SavedKeywordSet {
  id: string;
  title: string;
  createdAt: number;
  keywords: KeywordItem[];
  /** Only in sets saved by the first version (see KeywordItem.genres). */
  genre?: NovelGenre;
  note?: string;
}
