// ── Provider Adapter Registry ──
// Adapters are plain config objects — data, not behavior

import type { ProviderAdapter } from './types.js';

function id<T>(x: T): T { return x; }

function stripStreamOptions(body: Record<string, unknown>): Record<string, unknown> {
  const { stream_options, ...rest } = body as { stream_options?: unknown };
  return rest;
}

const ADAPTERS: Record<string, ProviderAdapter> = {
  'glm-zai': {
    name: 'glm-zai',
    timeout: 300_000,
    stripThinking: false,
    stripCacheControl: false,
    transformRequest: id,
    transformError: (e) => e,
  },
  'ollama-local': {
    name: 'ollama-local',
    timeout: 600_000,
    stripThinking: true,
    stripCacheControl: true,
    transformRequest: stripStreamOptions,
    transformError: (e) => e,
  },
  'openai-gpt': {
    name: 'openai-gpt',
    timeout: 300_000,
    stripThinking: true,
    stripCacheControl: true,
    transformRequest: id,
    transformError: (e) => e,
  },
  'zen': {
    name: 'zen',
    timeout: 300_000,
    stripThinking: false,
    stripCacheControl: false,
    transformRequest: id,
    transformError: (e) => e,
  },
};

const DEFAULT_ADAPTER = 'ollama-local';

export function getAdapter(name: string): ProviderAdapter {
  const adapter = ADAPTERS[name];
  if (!adapter) {
    throw new Error(`Unknown adapter: ${name}. Available: ${Object.keys(ADAPTERS).join(', ')}`);
  }
  return adapter;
}

export function listAdapters(): string[] {
  return Object.keys(ADAPTERS);
}

export { DEFAULT_ADAPTER };
