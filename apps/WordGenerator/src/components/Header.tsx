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
    <header className="bg-page border-b border-edge">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 min-h-16 py-3 flex flex-wrap gap-3 items-center justify-between">
        {/* Zone 1: Single text element wordmark */}
        <button
          onClick={() => setActiveTab(keysOf(TABS)[0])}
          className="text-left group cursor-pointer focus:outline-none"
        >
          <span className="font-serif text-xl sm:text-2xl font-bold tracking-tight text-ink group-hover:text-accent">
            글타래
          </span>
          <span className="ml-2 font-serif text-xs tracking-widest text-muted uppercase hidden sm:inline">
            Novel Prompt Generator
          </span>
        </button>

        {/* Zone 2: 4 clean text navigation links */}
        <nav aria-label="글타래 메뉴" className="flex flex-wrap items-center gap-1 sm:gap-6 text-xs sm:text-sm font-medium">
          {keysOf(TABS).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-2.5 py-1.5 rounded-control relative ${
                activeTab === tab
                  ? 'text-ink font-semibold bg-soft'
                  : 'text-muted hover:text-ink hover:bg-soft'
              }`}
            >
              {TABS[tab]}
              {tab === 'saved' && savedCount > 0 && (
                <span className="ml-1 text-[11px] tabular-nums text-muted font-mono">({num(savedCount)})</span>
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
              className="hidden md:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-accent bg-accent-soft hover:bg-accent-soft rounded-control border border-edge whitespace-nowrap cursor-pointer"
            >
              <span>어휘 풀 관리 ({poolSize})</span>
            </button>
          )}

          <button
            onClick={onCopy}
            title={`키워드를 ${copyLabel} 형식으로 복사`}
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-ink bg-soft hover:bg-soft rounded-control border border-edge whitespace-nowrap cursor-pointer"
          >
            {isCopied ? (
              <>
                <Check className="w-3.5 h-3.5 text-success" />
                <span className="text-success font-semibold">{copyLabel} 복사됨</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5 text-muted" />
                <span>{copyLabel} 복사</span>
              </>
            )}
          </button>

          <button
            onClick={onGenerate}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium text-on-action bg-action hover:bg-action rounded-control shadow-sm whitespace-nowrap cursor-pointer"
          >
            <Sparkles className="w-3.5 h-3.5 text-on-action" />
            <span>키워드 뽑기</span>
          </button>
        </div>
      </div>
    </header>
  );
};
