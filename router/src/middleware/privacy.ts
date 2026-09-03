// ── Privacy Screen Middleware ──
// Screens outbound request bodies through the pf-screen daemon (unix socket,
// one JSON request per connection) before they leave the router.
// Wire contract + policy: findings/2026-09-03-gas-pf-integration/decision.md

import net from 'node:net';
import crypto from 'node:crypto';
import type http from 'node:http';

const SOCKET_PATH = process.env.PF_SCREEN_SOCKET || '/run/pf-screen.sock';
const DISABLED = process.env.PF_SCREEN_DISABLE === '1';
const SCREEN_TIMEOUT_MS = 180_000;

// Namespaces the text cache: bump when daemon threshold/policy config changes
// so stale redaction results are not reused across the epoch boundary.
const CACHE_EPOCH = process.env.PF_POLICY_EPOCH || 'pf-screen-v1';
const CACHE_MAX = 1024;

interface DaemonReply {
  verdict: string;
  redacted: string;
  spans?: unknown[];
}

export interface ScreenOutcome {
  ok: boolean;
  reason?: 'overflow' | 'screen-error';
  redacted: number;
  mode: 'ok' | 'partial' | 'disabled';
}

interface TextRef {
  get(): string;
  set(s: string): void;
}

const textCache = new Map<string, DaemonReply>();

function hashText(text: string): string {
  return crypto.createHash('sha256').update(CACHE_EPOCH).update(text).digest('hex');
}

function screenText(text: string): Promise<DaemonReply> {
  return new Promise((resolve, reject) => {
    const sock = net.connect(SOCKET_PATH);
    let buf = '';
    const timer = setTimeout(() => {
      sock.destroy();
      reject(new Error('pf-screen socket timeout'));
    }, SCREEN_TIMEOUT_MS);
    sock.on('connect', () => {
      sock.write(JSON.stringify({ id: 'upb', text }));
      sock.end();
    });
    sock.on('data', (d: Buffer) => {
      buf += d.toString('utf8');
    });
    sock.on('close', () => {
      clearTimeout(timer);
      try {
        resolve(JSON.parse(buf) as DaemonReply);
      } catch {
        reject(new Error('pf-screen unparsable reply'));
      }
    });
    sock.on('error', (err: Error) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

// Collects mutable references to every privacy-relevant string in an
// OpenAI-format body: message content strings, content-block texts, and
// tool outputs (role:'tool' messages carry tool_result content here).
function extractTextRefs(body: Record<string, unknown>): TextRef[] {
  const refs: TextRef[] = [];
  const messages = body.messages;
  if (!Array.isArray(messages)) return refs;
  for (const msg of messages) {
    if (!msg || typeof msg !== 'object') continue;
    const holder = msg as Record<string, unknown>;
    const content = holder.content;
    if (typeof content === 'string') {
      refs.push({ get: () => holder.content as string, set: s => { holder.content = s; } });
    } else if (Array.isArray(content)) {
      for (const block of content) {
        if (!block || typeof block !== 'object') continue;
        const b = block as Record<string, unknown>;
        if (typeof b.text === 'string') {
          refs.push({ get: () => b.text as string, set: s => { b.text = s; } });
        }
      }
    }
  }
  return refs;
}

async function screenOne(text: string): Promise<DaemonReply> {
  const key = hashText(text);
  const hit = textCache.get(key);
  if (hit) return hit;
  const reply = await screenText(text);
  if (textCache.size >= CACHE_MAX) textCache.clear();
  textCache.set(key, reply);
  return reply;
}

export async function screenOutgoingBody(
  body: Record<string, unknown>,
  res: http.ServerResponse,
): Promise<ScreenOutcome> {
  if (DISABLED) {
    res.setHeader('X-PF-Screen', 'disabled');
    res.setHeader('X-PF-Redacted', '0');
    return { ok: true, redacted: 0, mode: 'disabled' };
  }

  const refs = extractTextRefs(body);
  if (refs.length === 0) {
    res.setHeader('X-PF-Screen', 'ok');
    res.setHeader('X-PF-Redacted', '0');
    return { ok: true, redacted: 0, mode: 'ok' };
  }

  let mode: 'ok' | 'partial' = 'ok';
  let redacted = 0;
  try {
    const replies = await Promise.all(refs.map(r => screenOne(r.get())));
    for (let i = 0; i < refs.length; i++) {
      const reply = replies[i];
      if (reply.verdict === 'overflow' || reply.verdict === 'error') {
        // Daemon-backed fail-closed: never forward unscreened text.
        res.setHeader('X-PF-Screen', 'error');
        return { ok: false, reason: reply.verdict === 'overflow' ? 'overflow' : 'screen-error', redacted, mode: 'ok' };
      }
      if (reply.verdict === 't2-skip-long' || reply.verdict === 't2-partial') mode = 'partial';
      const spanCount = Array.isArray(reply.spans) ? reply.spans.length : 0;
      if (reply.verdict !== 'clean') refs[i].set(reply.redacted);
      redacted += spanCount;
    }
  } catch (err) {
    // Daemon unreachable/unresponsive: fail closed.
    console.error('[pf-screen]', (err as Error).message);
    res.setHeader('X-PF-Screen', 'error');
    return { ok: false, reason: 'screen-error', redacted, mode: 'ok' };
  }

  res.setHeader('X-PF-Screen', mode);
  res.setHeader('X-PF-Redacted', String(redacted));
  return { ok: true, redacted, mode };
}
