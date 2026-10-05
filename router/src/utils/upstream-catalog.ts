// ── Upstream catalog mirror ──
// The invariant: a provider's valid model list IS its live /models endpoint.
// The proxy's own GET /v1/models mirrors that list (plus the wire names it
// maps) instead of serving only the static config. On fetch failure we serve
// the last good result (stale-while-error); never fail the listing outright.

import type { ProviderDefinition } from '../middleware/router-config.js';

export interface UpstreamEntry {
  id: string;
  owned_by?: string;
}

interface CacheRow {
  fetchedAt: number;
  entries: UpstreamEntry[];
}

const cache = new Map<string, CacheRow>();

// Test hook: drop all memoized catalogs.
export function resetUpstreamCatalogCache(): void {
  cache.clear();
}

export function modelsUrlFor(def: ProviderDefinition): string {
  const base = def.models_url || def.base_url;
  return base.replace(/\/+$/, '') + '/models';
}

function authHeaders(def: ProviderDefinition): Record<string, string> {
  const h: Record<string, string> = { 'User-Agent': 'upb-router/1.0' };
  if (def.api_key) h['Authorization'] = `Bearer ${def.api_key}`;
  for (const [k, v] of Object.entries(def.headers || {})) {
    if (k.toLowerCase() === 'authorization' || k.toLowerCase() === 'x-api-key') continue;
    h[k] = v;
  }
  return h;
}

/**
 * Live model ids for a provider, per the mirror policy:
 *  - ttlS <= 0  → always fetch fresh (tailnet-local lanes)
 *  - ttlS > 0   → reuse cache until it expires
 *  - fetch fails → last good cache of any age, else null (caller keeps static)
 */
export async function upstreamModels(
  key: string,
  def: ProviderDefinition,
  ttlS: number,
): Promise<UpstreamEntry[] | null> {
  const hit = cache.get(key);
  if (hit && ttlS > 0 && Date.now() - hit.fetchedAt < ttlS * 1000) {
    return hit.entries;
  }
  try {
    const res = await fetch(modelsUrlFor(def), {
      headers: authHeaders(def),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json() as { data?: Array<{ id?: string; owned_by?: string }> };
    const entries: UpstreamEntry[] = (body.data || [])
      .filter((m) => typeof m.id === 'string' && m.id)
      .map((m) => ({ id: m.id as string, owned_by: m.owned_by }));
    if (!entries.length) throw new Error('empty catalog');
    cache.set(key, { fetchedAt: Date.now(), entries });
    return entries;
  } catch (err) {
    console.warn(`[catalog] upstream fetch failed for ${key}: ${(err as Error).message}`);
    return hit ? hit.entries : null; // stale-while-error
  }
}

/** Should this provider's /v1/models be mirrored from upstream? */
export function mirrorEnabled(def: ProviderDefinition): boolean {
  return def.catalog !== 'static'; // live is the default, same rule as the CLI
}
