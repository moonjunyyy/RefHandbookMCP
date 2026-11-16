// English, by part of the site (each file: { korean: english }), merged.

import { ACCOUNT } from './account';
import { AGENTS } from './agents';
import { BOARD } from './board';
import { GRAPH } from './graph';
import { PROJECTS } from './projects';
import { SITE } from './site';

export const EN: Record<string, string> = { ...SITE, ...ACCOUNT, ...AGENTS, ...PROJECTS, ...BOARD, ...GRAPH };
