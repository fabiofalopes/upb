// ── Universal Provider Router — Main Entry Point ──
// Dual-intake proxy: serves both Anthropic Messages API (Claude Code)
// and OpenAI Chat Completions API (OpenCode, Hermes), routing by model prefix.
//
// Intake endpoints:
//   POST /v1/messages          — Anthropic format (Claude Code)
//   POST /v1/chat/completions  — OpenAI format (OpenCode, Hermes)
//   GET  /v1/models             — OpenAI format (model listing)
//   GET  /health                — Health check

import http from 'node:http';
import path from 'node:path';
import { validateAuth } from './middleware/auth.js';
import { loadConfig } from './middleware/config.js';
import { loadRouterConfig, type ProviderDefinition, type RouterConfig } from './middleware/router-config.js';
import { translateRequest, translateResponse, translateError, estimateTokenCount } from './utils/translate.js';
import { AnthropicStreamTransformer, createKeepaliveStream } from './utils/stream.js';
import { getAdapter, listAdapters } from './adapters/registry.js';
import { classifyError, shouldRetry, getRetryDelay, ErrorCategory } from './utils/errors.js';
import { logUsage, extractUsage, extractUsageFromSSE } from './utils/usage-logger.js';
import type { AnthropicRequest } from './types/anthropic.js';
import type { ProviderAdapter } from './adapters/types.js';

// ── Configuration ──

const routerCfg = loadRouterConfig();
const PORT = routerCfg.defaults.port;
const MAX_RETRIES = routerCfg.defaults.retries;
const LOCAL_SECRET = process.env.LOCAL_SECRET || routerCfg.defaults.local_secret;

// ── Provider Resolution ──

interface ResolvedProvider {
  name: string;
  definition: ProviderDefinition;
  adapter: ProviderAdapter;
  model: string; // the actual model name to send to the provider
}

function resolveProvider(
  model: string,
): ResolvedProvider {
  // Extract prefix from model name (e.g., "litellm/qwopus3.5" → prefix "litellm", model "qwopus3.5")
  const slashIdx = model.indexOf('/');
  const prefix = slashIdx > 0 ? model.slice(0, slashIdx) : '';
  const modelName = slashIdx > 0 ? model.slice(slashIdx + 1) : model;

  // Try exact prefix match
  if (prefix && routerCfg.providers[prefix]) {
    const def = routerCfg.providers[prefix];
    const adapter = getAdapterForProvider(prefix, def);
    return {
      name: prefix,
      definition: def,
      adapter,
      model: modelName,
    };
  }

  // Try matching model_map (for claude-* wire names)
  for (const [provName, def] of Object.entries(routerCfg.providers)) {
    if (def.model_map && def.model_map[model]) {
      const adapter = getAdapterForProvider(provName, def);
      const mappedModel = def.model_map[model];
      // Strip a leading "prefix/" ONLY when the prefix is itself a configured
      // provider (legacy "zen/big-pickle"-style routing). Otherwise the mapped
      // value is the exact upstream model id — e.g. aggregator catalogs like
      // PrimeIntellect use "org/model" ids that must reach upstream verbatim.
      const mappedSlashIdx = mappedModel.indexOf('/');
      const mappedPrefix = mappedSlashIdx > 0 ? mappedModel.slice(0, mappedSlashIdx) : '';
      const stripPrefix = mappedSlashIdx > 0 && Boolean(routerCfg.providers[mappedPrefix]);
      return {
        name: provName,
        definition: def,
        adapter,
        model: stripPrefix ? mappedModel.slice(mappedSlashIdx + 1) : mappedModel,
      };
    }
  }

  // Fall back to active provider
  const fallback = routerCfg.providers[routerCfg.active_provider];
  if (fallback) {
    const adapter = getAdapterForProvider(routerCfg.active_provider, fallback);
    return {
      name: routerCfg.active_provider,
      definition: fallback,
      adapter,
      model: modelName || model,
    };
  }

  // Last resort — first available provider
  const first = Object.entries(routerCfg.providers)[0];
  if (first) {
    const [n, d] = first;
    const adapter = getAdapterForProvider(n, d);
    return { name: n, definition: d, adapter, model: modelName || model };
  }

  throw new Error(`No providers configured and no env-var fallback available`);
}

function getAdapterForProvider(name: string, def: ProviderDefinition): ProviderAdapter {
  // Built-in adapters
  const known: Record<string, Partial<ProviderAdapter>> = {
    litellm: { stripThinking: false, stripCacheControl: false },
    zen: { stripThinking: false, stripCacheControl: false, timeout: 300_000 },
    'opencode-go': { stripThinking: false, stripCacheControl: false, timeout: 300_000 },
    zai: { stripThinking: false, stripCacheControl: false, timeout: 300_000 },
    ollama: { stripThinking: true, stripCacheControl: true, timeout: 600_000 },
  };

  const base = known[name] || {};
  return {
    name,
    timeout: def.timeout || base.timeout || 300_000,
    stripThinking: def.strip_thinking ?? base.stripThinking ?? true,
    stripCacheControl: def.strip_cache_control ?? base.stripCacheControl ?? true,
    transformRequest: (body) => body,
    transformError: (e) => e,
    extraHeaders: def.extra_headers || {},
  };
}

// ── Server ──

const server = http.createServer(async (req, res) => {
  try {
    await handleRequest(req, res);
  } catch (err) {
    console.error('[server] Unhandled error:', (err as Error).message);
    if (!res.headersSent) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        type: 'error',
        error: { type: 'api_error', message: 'Internal server error' },
      }));
    }
  }
});

async function handleRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  // ── CORS preflight ──
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, x-api-key, anthropic-version, anthropic-beta',
    });
    res.end();
    return;
  }

  // ── Health endpoint ──
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    });
    res.end(JSON.stringify({
      status: 'ok',
      service: 'universal-provider-router',
      version: routerCfg.version,
      providers: Object.keys(routerCfg.providers),
      active_provider: routerCfg.active_provider,
      uptime: process.uptime(),
    }));
    return;
  }

  // ── GET /v1/models — List available models ──
  if (req.method === 'GET' && req.url === '/v1/models') {
    const models: Array<{ id: string; object: string; created: number; owned_by: string }> = [];
    const now = Math.floor(Date.now() / 1000);

    for (const [name, def] of Object.entries(routerCfg.providers)) {
      // If provider has a model_map, expose those
      if (def.model_map) {
        for (const [wireName, mappedModel] of Object.entries(def.model_map)) {
          models.push({
            id: mappedModel,
            object: 'model',
            created: now,
            owned_by: name,
          });
        }
      }
    }

    // Also expose claude-* wire names for Claude Code compatibility
    for (const wireName of ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5']) {
      if (!models.find(m => m.id === wireName)) {
        models.push({
          id: wireName,
          object: 'model',
          created: now,
          owned_by: 'universal-router',
        });
      }
    }

    res.writeHead(200, {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    });
    res.end(JSON.stringify({ object: 'list', data: models }));
    return;
  }

  // ── GET /usage — Token usage summary ──
  if (req.method === 'GET' && (req.url === '/usage' || req.url?.startsWith('/usage?'))) {
    return handleUsageSummary(res);
  }

  // ── POST /v1/chat/completions — OpenAI format (OpenCode, Hermes, pi-agent) ──
  if (req.method === 'POST' && (req.url === '/v1/chat/completions' || req.url?.startsWith('/v1/chat/completions?'))) {
    return handleOpenAIRequest(req, res);
  }

  // ── POST /v1/messages — Anthropic Messages API (Claude Code) ──
  if (req.method === 'POST' && (req.url === '/v1/messages' || req.url?.startsWith('/v1/messages?'))) {
    return handleAnthropicRequest(req, res);
  }

  // ── POST /v1/messages/count_tokens — Token count stub ──
  if (req.method === 'POST' && req.url === '/v1/messages/count_tokens') {
    return handleCountTokens(req, res);
  }

  // ── 404 ──
  res.writeHead(404, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
  });
  res.end(JSON.stringify({ type: 'error', error: { type: 'not_found', message: `Not found: ${req.method} ${req.url}` } }));
}

// ── OpenAI Intake Handler (for OpenCode, Hermes) ──

async function handleOpenAIRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  // Parse body
  let body: Record<string, unknown>;
  try {
    const raw = await readBody(req);
    body = JSON.parse(raw);
  } catch (err) {
    res.writeHead(400, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: `Invalid JSON: ${(err as Error).message}`, type: 'invalid_request_error' } }));
    return;
  }

  const model = (body.model as string) || 'unknown';
  const isStream = body.stream === true;

  // Resolve provider
  let resolved: ResolvedProvider;
  try {
    resolved = resolveProvider(model);
  } catch (err) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: (err as Error).message, type: 'api_error' } }));
    return;
  }

  console.log(`[openai] ${isStream ? 'STREAM' : 'SYNC'} ${model} → ${resolved.name}/${resolved.model} | adapter: ${resolved.adapter.name}`);

  // Build provider URL and headers
  const baseUrl = resolved.definition.base_url.replace(/\/$/, '');
  const providerUrl = `${baseUrl}/chat/completions`;
  const outboundHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...resolved.adapter.extraHeaders,
  };
  if (resolved.definition.api_key) {
    const key = resolved.definition.api_key.replace(/^\$\{(.+?):-?(.*?)\}$/, (_m: string, _env: string, fallback: string) => {
      return process.env[_env] || fallback;
    });
    if (key) {
      outboundHeaders['Authorization'] = `Bearer ${key}`;
    }
  }

  // Build outbound request body
  const outboundBody = {
    ...body,
    model: resolved.model,
    ...(isStream ? { stream_options: { include_usage: true } } : {}),
  };

  // Forward with retry
  await forwardToProvider(providerUrl, outboundHeaders, outboundBody, isStream, res, resolved.adapter, model);
}

// ── Anthropic Intake Handler (for Claude Code) ──

async function handleAnthropicRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  // Auth check
  const authResult = validateAuth(req.headers as Record<string, string | string[] | undefined>);
  if (!authResult.authenticated) {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ type: 'error', error: authResult.error! }));
    return;
  }

  // Parse body
  let body: AnthropicRequest;
  try {
    const raw = await readBody(req);
    body = JSON.parse(raw) as AnthropicRequest;
  } catch (err) {
    res.writeHead(400, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      type: 'error',
      error: { type: 'invalid_request_error', message: `Invalid JSON body: ${(err as Error).message}` },
    }));
    return;
  }

  // Resolve provider from model name
  let resolved: ResolvedProvider;
  try {
    resolved = resolveProvider(body.model);
  } catch (err) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      type: 'error',
      error: { type: 'api_error', message: (err as Error).message },
    }));
    return;
  }

  console.log(`[anthropic] ${body.stream ? 'STREAM' : 'SYNC'} ${body.model} → ${resolved.name}/${resolved.model} | messages: ${body.messages.length} | tools: ${body.tools?.length || 0}`);

  // Build adapter-like config for the translate layer
  const adapterConfig = {
    adapter: resolved.name,
    baseUrl: resolved.definition.base_url,
    apiKey: resolved.definition.api_key || '',
    modelMap: { [body.model]: resolved.model },
  };

  // Translate: Anthropic → OpenAI
  let openaiRequest = translateRequest(body, adapterConfig, resolved.adapter);

  // Adapter-level transform
  openaiRequest = resolved.adapter.transformRequest(openaiRequest as Record<string, unknown>) as typeof openaiRequest;

  // Request usage in streaming responses
  if (body.stream) {
    (openaiRequest as Record<string, unknown>).stream_options = { include_usage: true };
  }

  // Build provider URL and headers
  const baseUrl = resolved.definition.base_url.replace(/\/$/, '');
  const providerUrl = `${baseUrl}/chat/completions`;
  const outboundHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...resolved.adapter.extraHeaders,
  };
  const resolvedKey = resolveEnvVar(resolved.definition.api_key);
  if (resolvedKey) {
    outboundHeaders['Authorization'] = `Bearer ${resolvedKey}`;
  }

  // Forward with retry
  if (body.stream) {
    // Streaming: set up SSE pipeline
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
      'Access-Control-Allow-Origin': '*',
    });

    const transformer = new AnthropicStreamTransformer(body.model);
    const keepaliveStream = createKeepaliveStream(transformer);

    try {
      const providerRes = await fetch(providerUrl, {
        method: 'POST',
        headers: outboundHeaders,
        body: JSON.stringify(openaiRequest),
        signal: AbortSignal.timeout(resolved.adapter.timeout),
      });

      if (!providerRes.ok) {
        const errorBody = await providerRes.text().catch(() => '');
        res.write(`event: error\ndata: ${JSON.stringify({ type: 'error', error: { type: 'api_error', message: `Provider ${providerRes.status}: ${errorBody.slice(0, 200)}` } })}\n\n`);
        res.end();
        return;
      }

      if (providerRes.body) {
        const reader = providerRes.body.getReader();
        let streamUsageLogged = false;
        const pump = async (): Promise<void> => {
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) {
                transformer.end();
                break;
              }
              if (!streamUsageLogged) {
                const usage = extractUsageFromSSE(Buffer.from(value).toString('utf-8'));
                if (usage) {
                  streamUsageLogged = true;
                  logUsage({
                    ts: new Date().toISOString(),
                    provider: resolved.name,
                    model: resolved.model,
                    wire_model: body.model,
                    ...usage,
                    stream: true,
                  });
                }
              }
              transformer.write(Buffer.from(value));
            }
          } catch (err) {
            console.error('[stream] Provider stream error:', (err as Error).message);
            transformer.destroy(err as Error);
          }
        };
        keepaliveStream.pipe(res);
        pump().catch(err => {
          console.error('[stream] Pump error:', (err as Error).message);
          keepaliveStream.push(null);
        });
      } else {
        res.end();
      }
    } catch (fetchErr) {
      console.error('[anthropic-stream] Fetch error:', (fetchErr as Error).message);
      res.write(`event: error\ndata: ${JSON.stringify({ type: 'error', error: { type: 'api_error', message: (fetchErr as Error).message } })}\n\n`);
      res.end();
    }
  } else {
    // Non-streaming
    await forwardToProvider(providerUrl, outboundHeaders, openaiRequest, false, res, resolved.adapter, body.model, true);
  }
}

// ── Count Tokens ──

async function handleCountTokens(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  const authResult = validateAuth(req.headers as Record<string, string | string[] | undefined>);
  if (!authResult.authenticated) {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ type: 'error', error: authResult.error! }));
    return;
  }

  let body: Record<string, unknown>;
  try {
    const raw = await readBody(req);
    body = JSON.parse(raw);
  } catch (err) {
    res.writeHead(400, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      type: 'error',
      error: { type: 'invalid_request_error', message: `Invalid JSON body: ${(err as Error).message}` },
    }));
    return;
  }

  const countResult = estimateTokenCount(body as Parameters<typeof estimateTokenCount>[0]);
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(countResult));
}

// ── Generic Provider Forwarder ──

async function forwardToProvider(
  providerUrl: string,
  headers: Record<string, string>,
  body: Record<string, unknown>,
  isStream: boolean,
  res: http.ServerResponse,
  adapter: ProviderAdapter,
  originalModel: string,
  translateResponse_toAnthropic = false,
): Promise<void> {
  let lastError: { statusCode: number; text: string } | null = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      if (attempt > 0) {
        const delay = getRetryDelay(attempt - 1);
        console.log(`[proxy] Retry attempt ${attempt}/${MAX_RETRIES} after ${delay}ms`);
        await new Promise(resolve => setTimeout(resolve, delay));
      }

      const providerRes = await fetch(providerUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(adapter.timeout),
      });

      if (!providerRes.ok) {
        let errorText = '';
        try { errorText = await providerRes.text(); } catch { errorText = ''; }

        let providerError: Record<string, unknown>;
        try { providerError = JSON.parse(errorText); } catch { providerError = { error: { message: `Provider returned ${providerRes.status}`, type: 'api_error' } }; }

        providerError = adapter.transformError(providerError);

        const errorType = (providerError.error as Record<string, unknown>)?.type as string || 'unknown';
        const category = classifyError(providerRes.status, errorType);
        console.error(`[proxy] Provider error: ${providerRes.status} ${errorType} [${category}]`);

        if (shouldRetry(category, attempt, MAX_RETRIES)) {
          lastError = { statusCode: providerRes.status, text: errorText };
          continue;
        }

        if (translateResponse_toAnthropic) {
          const anthropicErr = translateError(providerError as { error: { message: string; type: string } });
          res.writeHead(providerRes.status >= 500 ? 502 : providerRes.status, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(anthropicErr));
        } else {
          res.writeHead(providerRes.status >= 500 ? 502 : providerRes.status, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(providerError));
        }
        return;
      }

      // Success
      if (isStream) {
        res.writeHead(200, {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
          'X-Accel-Buffering': 'no',
          'Access-Control-Allow-Origin': '*',
        });

        if (translateResponse_toAnthropic) {
          // OpenAI SSE → Anthropic SSE translation needed
          const transformer = new AnthropicStreamTransformer(originalModel);
          const keepaliveStream = createKeepaliveStream(transformer);

          if (providerRes.body) {
            const reader = providerRes.body.getReader();
            let streamUsageLogged = false;
            const pump = async () => {
              try {
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) { transformer.end(); break; }
                  if (!streamUsageLogged) {
                    const usage = extractUsageFromSSE(Buffer.from(value).toString('utf-8'));
                    if (usage) {
                      streamUsageLogged = true;
                      logUsage({
                        ts: new Date().toISOString(),
                        provider: adapter.name,
                        model: (body as Record<string, unknown>).model as string || 'unknown',
                        wire_model: originalModel,
                        ...usage,
                        stream: true,
                      });
                    }
                  }
                  transformer.write(Buffer.from(value));
                }
              } catch (err) {
                transformer.destroy(err as Error);
              }
            };
            keepaliveStream.pipe(res);
            pump().catch(err => {
              keepaliveStream.push(null);
            });
          } else {
            res.end();
          }
        } else {
          // Passthrough: provider SSE → client directly
          if (providerRes.body) {
            const reader = providerRes.body.getReader();
            let streamUsageLogged = false;
            const pump = async () => {
              try {
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) { res.end(); break; }
                  // Extract usage from SSE chunks
                  if (!streamUsageLogged) {
                    const usage = extractUsageFromSSE(Buffer.from(value).toString('utf-8'));
                    if (usage) {
                      streamUsageLogged = true;
                      logUsage({
                        ts: new Date().toISOString(),
                        provider: adapter.name,
                        model: (body as Record<string, unknown>).model as string || 'unknown',
                        wire_model: originalModel,
                        ...usage,
                        stream: true,
                      });
                    }
                  }
                  res.write(value);
                }
              } catch (err) {
                console.error('[openai-stream] Pipe error:', (err as Error).message);
                res.end();
              }
            };
            pump();
          } else {
            res.end();
          }
        }
      } else {
        // Non-streaming
        const providerJson = await providerRes.json();
        // Log usage
        const usage = extractUsage(providerJson as Record<string, unknown>);
        if (usage) {
          logUsage({
            ts: new Date().toISOString(),
            provider: adapter.name,
            model: (body as Record<string, unknown>).model as string || 'unknown',
            wire_model: originalModel,
            ...usage,
            stream: false,
          });
        }
        if (translateResponse_toAnthropic) {
          const anthropicResponse = translateResponse(providerJson, originalModel);
          res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
          res.end(JSON.stringify(anthropicResponse));
        } else {
          res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
          res.end(JSON.stringify(providerJson));
        }
      }

      return; // success

    } catch (err) {
      const isTimeout = (err as Error).name === 'TimeoutError';
      const category = isTimeout ? ErrorCategory.RETRYABLE : classifyError(0, 'fetch_error');
      console.error(`[proxy] Request failed (attempt ${attempt + 1}): ${(err as Error).message} [${category}]`);

      if (shouldRetry(category, attempt, MAX_RETRIES)) {
        continue;
      }

      const errorPayload = {
        type: 'error',
        error: {
          type: isTimeout ? 'timeout_error' : 'api_error',
          message: `Request failed after ${attempt + 1} attempt(s): ${(err as Error).message}`,
        },
      };

      if (translateResponse_toAnthropic) {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(errorPayload));
      } else {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: errorPayload.error }));
      }
      return;
    }
  }

  // All retries exhausted
  const msg = `All retries exhausted. Last error: ${lastError?.text || 'unknown'}`;
  if (translateResponse_toAnthropic) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ type: 'error', error: { type: 'api_error', message: msg } }));
  } else {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: msg, type: 'api_error' } }));
  }
}

// ── Usage Summary Handler ──

async function handleUsageSummary(res: http.ServerResponse): Promise<void> {
  const { readFileSync, existsSync } = await import('node:fs');
  const USAGE_LOG = process.env.USAGE_LOG || path.join(process.cwd(), 'usage.jsonl');

  if (!existsSync(USAGE_LOG)) {
    res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ total_requests: 0, total_prompt_tokens: 0, total_completion_tokens: 0, total_tokens: 0, by_provider: {}, by_model: {} }));
    return;
  }

  const lines = readFileSync(USAGE_LOG, 'utf-8').trim().split('\n').filter(Boolean);
  let totalPrompt = 0, totalCompletion = 0, totalTokens = 0;
  const byProvider: Record<string, { requests: number; prompt_tokens: number; completion_tokens: number; total_tokens: number }> = {};
  const byModel: Record<string, { requests: number; prompt_tokens: number; completion_tokens: number; total_tokens: number }> = {};

  for (const line of lines) {
    try {
      const entry = JSON.parse(line);
      totalPrompt += entry.prompt_tokens || 0;
      totalCompletion += entry.completion_tokens || 0;
      totalTokens += entry.total_tokens || 0;

      const prov = entry.provider || 'unknown';
      if (!byProvider[prov]) byProvider[prov] = { requests: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
      byProvider[prov].requests++;
      byProvider[prov].prompt_tokens += entry.prompt_tokens || 0;
      byProvider[prov].completion_tokens += entry.completion_tokens || 0;
      byProvider[prov].total_tokens += entry.total_tokens || 0;

      const model = entry.model || 'unknown';
      if (!byModel[model]) byModel[model] = { requests: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
      byModel[model].requests++;
      byModel[model].prompt_tokens += entry.prompt_tokens || 0;
      byModel[model].completion_tokens += entry.completion_tokens || 0;
      byModel[model].total_tokens += entry.total_tokens || 0;
    } catch { /* skip malformed lines */ }
  }

  res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
  res.end(JSON.stringify({
    total_requests: lines.length,
    total_prompt_tokens: totalPrompt,
    total_completion_tokens: totalCompletion,
    total_tokens: totalTokens,
    by_provider: byProvider,
    by_model: byModel,
  }, null, 2));
}

// ── Helpers ──

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')));
    req.on('error', reject);
  });
}

function resolveEnvVar(val: string | undefined): string | undefined {
  if (!val) return undefined;
  // Handle ${VAR_NAME:-default} syntax
  return val.replace(/\$\{(.+?)(?::-(.*?))?\}/g, (_m: string, env: string, fallback: string) => {
    return process.env[env] || fallback || '';
  });
}

// ── Start server ──

server.listen(PORT, () => {
  console.log(`\n╔══════════════════════════════════════════════╗`);
  console.log(`║   Universal Provider Router                  ║`);
  console.log(`║   Port: ${PORT}                              ║`);
  console.log(`║   Providers: ${Object.keys(routerCfg.providers).length} configured           ║`);
  for (const [name, def] of Object.entries(routerCfg.providers)) {
    const icon = (def as ProviderDefinition).icon || '•';
    console.log(`║     ${icon} ${name.padEnd(14)} → ${def.base_url}`);
  }
  console.log(`║   Active: ${routerCfg.active_provider}                      ║`);
  console.log(`╚══════════════════════════════════════════════╝\n`);
  console.log(`[router] Endpoints:`);
  console.log(`  GET  /health`);
  console.log(`  GET  /v1/models`);
  console.log(`  POST /v1/chat/completions  ← OpenCode, Hermes, pi-agent`);
  console.log(`  POST /v1/messages          ← Claude Code`);
  console.log(`  POST /v1/messages/count_tokens`);
});

function shutdown(signal: string) {
  console.log(`\n[router] Received ${signal}, shutting down...`);
  server.close(() => {
    console.log('[router] Server closed');
    process.exit(0);
  });
  setTimeout(() => {
    console.error('[router] Forced shutdown');
    process.exit(1);
  }, 5000);
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

export { server };
