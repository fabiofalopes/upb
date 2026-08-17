// ── Provider Cooldown Registry ──
// In-memory provider quarantine: after upstream 429s (or exhausted retries on
// retryable 5xx) a provider is skipped for a TTL, so routing fails over to an
// alternate or fails fast instead of retry-looping into a known-bad upstream.

export const DEFAULT_COOLDOWN_SECONDS = 300;

export class CooldownRegistry {
  private expiries = new Map<string, number>(); // provider → expiry epoch ms
  private readonly defaultSeconds: number;
  private readonly overrides: Record<string, number>;
  private readonly now: () => number;

  constructor(
    defaultSeconds: number = DEFAULT_COOLDOWN_SECONDS,
    overrides: Record<string, number> = {},
    now: () => number = () => Date.now(),
  ) {
    this.defaultSeconds = defaultSeconds;
    this.overrides = overrides;
    this.now = now;
  }

  // Quarantine `provider` for its override TTL (or `seconds`/the default)
  mark(provider: string, seconds?: number): void {
    const ttl = seconds ?? this.overrides[provider] ?? this.defaultSeconds;
    this.expiries.set(provider, this.now() + ttl * 1000);
  }

  // Seconds left in the cooldown (0 when none); expired entries are dropped on read
  remainingSeconds(provider: string): number {
    const expiry = this.expiries.get(provider);
    if (expiry === undefined) return 0;
    const remaining = Math.ceil((expiry - this.now()) / 1000);
    if (remaining <= 0) {
      this.expiries.delete(provider);
      return 0;
    }
    return remaining;
  }

  isQuarantined(provider: string): boolean {
    return this.remainingSeconds(provider) > 0;
  }

  // Active cooldowns only: { provider: remaining_seconds } — for /health
  snapshot(): Record<string, number> {
    const out: Record<string, number> = {};
    for (const provider of this.expiries.keys()) {
      const remaining = this.remainingSeconds(provider);
      if (remaining > 0) out[provider] = remaining;
    }
    return out;
  }
}

export class ProviderQuarantinedError extends Error {
  readonly provider: string;
  readonly remaining: number;
  readonly model: string;

  constructor(provider: string, remaining: number, model: string) {
    super(`Provider '${provider}' is quarantined (${remaining}s cooldown remaining) and no alternate provider serves model '${model}'`);
    this.name = 'ProviderQuarantinedError';
    this.provider = provider;
    this.remaining = remaining;
    this.model = model;
  }
}
