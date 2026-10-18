import { beforeEach, describe, expect, it, vi } from 'vitest';

/** A browser with localStorage, served at /apps/wordgen/, and a site whose storage API is `server`. */
function browser(server: Map<string, string> | null) {
  const local = new Map<string, string>();
  vi.stubGlobal('document', { baseURI: 'https://www.m00nny.kr/apps/wordgen/' });
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => local.get(k) ?? null,
    setItem: (k: string, v: string) => void local.set(k, v),
    removeItem: (k: string) => void local.delete(k),
  });
  const calls: string[] = [];
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    calls.push(`${method} ${url}`);
    const json = (status: number, body?: unknown) =>
      new Response(body === undefined ? null : JSON.stringify(body),
                   { status, headers: { 'content-type': 'application/json' } });
    if (server === null) return new Response('<html>not found</html>', { status: 404 });
    const path = new URL(url).pathname;
    if (path === '/apps/wordgen/api/me') return json(200, { uid: 'alice' });
    const key = path.replace('/apps/wordgen/api/store/', '');
    if (method === 'PUT') { server.set(key, String(init.body)); return new Response(null, { status: 204 }); }
    return server.has(key) ? json(200, JSON.parse(server.get(key)!)) : json(404, { error: 'no such key' });
  });
  return { local, calls };
}

beforeEach(() => {
  vi.resetModules(); // each test connects afresh
  vi.unstubAllGlobals();
});

describe('storage', () => {
  it('keeps things in the account when the site is there', async () => {
    const server = new Map<string, string>();
    const { local } = browser(server);
    const storage = await import('./storage');
    expect(await storage.connect()).toEqual({ backend: 'account', uid: 'alice' });
    expect(await storage.save('saved-sets', [{ title: '1장' }])).toBe(true);
    expect(JSON.parse(server.get('saved-sets')!)).toEqual([{ title: '1장' }]);
    expect(local.get('geultarae_saved_sets')).toBe('[{"title":"1장"}]'); // and a copy here
  });

  it("brings this browser's old data to an empty account, once", async () => {
    const server = new Map<string, string>();
    const { local, calls } = browser(server);
    local.set('geultarae_draft', JSON.stringify({ title: '예전 초안', content: '...' }));
    const storage = await import('./storage');
    await storage.connect();
    expect(await storage.load('draft')).toEqual({ title: '예전 초안', content: '...' });
    expect(JSON.parse(server.get('draft')!).title).toBe('예전 초안');
    server.set('draft', JSON.stringify({ title: '다른 기기에서 쓴 초안' }));
    expect(await storage.load('draft')).toEqual({ title: '다른 기기에서 쓴 초안' }); // the account wins after
    expect(calls.filter(c => c.startsWith('PUT'))).toHaveLength(1);
  });

  it('is this browser alone without the site (npm run dev)', async () => {
    const { local } = browser(null);
    const storage = await import('./storage');
    expect(await storage.connect()).toEqual({ backend: 'browser', uid: null });
    await storage.save('custom-words', [{ text: '은하' }]);
    expect(await storage.load('custom-words')).toEqual([{ text: '은하' }]);
    expect(local.has('geultarae_custom_word_pool_v2')).toBe(true);
  });
});
