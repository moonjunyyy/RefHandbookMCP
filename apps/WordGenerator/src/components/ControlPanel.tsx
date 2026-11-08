import React, { useState } from 'react';
import { Sliders, Plus, Sparkles, Layers, Split, Database, Settings2 } from 'lucide-react';
import { BalanceMode, CategoryType, CombinationStyle } from '../types';
import { BALANCE_MODES, CATEGORY_NAMES, COMBINATION_STYLES, keysOf } from '../data/labels';
import { num, partBreakdown } from '../utils/format';
import { LoadedLexicon } from '../lib/lexicons';
import { wordPoolManager } from '../utils/wordPoolManager';
import { KEYWORD_COUNT, QUICK_COUNTS, clampCount } from '../config';

interface ControlPanelProps {
  keywordCount: number;
  setKeywordCount: (count: number) => void;
  balanceMode: BalanceMode;
  setBalanceMode: (mode: BalanceMode) => void;
  combinationStyle: CombinationStyle;
  setCombinationStyle: (style: CombinationStyle) => void;
  onGenerate: () => void;
  onAddCustomKeyword: (korean: string, category: CategoryType) => void;
  onOpenPoolManager?: () => void;
  /** Extra word lists that loaded, which are on, and switching one. */
  lexicons: LoadedLexicon[];
  enabledLexicons: string[];
  onToggleLexicon: (id: string) => void;
}

export const ControlPanel: React.FC<ControlPanelProps> = ({
  keywordCount,
  setKeywordCount,
  balanceMode,
  setBalanceMode,
  combinationStyle,
  setCombinationStyle,
  onGenerate,
  onAddCustomKeyword,
  onOpenPoolManager,
  lexicons,
  enabledLexicons,
  onToggleLexicon,
}) => {
  const [customWord, setCustomWord] = useState('');
  const [customCat, setCustomCat] = useState<CategoryType>('object');
  const [showCustomInput, setShowCustomInput] = useState(false);

  const stats = wordPoolManager.getStats();

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (customWord.trim()) {
      onAddCustomKeyword(customWord.trim(), customCat);
      setCustomWord('');
      setShowCustomInput(false);
    }
  };

  return (
    <section className="bg-surface border border-edge rounded-panel p-5 sm:p-6 shadow-xs space-y-6">
      {/* 0. Word Pool Scale Status Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-edge text-xs text-muted">
        <div className="flex flex-wrap items-center gap-2 font-medium">
          <Database className="w-3.5 h-3.5 text-accent" />
          <span className="text-ink font-semibold">문학 어휘 풀:</span>
          <span className="font-mono tabular-nums text-ink font-bold">
            총 {num(stats.total)}개 어휘 등록됨
          </span>
          <span aria-hidden="true" className="text-muted">·</span>
          <span className="text-muted font-mono text-[11px]">{partBreakdown(stats)}</span>
          {lexicons.map(l => (
            <label key={l.id} className="inline-flex items-center gap-1.5 ml-1 px-2 py-0.5 rounded-control border border-edge bg-soft cursor-pointer select-none hover:border-edge"
                   title={`${l.credit.publisher} 「${l.credit.source}」에서 고른 ${num(l.size)}개 어휘 (${l.credit.license})`}>
              <input type="checkbox" checked={enabledLexicons.includes(l.id)} onChange={() => onToggleLexicon(l.id)}
                     className="accent-accent" />
              <span className="text-ink">{l.label} 어휘 포함</span>
              {/* what it adds: its words the pool did not have already (when off, the whole list) */}
              <span className="font-mono text-[11px] text-muted">+{num(stats.bySource[l.id] ?? l.size)}</span>
            </label>
          ))}
        </div>

        {onOpenPoolManager && (
          <button
            onClick={onOpenPoolManager}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-accent bg-accent-soft hover:bg-accent-soft border border-edge rounded-control self-start sm:self-auto cursor-pointer"
          >
            <Settings2 className="w-3.5 h-3.5 text-accent" />
            <span>어휘 추가 &amp; 중복 검사</span>
          </button>
        )}
      </div>

      {/* 1. Grammatical Combination Style (수식어 / 술어 / 목적어 분할 및 조합 방식) */}
      <div>
        <label className="text-xs uppercase tracking-wider font-semibold text-ink flex items-center gap-1.5 mb-2.5">
          <Split className="w-3.5 h-3.5 text-muted" />
          <span>문법 구조 및 분할 조합 방식</span>
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
          {keysOf(COMBINATION_STYLES).map(style => (
            <button
              key={style}
              onClick={() => setCombinationStyle(style)}
              className={`p-2.5 text-left rounded-control border transition-shadow cursor-pointer ${
                combinationStyle === style
                  ? 'bg-action text-on-action border-edge shadow-xs'
                  : 'bg-soft hover:bg-surface text-ink border-edge'
              }`}
            >
              <div className="text-xs font-bold leading-tight">{COMBINATION_STYLES[style].label}</div>
              <div className={`text-[11px] mt-0.5 ${combinationStyle === style ? 'text-on-action' : 'text-muted'}`}>
                {COMBINATION_STYLES[style].example}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 2. Keyword Count Section */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs uppercase tracking-wider font-semibold text-ink flex items-center gap-1.5">
            <Sliders className="w-3.5 h-3.5 text-muted" />
            <span>생성할 키워드 개수</span>
          </label>
          <span className="font-mono tabular-nums text-sm font-bold text-accent bg-accent-soft px-2 py-0.5 rounded-control border border-edge">
            {keywordCount}개
          </span>
        </div>

        <div className="flex flex-col sm:flex-row items-center gap-4">
          <div className="flex items-center gap-1.5 w-full sm:w-auto">
            {QUICK_COUNTS.map(count => (
              <button
                key={count}
                onClick={() => setKeywordCount(count)}
                className={`flex-1 sm:flex-initial px-2.5 py-1.5 text-xs font-mono tabular-nums rounded-control border cursor-pointer ${
                  keywordCount === count
                    ? 'bg-action text-on-action border-edge font-bold'
                    : 'bg-soft hover:bg-soft text-ink border-edge'
                }`}
              >
                {count}
              </button>
            ))}
          </div>

          <div className="w-full flex-1 flex items-center gap-2">
            <span className="text-xs text-muted font-mono">{KEYWORD_COUNT.min}</span>
            <input
              type="range"
              min={KEYWORD_COUNT.min}
              max={KEYWORD_COUNT.max}
              value={clampCount(keywordCount)}
              onChange={e => setKeywordCount(clampCount(Number(e.target.value)))}
              className="w-full h-1.5 bg-soft rounded-panel appearance-none cursor-pointer accent-accent"
            />
            <span className="text-xs text-muted font-mono">{KEYWORD_COUNT.max}</span>
          </div>
        </div>
      </div>

      {/* 4. Category Composition & Action Buttons */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pt-4 border-t border-edge">
        <div>
          <label className="text-xs uppercase tracking-wider font-semibold text-ink flex items-center gap-1.5 mb-2">
            <Layers className="w-3.5 h-3.5 text-muted" />
            <span>범주 배분 모드</span>
          </label>
          <div className="flex flex-wrap gap-1.5">
            {keysOf(BALANCE_MODES).map(mode => (
              <button
                key={mode}
                onClick={() => setBalanceMode(mode)}
                className={`px-2.5 py-1 text-xs rounded-control border cursor-pointer ${
                  balanceMode === mode
                    ? 'bg-action text-on-action border-edge font-medium'
                    : 'bg-soft text-muted border-edge hover:bg-soft'
                }`}
              >
                {BALANCE_MODES[mode].label}
              </button>
            ))}
          </div>
        </div>

        {/* Custom Word Input & Generate Trigger */}
        <div className="min-w-0 max-w-full flex flex-wrap items-center gap-2">
          {!showCustomInput ? (
            <button
              onClick={() => setShowCustomInput(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-ink bg-soft hover:bg-soft rounded-control border border-edge cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>직접 단어 추가</span>
            </button>
          ) : (
            <form onSubmit={handleAddSubmit} className="flex flex-wrap min-w-0 items-center gap-1.5">
              <input
                type="text"
                value={customWord}
                onChange={e => setCustomWord(e.target.value)}
                placeholder="단어 입력"
                className="px-2.5 py-1 text-xs border border-edge rounded-control focus:outline-none focus:ring-1 focus:ring-accent w-32"
                autoFocus
              />
              <select
                value={customCat}
                onChange={e => setCustomCat(e.target.value as CategoryType)}
                className="px-2 py-1 text-xs border border-edge rounded-control bg-surface"
              >
                {keysOf(CATEGORY_NAMES).map(c => (
                  <option key={c} value={c}>
                    {CATEGORY_NAMES[c]}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                className="px-2.5 py-1 text-xs font-medium text-on-action bg-action rounded-control hover:bg-action cursor-pointer"
              >
                추가
              </button>
              <button
                type="button"
                onClick={() => setShowCustomInput(false)}
                className="px-2 py-1 text-xs text-muted hover:text-ink cursor-pointer"
              >
                닫기
              </button>
            </form>
          )}

          <button
            onClick={onGenerate}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-on-action bg-action hover:bg-action rounded-control shadow-xs cursor-pointer whitespace-nowrap"
          >
            <Sparkles className="w-3.5 h-3.5 text-on-action" />
            <span>새로 뽑기</span>
          </button>
        </div>
      </div>
    </section>
  );
};
