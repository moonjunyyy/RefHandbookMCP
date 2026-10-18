/**
 * Where 글타래 keeps what the user saves (keyword sets, the draft, their own words).
 *
 * Served by the site (/apps/<id>/, behind its sign-in), it is the user's account: the site's storage
 * API next to the app (`api/store/<key>`), so the same sets and draft are there on any device.
 * Anywhere else (npm run dev, a file), it is this browser's localStorage. localStorage is also kept
 * as a copy in account mode, so a failed save is not a lost one; and the first time an account is
 * empty, what this browser already had is carried over to it.
 */

import { TIMING_MS } from '../config';

export type Backend = 'account' | 'browser';

export type StoreKey = 'saved-sets' | 'draft' | 'custom-words' | 'settings';

/** The localStorage names of the version before accounts, kept so nothing saved there is lost. */
const LOCAL_NAMES: Record<StoreKey, string> = {
  'saved-sets': 'geultarae_saved_sets',
  draft: 'geultarae_draft',
  'custom-words': 'geultarae_custom_word_pool_v2',
  settings: 'geultarae_settings',
};

let backend: Backend = 'browser';
let uid: string | null = null;

const api = (path: string) => new URL(`api/${path}`, document.baseURI).toString();

function readLocal<T>(key: StoreKey): T | null {
  try {
    const raw = localStorage.getItem(LOCAL_NAMES[key]);
    return raw === null ? null : (JSON.parse(raw) as T);
  } catch {
    return null;
  }
}

function writeLocal(key: StoreKey, value: unknown): void {
  try {
    localStorage.setItem(LOCAL_NAMES[key], JSON.stringify(value));
  } catch {
    // full or disabled: the account copy (if any) still holds it
  }
}

/** Find out once where things are kept. */
export async function connect(): Promise<{ backend: Backend; uid: string | null }> {
  try {
    const r = await fetch(api('me'), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    const body = r.ok && r.headers.get('content-type')?.includes('application/json') ? await r.json() : null;
    if (body && typeof body.uid === 'string') {
      backend = 'account';
      uid = body.uid;
    }
  } catch {
    // no site around: this browser it is
  }
  return { backend, uid };
}

export function where(): { backend: Backend; uid: string | null } {
  return { backend, uid };
}

export async function load<T>(key: StoreKey): Promise<T | null> {
  const local = readLocal<T>(key);
  if (backend === 'browser') return local;
  try {
    const r = await fetch(api(`store/${key}`), { credentials: 'same-origin' });
    if (r.ok) {
      const value = (await r.json()) as T;
      writeLocal(key, value);
      return value;
    }
    if (r.status === 404 && local !== null) {
      await save(key, local); // the first visit with an account: bring this browser's copy along
      return local;
    }
  } catch {
    // offline: the local copy is the best there is
  }
  return local;
}

/** Saves; resolves to false if the account could not be reached (the browser copy is kept anyway). */
export async function save(key: StoreKey, value: unknown): Promise<boolean> {
  writeLocal(key, value);
  if (backend === 'browser') return true;
  try {
    const r = await fetch(api(`store/${key}`), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(value),
    });
    return r.ok;
  } catch {
    return false;
  }
}

const timers = new Map<StoreKey, ReturnType<typeof setTimeout>>();

/** For values that change on every keystroke (the draft): one save after `ms` of quiet. */
export function saveSoon(key: StoreKey, value: unknown, ms: number = TIMING_MS.draftSave, done?: (ok: boolean) => void): void {
  writeLocal(key, value);
  clearTimeout(timers.get(key));
  timers.set(key, setTimeout(() => {
    timers.delete(key);
    void save(key, value).then(ok => done?.(ok));
  }, ms));
}
