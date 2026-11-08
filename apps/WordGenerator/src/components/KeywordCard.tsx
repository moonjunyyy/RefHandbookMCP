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
      className={`group relative flex flex-col justify-between p-4 sm:p-5 rounded-panel border transition-shadow duration-200 ${
        keyword.isLocked
          ? 'bg-accent-soft border-edge shadow-xs'
          : 'bg-surface border-edge hover:border-edge shadow-2xs hover:shadow-xs'
      }`}
    >
      <div>
        {/* Top Header: Unboxed metadata + lock/action icons */}
        <div className="flex items-center justify-between text-xs text-muted mb-2">
          {/* Category kicker without pills */}
          <div className="flex items-center gap-1.5 font-medium tracking-tight">
            <span className="font-mono tabular-nums text-muted">
              {String(index + 1).padStart(2, '0')}
            </span>
            <span aria-hidden="true" className="text-muted">·</span>
            <span className="text-ink font-semibold">{keyword.categoryKo}</span>
          </div>

          {/* Functional Actions */}
          <div className="flex items-center gap-1">
            {/* Lock / Pin */}
            <button
              onClick={() => onToggleLock(keyword.id)}
              title={keyword.isLocked ? '고정 해제' : '이 키워드 고정하기 (새로 뽑아도 유지)'}
              className={`p-1 rounded-control cursor-pointer ${
                keyword.isLocked
                  ? 'text-accent hover:text-accent bg-accent-soft'
                  : 'text-muted hover:text-ink hover:bg-soft'
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
              className="p-1 text-muted hover:text-ink hover:bg-soft rounded-control cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5 group-hover:rotate-45 transition-transform" />
            </button>

            {/* Remove */}
            <button
              onClick={() => onRemove(keyword.id)}
              title="키워드 삭제"
              className="p-1 text-muted hover:text-danger hover:bg-danger-soft rounded-control cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Primary Korean Keyword */}
        <h3 className="font-serif text-lg sm:text-xl font-bold text-ink leading-snug tracking-tight">
          {keyword.korean}
        </h3>

      </div>

      {/* Grammar Breakdown or Writer Cue */}
      <div className="mt-4 pt-3 border-t border-edge space-y-1.5">
        {keyword.components ? (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted font-mono">
            {keyword.components.modifier && (
              <span className="text-muted">
                {WORD_PARTS.modifier.short}: <strong className="text-ink font-serif">{keyword.components.modifier}</strong>
              </span>
            )}
            {keyword.components.modifier && keyword.components.object && (
              <span aria-hidden="true" className="text-muted">·</span>
            )}
            {keyword.components.object && (
              <span className="text-muted">
                {WORD_PARTS.object.short}: <strong className="text-ink font-serif">{keyword.components.object}</strong>
              </span>
            )}
            {keyword.components.predicate && (
              <>
                <span aria-hidden="true" className="text-muted">·</span>
                <span className="text-muted">
                  {WORD_PARTS.predicate.short}: <strong className="text-ink font-serif">{keyword.components.predicate}</strong>
                </span>
              </>
            )}
          </div>
        ) : (
          <div className="text-xs text-muted leading-relaxed">
            {keyword.descriptionKo}
          </div>
        )}
      </div>
    </div>
  );
};
