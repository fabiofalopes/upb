// ── Auth Middleware ──
// Validates inbound x-api-key or Authorization: Bearer against LOCAL_SECRET env var

const LOCAL_SECRET = process.env.LOCAL_SECRET || 'claude-universal-local';

export interface AuthResult {
  authenticated: boolean;
  error?: { type: string; message: string };
}

export function validateAuth(headers: Record<string, string | string[] | undefined>): AuthResult {
  // Extract the API key from x-api-key header
  const apiKey = headers['x-api-key'];

  // Extract from Authorization: Bearer <token>
  let bearerToken: string | undefined;
  const authHeader = headers['authorization'];
  if (typeof authHeader === 'string' && authHeader.startsWith('Bearer ')) {
    bearerToken = authHeader.slice(7);
  } else if (Array.isArray(authHeader)) {
    for (const h of authHeader) {
      if (h.startsWith('Bearer ')) {
        bearerToken = h.slice(7);
        break;
      }
    }
  }

  const token = apiKey || bearerToken;

  if (!token) {
    return {
      authenticated: false,
      error: { type: 'authentication_error', message: 'No API key provided' },
    };
  }

  if (token !== LOCAL_SECRET) {
    return {
      authenticated: false,
      error: { type: 'authentication_error', message: 'Invalid local key' },
    };
  }

  return { authenticated: true };
}
