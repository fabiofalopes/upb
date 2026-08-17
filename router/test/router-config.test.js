import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const ENV_KEYS = ['UPB_CONFIG', 'UPB_PROVIDER', 'UPB_BASE_URL'];

test('pricing, cooldown_seconds, kind and headers parse from a YAML routes snippet', async (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'upb-cfg-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));

  const cfgPath = join(dir, 'routes.yaml');
  writeFileSync(cfgPath, `version: 1
defaults:
  port: 8999
  retries: 1
providers:
  alibaba:
    kind: upb
    enabled: true
    base_url: https://example.com/v1
    timeout: 300000
    cooldown_seconds: 60
    headers:
      User-Agent: mistral-client-python/Mistral-Vibe/2.21.0
    models:
      qwen3.6-flash:
        port: 8702
        pricing:
          input_per_1m: 0.26
          output_per_1m: 1.56
      glm-5.2:
        port: 8706
        pricing:
          input_per_1m: 1.46
          output_per_1m: 4.58
active_provider: alibaba
`);

  const saved = {};
  for (const k of ENV_KEYS) saved[k] = process.env[k];
  t.after(() => {
    for (const k of ENV_KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });
  process.env.UPB_CONFIG = cfgPath;
  delete process.env.UPB_PROVIDER;
  delete process.env.UPB_BASE_URL;

  const { loadRouterConfig, resetRouterConfig } = await import('../dist/middleware/router-config.js');
  resetRouterConfig();
  t.after(() => resetRouterConfig());

  const cfg = loadRouterConfig();
  const flash = cfg.providers.alibaba.models['qwen3.6-flash'];
  assert.equal(flash.pricing.input_per_1m, 0.26);
  assert.equal(flash.pricing.output_per_1m, 1.56);
  const glm = cfg.providers.alibaba.models['glm-5.2'];
  assert.equal(glm.pricing.input_per_1m, 1.46);
  assert.equal(glm.pricing.output_per_1m, 4.58);
  assert.equal(cfg.providers.alibaba.cooldown_seconds, 60);
  assert.equal(cfg.providers.alibaba.kind, 'upb');
  assert.equal(cfg.providers.alibaba.enabled, true);
  assert.equal(cfg.providers.alibaba.headers['User-Agent'], 'mistral-client-python/Mistral-Vibe/2.21.0');
});

test('env-var mode leaves pricing and cooldown undefined', async (t) => {
  const saved = {};
  for (const k of ENV_KEYS) saved[k] = process.env[k];
  t.after(() => {
    for (const k of ENV_KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });
  delete process.env.UPB_CONFIG;
  process.env.UPB_PROVIDER = 'ollama-local';
  process.env.UPB_BASE_URL = 'http://localhost:11434/v1';

  const { loadRouterConfig, resetRouterConfig } = await import('../dist/middleware/router-config.js');
  resetRouterConfig();
  t.after(() => resetRouterConfig());

  const cfg = loadRouterConfig();
  const provider = cfg.providers['ollama-local'];
  assert.equal(provider.models, undefined);
  assert.equal(provider.cooldown_seconds, undefined);
});
