import React, { useState, useEffect } from 'react';
import { Copy, Check, Download, Sparkles, BookOpen, FileText } from 'lucide-react';
import { KeywordItem } from '../types';
import { generateStoryPrompt, formatKeywords, keywordUsedIn } from '../utils/generator';
import * as storage from '../lib/storage';
import { DEFAULTS, READING_CHARS_PER_MINUTE, TIMING_MS } from '../config';
import { num } from '../utils/format';

interface NovelDraftPadProps {
  keywords: KeywordItem[];
  onBackToGenerator: () => void;
  onSaveFailed?: () => void;
}

interface Draft {
  title?: string;
  content?: string;
  updatedAt?: number;
}

export const NovelDraftPad: React.FC<NovelDraftPadProps> = ({
  keywords,
  onBackToGenerator,
  onSaveFailed,
}) => {
  const [draftTitle, setDraftTitle] = useState(DEFAULTS.draftTitle);
  const [draftContent, setDraftContent] = useState('');
  const [isCopied, setIsCopied] = useState(false);

  const [loaded, setLoaded] = useState(false);

  // The saved draft (the account's, or this browser's): typing waits for it, so it is never overwritten
  useEffect(() => {
    let live = true;
    void storage.load<Draft>('draft').then(saved => {
      if (!live) return;
      if (saved?.title) setDraftTitle(saved.title);
      if (saved?.content) setDraftContent(saved.content);
      setLoaded(true);
    });
    return () => { live = false; };
  }, []);

  const persist = (title: string, content: string) => {
    storage.saveSoon('draft', { title, content, updatedAt: Date.now() }, TIMING_MS.draftSave, ok => { if (!ok) onSaveFailed?.(); });
  };

  const handleContentChange = (val: string) => {
    setDraftContent(val);
    persist(draftTitle, val);
  };

  const handleTitleChange = (val: string) => {
    setDraftTitle(val);
    persist(val, draftContent);
  };

  // Check which keywords are used in draft
  const usedKeywords = keywords.filter(k => keywordUsedIn(draftContent, k));

  const promptSuggestion = generateStoryPrompt(keywords);

  const handleInsertPrompt = () => {
    const prefix = draftContent ? `${draftContent}\n\n[플롯 가이드]\n${promptSuggestion}\n\n` : `[플롯 가이드]\n${promptSuggestion}\n\n`;
    handleContentChange(prefix);
  };

  const handleCopyDraft = async () => {
    await navigator.clipboard.writeText(`${draftTitle}\n\n${draftContent}`);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), TIMING_MS.copied);
  };

  const handleDownloadTxt = () => {
    const element = document.createElement('a');
    const file = new Blob([`${draftTitle}\n\n키워드: ${formatKeywords(keywords, 'comma')}\n\n${draftContent}`], {
      type: 'text/plain;charset=utf-8',
    });
    element.href = URL.createObjectURL(file);
    element.download = `${draftTitle || DEFAULTS.draftTitle}.txt`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  const charCount = draftContent.length;
  const charCountNoSpace = draftContent.replace(/\s+/g, '').length;
  const wordCount = draftContent.trim() ? draftContent.trim().split(/\s+/).length : 0;
  const estReadMinutes = Math.max(1, Math.ceil(charCount / READING_CHARS_PER_MINUTE));

  return (
    <div className="space-y-6">
      {/* Top Banner: Active Keywords & Progress */}
      <div className="bg-white border border-stone-200 rounded-lg p-5 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-stone-100">
          <div>
            <div className="flex items-center gap-2 text-xs text-stone-500 font-medium">
              <span>ACTIVE NOVEL KEYWORDS</span>
              <span aria-hidden="true">·</span>
              <span>
                반영률:{' '}
                <strong className="text-amber-800 font-mono tabular-nums">
                  {usedKeywords.length} / {keywords.length}
                </strong>
                개 완료
              </span>
            </div>
            <p className="font-serif-kr text-base sm:text-lg text-stone-900 mt-1 font-medium">
              {formatKeywords(keywords, 'comma')}
            </p>
          </div>

          <button
            onClick={onBackToGenerator}
            className="text-xs text-stone-600 hover:text-stone-900 border border-stone-200 hover:bg-stone-50 px-3 py-1.5 rounded transition-colors self-start sm:self-auto cursor-pointer"
          >
            키워드 재선택하러 가기
          </button>
        </div>

        {/* Individual keyword badges showing checkmarks when used */}
        <div className="flex flex-wrap gap-2 pt-3">
          {keywords.map(k => {
            const isUsed = usedKeywords.some(u => u.id === k.id);
            return (
              <span
                key={k.id}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded transition-all ${
                  isUsed
                    ? 'bg-emerald-50 text-emerald-800 border border-emerald-300 font-semibold'
                    : 'bg-stone-100/70 text-stone-600 border border-stone-200'
                }`}
              >
                {isUsed ? (
                  <Check className="w-3 h-3 text-emerald-600" />
                ) : (
                  <span className="w-1.5 h-1.5 rounded-full bg-stone-400" />
                )}
                <span>{k.korean}</span>
              </span>
            );
          })}
        </div>
      </div>

      {/* Algorithmic Narrative Prompt Inspiration Card */}
      <div className="bg-amber-50/50 border border-amber-200/80 rounded-lg p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <Sparkles className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
            <div>
              <h3 className="text-xs uppercase tracking-wider font-bold text-amber-900">
                키워드 기반 플롯 시놉시스 제안
              </h3>
              <p className="font-serif-kr text-sm sm:text-base text-stone-800 mt-1 leading-relaxed">
                {promptSuggestion}
              </p>
            </div>
          </div>
          <button
            onClick={handleInsertPrompt}
            className="shrink-0 px-2.5 py-1 text-xs font-medium text-amber-900 bg-amber-100 hover:bg-amber-200 border border-amber-300 rounded transition-colors cursor-pointer"
          >
            본문에 삽입
          </button>
        </div>
      </div>

      {/* Main Drafting Workspace */}
      <div className="bg-white border border-stone-200 rounded-lg p-5 sm:p-7 shadow-xs">
        {/* Title input */}
        <div className="flex items-center justify-between gap-4 pb-4 border-b border-stone-100">
          <input
            type="text"
            value={draftTitle}
            onChange={e => handleTitleChange(e.target.value)}
            disabled={!loaded}
            placeholder="소설 제목을 입력하세요"
            className="font-serif-kr text-xl sm:text-2xl font-bold text-stone-900 border-none focus:outline-none w-full bg-transparent placeholder:text-stone-300"
          />

          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={handleCopyDraft}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs text-stone-700 bg-stone-100 hover:bg-stone-200 rounded border border-stone-300 transition-colors cursor-pointer"
            >
              {isCopied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{isCopied ? '복사됨' : '본문 복사'}</span>
            </button>
            <button
              onClick={handleDownloadTxt}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs text-stone-700 bg-stone-100 hover:bg-stone-200 rounded border border-stone-300 transition-colors cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" />
              <span>TXT 다운로드</span>
            </button>
          </div>
        </div>

        {/* Textarea */}
        <textarea
          value={draftContent}
          onChange={e => handleContentChange(e.target.value)}
          disabled={!loaded}
          placeholder={loaded ? `선택한 키워드들을 자연스럽게 녹여내며 이야기를 시작해보세요.\n\n예시: 눈보라가 창문을 사납게 두드리는 밤이었다...` : '불러오는 중…'}
          className="w-full h-96 sm:h-[480px] py-4 text-base sm:text-lg font-serif-kr text-stone-900 border-none focus:outline-none resize-none leading-loose placeholder:text-stone-300"
        />

        {/* Footer Statistics */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-stone-100 text-xs text-stone-500 font-mono tabular-nums">
          <div className="flex items-center gap-3">
            <span>공백 포함 <strong>{num(charCount)}</strong>자</span>
            <span aria-hidden="true">·</span>
            <span>공백 제외 <strong>{num(charCountNoSpace)}</strong>자</span>
            <span aria-hidden="true">·</span>
            <span>단어 <strong>{num(wordCount)}</strong>개</span>
          </div>
          <div>
            <span>예상 독서 시간: 약 {estReadMinutes}분</span>
          </div>
        </div>
      </div>
    </div>
  );
};
