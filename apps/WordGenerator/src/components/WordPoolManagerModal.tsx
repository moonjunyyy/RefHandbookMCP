import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  Plus,
  AlertCircle,
  CheckCircle2,
  Database,
  Trash2,
  FileSpreadsheet,
  RotateCcw,
} from 'lucide-react';
import { wordPoolManager } from '../utils/wordPoolManager';
import { PoolTab, SemanticDomain, WordPartType } from '../types';
import { DOMAINS, POOL_TABS, WORD_PARTS, keysOf } from '../data/labels';
import { DEFAULTS } from '../config';
import { num, partBreakdown } from '../utils/format';

const selectClass = 'w-full px-3 py-1.5 text-xs border border-edge rounded-control bg-surface focus:outline-none';

/** The part of speech and domain a new word goes under (both forms). */
function PartDomainFields({ part, setPart, domain, setDomain, partLabel, domainLabel }: {
  part: WordPartType; setPart: (p: WordPartType) => void;
  domain: SemanticDomain; setDomain: (d: SemanticDomain) => void;
  partLabel: string; domainLabel: string;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <label className="block text-xs font-semibold text-ink mb-1">{partLabel}</label>
        <select value={part} onChange={e => setPart(e.target.value as WordPartType)} className={selectClass}>
          {keysOf(WORD_PARTS).map(p => (
            <option key={p} value={p}>{WORD_PARTS[p].label} ({WORD_PARTS[p].hint})</option>
          ))}
        </select>
      </div>
      <div>
        <label className="block text-xs font-semibold text-ink mb-1">{domainLabel}</label>
        <select value={domain} onChange={e => setDomain(e.target.value as SemanticDomain)} className={selectClass}>
          {keysOf(DOMAINS).map(d => (
            <option key={d} value={d}>{DOMAINS[d].label} ({DOMAINS[d].hint})</option>
          ))}
        </select>
      </div>
    </div>
  );
}

interface WordPoolManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onPoolUpdated: () => void;
}

export const WordPoolManagerModal: React.FC<WordPoolManagerModalProps> = ({
  isOpen,
  onClose,
  onPoolUpdated,
}) => {
  const [activeTab, setActiveTab] = useState<PoolTab>(keysOf(POOL_TABS)[0]);

  // Single word state
  const [singleText, setSingleText] = useState('');
  const [singlePart, setSinglePart] = useState<WordPartType>(DEFAULTS.newWord.part);
  const [singleDomain, setSingleDomain] = useState<SemanticDomain>(DEFAULTS.newWord.domain);

  // Batch word state
  const [batchText, setBatchText] = useState('');
  const [batchPart, setBatchPart] = useState<WordPartType>(DEFAULTS.newWord.part);
  const [batchDomain, setBatchDomain] = useState<SemanticDomain>(DEFAULTS.newWord.domain);
  const [batchResult, setBatchResult] = useState<{
    addedCount: number;
    duplicateCount: number;
    duplicateWords: string[];
  } | null>(null);

  const sheet = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!isOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const d = sheet.current;
    d?.showModal();
    return () => { d?.close(); if (previous?.isConnected) previous.focus(); };
  }, [isOpen]);
  if (!isOpen) return null;

  const stats = wordPoolManager.getStats();
  const customWords = wordPoolManager.getCustomWords();

  // Real-time duplicate check for single word
  const trimmedSingle = singleText.trim();
  const isDuplicate = trimmedSingle ? wordPoolManager.hasWord(trimmedSingle) : false;

  const handleAddSingle = (e: React.FormEvent) => {
    e.preventDefault();
    if (!trimmedSingle) return;

    const res = wordPoolManager.addWord(trimmedSingle, singlePart, singleDomain);
    if (res.success) {
      setSingleText('');
      onPoolUpdated();
    }
  };

  const handleAddBatch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!batchText.trim()) return;

    const res = wordPoolManager.addBatchWords(batchText, batchPart, batchDomain);
    setBatchResult(res);
    setBatchText('');
    onPoolUpdated();
  };

  const handleRemoveCustom = (id: string) => {
    wordPoolManager.removeCustomWord(id);
    onPoolUpdated();
  };

  const handleReset = () => {
    if (window.confirm('사용자가 추가한 모든 단어를 초기화하고 기본 사전으로 되돌릴까요?')) {
      wordPoolManager.resetToDefaults();
      onPoolUpdated();
    }
  };

  return (
    <dialog ref={sheet} aria-labelledby="pool-title" onCancel={onClose} onKeyDown={e => e.stopPropagation()} className="pool-dialog bg-transparent p-4 max-h-[95dvh] overflow-y-auto">
      <div className="bg-surface border border-edge rounded-panel shadow-2xl max-w-2xl w-full p-6 space-y-6 relative my-8">
        {/* Header */}
        <div className="flex items-start justify-between pb-4 border-b border-edge">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-widest text-accent font-semibold font-mono">
              <Database className="w-3.5 h-3.5" />
              <span>Lexicon Pool &amp; Deduplication Engine</span>
            </div>
            <h2 id="pool-title" className="font-serif text-xl sm:text-2xl font-bold text-ink mt-1">
              어휘 풀 관리 및 중복 방지 등록기
            </h2>
            <p className="text-xs text-muted mt-0.5">
              총 {num(stats.total)}개 등록됨 ({partBreakdown(stats)} · 사용자 추가 {num(stats.customCount)})
            </p>
          </div>

          <button
            onClick={onClose}
            aria-label="닫기"
            className="p-1.5 text-muted hover:text-ink hover:bg-soft rounded-control cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab switchers */}
        <div className="flex items-center gap-1 p-1 bg-soft rounded-panel text-xs font-medium">
          {keysOf(POOL_TABS).map(tab => (
            <button
              key={tab}
              onClick={() => {
                setActiveTab(tab);
                setBatchResult(null);
              }}
              className={`flex-1 py-1.5 rounded-control transition-shadow cursor-pointer ${
                activeTab === tab
                  ? 'bg-surface text-ink shadow-xs font-bold'
                  : 'text-muted hover:text-ink'
              }`}
            >
              {POOL_TABS[tab]}{tab === 'list' && ` (${num(customWords.length)})`}
            </button>
          ))}
        </div>

        {/* Tab 1: Single Word */}
        {activeTab === 'single' && (
          <form onSubmit={handleAddSingle} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-ink mb-1">
                등록할 어휘
              </label>
              <input
                type="text"
                value={singleText}
                onChange={e => setSingleText(e.target.value)}
                placeholder="예: 비취색의, 녹아내린 촛농, 파헤치다"
                className="w-full px-3.5 py-2 text-sm border border-edge rounded-control focus:outline-none focus:ring-2 focus:ring-accent font-serif"
                autoFocus
              />

              {/* Real-time duplicate status feedback */}
              {trimmedSingle && (
                <div className="mt-2 text-xs flex items-center gap-1.5">
                  {isDuplicate ? (
                    <span className="text-danger font-medium flex items-center gap-1">
                      <AlertCircle className="w-3.5 h-3.5" />
                      이미 어휘 풀에 존재하는 중복 단어입니다. (중복 방지됨)
                    </span>
                  ) : (
                    <span className="text-success font-medium flex items-center gap-1">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      등록 가능한 새로운 고유 어휘입니다!
                    </span>
                  )}
                </div>
              )}
            </div>

            <PartDomainFields part={singlePart} setPart={setSinglePart} domain={singleDomain}
                              setDomain={setSingleDomain} partLabel="문법 품사 (Part)" domainLabel="의미 영역 (Domain)" />

            <div className="pt-2 flex justify-end">
              <button
                type="submit"
                disabled={!trimmedSingle || isDuplicate}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-on-action bg-action hover:bg-action disabled:bg-soft disabled:text-muted rounded-control cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>풀에 추가하기</span>
              </button>
            </div>
          </form>
        )}

        {/* Tab 2: Batch Add */}
        {activeTab === 'batch' && (
          <form onSubmit={handleAddBatch} className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-semibold text-ink">
                  단어 대량 붙여넣기 (쉼표 또는 줄바꿈 구분)
                </label>
                <span className="text-[11px] text-muted">
                  자동으로 중복을 검사하고 고유한 단어만 등록합니다.
                </span>
              </div>
              <textarea
                value={batchText}
                onChange={e => setBatchText(e.target.value)}
                placeholder="예: 비취색의, 시리도록 푸른, 칠흑 같은, 달빛에 젖은"
                className="w-full h-32 p-3 text-xs border border-edge rounded-control focus:outline-none focus:ring-2 focus:ring-accent font-serif resize-none"
              />
            </div>

            <PartDomainFields part={batchPart} setPart={setBatchPart} domain={batchDomain}
                              setDomain={setBatchDomain} partLabel="공통 품사" domainLabel="공통 의미 영역" />

            {/* Batch execution report */}
            {batchResult && (
              <div className="p-3 bg-soft border border-edge rounded-control text-xs space-y-1">
                <div className="font-semibold text-ink flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-success" />
                  <span>
                    총 {batchResult.addedCount}개 어휘 성공적으로 등록 완료!
                  </span>
                </div>
                {batchResult.duplicateCount > 0 && (
                  <div className="text-accent text-[11px]">
                    중복으로 제외된 단어 ({batchResult.duplicateCount}개):{' '}
                    {batchResult.duplicateWords.slice(0, 5).join(', ')}
                    {batchResult.duplicateWords.length > 5 && ' 외'}
                  </div>
                )}
              </div>
            )}

            <div className="pt-2 flex justify-end">
              <button
                type="submit"
                disabled={!batchText.trim()}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-on-action bg-action hover:bg-action disabled:bg-soft disabled:text-muted rounded-control cursor-pointer"
              >
                <FileSpreadsheet className="w-3.5 h-3.5" />
                <span>중복 검사 및 일괄 추가</span>
              </button>
            </div>
          </form>
        )}

        {/* Tab 3: Custom Word List */}
        {activeTab === 'list' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between text-xs text-muted">
              <span>작가가 직접 등록한 단어 목록</span>
              {customWords.length > 0 && (
                <button
                  onClick={handleReset}
                  className="text-danger hover:text-danger flex items-center gap-1 cursor-pointer"
                >
                  <RotateCcw className="w-3 h-3" />
                  <span>모두 초기화</span>
                </button>
              )}
            </div>

            {customWords.length === 0 ? (
              <div className="text-center py-10 text-muted text-xs font-serif">
                아직 직접 추가한 사용자 단어가 없습니다.
              </div>
            ) : (
              <div className="max-h-60 overflow-y-auto divide-y divide-edge border border-edge rounded-control">
                {customWords.map(word => (
                  <div
                    key={word.id}
                    className="p-2.5 flex items-center justify-between text-xs hover:bg-soft"
                  >
                    <div>
                      <span className="font-serif font-bold text-ink mr-2">
                        {word.text}
                      </span>
                      <span className="text-[11px] text-muted font-mono">
                        ({WORD_PARTS[word.part]?.label ?? word.part} / {DOMAINS[word.domain]?.label ?? word.domain})
                      </span>
                    </div>
                    <button
                      onClick={() => handleRemoveCustom(word.id)}
                      className="text-muted hover:text-danger p-1 cursor-pointer"
                      title="삭제"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </dialog>
  );
};
