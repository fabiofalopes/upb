import test from 'node:test';
import assert from 'node:assert/strict';
import { CooldownRegistry, DEFAULT_COOLDOWN_SECONDS, ProviderQuarantinedError } from '../dist/utils/cooldown.js';

test('mark applies the default TTL', () => {
  let now = 1_000_000;
  const cd = new CooldownRegistry(DEFAULT_COOLDOWN_SECONDS, {}, () => now);
  cd.mark('alpha');
  assert.equal(cd.isQuarantined('alpha'), true);
  assert.equal(cd.remainingSeconds('alpha'), 300);
  assert.equal(cd.isQuarantined('omega'), false);
  assert.equal(cd.remainingSeconds('omega'), 0);
});

test('cooldown expires and is dropped on read', () => {
  let now = 0;
  const cd = new CooldownRegistry(300, {}, () => now);
  cd.mark('alpha');
  now = 299_000;
  assert.equal(cd.remainingSeconds('alpha'), 1);
  assert.equal(cd.isQuarantined('alpha'), true);
  now = 300_000;
  assert.equal(cd.remainingSeconds('alpha'), 0);
  assert.equal(cd.isQuarantined('alpha'), false);
  // expired entry was removed
  assert.deepEqual(cd.snapshot(), {});
});

test('per-provider override and explicit seconds win over the default', () => {
  let now = 0;
  const cd = new CooldownRegistry(300, { zen: 39600 }, () => now);
  cd.mark('zen');
  assert.equal(cd.remainingSeconds('zen'), 39600);
  cd.mark('alpha');
  assert.equal(cd.remainingSeconds('alpha'), 300);
  cd.mark('alpha', 10);
  assert.equal(cd.remainingSeconds('alpha'), 10);
});

test('snapshot lists only active cooldowns with remaining seconds', () => {
  let now = 0;
  const cd = new CooldownRegistry(300, {}, () => now);
  cd.mark('a', 100);
  cd.mark('b', 50);
  now = 60_000; // fake clock is epoch ms — advance 60s
  assert.deepEqual(cd.snapshot(), { a: 40 });
});

test('ProviderQuarantinedError carries provider, remaining seconds and model', () => {
  const err = new ProviderQuarantinedError('zen', 39600, 'big-pickle');
  assert.equal(err.provider, 'zen');
  assert.equal(err.remaining, 39600);
  assert.equal(err.model, 'big-pickle');
  assert.ok(err.message.includes('zen'));
  assert.ok(err.message.includes('39600'));
  assert.ok(err.message.includes('big-pickle'));
});
