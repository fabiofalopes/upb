// ── SSE Streaming Pipeline ──
// Translates OpenAI SSE stream to Anthropic SSE format
// This is the critical path — claude-code always streams

import type { OpenAIStreamChunk, OpenAIStreamToolCallDelta } from '../types/openai.js';
import { Readable, Transform, type TransformCallback } from 'node:stream';
import { randomUUID } from 'node:crypto';

// ── SSE Parser: parses raw SSE text from provider into parsed events ──

function parseSSELines(buffer: string): string[] {
  const events: string[] = [];
  let i = 0;
  while (true) {
    const end = buffer.indexOf('\n\n', i);
    if (end === -1) break;
    const block = buffer.slice(i, end);
    const dataLine = block.split('\n').find(l => l.startsWith('data: '));
    if (dataLine) events.push(dataLine.slice(6));
    i = end + 2;
  }
  return events;
}

// ── Tool call assembly state ──

interface ToolCallState {
  name: string;
  argumentsBuffer: string;
}

// ── Anthropic SSE formatting helpers ──

function formatSSE(event: string | null, data: object): string {
  let result = '';
  if (event) {
    result += `event: ${event}\n`;
  }
  result += `data: ${JSON.stringify(data)}\n\n`;
  return result;
}

function generateMessageId(): string {
  return `msg_${randomUUID().replace(/-/g, '').slice(0, 24)}`;
}

// ── Stream State Machine ──

enum StreamState {
  INIT,
  TEXT_BLOCK,
  TOOL_BLOCK,
  DONE,
}

interface StreamContext {
  state: StreamState;
  messageId: string;
  model: string;
  currentBlockIndex: number;
  toolCallStates: Map<number, ToolCallState>;
  lastEmitTime: number;
  outputTokens: number;
  started: boolean;
}

// ── Main Stream Transformer ──

export class AnthropicStreamTransformer extends Transform {
  private ctx: StreamContext;
  private pendingData = '';
  private keepaliveInterval: ReturnType<typeof setInterval> | null = null;

  constructor(model: string) {
    super({ objectMode: false });
    this.ctx = {
      state: StreamState.INIT,
      messageId: generateMessageId(),
      model,
      currentBlockIndex: 0,
      toolCallStates: new Map(),
      lastEmitTime: Date.now(),
      outputTokens: 0,
      started: false,
    };
  }

  _transform(chunk: Buffer, _encoding: string, callback: TransformCallback): void {
    this.ctx.lastEmitTime = Date.now();
    this.pendingData += chunk.toString('utf-8');

    const events = parseSSELines(this.pendingData);
    // Retain incomplete data (after last \n\n)
    const lastDoubleNewline = this.pendingData.lastIndexOf('\n\n');
    this.pendingData = lastDoubleNewline === -1 ? '' : this.pendingData.slice(lastDoubleNewline + 2);

    for (const event of events) {
      this.processProviderEvent(event);
    }

    callback();
  }

  private processProviderEvent(data: string): void {
    // [DONE] sentinel
    if (data === '[DONE]') {
      this.emitDone();
      return;
    }

    let parsed: OpenAIStreamChunk;
    try {
      parsed = JSON.parse(data);
    } catch {
      console.error('[stream] Failed to parse SSE data:', data.slice(0, 200));
      return;
    }

    const choice = parsed.choices?.[0];
    if (!choice) {
      // Some chunks only have usage info
      if (parsed.usage) {
        this.ctx.outputTokens = parsed.usage.completion_tokens || 0;
      }
      return;
    }

    // Track usage if present
    if (parsed.usage) {
      this.ctx.outputTokens = parsed.usage.completion_tokens || this.ctx.outputTokens;
    }

    // First chunk: emit message_start
    if (!this.ctx.started) {
      this.emitMessageStart();
      this.ctx.started = true;
    }

    const delta = choice.delta;

    // Resolve content: some reasoning models (GLM-5.2, DeepSeek-V4, Qwen3.5)
    // put their output in `reasoning` or `reasoning_content` instead of `content`.
    const deltaAny = delta as Record<string, unknown>;
    const text: string | null | undefined =
      delta.content ||
      (deltaAny.reasoning as string | null | undefined) ||
      (deltaAny.reasoning_content as string | null | undefined) ||
      null;

    // Handle role assignment (first meaningful chunk)
    // Also skip if only role + empty content but reasoning is present
    if (delta.role === 'assistant' && !text && !delta.tool_calls) {
      return; // Just the role declaration, or reasoning-only chunk with no content yet
    }

    // Text content (from either content or reasoning_content)
    if (text) {
      this.handleTextDelta(text);
    }

    // Tool call deltas
    if (delta.tool_calls && delta.tool_calls.length > 0) {
      for (const tc of delta.tool_calls) {
        this.handleToolCallDelta(tc);
      }
    }

    // Finish reason — no-op, emitDone handles all block closing
  }

  private emitMessageStart(): void {
    const event = formatSSE('message_start', {
      type: 'message_start',
      message: {
        id: this.ctx.messageId,
        type: 'message',
        role: 'assistant',
        content: [],
        model: this.ctx.model,
        stop_reason: null,
        stop_sequence: null,
        usage: {
          input_tokens: 0,
          output_tokens: 0,
        },
      },
    });
    this.push(event);
  }

  private handleTextDelta(text: string): void {
    if (this.ctx.state !== StreamState.TEXT_BLOCK) {
      // Close any previous block
      if (this.ctx.state === StreamState.TOOL_BLOCK) {
        this.pushCurrentToolBlock();
      }
      // Start new text block
      this.ctx.state = StreamState.TEXT_BLOCK;
      this.push(formatSSE('content_block_start', {
        type: 'content_block_start',
        index: this.ctx.currentBlockIndex,
        content_block: { type: 'text', text: '' },
      }));
    }

    this.push(formatSSE('content_block_delta', {
      type: 'content_block_delta',
      index: this.ctx.currentBlockIndex,
      delta: { type: 'text_delta', text },
    }));

    this.ctx.outputTokens += 1; // rough estimate
    this.ctx.lastEmitTime = Date.now();
  }

  private handleToolCallDelta(tc: OpenAIStreamToolCallDelta): void {
    const callIndex = tc.index;

    // Initialize tool call state if this is a new call
    if (!this.ctx.toolCallStates.has(callIndex)) {
      // Close any open text block first
      if (this.ctx.state === StreamState.TEXT_BLOCK) {
        this.push(formatSSE('content_block_stop', {
          type: 'content_block_stop',
          index: this.ctx.currentBlockIndex,
        }));
        this.ctx.currentBlockIndex++;
      }

      // Close any previous tool block
      if (this.ctx.state === StreamState.TOOL_BLOCK) {
        this.pushCurrentToolBlock();
      }

      // Start new tool block
      this.ctx.state = StreamState.TOOL_BLOCK;
      const providerCallId = tc.id || `call_${randomUUID().replace(/-/g, '').slice(0, 24)}`;

      this.ctx.toolCallStates.set(callIndex, {
        name: tc.function?.name || '',
        argumentsBuffer: '',
      });

      this.push(formatSSE('content_block_start', {
        type: 'content_block_start',
        index: this.ctx.currentBlockIndex,
        content_block: {
          type: 'tool_use',
          id: providerCallId,
          name: tc.function?.name || '',
          input: {},
        },
      }));
    }

    // Append to arguments buffer
    const state = this.ctx.toolCallStates.get(callIndex)!;
    if (tc.function?.name) {
      state.name = tc.function.name;
    }
    if (tc.function?.arguments) {
      state.argumentsBuffer += tc.function.arguments;

      // Emit input_json_delta
      this.push(formatSSE('content_block_delta', {
        type: 'content_block_delta',
        index: this.ctx.currentBlockIndex,
        delta: {
          type: 'input_json_delta',
          partial_json: tc.function.arguments,
        },
      }));
    }

    this.ctx.lastEmitTime = Date.now();
  }

  private pushCurrentToolBlock(): void {
    this.push(formatSSE('content_block_stop', {
      type: 'content_block_stop',
      index: this.ctx.currentBlockIndex,
    }));
    this.ctx.currentBlockIndex++;
    this.ctx.state = StreamState.INIT;
  }

  private emitDone(): void {
    if (!this.ctx.started) {
      // Provider sent DONE without any content
      this.emitMessageStart();
      this.ctx.started = true;
    }

    // Close any remaining open block
    if (this.ctx.state === StreamState.TEXT_BLOCK) {
      this.push(formatSSE('content_block_stop', {
        type: 'content_block_stop',
        index: this.ctx.currentBlockIndex,
      }));
    } else if (this.ctx.state === StreamState.TOOL_BLOCK) {
      this.pushCurrentToolBlock();
    }

    // Determine stop reason
    // If there were tool calls, use tool_use; otherwise end_turn
    const hasToolCalls = this.ctx.toolCallStates.size > 0;
    const stopReason = hasToolCalls ? 'tool_use' : 'end_turn';

    // message_delta
    this.push(formatSSE('message_delta', {
      type: 'message_delta',
      delta: {
        stop_reason: stopReason,
        stop_sequence: null,
      },
      usage: {
        output_tokens: Math.max(1, this.ctx.outputTokens),
      },
    }));

    // message_stop
    this.push(formatSSE('message_stop', {
      type: 'message_stop',
    }));

    this.ctx.state = StreamState.DONE;
  }

  _flush(callback: TransformCallback): void {
    if (this.ctx.state !== StreamState.DONE) {
      this.emitDone();
    }
    callback();
  }
}

// ── Keepalive Emitter ──
// Wraps a server response to emit SSE keepalive comments every 30s

const KEEPALIVE_MS = 30_000;

export function createKeepaliveStream(
  source: Readable,
): Readable {
  let lastEmitTime = Date.now();
  let keepaliveTimer: ReturnType<typeof setInterval>;

  const keepalive = new Readable({
    read() {
      // no-op
    },
  });

  // Forward data from source
  source.on('data', (chunk: Buffer) => {
    lastEmitTime = Date.now();
    keepalive.push(chunk);
  });

  source.on('end', () => {
    clearInterval(keepaliveTimer);
    keepalive.push(null);
  });

  source.on('error', (err: Error) => {
    clearInterval(keepaliveTimer);
    keepalive.destroy(err);
  });

  keepaliveTimer = setInterval(() => {
    if (Date.now() - lastEmitTime > KEEPALIVE_MS) {
      keepalive.push(': keepalive\n\n');
    }
  }, KEEPALIVE_MS / 2);

  return keepalive;
}
