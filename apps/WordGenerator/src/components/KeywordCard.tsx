import React from 'react';
import { Lock, Unlock, RefreshCw, X } from 'lucide-react';
import { KeywordItem } from '../types';
import { WORD_PARTS } from '../data/labels';

interface KeywordCardProps {
  keyword: KeywordItem;
  index: number;
  onToggleLock: (id: string) => void;
  onRerollSingle: (keyword: KeywordItem) => void;
  onRemove: (id: string) => void;
}

export const KeywordCard: React.FC<KeywordCardProps> = ({
  keyword,
  index,
  onToggleLock,
  onRerollSingle,
  onRemove,
}) => {
  return (
    <div
      className={`group relative flex flex-col justify-between p-4 sm:p-5 rounded-lg border transition-all duration-200 ${
        keyword.isLocked
          ? 'bg-amber-50/40 border-amber-300/80 shadow-xs'
          : 'bg-white border-stone-200 hover:border-stone-300 shadow-2xs hover:shadow-xs'
      }`}
    >
      <div>
        {/* Top Header: Unboxed metadata + lock/action icons */}
        <div className="flex items-center justify-between text-xs text-stone-500 mb-2">
          {/* Category kicker without pills */}
          <div className="flex items-center gap-1.5 font-medium tracking-tight">
            <span className="font-mono tabular-nums text-stone-400">
              {String(index + 1).padStart(2, '0')}
            </span>
            <span aria-hidden="true" className="text-stone-300">·</span>
            <span className="text-stone-700 font-semibold">{keyword.categoryKo}</span>
          </div>

          {/* Functional Actions */}
          <div className="flex items-center gap-1">
            {/* Lock / Pin */}
            <button
              onClick={() => onToggleLock(keyword.id)}
              title={keyword.isLocked ? '고정 해제' : '이 키워드 고정하기 (새로 뽑아도 유지)'}
              className={`p-1 rounded transition-colors cursor-pointer ${
                keyword.isLocked
                  ? 'text-amber-700 hover:text-amber-800 bg-amber-100/60'
                  : 'text-stone-400 hover:text-stone-700 hover:bg-stone-100'
              }`}
            >
              {keyword.isLocked ? (
                <Lock className="w-3.5 h-3.5" />
              ) : (
                <Unlock className="w-3.5 h-3.5" />
              )}
            </button>

            {/* Individual Reroll */}
            <button
              onClick={() => onRerollSingle(keyword)}
              title="이 키워드만 새로 교체하기"
              className="p-1 text-stone-400 hover:text-stone-700 hover:bg-stone-100 rounded transition-colors cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5 group-hover:rotate-45 transition-transform" />
            </button>

            {/* Remove */}
            <button
              onClick={() => onRemove(keyword.id)}
              title="키워드 삭제"
              className="p-1 text-stone-400 hover:text-rose-600 hover:bg-rose-50 rounded transition-colors cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Primary Korean Keyword */}
        <h3 className="font-serif-kr text-lg sm:text-xl font-bold text-stone-900 leading-snug tracking-tight">
          {keyword.korean}
        </h3>

      </div>

      {/* Grammar Breakdown or Writer Cue */}
      <div className="mt-4 pt-3 border-t border-stone-100 space-y-1.5">
        {keyword.components ? (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-stone-500 font-mono">
            {keyword.components.modifier && (
              <span className="text-stone-600">
                {WORD_PARTS.modifier.short}: <strong className="text-stone-800 font-serif-kr">{keyword.components.modifier}</strong>
              </span>
            )}
            {keyword.components.modifier && keyword.components.object && (
              <span aria-hidden="true" className="text-stone-300">·</span>
            )}
            {keyword.components.object && (
              <span className="text-stone-600">
                {WORD_PARTS.object.short}: <strong className="text-stone-800 font-serif-kr">{keyword.components.object}</strong>
              </span>
            )}
            {keyword.components.predicate && (
              <>
                <span aria-hidden="true" className="text-stone-300">·</span>
                <span className="text-stone-600">
                  {WORD_PARTS.predicate.short}: <strong className="text-stone-800 font-serif-kr">{keyword.components.predicate}</strong>
                </span>
              </>
            )}
          </div>
        ) : (
          <div className="text-xs text-stone-600 leading-relaxed">
            {keyword.descriptionKo}
          </div>
        )}
      </div>
    </div>
  );
};
