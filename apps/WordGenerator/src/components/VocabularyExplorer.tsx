import React, { useState, useMemo } from 'react';
import { Search, Plus, Check, Database, Settings2 } from 'lucide-react';
import { KeywordItem, WordPartType } from '../types';
import { wordPoolManager, PoolEntry } from '../utils/wordPoolManager';
import { CATEGORY_NAMES, SOURCE_LABELS, WORD_PARTS, categoryOf, keysOf } from '../data/labels';
import { LoadedLexicon } from '../lib/lexicons';
import { LexiconCredits } from './LexiconCredits';
import { BUILTIN_SOURCE, CUSTOM_SOURCE } from '../utils/wordPoolManager';
import { num, partBreakdown } from '../utils/format';
import { DICTIONARY_PAGE } from '../config';

interface VocabularyExplorerProps {
  lexicons: LoadedLexicon[];
  activeKeywords: KeywordItem[];
  onAddKeyword: (item: KeywordItem) => void;
  onOpenPoolManager?: () => void;
}

export const VocabularyExplorer: React.FC<VocabularyExplorerProps> = ({
  lexicons,
  activeKeywords,
  onAddKeyword,
  onOpenPoolManager,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedPart, setSelectedPart] = useState<WordPartType | 'all'>('all');
  const [displayLimit, setDisplayLimit] = useState<number>(DICTIONARY_PAGE.first);

  const stats = wordPoolManager.getStats();
  const activeWordsSet = useMemo(
    () => new Set(activeKeywords.map(k => k.korean)),
    [activeKeywords]
  );

  const allWords = wordPoolManager.entries();

  const filteredWords = useMemo(() => {
    return allWords.filter(item => {
      const matchPart = selectedPart === 'all' || item.part === selectedPart;
      const matchSearch =
        !searchQuery.trim() ||
        item.text.toLowerCase().includes(searchQuery.toLowerCase());
      return matchPart && matchSearch;
    });
  }, [allWords, selectedPart, searchQuery]);

  const handleAddWord = (item: PoolEntry) => {
    const category = categoryOf(item.part, item.domain);
    const newItem: KeywordItem = {
      id: `pool-pick-${crypto.randomUUID()}`,
      korean: item.text,
      category,
      categoryKo: CATEGORY_NAMES[category],
      descriptionKo: `${WORD_PARTS[item.part].label} 풀에서 직접 추가한 어휘`,
      partType: item.part,
    };
    onAddKeyword(newItem);
  };

  return (
    <div className="bg-white border border-stone-200 rounded-lg p-5 sm:p-6 shadow-xs space-y-5">
      {/* Header and Search */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-stone-200">
        <div>
          <div className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-amber-800 font-semibold font-mono">
            <Database className="w-3.5 h-3.5" />
            <span>{num(stats.total)} Korean Literary Words</span>
          </div>
          <h1 className="font-serif-kr text-xl sm:text-2xl font-bold text-stone-900 mt-0.5">
            수식어 · 목적어 · 술어 어휘 풀 사전
          </h1>
          <p className="text-xs text-stone-500 mt-0.5">
            총 {num(stats.total)}개 어휘 ({partBreakdown(stats)})
          </p>
          <LexiconCredits lexicons={lexicons} className="text-[11px] text-stone-400 mt-0.5" />
        </div>

        <div className="flex items-center gap-2">
          {/* Search bar */}
          <div className="relative w-full sm:w-56">
            <Search className="w-4 h-4 text-stone-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="단어 검색 (예: 오래된, 은시계)..."
              className="w-full pl-9 pr-3 py-1.5 text-xs border border-stone-300 rounded-md focus:outline-none focus:ring-1 focus:ring-stone-400 bg-stone-50"
            />
          </div>

          {onOpenPoolManager && (
            <button
              onClick={onOpenPoolManager}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-amber-900 hover:bg-amber-800 rounded-md transition-colors whitespace-nowrap cursor-pointer"
            >
              <Settings2 className="w-3.5 h-3.5 text-amber-200" />
              <span>어휘 추가 &amp; 중복 검사</span>
            </button>
          )}
        </div>
      </div>

      {/* Part of Speech Filter Tabs */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setSelectedPart('all')}
          className={`px-3 py-1.5 text-xs font-medium rounded border transition-colors cursor-pointer ${
            selectedPart === 'all'
              ? 'bg-stone-900 text-white border-stone-900 font-semibold'
              : 'bg-stone-50 text-stone-700 border-stone-200 hover:bg-stone-100'
          }`}
        >
          전체 어휘 ({num(stats.total)})
        </button>

        {keysOf(WORD_PARTS).map(part => (
          <button
            key={part}
            onClick={() => setSelectedPart(part)}
            className={`px-3 py-1.5 text-xs font-medium rounded border transition-colors cursor-pointer ${
              selectedPart === part
                ? 'bg-amber-900 text-white border-amber-900 font-semibold'
                : 'bg-stone-50 text-stone-700 border-stone-200 hover:bg-stone-100'
            }`}
          >
            {WORD_PARTS[part].label} 풀 ({num(stats.byPart[part])})
          </button>
        ))}
      </div>

      {/* Word Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2.5 max-h-[600px] overflow-y-auto pr-1">
        {filteredWords.slice(0, displayLimit).map(item => {
          const isAdded = activeWordsSet.has(item.text);
          const partBadge = WORD_PARTS[item.part].short;
          const sourceBadge = item.source === BUILTIN_SOURCE ? null
            : item.source === CUSTOM_SOURCE ? SOURCE_LABELS.custom
            : lexicons.find(l => l.id === item.source)?.label ?? item.source;

          return (
            <div
              key={item.text}
              className="p-2.5 rounded border border-stone-200 bg-stone-50/60 hover:bg-white hover:border-stone-300 transition-all flex flex-col justify-between"
            >
              <div>
                <span className="text-[10px] text-stone-400 font-mono">
                  {partBadge}{sourceBadge && <span className="text-amber-700/70"> · {sourceBadge}</span>}
                </span>
                <div className="font-serif-kr text-sm font-bold text-stone-900 mt-0.5 leading-snug">
                  {item.text}
                </div>
              </div>

              <div className="mt-2 pt-1.5 border-t border-stone-200/50 flex justify-end">
                <button
                  onClick={() => handleAddWord(item)}
                  disabled={isAdded}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded transition-colors cursor-pointer ${
                    isAdded
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 cursor-default'
                      : 'bg-white hover:bg-stone-100 text-stone-700 border border-stone-300'
                  }`}
                >
                  {isAdded ? (
                    <>
                      <Check className="w-2.5 h-2.5 text-emerald-600" />
                      <span>포함됨</span>
                    </>
                  ) : (
                    <>
                      <Plus className="w-2.5 h-2.5" />
                      <span>추가</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {filteredWords.length > displayLimit && (
        <div className="flex flex-col items-center gap-2 pt-2">
          <div className="text-xs text-stone-400 font-mono">
            {num(filteredWords.length)}개 중 {num(Math.min(displayLimit, filteredWords.length))}개 표시 중
          </div>
          <button
            onClick={() => setDisplayLimit(prev => prev + DICTIONARY_PAGE.more)}
            className="px-4 py-2 text-xs font-semibold text-stone-700 bg-stone-100 hover:bg-stone-200 rounded-md border border-stone-300 transition-colors cursor-pointer"
          >
            어휘 더 보기 (+{num(Math.min(DICTIONARY_PAGE.more, filteredWords.length - displayLimit))}개)
          </button>
        </div>
      )}

      {filteredWords.length === 0 && (
        <div className="text-center py-12 text-stone-400 font-serif-kr">
          검색어와 일치하는 어휘가 풀에 없습니다.
        </div>
      )}
    </div>
  );
};
