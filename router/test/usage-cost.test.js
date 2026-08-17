import test from 'node:test';
import assert from 'node:assert/strict';
import { computeCostUsd, aggregateUsage } from '../dist/utils/usage-logger.js';

test('cost math: 1000 in + 1000 out on qwen3.6-flash (0.26/1.56 per 1M)', () => {
  const pricing = { input_per_1m: 0.26, output_per_1m: 1.56 };
  const cost = computeCostUsd(pricing, { prompt_tokens: 1000, completion_tokens: 1000 });
  // 1000 * 0.26/1e6 + 1000 * 1.56/1e6 = 0.00026 + 0.00156
  assert.ok(Math.abs(cost - 0.00182) < 1e-12);
});

test('cost is null when the model has no pricing', () => {
  assert.equal(computeCostUsd(undefined, { prompt_tokens: 42, completion_tokens: 7 }), null);
});

test('aggregation tolerates legacy lines without cost_usd', () => {
  const lines = [
    JSON.stringify({ ts: '2026-08-01T00:00:00Z', provider: 'alibaba', model: 'qwen3.6-flash', wire_model: 'claude-sonnet-4-6', prompt_tokens: 100, completion_tokens: 50, total_tokens: 150, stream: false }),
    JSON.stringify({ ts: '2026-08-17T00:00:00Z', provider: 'alibaba', model: 'qwen3.6-flash', wire_model: 'claude-sonnet-4-6', prompt_tokens: 1000, completion_tokens: 1000, total_tokens: 2000, stream: false, cost_usd: 0.00182 }),
    JSON.stringify({ ts: '2026-08-17T00:00:01Z', provider: 'zen', model: 'big-pickle', wire_model: 'claude-haiku-4-5', prompt_tokens: 10, completion_tokens: 10, total_tokens: 20, stream: true, cost_usd: null }),
    'this line is not json',
  ];
  const agg = aggregateUsage(lines);
  assert.equal(agg.total_requests, 4);
  assert.equal(agg.total_prompt_tokens, 1110);
  assert.equal(agg.total_completion_tokens, 1060);
  assert.equal(agg.total_tokens, 2170);
  assert.ok(Math.abs(agg.cost_usd - 0.00182) < 1e-12);
  assert.ok(Math.abs(agg.by_provider.alibaba.cost_usd - 0.00182) < 1e-12);
  assert.equal(agg.by_provider.zen.cost_usd, 0);
  assert.ok(Math.abs(agg.by_model['qwen3.6-flash'].cost_usd - 0.00182) < 1e-12);
  assert.equal(agg.by_model['big-pickle'].cost_usd, 0);
});

test('empty aggregate shape includes zeroed cost fields', () => {
  const agg = aggregateUsage([]);
  assert.equal(agg.total_requests, 0);
  assert.equal(agg.total_tokens, 0);
  assert.equal(agg.cost_usd, 0);
  assert.deepEqual(agg.by_provider, {});
  assert.deepEqual(agg.by_model, {});
});
