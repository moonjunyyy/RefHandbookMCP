/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Header } from './components/Header';
import { CommaOutputHero } from './components/CommaOutputHero';
import { KeywordCard } from './components/KeywordCard';
import { ControlPanel } from './components/ControlPanel';
import { NovelDraftPad } from './components/NovelDraftPad';
import { VocabularyExplorer } from './components/VocabularyExplorer';
import { SavedSetsView } from './components/SavedSetsView';
import { WordPoolManagerModal } from './components/WordPoolManagerModal';
import { wordPoolManager, PoolWordItem } from './utils/wordPoolManager';
import * as storage from './lib/storage';
import { DEFAULTS, EXTRA_LEXICONS, KEYWORD_COUNT, SHORTCUTS, TIMING_MS, clampCount, shortcutFor } from './config';
import { LoadedLexicon, loadExtraLexicons } from './lib/lexicons';
import { LexiconCredits } from './components/LexiconCredits';
import {
  BalanceMode,
  CategoryType,
  CombinationStyle,
  KeywordItem,
  OutputFormat,
  Tab,
  SavedKeywordSet,
} from './types';
import {
  generateKeywords,
  replaceSingleKeyword,
  formatKeywords,
} from './utils/generator';
import { CATEGORY_NAMES, OUTPUT_FORMATS } from './data/labels';
import { splitList } from './utils/format';

export default function App() {
  const [keywordCount, setCount] = useState<number>(KEYWORD_COUNT.initial);
  // every change of the count goes through the limits (src/config.ts)
  const setKeywordCount = useCallback((next: number | ((prev: number) => number)) => {
    setCount(prev => clampCount(typeof next === 'function' ? next(prev) : next));
  }, []);
  const [balanceMode, setBalanceMode] = useState<BalanceMode>(DEFAULTS.mode);
  const [combinationStyle, setCombinationStyle] = useState<CombinationStyle>(DEFAULTS.style);
  const [outputFormat, setOutputFormat] = useState<OutputFormat>(DEFAULTS.format);
  const [activeTab, setActiveTab] = useState<Tab>(DEFAULTS.tab);
  const [isPoolModalOpen, setIsPoolModalOpen] = useState<boolean>(false);

  const [keywords, setKeywords] = useState<KeywordItem[]>([]);
  const [savedSets, setSavedSets] = useState<SavedKeywordSet[]>([]);
  const [isCopied, setIsCopied] = useState<boolean>(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [place, setPlace] = useState<{ backend: storage.Backend; uid: string | null } | null>(null);
  const [lexicons, setLexicons] = useState<LoadedLexicon[]>([]);
  const [enabledLexicons, setEnabledLexicons] = useState<string[]>([]);

  // Show temporary toast notification (a new one replaces the last, with its own full time)
  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastMessage(null), TIMING_MS.toast);
  }, []);

  const saveFailed = useCallback(() => {
    showToast('계정에 저장하지 못했습니다. 이 브라우저에는 남아 있습니다.');
  }, [showToast]);

  // Where things are kept (the account, or this browser), then what is kept there: the user's own
  // words go into the pool before the first draw, so they can come up in it
  useEffect(() => {
    let live = true;
    void (async () => {
      const where = await storage.connect();
      const [sets, custom, settings, extras] = await Promise.all([
        storage.load<SavedKeywordSet[]>('saved-sets'),
        storage.load<PoolWordItem[]>('custom-words'),
        storage.load<{ lexicons?: string[] }>('settings'),
        loadExtraLexicons(),
      ]);
      if (!live) return;
      // the extra word lists the user left on (or, the first time, those on by default)
      const wanted = Array.isArray(settings?.lexicons)
        ? settings.lexicons
        : EXTRA_LEXICONS.filter(l => l.enabledByDefault).map(l => l.id);
      const enabled = extras.map(l => l.id).filter(id => wanted.includes(id));
      wordPoolManager.initializePool(custom ?? []);
      wordPoolManager.setExtraLexicons(extras, enabled);
      setLexicons(extras);
      setEnabledLexicons(enabled);
      wordPoolManager.onChange = words => {
        void storage.save('custom-words', words).then(ok => { if (!ok) saveFailed(); });
      };
      setSavedSets(Array.isArray(sets) ? sets : []);
      setKeywords(generateKeywords({ count: KEYWORD_COUNT.initial, mode: DEFAULTS.mode, combinationStyle: DEFAULTS.style }));
      setPlace(where);
    })();
    return () => { live = false; };
  }, [saveFailed]);

  // Draw from an extra word list or not; remembered with the rest (lib/storage)
  const handleToggleLexicon = useCallback((id: string) => {
    const next = enabledLexicons.includes(id) ? enabledLexicons.filter(x => x !== id) : [...enabledLexicons, id];
    wordPoolManager.setEnabledExtras(next);
    setEnabledLexicons(next);
    setKeywords(prev => [...prev]); // the counts shown follow the pool
    void storage.save('settings', { lexicons: next }).then(ok => { if (!ok) saveFailed(); });
  }, [enabledLexicons, saveFailed]);

  const persistSets = useCallback((next: SavedKeywordSet[]) => {
    setSavedSets(next);
    void storage.save('saved-sets', next).then(ok => { if (!ok) saveFailed(); });
  }, [saveFailed]);

  // Generate new batch of keywords
  const handleGenerate = useCallback(() => {
    setKeywords(prev =>
      generateKeywords({
        count: keywordCount,
        mode: balanceMode,
        combinationStyle,
        existingKeywords: prev,
      })
    );
    showToast('새로운 키워드 조합이 생성되었습니다.');
  }, [keywordCount, balanceMode, combinationStyle, showToast]);

  // Copy to the clipboard: the keywords in the selected format, or `customText` (a saved set's line)
  const handleCopy = useCallback(async (customText?: string) => {
    const textToCopy = customText ?? formatKeywords(keywords, outputFormat);
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(textToCopy);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = textToCopy;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      if (customText) {
        setCopiedId(customText);
        setTimeout(() => setCopiedId(null), TIMING_MS.copied);
      } else {
        setIsCopied(true);
        setTimeout(() => setIsCopied(false), TIMING_MS.copied);
      }
      showToast(customText ? '키워드가 클립보드에 복사되었습니다.'
                           : `키워드가 ${OUTPUT_FORMATS[outputFormat]} 형식으로 클립보드에 복사되었습니다.`);
    } catch {
      showToast('복사에 실패했습니다.');
    }
  }, [keywords, outputFormat, showToast]);

  // Lock or unlock an individual keyword
  const handleToggleLock = useCallback((id: string) => {
    setKeywords(prev =>
      prev.map(k => (k.id === id ? { ...k, isLocked: !k.isLocked } : k))
    );
  }, []);

  // Replace a single keyword
  const handleRerollSingle = useCallback((keyword: KeywordItem) => {
    setKeywords(prev => {
      const updated = replaceSingleKeyword(keyword, prev, combinationStyle);
      return prev.map(k => (k.id === keyword.id ? updated : k));
    });
  }, [combinationStyle]);

  // Remove a keyword
  const handleRemoveKeyword = useCallback((id: string) => {
    const next = keywords.filter(k => k.id !== id);
    setKeywords(next);
    setKeywordCount(next.length);
  }, [keywords, setKeywordCount]);

  // Add one keyword of the writer's own to this set (locked, so a shuffle keeps it). It is not put
  // into the word pool: that is the pool manager's job, where its part and domain are chosen.
  const handleAddCustomKeyword = useCallback((korean: string, category: CategoryType) => {
    const norm = korean.trim().replace(/\s+/g, ' ');
    if (!norm) return;
    if (keywords.some(k => k.korean === norm)) {
      showToast(`'${norm}'은(는) 이미 목록에 있습니다.`);
      return;
    }
    const newItem: KeywordItem = {
      id: `custom-${crypto.randomUUID()}`,
      korean: norm,
      category,
      categoryKo: CATEGORY_NAMES[category],
      descriptionKo: '작가가 직접 추가한 창작 키워드',
      isLocked: true,
    };
    setKeywords(prev => [...prev, newItem]);
    setKeywordCount(prev => prev + 1);
    showToast(`'${norm}' 키워드가 활성 목록에 추가되었습니다.`);
  }, [keywords, showToast]);

  // Parse manual comma-separated text edit
  const handleManualCommaEdit = useCallback((rawText: string) => {
    const rawTokens = splitList(rawText);

    if (rawTokens.length === 0) return;

    const newItems: KeywordItem[] = rawTokens.map((word, idx) => {
      const existing = keywords.find(k => k.korean === word);
      if (existing) return existing;

      return {
        id: `manual-${crypto.randomUUID()}`,
        korean: word,
        category: 'object',
        categoryKo: '사물·오브제',
        descriptionKo: '쉼표 목록에서 직접 편집한 키워드',
        isLocked: false,
      };
    });

    setKeywords(newItems);
    setKeywordCount(newItems.length);
    showToast(`${newItems.length}개의 키워드로 갱신되었습니다.`);
  }, [keywords, showToast]);

  // Save current set
  const handleSaveCurrentSet = useCallback(() => {
    const title = window.prompt(
      '저장할 키워드 세트의 제목을 입력하세요 (예: 1장 도입부 플롯):',
      `${keywords[0]?.korean || '소설'} 모티프`
    );
    if (!title) return;

    const newSet: SavedKeywordSet = {
      id: `set-${crypto.randomUUID()}`,
      title: title.trim(),
      createdAt: Date.now(),
      keywords: [...keywords],
    };

    persistSets([newSet, ...savedSets]);
    showToast(`'${title}' 세트가 보관함에 저장되었습니다.`);
  }, [keywords, savedSets, persistSets, showToast]);

  // Restore saved set
  const handleRestoreSet = useCallback((set: SavedKeywordSet) => {
    setKeywords(set.keywords);
    setKeywordCount(set.keywords.length);
    setActiveTab('generator');
    showToast(`'${set.title}' 세트를 불러왔습니다.`);
  }, [showToast]);

  // Delete saved set
  const handleDeleteSet = useCallback((id: string) => {
    persistSets(savedSets.filter(s => s.id !== id));
    showToast('보관함에서 삭제되었습니다.');
  }, [savedSets, persistSets, showToast]);

  // Add word from vocabulary explorer
  const handleAddFromDictionary = useCallback((item: KeywordItem) => {
    if (keywords.some(k => k.korean === item.korean)) {
      showToast('이미 키워드 목록에 포함되어 있습니다.');
      return;
    }
    setKeywords(prev => [...prev, item]);
    setKeywordCount(prev => prev + 1);
    showToast(`'${item.korean}' 키워드가 추가되었습니다.`);
  }, [keywords, showToast]);

  // Keyboard shortcut listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger when user is typing in input or textarea
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }

      const action = shortcutFor(e);
      if (action === 'generate') {
        e.preventDefault(); // Space would scroll the page
        handleGenerate();
      } else if (action === 'copy') {
        void handleCopy();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleGenerate, handleCopy]);

  return (
    <div className="min-h-screen bg-[#FBF9F5] text-stone-900 flex flex-col justify-between selection:bg-amber-100 selection:text-amber-900">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-stone-900 text-white text-xs px-4 py-2.5 rounded-md shadow-lg border border-stone-700 animate-fade-in flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
          <span>{toastMessage}</span>
        </div>
      )}

      <div>
        {/* Top Bar Header */}
        <Header
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          onGenerate={handleGenerate}
          onCopy={() => void handleCopy()}
          copyLabel={OUTPUT_FORMATS[outputFormat]}
          isCopied={isCopied}
          savedCount={savedSets.length}
          onOpenPoolManager={() => setIsPoolModalOpen(true)}
        />

        {/* Main Content Container */}
        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6">
          {activeTab === 'generator' && (
            <>
              {/* Editorial Intro Banner */}
              <div className="border-b border-stone-200 pb-4">
                <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2">
                  <div className="flex items-center gap-2 text-xs text-stone-500 uppercase tracking-widest font-mono">
                    <span>CREATIVE WRITING ENGINE</span>
                    <span aria-hidden="true">·</span>
                    <span>KOREAN NOVEL PROMPTS</span>
                  </div>
                  <div className="text-xs text-stone-400">
                    {place?.backend === 'account'
                      ? <>저장: <span className="text-stone-600 font-medium">{place.uid}</span> 계정</>
                      : '저장: 이 브라우저에만'}
                  </div>
                  <div className="text-xs text-stone-400 hidden sm:block">
                    단축키:{' '}
                    {SHORTCUTS.map((s, i) => (
                      <React.Fragment key={s.action}>
                        {i > 0 && ' · '}
                        <kbd className="px-1.5 py-0.5 bg-stone-200/80 rounded text-[11px] font-mono text-stone-700">{s.label}</kbd>{' '}
                        {s.description}
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              </div>

              {/* Central Comma Output Hero Section */}
              <CommaOutputHero
                keywords={keywords}
                outputFormat={outputFormat}
                setOutputFormat={setOutputFormat}
                onCopy={() => void handleCopy()}
                isCopied={isCopied}
                onSaveCurrentSet={handleSaveCurrentSet}
                onRerollAll={handleGenerate}
                onOpenDraft={() => setActiveTab('draft')}
                onManualCommaEdit={handleManualCommaEdit}
              />

              {/* Controls: Count, Genre, Balance */}
              <ControlPanel
                keywordCount={keywordCount}
                setKeywordCount={setKeywordCount}
                balanceMode={balanceMode}
                setBalanceMode={setBalanceMode}
                combinationStyle={combinationStyle}
                setCombinationStyle={setCombinationStyle}
                onGenerate={handleGenerate}
                onAddCustomKeyword={handleAddCustomKeyword}
                onOpenPoolManager={() => setIsPoolModalOpen(true)}
                lexicons={lexicons}
                enabledLexicons={enabledLexicons}
                onToggleLexicon={handleToggleLexicon}
              />

              {/* Grid of Individual Keyword Cards */}
              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs text-stone-500">
                    <span className="font-semibold text-stone-800 uppercase tracking-wider">
                      개별 키워드 카드 ({keywords.length})
                    </span>
                    <span aria-hidden="true">·</span>
                    <span>자물쇠(🔒)를 클릭하면 해당 단어를 고정한 채 다시 뽑을 수 있습니다</span>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3.5">
                  {keywords.map((keyword, index) => (
                    <KeywordCard
                      key={keyword.id}
                      keyword={keyword}
                      index={index}
                      onToggleLock={handleToggleLock}
                      onRerollSingle={handleRerollSingle}
                      onRemove={handleRemoveKeyword}
                    />
                  ))}
                </div>
              </section>
            </>
          )}

          {activeTab === 'draft' && (
            <NovelDraftPad
              keywords={keywords}
              onBackToGenerator={() => setActiveTab('generator')}
              onSaveFailed={saveFailed}
            />
          )}

          {activeTab === 'dictionary' && (
            <VocabularyExplorer
              lexicons={lexicons}
              activeKeywords={keywords}
              onAddKeyword={handleAddFromDictionary}
              onOpenPoolManager={() => setIsPoolModalOpen(true)}
            />
          )}

          {activeTab === 'saved' && (
            <SavedSetsView
              savedSets={savedSets}
              onRestoreSet={handleRestoreSet}
              onDeleteSet={handleDeleteSet}
              onCopyComma={handleCopy}
              copiedId={copiedId}
              onBackToGenerator={() => setActiveTab('generator')}
            />
          )}
        </main>
      </div>

      {/* Word Pool Manager Modal */}
      <WordPoolManagerModal
        isOpen={isPoolModalOpen}
        onClose={() => setIsPoolModalOpen(false)}
        onPoolUpdated={() => setKeywords(prev => [...prev])}
      />

      {/* Quiet Literary Editorial Footer */}
      <footer className="mt-16 border-t border-stone-200 bg-stone-100/50 py-8 text-xs text-stone-500">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-serif-kr font-bold text-stone-800">글타래</span>
            <span aria-hidden="true">·</span>
            <span>소설 창작용 한국어 키워드 생성기</span>
          </div>

          <p className="font-serif-kr italic text-stone-400 text-center sm:text-right">
            &ldquo;하나의 사물과 뜻밖의 성향이 부딪칠 때, 닫혀 있던 첫 문장이 열린다.&rdquo;
          </p>
        </div>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 mt-3">
          <LexiconCredits lexicons={lexicons} className="text-[11px] text-stone-400 text-center sm:text-left" />
        </div>
      </footer>
    </div>
  );
}
