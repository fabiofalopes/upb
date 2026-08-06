// ── Translation: Anthropic ↔ OpenAI ──
// Core request/response translation between Anthropic Messages API and OpenAI Chat Completions API

import type {
  AnthropicRequest,
  AnthropicResponse,
  AnthropicMessage,
  AnthropicContentBlock,
  AnthropicToolUseBlock,
  AnthropicToolResultBlock,
  AnthropicTextBlock,
  AnthropicTool,
  AnthropicError,
  AnthropicCountTokensResponse,
  AnthropicToolChoice,
} from '../types/anthropic.js';
import type {
  OpenAIRequest,
  OpenAIMessage,
  OpenAIAssistantMessage,
  OpenAIToolMessage,
  OpenAITool,
  OpenAIToolCall,
  OpenAIResponse,
  OpenAIError,
} from '../types/openai.js';
import type { ProviderConfig } from '../middleware/config.js';
import type { ProviderAdapter } from '../adapters/types.js';

// ── Request Translation: Anthropic → OpenAI ──

export function translateRequest(
  body: AnthropicRequest,
  config: ProviderConfig,
  adapter?: ProviderAdapter,
): OpenAIRequest {
  // Strip thinking config if adapter says so
  if (adapter?.stripThinking) {
    body = stripThinkingBlocks(body);
  }

  // Strip thinking blocks from message content if adapter says so
  let messages = body.messages;
  if (adapter?.stripThinking) {
    messages = stripThinkingFromMessages(messages);
  }

  const tools = body.tools ? translateTools(body.tools) : undefined;
  const toolChoice = body.tool_choice ? translateToolChoice(body.tool_choice) : undefined;

  // Strip cache_control from system blocks if adapter says so
  let systemBlocks = body.system;
  if (adapter?.stripCacheControl && systemBlocks) {
    systemBlocks = stripCacheControlFromSystem(systemBlocks);
  }

  const finalMessages = translateMessages(messages, systemBlocks, adapter?.stripCacheControl ?? false);

  return {
    model: resolveModel(body.model, config),
    max_tokens: body.max_tokens,
    messages: finalMessages,
    tools,
    tool_choice: toolChoice as OpenAIRequest['tool_choice'],
    stream: body.stream,
    temperature: body.temperature,
    top_p: body.top_p,
  };
}

// ── Thinking Block Stripping ──

function stripThinkingBlocks(body: AnthropicRequest): AnthropicRequest {
  const { thinking, ...rest } = body;
  return rest as AnthropicRequest;
}

function stripThinkingFromMessages(messages: AnthropicMessage[]): AnthropicMessage[] {
  return messages.map(msg => ({
    ...msg,
    content: Array.isArray(msg.content)
      ? (msg.content as AnthropicContentBlock[]).filter(b => b.type !== 'thinking')
      : msg.content,
  }));
}

// ── Cache Control Stripping ──

function stripCacheControlFromSystem(
  system: AnthropicRequest['system'],
): AnthropicRequest['system'] {
  if (!system) return system;
  if (Array.isArray(system)) {
    return system.map(block => {
      const { cache_control, ...rest } = block as AnthropicTextBlock & { cache_control?: unknown };
      return rest as AnthropicTextBlock;
    });
  }
  // Single block
  const { cache_control, ...rest } = system as AnthropicTextBlock & { cache_control?: unknown };
  return rest as AnthropicTextBlock;
}

function resolveModel(model: string, config: ProviderConfig): string {
  return config.modelMap[model] || model;
}

function translateMessages(
  messages: AnthropicMessage[],
  system?: AnthropicTextBlock | AnthropicTextBlock[] | string,
  skipCacheControl = false,
): OpenAIMessage[] {
  const result: OpenAIMessage[] = [];

  // System → messages[0] with role system
  if (system) {
    // Handle string system prompts
    const sysBlocks = typeof system === 'string'
      ? [{ type: 'text' as const, text: system }]
      : Array.isArray(system) ? system : [system];
    const sysText = sysBlocks
      .map(b => extractText(b))
      .filter(Boolean)
      .join('\n\n');
    if (sysText) {
      result.push({ role: 'system', content: sysText });
    }
  }

  for (const msg of messages) {
    const translated = translateMessage(msg, skipCacheControl);
    result.push(...translated);
  }

  return result;
}

function translateMessage(msg: AnthropicMessage, skipCacheControl: boolean): OpenAIMessage[] {
  const content = normalizeContent(msg.content);
  const stripped = skipCacheControl ? content : stripCacheControl(content);

  if (msg.role === 'user') {
    return translateUserMessage(stripped);
  } else if (msg.role === 'assistant') {
    return translateAssistantMessage(stripped);
  }

  return [{ role: 'user', content: JSON.stringify(msg.content) }];
}

function translateUserMessage(blocks: AnthropicContentBlock[]): OpenAIMessage[] {
  // Separate text and tool_result blocks
  const textBlocks = blocks.filter(
    b => b.type === 'text' && extractText(b as AnthropicTextBlock),
  );
  const toolResultBlocks = blocks.filter(b => b.type === 'tool_result');

  const result: OpenAIMessage[] = [];

  // Text content as user message
  if (textBlocks.length > 0) {
    const text = textBlocks.map(b => extractText(b as AnthropicTextBlock)).join('\n');
    result.push({ role: 'user', content: text });
  }

  // Tool results as tool messages
  for (const block of toolResultBlocks) {
    result.push(translateToolResult(block as AnthropicToolResultBlock));
  }

  // If no text and no tool results, emit empty user message
  if (result.length === 0) {
    result.push({ role: 'user', content: '' });
  }

  return result;
}

function translateAssistantMessage(blocks: AnthropicContentBlock[]): OpenAIMessage[] {
  // Extract text and tool_use blocks
  const textBlocks = blocks.filter(
    b => b.type === 'text' && extractText(b as AnthropicTextBlock),
  );
  const toolUseBlocks = blocks.filter(b => b.type === 'tool_use') as AnthropicToolUseBlock[];

  const msg: OpenAIAssistantMessage = {
    role: 'assistant',
    content: textBlocks.length > 0 ? textBlocks.map(b => extractText(b as AnthropicTextBlock)).join('\n') : null,
  };

  if (toolUseBlocks.length > 0) {
    msg.tool_calls = toolUseBlocks.map(translateToolUse);
  }

  return [msg];
}

function translateToolUse(block: AnthropicToolUseBlock): OpenAIToolCall {
  return {
    id: block.id,
    type: 'function',
    function: {
      name: block.name,
      arguments: JSON.stringify(block.input),
    },
  };
}

function translateToolResult(block: AnthropicToolResultBlock): OpenAIToolMessage {
  let content = '';
  if (typeof block.content === 'string') {
    content = block.content;
  } else if (Array.isArray(block.content)) {
    content = block.content
      .map(b => (b.type === 'text' ? (b as AnthropicTextBlock).text : JSON.stringify(b)))
      .join('\n');
  }

  return {
    role: 'tool',
    tool_call_id: block.tool_use_id,
    content,
  };
}

function translateTools(tools: AnthropicTool[]): OpenAITool[] {
  return tools.map(tool => ({
    type: 'function' as const,
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.input_schema,
    },
  }));
}

function translateToolChoice(choice: AnthropicToolChoice): OpenAIRequest['tool_choice'] {
  if (typeof choice === 'object') {
    if (choice.type === 'auto') return 'auto';
    if (choice.type === 'any') return 'required';
    if (choice.type === 'tool') return { type: 'function', function: { name: choice.name } };
  }
  return 'auto';
}

// ── Response Translation: OpenAI → Anthropic ──

export function translateResponse(
  response: OpenAIResponse,
  originalModel: string,
): AnthropicResponse {
  const choice = response.choices[0];
  const content: AnthropicContentBlock[] = [];

  // Text content — fall back to reasoning/reasoning_content for models that
  // put their output there (GLM-5.2, DeepSeek-V4, Qwen3.5 on Ollama Cloud)
  const textContent = choice?.message?.content
    || choice?.message?.reasoning
    || choice?.message?.reasoning_content
    || null;
  if (textContent) {
    content.push({ type: 'text', text: textContent });
  }

  // Tool calls → tool_use blocks
  if (choice?.message?.tool_calls) {
    for (const tc of choice.message.tool_calls) {
      let input: Record<string, unknown> = {};
      try {
        input = JSON.parse(tc.function.arguments);
      } catch {
        input = { _raw: tc.function.arguments };
      }
      content.push({
        type: 'tool_use',
        id: tc.id,
        name: tc.function.name,
        input,
      });
    }
  }

  const stopReason = mapStopReason(choice?.finish_reason);

  return {
    id: `msg_${response.id}`,
    type: 'message',
    role: 'assistant',
    content,
    model: originalModel,
    stop_reason: stopReason,
    stop_sequence: null,
    usage: {
      input_tokens: response.usage?.prompt_tokens || 0,
      output_tokens: response.usage?.completion_tokens || 0,
    },
  };
}

function mapStopReason(
  reason: string | null | undefined,
): AnthropicResponse['stop_reason'] {
  switch (reason) {
    case 'stop':
      return 'end_turn';
    case 'tool_calls':
      return 'tool_use';
    case 'length':
      return 'max_tokens';
    default:
      return 'end_turn';
  }
}

// ── Error Translation ──

export function translateError(error: OpenAIError): AnthropicError {
  const typeMap: Record<string, string> = {
    rate_limit_error: 'rate_limit_error',
    invalid_request_error: 'invalid_request_error',
    authentication_error: 'authentication_error',
  };

  return {
    type: 'error',
    error: {
      type: typeMap[error.error.type] || 'api_error',
      message: error.error.message,
    },
  };
}

// ── Count Tokens Stub ──

export function estimateTokenCount(body: {
  messages?: AnthropicMessage[];
  system?: unknown;
  tools?: AnthropicTool[];
}): AnthropicCountTokensResponse {
  let totalChars = 0;

  if (body.system) {
    const sysText = typeof body.system === 'string'
      ? body.system
      : Array.isArray(body.system)
        ? (body.system as AnthropicTextBlock[]).map(s => s.text || '').join('')
        : '';
    totalChars += sysText.length;
  }

  if (body.messages) {
    for (const msg of body.messages) {
      if (typeof msg.content === 'string') {
        totalChars += msg.content.length;
      } else if (Array.isArray(msg.content)) {
        for (const block of msg.content) {
          if (block.type === 'text') totalChars += (block as AnthropicTextBlock).text.length;
          else totalChars += JSON.stringify(block).length;
        }
      }
    }
  }

  if (body.tools) {
    totalChars += JSON.stringify(body.tools).length;
  }

  // Rough estimate: ~4 chars per token
  const inputTokens = Math.max(1, Math.ceil(totalChars / 4));

  return {
    input_tokens: inputTokens,
    output_tokens: 0,
  };
}

// ── Helpers ──

function normalizeContent(content: AnthropicContentBlock[] | string): AnthropicContentBlock[] {
  if (typeof content === 'string') {
    return [{ type: 'text', text: content }];
  }
  return content;
}

function extractText(block: AnthropicTextBlock): string {
  return block.text || '';
}

function stripCacheControl(blocks: AnthropicContentBlock[]): AnthropicContentBlock[] {
  return blocks.map((block) => {
    const { type } = block;
    const copy = { ...block };
    // Delete cache_control if it exists
    if ('cache_control' in copy) {
      delete (copy as Record<string, unknown>).cache_control;
    }
    return copy;
  });
}
