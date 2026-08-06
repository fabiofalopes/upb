// Token usage logger — appends JSONL to a file
import { appendFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';

const USAGE_LOG = process.env.USAGE_LOG || join(process.cwd(), 'usage.jsonl');

export interface UsageEntry {
  ts: string;           // ISO timestamp
  provider: string;     // resolved provider name (e.g. "alibaba-token-plan")
  model: string;        // actual model sent to provider
  wire_model: string;   // original model name from client
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  stream: boolean;
}

export function logUsage(entry: UsageEntry): void {
  try {
    mkdirSync(dirname(USAGE_LOG), { recursive: true });
    appendFileSync(USAGE_LOG, JSON.stringify(entry) + '\n');
  } catch (err) {
    console.error('[usage-logger] Failed to write:', (err as Error).message);
  }
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
