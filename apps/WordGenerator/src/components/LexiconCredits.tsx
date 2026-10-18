import React from 'react';
import { LoadedLexicon } from '../lib/lexicons';

/** Where the extra words come from, with their licence (the licences require saying so). */
export const LexiconCredits: React.FC<{ lexicons: LoadedLexicon[]; className?: string }> = ({ lexicons, className }) => {
  if (lexicons.length === 0) return null;
  return (
    <p className={className}>
      {lexicons.map((l, i) => (
        <React.Fragment key={l.id}>
          {i > 0 && ' · '}
          어휘 일부 출처: {l.credit.publisher}{' '}
          <a href={l.credit.url} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-stone-700">
            「{l.credit.source}」
          </a>
          {l.credit.dumpCreated && ` (${l.credit.dumpCreated.slice(0, 10).replaceAll('/', '-')} 판)`},{' '}
          <a href={l.credit.licenseUrl} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-stone-700">
            {l.credit.license}
          </a>
        </React.Fragment>
      ))}
    </p>
  );
};
