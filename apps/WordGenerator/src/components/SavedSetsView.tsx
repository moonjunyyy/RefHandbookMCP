import React from 'react';
import { Copy, Trash2, ArrowUpRight, Check, BookMarked } from 'lucide-react';
import { SavedKeywordSet } from '../types';
import { formatKeywords } from '../utils/generator';
import { GENRE_NAMES, OUTPUT_FORMATS } from '../data/labels';
import { num } from '../utils/format';

interface SavedSetsViewProps {
  savedSets: SavedKeywordSet[];
  onRestoreSet: (set: SavedKeywordSet) => void;
  onDeleteSet: (id: string) => void;
  onCopyComma: (text: string) => void;
  copiedId: string | null;
  onBackToGenerator: () => void;
}

export const SavedSetsView: React.FC<SavedSetsViewProps> = ({
  savedSets,
  onRestoreSet,
  onDeleteSet,
  onCopyComma,
  copiedId,
  onBackToGenerator,
}) => {
  return (
    <div className="bg-white border border-stone-200 rounded-lg p-5 sm:p-6 shadow-xs space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-stone-200">
        <div>
          <h2 className="text-xs uppercase tracking-widest text-stone-500 font-medium">
            Saved Prompt Collections
          </h2>
          <h1 className="font-serif-kr text-xl font-bold text-stone-900 mt-0.5">
            저장된 키워드 보관함
          </h1>
          <p className="text-xs text-stone-500 mt-0.5">
            총 {num(savedSets.length)}개의 저장된 소설 플롯 키워드 세트
          </p>
        </div>

        <button
          onClick={onBackToGenerator}
          className="text-xs text-stone-600 hover:text-stone-900 border border-stone-300 hover:bg-stone-50 px-3 py-1.5 rounded transition-colors self-start sm:self-auto cursor-pointer"
        >
          새 키워드 생성하기
        </button>
      </div>

      {savedSets.length === 0 ? (
        <div className="text-center py-16 space-y-3">
          <BookMarked className="w-10 h-10 text-stone-300 mx-auto" />
          <h3 className="font-serif-kr text-base font-semibold text-stone-700">
            아직 보관된 키워드 세트가 없습니다
          </h3>
          <p className="text-xs text-stone-500 max-w-sm mx-auto">
            생성기 화면에서 마음에 드는 키워드 조합을 &lsquo;보관함에 저장&rsquo; 버튼으로 기록해보세요.
          </p>
          <button
            onClick={onBackToGenerator}
            className="mt-2 inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium text-white bg-stone-900 hover:bg-stone-800 rounded transition-colors cursor-pointer"
          >
            키워드 뽑으러 가기
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {savedSets.map(set => {
            const commaText = formatKeywords(set.keywords, 'comma');
            const dateStr = new Date(set.createdAt).toLocaleDateString('ko-KR', {
              year: 'numeric',
              month: 'long',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            });

            return (
              <div
                key={set.id}
                className="p-4 sm:p-5 rounded-lg border border-stone-200 bg-stone-50/40 hover:bg-white hover:border-stone-300 transition-all space-y-3"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-xs text-stone-500">
                    <span className="font-semibold text-stone-900 font-serif-kr text-base">
                      {set.title}
                    </span>
                    {set.genre && set.genre !== 'all' && (
                      <>
                        <span aria-hidden="true" className="text-stone-300">·</span>
                        <span>{GENRE_NAMES[set.genre]}</span>
                      </>
                    )}
                    <span aria-hidden="true" className="text-stone-300">·</span>
                    <span className="font-mono tabular-nums">{dateStr}</span>
                  </div>

                  <div className="flex items-center gap-1.5 self-end sm:self-auto">
                    <button
                      onClick={() => onCopyComma(commaText)}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-stone-700 bg-white hover:bg-stone-100 rounded border border-stone-300 transition-colors cursor-pointer"
                    >
                      {copiedId === commaText ? (
                        <>
                          <Check className="w-3 h-3 text-emerald-600" />
                          <span className="text-emerald-700">복사됨</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3 h-3 text-stone-500" />
                          <span>{OUTPUT_FORMATS.comma} 복사</span>
                        </>
                      )}
                    </button>

                    <button
                      onClick={() => onRestoreSet(set)}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-amber-900 bg-amber-50 hover:bg-amber-100 rounded border border-amber-200 transition-colors cursor-pointer"
                    >
                      <ArrowUpRight className="w-3 h-3" />
                      <span>불러오기</span>
                    </button>

                    <button
                      onClick={() => onDeleteSet(set.id)}
                      title="보관함에서 삭제"
                      className="p-1 text-stone-400 hover:text-rose-600 hover:bg-rose-50 rounded transition-colors cursor-pointer"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Comma-separated preview */}
                <p className="font-serif-kr text-base text-stone-800 bg-stone-100/70 p-3 rounded border border-stone-200/60 leading-relaxed">
                  {commaText}
                </p>

                {/* Chips of individual items with categories */}
                <div className="flex flex-wrap gap-1.5">
                  {set.keywords.map(k => (
                    <span
                      key={k.id}
                      className="text-xs text-stone-600 bg-white border border-stone-200 px-2 py-0.5 rounded"
                    >
                      <strong className="text-stone-800">{k.korean}</strong>{' '}
                      <span className="text-stone-400">({k.categoryKo})</span>
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
