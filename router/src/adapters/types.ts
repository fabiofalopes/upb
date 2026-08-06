// ── Provider Adapter Interface ──
// Each adapter customizes behavior for a specific LLM provider

export interface ProviderAdapter {
  name: string;

  // Transform the request body before sending to provider
  transformRequest(body: Record<string, unknown>): Record<string, unknown>;

  // Transform the provider's response/error before translation
  transformError(error: Record<string, unknown>): Record<string, unknown>;

  // Provider-specific timeout (ms)
  timeout: number;

  // Whether to strip thinking blocks from requests
  stripThinking: boolean;

  // Whether to strip cache_control blocks
  stripCacheControl: boolean;

  // Extra headers to add to provider requests
  extraHeaders?: Record<string, string>;
}
