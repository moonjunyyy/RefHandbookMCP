// English, by part of the site (each file: { korean: english }), merged.

import { ACCOUNT } from './account';
import { AGENTS } from './agents';
import { SITE } from './site';

export const EN: Record<string, string> = { ...SITE, ...ACCOUNT, ...AGENTS };
