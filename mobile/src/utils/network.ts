import { config } from '../config';

export async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs = config.requestTimeoutMs,
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const externalSignal = init.signal;

  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}
