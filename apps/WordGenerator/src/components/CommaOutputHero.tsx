import React, { useState } from 'react';
import { Copy, Check, SlidersHorizontal, BookOpen, BookmarkPlus, RefreshCw } from 'lucide-react';
import { KeywordItem, OutputFormat } from '../types';
import { formatKeywords } from '../utils/generator';
import { OUTPUT_FORMATS, keysOf } from '../data/labels';
import { num } from '../utils/format';

interface CommaOutputHeroProps {
  keywords: KeywordItem[];
  outputFormat: OutputFormat;
  setOutputFormat: (format: OutputFormat) => void;
  /** Copies the keywords in the selected format. */
  onCopy: () => void;
  isCopied: boolean;
  onSaveCurrentSet: () => void;
  onRerollAll: () => void;
  onOpenDraft: () => void;
  onManualCommaEdit: (rawText: string) => void;
}

export const CommaOutputHero: React.FC<CommaOutputHeroProps> = ({
  keywords,
  outputFormat,
  setOutputFormat,
  onCopy,
  isCopied,
  onSaveCurrentSet,
  onRerollAll,
  onOpenDraft,
  onManualCommaEdit,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const [editText, setEditText] = useState('');

  const formattedText = formatKeywords(keywords, outputFormat);
  const commaSeparatedText = formatKeywords(keywords, 'comma');

  const handleStartEdit = () => {
    setEditText(commaSeparatedText);
    setIsEditing(true);
  };

  const handleSaveEdit = () => {
    onManualCommaEdit(editText);
    setIsEditing(false);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
  };

  // Category counts breakdown for clean editorial metadata
  const categoryCounts = keywords.reduce((acc, k) => {
    acc[k.categoryKo] = (acc[k.categoryKo] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  return (
    <section className="bg-surface border border-edge rounded-panel p-5 sm:p-7 shadow-xs">
      {/* Title & Format Switcher Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-edge">
        <div>
          <h2 className="text-xs uppercase tracking-widest text-muted font-medium">
            Keyword Output
          </h2>
          <h1 className="font-serif text-xl sm:text-2xl font-bold text-ink mt-0.5">
            소설 창작 키워드
          </h1>
        </div>

        {/* Format Selector: functional segmented control */}
        <div className="flex flex-wrap items-center gap-1 p-1 bg-soft rounded-control min-w-0 max-w-full">
          {keysOf(OUTPUT_FORMATS).map(format => (
            <button
              key={format}
              onClick={() => setOutputFormat(format)}
              className={`px-2.5 py-1 text-xs font-medium rounded-control whitespace-nowrap cursor-pointer ${
                outputFormat === format
                  ? 'bg-surface text-ink shadow-xs font-semibold'
                  : 'text-muted hover:text-ink'
              }`}
            >
              {OUTPUT_FORMATS[format]}
            </button>
          ))}
        </div>
      </div>

      {/* Main Text Display or Inline Editor */}
      <div className="my-5">
        {isEditing ? (
          <div className="space-y-2">
            <textarea
              value={editText}
              onChange={e => setEditText(e.target.value)}
              placeholder="쉼표(,)로 구분하여 키워드를 입력하세요. 예: 오래된 시계, 결벽증, 비오는 골목"
              className="w-full h-28 p-3 text-base sm:text-lg font-serif border border-edge rounded-control focus:outline-none focus:ring-2 focus:ring-accent bg-accent-soft text-ink resize-none leading-relaxed"
              autoFocus
            />
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted">
                쉼표(,)를 기준으로 단어가 개별 키워드 카드로 자동 변환됩니다.
              </span>
              <div className="flex flex-col sm:flex-row sm:flex-wrap items-stretch sm:items-center gap-2 w-full sm:w-auto">
                <button
                  onClick={handleCancelEdit}
                  className="px-3 py-1 text-muted hover:text-ink rounded-control cursor-pointer"
                >
                  취소
                </button>
                <button
                  onClick={handleSaveEdit}
                  className="px-3 py-1 text-on-action bg-action hover:bg-action rounded-control font-medium cursor-pointer"
                >
                  적용하기
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="relative group p-4 sm:p-5 bg-soft rounded-control border border-edge">
            <p className="font-serif text-lg sm:text-2xl text-ink leading-relaxed tracking-normal select-all whitespace-pre-line">
              {formattedText || (
                <span className="text-muted italic">키워드가 아직 없습니다. &lsquo;키워드 뽑기&rsquo;를 눌러보세요.</span>
              )}
            </p>

            <button
              onClick={handleStartEdit}
              className="absolute top-2.5 right-2.5 opacity-0 group-hover:opacity-100 transition-opacity text-xs text-muted hover:text-ink bg-surface px-2 py-1 rounded-control border border-edge shadow-2xs cursor-pointer"
            >
              직접 수정
            </button>
          </div>
        )}
      </div>

      {/* Unboxed Metadata Discipline */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted mb-5">
        <span className="font-medium text-ink">
          총 <strong className="font-mono tabular-nums text-ink">{num(keywords.length)}</strong>개 키워드
        </span>
        <span aria-hidden="true" className="text-muted">·</span>
        {Object.entries(categoryCounts).map(([cat, count], idx) => (
          <React.Fragment key={cat}>
            <span>
              {cat} <span className="font-mono tabular-nums text-ink">{count}</span>
            </span>
            {idx < Object.entries(categoryCounts).length - 1 && (
              <span aria-hidden="true" className="text-muted">·</span>
            )}
          </React.Fragment>
        ))}
        <span aria-hidden="true" className="text-muted">·</span>
        <span className="text-muted">{OUTPUT_FORMATS[outputFormat]} 형식으로 복사됩니다</span>
      </div>

      {/* Action Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-edge">
        <div className="flex flex-col sm:flex-row sm:flex-wrap items-stretch sm:items-center gap-2 w-full sm:w-auto">
          {/* Primary Action Button: Copy Comma-Separated */}
          <button
            onClick={onCopy}
            className={`inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold rounded-control shadow-xs cursor-pointer ${
              isCopied
                ? 'bg-action text-on-action hover:bg-action'
                : 'bg-action text-on-action hover:bg-action'
            }`}
          >
            {isCopied ? (
              <>
                <Check className="w-4 h-4" />
                <span>{OUTPUT_FORMATS[outputFormat]} 복사됨!</span>
              </>
            ) : (
              <>
                <Copy className="w-4 h-4 text-on-action" />
                <span>{OUTPUT_FORMATS[outputFormat]} 복사</span>
              </>
            )}
          </button>

          <button
            onClick={onRerollAll}
            title="고정(잠금)되지 않은 키워드를 새로 무작위 생성합니다"
            className="inline-flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-medium text-ink bg-surface hover:bg-soft border border-edge rounded-control cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5 text-muted" />
            <span>다시 뽑기</span>
          </button>
        </div>

        <div className="flex flex-col sm:flex-row sm:flex-wrap items-stretch sm:items-center gap-2 w-full sm:w-auto">
          <button
            onClick={onSaveCurrentSet}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-ink hover:text-ink bg-soft hover:bg-soft rounded-control cursor-pointer"
          >
            <BookmarkPlus className="w-3.5 h-3.5 text-accent" />
            <span>보관함에 저장</span>
          </button>

          <button
            onClick={onOpenDraft}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-accent bg-accent-soft hover:bg-accent-soft border border-edge rounded-control cursor-pointer"
          >
            <BookOpen className="w-3.5 h-3.5 text-accent" />
            <span>소설 집필 시작</span>
          </button>
        </div>
      </div>
    </section>
  );
};
