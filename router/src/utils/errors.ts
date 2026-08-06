// ── Error Classification & Retry Logic ──
// Classifies provider errors and provides retry decision logic

export enum ErrorCategory {
  RETRYABLE = 'retryable',
  NON_RETRYABLE = 'non_retryable',
  PROVIDER_ERROR = 'provider_error',
}

export function classifyError(statusCode: number, errorType: string): ErrorCategory {
  // Network errors (fetch failed, DNS, connection refused, etc.)
  if (statusCode === 0 || errorType === 'fetch_error' || errorType === 'network_error') {
    return ErrorCategory.RETRYABLE;
  }
  // Timeout
  if (errorType === 'TimeoutError' || errorType === 'abortError') {
    return ErrorCategory.RETRYABLE;
  }
  // Rate limit or server errors
  if (statusCode === 429 || statusCode === 408 || statusCode >= 500) {
    return ErrorCategory.RETRYABLE;
  }
  // Client errors (auth, invalid request)
  if (statusCode === 401 || statusCode === 403 || statusCode === 400) {
    return ErrorCategory.NON_RETRYABLE;
  }
  return ErrorCategory.PROVIDER_ERROR;
}

export function shouldRetry(category: ErrorCategory, attempt: number, maxRetries: number): boolean {
  if (category !== ErrorCategory.RETRYABLE) return false;
  if (attempt >= maxRetries) return false;
  return true;
}

export function getRetryDelay(attempt: number): number {
  // Exponential backoff with jitter
  const base = Math.min(1000 * Math.pow(2, attempt), 30_000);
  return base + Math.random() * 1000;
}
