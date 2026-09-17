// Per-provider concurrency gate — FIFO queue honoring def.max_parallel.
// Doctrine (2026-09-13): free-tier providers (freebuff) run max_parallel: 1
// so the router never stresses an endpoint beyond what its own harness
// allows. Waiters queue FIFO up to QUEUE_TIMEOUT_MS, then get a clean
// overloaded-style rejection so callers can back off.

export interface QueueSlot {
  release(): void;
}

interface Lane {
  active: number;
  waiters: Array<() => void>; // FIFO resolve callbacks
  limit: number | null;       // null = unlimited
}

export class QueueTimeoutError extends Error {
  constructor(provider: string, waitedMs: number) {
    super(`Provider ${provider} queue timeout after ${waitedMs}ms (busy lane)`);
    this.name = 'QueueTimeoutError';
  }
}

const lanes = new Map<string, Lane>();
export const QUEUE_TIMEOUT_MS = 120_000;

export function laneStatus(): Record<string, { active: number; queued: number; limit: number | null }> {
  const out: Record<string, { active: number; queued: number; limit: number | null }> = {};
  for (const [name, lane] of lanes) {
    out[name] = { active: lane.active, queued: lane.waiters.length, limit: lane.limit };
  }
  return out;
}

export async function acquireSlot(provider: string, maxParallel?: number): Promise<QueueSlot> {
  const limit = maxParallel && maxParallel > 0 ? maxParallel : null;

  let lane = lanes.get(provider);
  if (!lane) {
    lane = { active: 0, waiters: [], limit };
    lanes.set(provider, lane);
  }
  if (lane.limit !== limit) lane.limit = limit; // config may have changed on reload

  if (lane.limit === null || lane.active < lane.limit) {
    lane.active++;
    return makeSlot(lane);
  }

  // FIFO wait with timeout
  return new Promise<QueueSlot>((resolve, reject) => {
    let settled = false;
    const waiter = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      lane!.active++;
      resolve(makeSlot(lane!));
    };
    const timer = setTimeout(() => {
      const idx = lane!.waiters.indexOf(waiter);
      if (idx >= 0) lane!.waiters.splice(idx, 1);
      if (!settled) {
        settled = true;
        reject(new QueueTimeoutError(provider, QUEUE_TIMEOUT_MS));
      }
    }, QUEUE_TIMEOUT_MS);
    lane!.waiters.push(waiter);
  });
}

function makeSlot(lane: Lane): QueueSlot {
  return {
    release(): void {
      lane.active = Math.max(0, lane.active - 1);
      const next = lane.waiters.shift();
      if (next) next();
    },
  };
}
