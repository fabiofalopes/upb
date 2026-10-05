// E2E: the proxy's GET /v1/models mirrors the upstream live catalog —
// including ids it never had in config — and reflects retirement at ttl=0.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
}
function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

test('GET /v1/models mirrors upstream; retired ids disappear at ttl=0', async (t) => {
  // Mock upstream whose catalog we can mutate
  let serving = ['alpha-model', 'beta-model'];
  const upstream = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/v1/models') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        object: 'list',
        data: serving.map((id) => ({ id, object: 'model', owned_by: 'mock' })),
      }));
      return;
    }
    res.writeHead(404);
    res.end();
  });
  await listen(upstream);
  t.after(() => close(upstream));

  const base = `http://127.0.0.1:${upstream.address().port}/v1`;
  const ENV_KEYS = ['UPB_PROVIDER', 'UPB_BASE_URL', 'UPB_MODEL_MAP',
                    'UPB_CATALOG_TTL', 'UPB_PORT', 'LOCAL_SECRET', 'USAGE_LOG',
                    'UPB_CONFIG', 'UPB_API_KEY'];
  const saved = {};
  for (const k of ENV_KEYS) saved[k] = process.env[k];
  t.after(() => {
    for (const k of ENV_KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });
  const probe = http.createServer();
  await listen(probe);
  const routerPort = probe.address().port;
  await close(probe);

  process.env.UPB_PROVIDER = 'mockprov';
  process.env.UPB_BASE_URL = base;
  process.env.UPB_API_KEY = '';
  process.env.UPB_MODEL_MAP = JSON.stringify({ 'claude-haiku-4-5': 'alpha-model' });
  process.env.UPB_CATALOG_TTL = '0';   // tailnet-local rule: always fresh
  process.env.UPB_PORT = String(routerPort);
  process.env.LOCAL_SECRET = 'test-secret';
  process.env.USAGE_LOG = `/tmp/upb-catalog-test-${routerPort}.jsonl`;
  delete process.env.UPB_CONFIG;

  const { server } = await import('../dist/index.js');
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const url = `http://127.0.0.1:${routerPort}/v1/models`;
  let up = false;
  for (let i = 0; i < 50 && !up; i++) {
    try { up = (await fetch(`http://127.0.0.1:${routerPort}/health`)).ok; } catch { /* wait */ }
    if (!up) await new Promise((r) => setTimeout(r, 100));
  }
  assert.equal(up, true, 'router became healthy');

  const ids = async () => (await (await fetch(url)).json()).data.map((m) => m.id);

  // Mirrored: upstream ids the router's config never declared
  let listed = await ids();
  assert.ok(listed.includes('alpha-model'), 'bare upstream id listed');
  assert.ok(listed.includes('mockprov/alpha-model'), 'namespaced upstream id listed');
  assert.ok(listed.includes('beta-model'), 'second upstream id listed');
  assert.ok(listed.includes('claude-haiku-4-5'), 'mapped wire name listed');

  // Upstream retires beta-model — with ttl=0 the proxy reflects it immediately
  serving = ['alpha-model'];
  listed = await ids();
  assert.ok(!listed.includes('beta-model'), 'retired model disappears (no stale cache)');
  assert.ok(listed.includes('alpha-model'), 'still-serving model stays');
});

test('upstream /models failure serves the stale cache (stale-while-error)', async (t) => {
  let mode = 'ok';   // 'ok' | 'down'
  let listed = ['gamma-model'];
  const upstream = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/v1/models' && mode === 'ok') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ object: 'list', data: listed.map((id) => ({ id })) }));
      return;
    }
    res.writeHead(500);
    res.end();
  });
  await listen(upstream);
  t.after(() => close(upstream));

  // Unit-level: exercise the util directly with a long TTL
  const { upstreamModels, resetUpstreamCatalogCache } =
    await import('../dist/utils/upstream-catalog.js');
  resetUpstreamCatalogCache();
  t.after(resetUpstreamCatalogCache);

  const def = {
    type: 'openai_compatible',
    base_url: `http://127.0.0.1:${upstream.address().port}/v1`,
    timeout: 5000,
  };
  const first = await upstreamModels('stale-test', def, 3600);
  assert.deepEqual(first.map((m) => m.id), ['gamma-model']);

  mode = 'down';
  listed = [];
  const second = await upstreamModels('stale-test', def, 3600);
  assert.deepEqual(second.map((m) => m.id), ['gamma-model'],
    'serves last good cache when upstream 500s');

  // No cache at all → null (caller keeps static fallback)
  resetUpstreamCatalogCache();
  const none = await upstreamModels('never-cached', def, 3600);
  assert.equal(none, null);
});
