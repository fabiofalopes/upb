// ── Universal Provider Router Config ──
// YAML-based multi-provider configuration with model-prefix routing

import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import YAML from 'yaml';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export interface ProviderDefinition {
  type: 'openai_compatible';
  base_url: string;
  api_key?: string;
  model_map?: Record<string, string>;
  model_prefix?: string;
  timeout: number;
  strip_thinking?: boolean;
  strip_cache_control?: boolean;
  extra_headers?: Record<string, string>;
  icon?: string;
}

export interface RouterConfig {
  version: string;
  defaults: {
    timeout: number;
    retries: number;
    strip_betas: boolean;
    thinking_mode: 'strip' | 'passthrough' | 'force_enable';
    local_secret: string;
    port: number;
  };
  providers: Record<string, ProviderDefinition>;
  active_provider: string;
}

const DEFAULT_CONFIG: RouterConfig = {
  version: '1',
  defaults: {
    timeout: 300_000,
    retries: 3,
    strip_betas: true,
    thinking_mode: 'passthrough',
    local_secret: 'claude-universal-local',
    port: 8443,
  },
  providers: {},
  active_provider: 'litellm',
};

let cachedConfig: RouterConfig | null = null;
let configPath: string | null = null;

export function setConfigPath(cp: string): void {
  configPath = cp;
  cachedConfig = null;
}

export function loadRouterConfig(): RouterConfig {
  if (cachedConfig) return cachedConfig;

  // Env-var mode takes priority: launchers (upb) and the systemd service set
  // UPB_* to pin a single provider+model per proxy instance. Only when no
  // UPB_* override is present do we fall through to YAML discovery.
  if (process.env.UPB_PROVIDER || process.env.UPB_BASE_URL) {
    console.log(`[config] Using env-var config (UPB_PROVIDER=${process.env.UPB_PROVIDER || 'unset'})`);
    cachedConfig = buildFromEnv();
    return cachedConfig;
  }

  // Try config path from env, then default locations
  const paths = [
    configPath,
    process.env.UPB_CONFIG,
    path.join(os.homedir(), '.config', 'universal-router', 'providers.yaml'),
    path.join(process.cwd(), 'providers.yaml'),
    path.join(__dirname, '..', '..', 'providers.yaml'),
  ];

  for (const p of paths) {
    if (!p) continue;
    if (fs.existsSync(p)) {
      try {
        const raw = fs.readFileSync(p, 'utf-8');
        // Resolve ${ENV_VAR:-default} placeholders
        const resolved = raw.replace(/\$\{(.+?)(?::-(.*?))?\}/g, (_m: string, env: string, fallback: string) => {
          return process.env[env] || fallback || '';
        });
        const parsed = YAML.parse(resolved) as Partial<RouterConfig>;
        cachedConfig = mergeWithDefaults(parsed, p);
        console.log(`[config] Loaded router config from ${p} (${Object.keys(cachedConfig.providers).length} providers)`);
        return cachedConfig!;
      } catch (err) {
        console.error(`[config] Error loading ${p}:`, (err as Error).message);
      }
    }
  }

  console.warn('[config] No YAML config found, using env-var-only mode');
  cachedConfig = buildFromEnv();
  return cachedConfig;
}

export function resetRouterConfig(): void {
  cachedConfig = null;
}

function mergeWithDefaults(parsed: Partial<RouterConfig>, _sourcePath: string): RouterConfig {
  return {
    version: String(parsed.version || DEFAULT_CONFIG.version),
    defaults: { ...DEFAULT_CONFIG.defaults, ...(parsed.defaults || {}) },
    providers: (parsed.providers || {}) as Record<string, ProviderDefinition>,
    active_provider: parsed.active_provider || DEFAULT_CONFIG.active_provider,
  };
}

// ── Fallback: env-var config (backward compatible) ──

function buildFromEnv(): RouterConfig {
  const adapter = process.env.UPB_PROVIDER || 'ollama-local';

  const provider: ProviderDefinition = {
    type: 'openai_compatible',
    base_url: process.env.UPB_BASE_URL || 'http://localhost:11434/v1',
    api_key: process.env.UPB_API_KEY || (adapter === 'ollama-local' ? 'ollama' : ''),
    timeout: parseInt(process.env.UPB_TIMEOUT || '300000', 10),
    strip_thinking: adapter === 'ollama-local' || adapter === 'openai-gpt',
    strip_cache_control: adapter === 'ollama-local' || adapter === 'openai-gpt',
  };

  const modelMapStr = process.env.UPB_MODEL_MAP;
  if (modelMapStr) {
    try {
      provider.model_map = JSON.parse(modelMapStr);
    } catch { /* ignore */ }
  }

  return {
    version: '1',
    defaults: {
      ...DEFAULT_CONFIG.defaults,
      port: parseInt(process.env.UPB_PORT || process.env.PORT || '8443', 10),
    },
    providers: { [adapter]: provider },
    active_provider: adapter,
  };
}
