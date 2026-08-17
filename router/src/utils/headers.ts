// ── Provider Header Merge ──
// Merges per-provider custom headers (routes.yaml `providers.<name>.headers`)
// into an outgoing header set. Applied AFTER auth header injection so provider
// config can never overwrite credentials.

const PROTECTED_HEADERS = new Set(['authorization', 'x-api-key']);

export function mergeProviderHeaders(target: Record<string, string>, extra: Record<string, string>): Record<string, string> {
  for (const [name, value] of Object.entries(extra)) {
    if (PROTECTED_HEADERS.has(name.toLowerCase())) continue;
    target[name] = value;
  }
  return target;
}
