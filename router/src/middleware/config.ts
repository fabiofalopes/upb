// ── Provider Config Middleware ──
// Loads provider configuration from environment variables

export interface ProviderConfig {
  baseUrl: string;
  apiKey: string;
  modelMap: Record<string, string>;
  adapter: string; // adapter name (glm-zai, ollama-local, openai-gpt)
}

let cachedConfig: ProviderConfig | null = null;

export function loadConfig(): ProviderConfig {
  if (cachedConfig) return cachedConfig;

  const adapter = process.env.UPB_PROVIDER || 'ollama-local';

  let baseUrl = process.env.UPB_BASE_URL || '';
  const defaultKey = adapter === 'ollama-local' ? 'ollama' : '';
  let apiKey = process.env.UPB_API_KEY || defaultKey;

  if (!apiKey && adapter !== 'ollama-local' && adapter !== 'zen') {
    console.warn(`[config] WARNING: No API key set for adapter '${adapter}'. Set UPB_API_KEY.`);
  }

  // Apply adapter defaults when base URL is not explicitly set
  if (!process.env.UPB_BASE_URL) {
    baseUrl = getAdapterDefaults(adapter).baseUrl;
  }

  let modelMap: Record<string, string> | null = null;
  const modelMapStr = process.env.UPB_MODEL_MAP;
  if (modelMapStr) {
    try {
      modelMap = JSON.parse(modelMapStr);
    } catch {
      console.error('[config] Bad UPB_MODEL_MAP JSON, falling back to adapter defaults');
    }
  }
  modelMap ??= getAdapterDefaults(adapter).modelMap;

  cachedConfig = { baseUrl, apiKey, modelMap, adapter };
  return cachedConfig;
}

export function resetConfig(): void {
  cachedConfig = null;
}

interface AdapterDefaults {
  baseUrl: string;
  modelMap: Record<string, string>;
}

function getAdapterDefaults(adapterName: string): AdapterDefaults {
  const defaults: Record<string, AdapterDefaults> = {
    'glm-zai': {
      baseUrl: 'https://api.z.ai/api/coding/paas/v4',
      modelMap: {
        'claude-opus-4-6': 'glm-4.7',
        'claude-sonnet-4-6': 'glm-4.7',
        'claude-haiku-4-5': 'glm-4.5-air',
      },
    },
    'ollama-local': {
      baseUrl: 'http://localhost:11434/v1',
      modelMap: {
        'claude-opus-4-6': 'qwen2.5-coder:32b',
        'claude-sonnet-4-6': 'qwen2.5-coder:32b',
        'claude-haiku-4-5': 'llama3.2:3b',
      },
    },
    'openai-gpt': {
      baseUrl: 'https://api.openai.com/v1',
      modelMap: {
        'claude-opus-4-6': 'o3',
        'claude-sonnet-4-6': 'gpt-4o',
        'claude-haiku-4-5': 'gpt-4o-mini',
      },
    },
    'zen': {
      baseUrl: 'https://opencode.ai/zen/v1',
      modelMap: {
        'claude-opus-4-6': 'big-pickle',
        'claude-sonnet-4-6': 'deepseek-v4-flash-free',
        'claude-haiku-4-5': 'north-mini-code-free',
      },
    },
  };

  return defaults[adapterName] || defaults['openai-gpt']!;
}
