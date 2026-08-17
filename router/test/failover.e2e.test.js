// E2E: boot the router against two local mock upstreams — provider A always
// answers 429, provider B answers 200 — and assert the cooldown failover.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
}

function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

test('429 quarantines provider A; the next request fails over to provider B', async (t) => {
  const hits = { 'mock-a': 0, 'mock-b': 0 };

  const mkMock = (name) => http.createServer((req, res) => {
    let raw = '';
    req.on('data', (c) => { raw += c; });
    req.on('end', () => {
      hits[name]++;
      if (name === 'mock-a') {
        res.writeHead(429, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: { message: 'weekly quota exhausted', type: 'rate_limit_error' } }));
        return;
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        id: 'chatcmpl-1', object: 'chat.completion', model: 'test-model',
        choices: [{ index: 0, message: { role: 'assistant', content: 'served-by-b' }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 3, completion_tokens: 5, total_tokens: 8 },
      }));
    });
  });

  const mockA = mkMock('mock-a');
  const mockB = mkMock('mock-b');
  await listen(mockA);
  await listen(mockB);
  t.after(() => Promise.all([close(mockA), close(mockB)]));

  const dir = mkdtempSync(join(tmpdir(), 'upb-failover-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));

  // pick a free port for the router (bind, read, release — tiny race, fine here)
  const probe = http.createServer();
  await listen(probe);
  const routerPort = probe.address().port;
  await close(probe);

  writeFileSync(join(dir, 'routes.yaml'), `version: 1
defaults:
  port: ${routerPort}
  retries: 0
providers:
  mock-a:
    kind: upb
    enabled: true
    base_url: http://127.0.0.1:${mockA.address().port}/v1
    timeout: 5000
    models:
      test-model: {}
  mock-b:
    kind: upb
    enabled: true
    base_url: http://127.0.0.1:${mockB.address().port}/v1
    timeout: 5000
    models:
      test-model: {}
active_provider: mock-a
`);

  const ENV_KEYS = ['UPB_CONFIG', 'UPB_PROVIDER', 'UPB_BASE_URL', 'USAGE_LOG'];
  const saved = {};
  for (const k of ENV_KEYS) saved[k] = process.env[k];
  t.after(() => {
    for (const k of ENV_KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });
  process.env.UPB_CONFIG = join(dir, 'routes.yaml');
  process.env.USAGE_LOG = join(dir, 'usage.jsonl');
  delete process.env.UPB_PROVIDER;
  delete process.env.UPB_BASE_URL;

  const { server } = await import('../dist/index.js');
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const base = `http://127.0.0.1:${routerPort}`;
  let up = false;
  for (let i = 0; i < 50 && !up; i++) {
    try {
      const r = await fetch(`${base}/health`);
      if (r.ok) up = true;
    } catch { /* not listening yet */ }
    if (!up) await new Promise((r) => setTimeout(r, 100));
  }
  assert.equal(up, true, 'router became healthy');

  // Request 1: routes to mock-a (active provider), eats the 429, gets marked
  const first = await fetch(`${base}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'test-model', messages: [{ role: 'user', content: 'hi' }] }),
  });
  assert.equal(first.status, 429);
  assert.equal(hits['mock-a'], 1);

  // Request 2: mock-a is quarantined → fails over to mock-b
  const second = await fetch(`${base}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'test-model', messages: [{ role: 'user', content: 'hi again' }] }),
  });
  assert.equal(second.status, 200);
  const secondBody = await second.json();
  assert.equal(secondBody.choices[0].message.content, 'served-by-b');
  assert.equal(hits['mock-a'], 1, 'no further traffic to quarantined provider');
  assert.equal(hits['mock-b'], 1);

  // /health exposes the active cooldown
  const health = await (await fetch(`${base}/health`)).json();
  assert.equal(typeof health.cooldowns['mock-a'], 'number');
  assert.ok(health.cooldowns['mock-a'] > 0);
});
