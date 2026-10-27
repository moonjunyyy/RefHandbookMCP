// The services' JSON APIs (docs/site.md "APIs and pages"): every write carries the header the
// backends require of the site's own pages; an error answer is {"error": {code, message}}.

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any

async function call(method: string, url: string, body?: unknown): Promise<Json> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') headers['X-Requested-With'] = 'fetch';
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let r: Response;
  try {
    r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                           credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, 'network', '서버에 닿지 않습니다. 잠시 뒤 다시 시도하세요.');
  }
  const text = await r.text();
  let data: Json = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* not JSON: an error page on the way */ }
  if (r.ok) return data;
  if (r.status === 401) {
    location.assign(`/auth/login?next=${encodeURIComponent(location.pathname + location.search)}`);
  }
  const e = data?.error;
  throw new ApiError(r.status, e?.code ?? 'http', e?.message ?? `요청이 실패했습니다 (${r.status})`);
}

/** One service's API at its prefix: api('/agents/api/v1').get('/runs'). */
export function api(prefix: string) {
  return {
    get: (path: string) => call('GET', prefix + path),
    post: (path: string, body: unknown = {}) => call('POST', prefix + path, body),
    put: (path: string, body: unknown) => call('PUT', prefix + path, body),
    patch: (path: string, body: unknown) => call('PATCH', prefix + path, body),
    del: (path: string) => call('DELETE', prefix + path),
  };
}

export const site = api('/auth/api/v1');
export const agents = api('/agents/api/v1');
/** The account portal's API: under the portal's root, which the site's frame says (/account). */
export const account = () => api(`${frame.portal}/api/v1`);

export interface Card { id: string; title: string; description: string; code: string; icon: string; href: string;
                      links: { label: string; href: string }[] }
export interface Frame { uid: string | null; title: string; signin: string; portal: string; cards: Card[];
                         menu: { label: string; href: string }[] }
export const frame: Frame = { uid: null, title: '', signin: '/auth', portal: '/account', cards: [], menu: [] };
