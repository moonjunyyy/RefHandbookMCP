import React from 'react';
import { Sparkles, Copy, Check } from 'lucide-react';
import { wordPoolManager } from '../utils/wordPoolManager';
import { TABS, keysOf } from '../data/labels';
import { Tab } from '../types';
import { num } from '../utils/format';

interface HeaderProps {
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
  onGenerate: () => void;
  /** Copies the keywords in the selected format (named by `copyLabel`). */
  onCopy: () => void;
  copyLabel: string;
  isCopied: boolean;
  savedCount: number;
  onOpenPoolManager?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  onGenerate,
  onCopy,
  copyLabel,
  isCopied,
  savedCount,
  onOpenPoolManager,
}) => {
  const poolSize = num(wordPoolManager.getStats().total);
  return (
    <header className="sticky top-0 z-40 bg-[#FBF9F5]/95 backdrop-blur-md border-b border-stone-200">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        {/* Zone 1: Single text element wordmark */}
        <button
          onClick={() => setActiveTab(keysOf(TABS)[0])}
          className="text-left group cursor-pointer focus:outline-none"
        >
          <span className="font-serif-kr text-xl sm:text-2xl font-bold tracking-tight text-stone-900 group-hover:text-amber-800 transition-colors">
            글타래
          </span>
          <span className="ml-2 font-display text-xs tracking-widest text-stone-400 uppercase hidden sm:inline">
            Novel Prompt Generator
          </span>
        </button>

        {/* Zone 2: 4 clean text navigation links */}
        <nav className="flex items-center gap-1 sm:gap-6 text-xs sm:text-sm font-medium">
          {keysOf(TABS).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-2.5 py-1.5 rounded transition-colors relative ${
                activeTab === tab
                  ? 'text-stone-900 font-semibold bg-stone-200/60'
                  : 'text-stone-600 hover:text-stone-900 hover:bg-stone-100'
              }`}
            >
              {TABS[tab]}
              {tab === 'saved' && savedCount > 0 && (
                <span className="ml-1 text-[11px] tabular-nums text-stone-500 font-mono">({num(savedCount)})</span>
              )}
            </button>
          ))}
        </nav>

        {/* Zone 3: 1-2 primary actions */}
        <div className="flex items-center gap-2">
          {onOpenPoolManager && (
            <button
              onClick={onOpenPoolManager}
              title={`${poolSize} 어휘 풀 조회 및 중복 방지 등록`}
              className="hidden md:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-amber-900 bg-amber-50 hover:bg-amber-100/80 rounded-md border border-amber-200 transition-colors whitespace-nowrap cursor-pointer"
            >
              <span>어휘 풀 관리 ({poolSize})</span>
            </button>
          )}

          <button
            onClick={onCopy}
            title={`키워드를 ${copyLabel} 형식으로 복사`}
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-stone-700 bg-stone-100 hover:bg-stone-200/80 rounded-md border border-stone-300 transition-colors whitespace-nowrap cursor-pointer"
          >
            {isCopied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-600" />
                <span className="text-emerald-700 font-semibold">{copyLabel} 복사됨</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5 text-stone-500" />
                <span>{copyLabel} 복사</span>
              </>
            )}
          </button>

          <button
            onClick={onGenerate}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium text-white bg-stone-900 hover:bg-stone-800 rounded-md transition-colors shadow-sm whitespace-nowrap cursor-pointer"
          >
            <Sparkles className="w-3.5 h-3.5 text-amber-300" />
            <span>키워드 뽑기</span>
          </button>
        </div>
      </div>
    </header>
  );
};
