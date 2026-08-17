import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeProviderHeaders } from '../dist/utils/headers.js';

test('provider headers merge into the outgoing set', () => {
  const headers = { 'Content-Type': 'application/json' };
  mergeProviderHeaders(headers, { 'User-Agent': 'mistral-client-python/Mistral-Vibe/2.21.0' });
  assert.equal(headers['User-Agent'], 'mistral-client-python/Mistral-Vibe/2.21.0');
  assert.equal(headers['Content-Type'], 'application/json');
});

test('provider headers can never clobber auth headers (case-insensitive)', () => {
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer real-key',
    'x-api-key': 'real-key',
  };
  mergeProviderHeaders(headers, {
    'Authorization': 'Bearer evil',
    'authorization': 'Bearer evil-too',
    'x-api-key': 'evil',
    'X-API-KEY': 'evil-too',
  });
  assert.equal(headers['Authorization'], 'Bearer real-key');
  assert.equal(headers['x-api-key'], 'real-key');
});
