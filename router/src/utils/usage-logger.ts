// Token usage logger — appends JSONL to a file
import { appendFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { ModelPricing } from '../middleware/router-config.js';

const USAGE_LOG = process.env.USAGE_LOG || join(process.cwd(), 'usage.jsonl');

export interface UsageEntry {
  ts: string;           // ISO timestamp
  provider: string;     // resolved provider name (e.g. "alibaba-token-plan")
  model: string;        // actual model sent to provider
  wire_model: string;   // original model name from client
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number | null; // computed from model pricing; null when unpriced
  stream: boolean;
}

// cost = input_tokens * input_per_1m/1e6 + output_tokens * output_per_1m/1e6
export function computeCostUsd(
  pricing: ModelPricing | undefined,
  usage: { prompt_tokens: number; completion_tokens: number },
): number | null {
  if (!pricing) return null;
  return usage.prompt_tokens * pricing.input_per_1m / 1e6 + usage.completion_tokens * pricing.output_per_1m / 1e6;
}

export function logUsage(entry: UsageEntry): void {
  try {
    mkdirSync(dirname(USAGE_LOG), { recursive: true });
    appendFileSync(USAGE_LOG, JSON.stringify(entry) + '\n');
  } catch (err) {
    console.error('[usage-logger] Failed to write:', (err as Error).message);
  }
}

export interface UsageTotals {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

export interface UsageAggregate {
  total_requests: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  by_provider: Record<string, UsageTotals>;
  by_model: Record<string, UsageTotals>;
}

// Aggregate parsed JSONL lines. Tolerates legacy entries that predate cost_usd
// (they count toward tokens but add $0).
export function aggregateUsage(lines: string[]): UsageAggregate {
  let totalPrompt = 0, totalCompletion = 0, totalTokens = 0, totalCost = 0;
  const byProvider: Record<string, UsageTotals> = {};
  const byModel: Record<string, UsageTotals> = {};

  for (const line of lines) {
    let entry: Record<string, unknown>;
    try {
      entry = JSON.parse(line);
    } catch { continue; }
    if (typeof entry !== 'object' || entry === null) continue;

    const prompt = readNumber(entry.prompt_tokens);
    const completion = readNumber(entry.completion_tokens);
    const total = readNumber(entry.total_tokens);
    const cost = readNumber(entry.cost_usd);
    totalPrompt += prompt;
    totalCompletion += completion;
    totalTokens += total;
    totalCost += cost;

    const prov = typeof entry.provider === 'string' ? entry.provider : 'unknown';
    if (!byProvider[prov]) byProvider[prov] = { requests: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cost_usd: 0 };
    byProvider[prov].requests++;
    byProvider[prov].prompt_tokens += prompt;
    byProvider[prov].completion_tokens += completion;
    byProvider[prov].total_tokens += total;
    byProvider[prov].cost_usd += cost;

    const model = typeof entry.model === 'string' ? entry.model : 'unknown';
    if (!byModel[model]) byModel[model] = { requests: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cost_usd: 0 };
    byModel[model].requests++;
    byModel[model].prompt_tokens += prompt;
    byModel[model].completion_tokens += completion;
    byModel[model].total_tokens += total;
    byModel[model].cost_usd += cost;
  }

  return {
    total_requests: lines.length,
    total_prompt_tokens: totalPrompt,
    total_completion_tokens: totalCompletion,
    total_tokens: totalTokens,
    cost_usd: totalCost,
    by_provider: byProvider,
    by_model: byModel,
  };
}

function readNumber(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

// Extract usage from an OpenAI-format response body (non-streaming)
export function extractUsage(json: Record<string, unknown>): { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null {
  const usage = json.usage as Record<string, unknown> | undefined;
  if (!usage) return null;
  return {
    prompt_tokens: (usage.prompt_tokens as number) || 0,
    completion_tokens: (usage.completion_tokens as number) || 0,
    total_tokens: (usage.total_tokens as number) || ((usage.prompt_tokens as number) || 0) + ((usage.completion_tokens as number) || 0),
  };
}

// Extract usage from raw SSE text (streaming) — scans for data lines with usage
export function extractUsageFromSSE(text: string): { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null {
  const lines = text.split('\n');
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const data = line.slice(6).trim();
    if (data === '[DONE]') continue;
    try {
      const parsed = JSON.parse(data);
      if (parsed.usage && (parsed.usage.prompt_tokens || parsed.usage.completion_tokens)) {
        return {
          prompt_tokens: parsed.usage.prompt_tokens || 0,
          completion_tokens: parsed.usage.completion_tokens || 0,
          total_tokens: parsed.usage.total_tokens || (parsed.usage.prompt_tokens || 0) + (parsed.usage.completion_tokens || 0),
        };
      }
    } catch { /* not JSON, skip */ }
  }
  return null;
}
