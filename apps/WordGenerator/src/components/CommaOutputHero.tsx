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
    <section className="bg-white border border-stone-200 rounded-lg p-5 sm:p-7 shadow-xs">
      {/* Title & Format Switcher Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-stone-200">
        <div>
          <h2 className="text-xs uppercase tracking-widest text-stone-500 font-medium">
            Keyword Output
          </h2>
          <h1 className="font-serif-kr text-xl sm:text-2xl font-bold text-stone-900 mt-0.5">
            소설 창작 키워드
          </h1>
        </div>

        {/* Format Selector: functional segmented control */}
        <div className="flex items-center gap-1 p-1 bg-stone-100 rounded-md overflow-x-auto">
          {keysOf(OUTPUT_FORMATS).map(format => (
            <button
              key={format}
              onClick={() => setOutputFormat(format)}
              className={`px-2.5 py-1 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                outputFormat === format
                  ? 'bg-white text-stone-900 shadow-xs font-semibold'
                  : 'text-stone-600 hover:text-stone-900'
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
              className="w-full h-28 p-3 text-base sm:text-lg font-serif-kr border border-amber-300 rounded-md focus:outline-none focus:ring-2 focus:ring-amber-500/20 bg-amber-50/20 text-stone-900 resize-none leading-relaxed"
              autoFocus
            />
            <div className="flex items-center justify-between text-xs">
              <span className="text-stone-500">
                쉼표(,)를 기준으로 단어가 개별 키워드 카드로 자동 변환됩니다.
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCancelEdit}
                  className="px-3 py-1 text-stone-600 hover:text-stone-900 rounded cursor-pointer"
                >
                  취소
                </button>
                <button
                  onClick={handleSaveEdit}
                  className="px-3 py-1 text-white bg-stone-900 hover:bg-stone-800 rounded font-medium cursor-pointer"
                >
                  적용하기
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="relative group p-4 sm:p-5 bg-stone-50/80 rounded-md border border-stone-200">
            <p className="font-serif-kr text-lg sm:text-2xl text-stone-900 leading-relaxed tracking-normal select-all whitespace-pre-line">
              {formattedText || (
                <span className="text-stone-400 italic">키워드가 아직 없습니다. &lsquo;키워드 뽑기&rsquo;를 눌러보세요.</span>
              )}
            </p>

            <button
              onClick={handleStartEdit}
              className="absolute top-2.5 right-2.5 opacity-0 group-hover:opacity-100 transition-opacity text-xs text-stone-500 hover:text-stone-900 bg-white/90 px-2 py-1 rounded border border-stone-200 shadow-2xs cursor-pointer"
            >
              직접 수정
            </button>
          </div>
        )}
      </div>

      {/* Unboxed Metadata Discipline */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-stone-500 mb-5">
        <span className="font-medium text-stone-700">
          총 <strong className="font-mono tabular-nums text-stone-900">{num(keywords.length)}</strong>개 키워드
        </span>
        <span aria-hidden="true" className="text-stone-300">·</span>
        {Object.entries(categoryCounts).map(([cat, count], idx) => (
          <React.Fragment key={cat}>
            <span>
              {cat} <span className="font-mono tabular-nums text-stone-700">{count}</span>
            </span>
            {idx < Object.entries(categoryCounts).length - 1 && (
              <span aria-hidden="true" className="text-stone-300">·</span>
            )}
          </React.Fragment>
        ))}
        <span aria-hidden="true" className="text-stone-300">·</span>
        <span className="text-stone-400">{OUTPUT_FORMATS[outputFormat]} 형식으로 복사됩니다</span>
      </div>

      {/* Action Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-stone-100">
        <div className="flex items-center gap-2">
          {/* Primary Action Button: Copy Comma-Separated */}
          <button
            onClick={onCopy}
            className={`inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold rounded-md transition-colors shadow-xs cursor-pointer ${
              isCopied
                ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                : 'bg-stone-900 text-white hover:bg-stone-800'
            }`}
          >
            {isCopied ? (
              <>
                <Check className="w-4 h-4" />
                <span>{OUTPUT_FORMATS[outputFormat]} 복사됨!</span>
              </>
            ) : (
              <>
                <Copy className="w-4 h-4 text-amber-300" />
                <span>{OUTPUT_FORMATS[outputFormat]} 복사하기 (Copy)</span>
              </>
            )}
          </button>

          <button
            onClick={onRerollAll}
            title="고정(잠금)되지 않은 키워드를 새로 무작위 생성합니다"
            className="inline-flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-medium text-stone-700 bg-white hover:bg-stone-50 border border-stone-300 rounded-md transition-colors cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5 text-stone-500" />
            <span>다시 뽑기</span>
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onSaveCurrentSet}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-stone-700 hover:text-stone-900 bg-stone-100/80 hover:bg-stone-200/80 rounded-md transition-colors cursor-pointer"
          >
            <BookmarkPlus className="w-3.5 h-3.5 text-amber-700" />
            <span>보관함에 저장</span>
          </button>

          <button
            onClick={onOpenDraft}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-amber-900 bg-amber-50 hover:bg-amber-100/80 border border-amber-200/80 rounded-md transition-colors cursor-pointer"
          >
            <BookOpen className="w-3.5 h-3.5 text-amber-800" />
            <span>소설 집필 시작</span>
          </button>
        </div>
      </div>
    </section>
  );
};
