export const AUTH_TIMEOUT_MS = 20_000

/** Bounds the UI wait; it does not cancel an SDK operation already in progress. */
export function withTimeout<T>(operation: PromiseLike<T>, timeoutMs = AUTH_TIMEOUT_MS): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Authentication timed out. Check your connection; a pending sign-in may still complete.')), timeoutMs)
    Promise.resolve(operation).then(resolve, reject).finally(() => clearTimeout(timer))
  })
}

/** Auth events take precedence over a slower startup session read. */
export function watchSession<T>(options: {
  read: () => Promise<{ session: T | null; error?: unknown }>
  subscribe: (callback: (session: T | null) => void) => () => void
  onSession: (session: T | null) => void
  onError: () => void
  timeoutMs?: number
}): () => void {
  let active = true
  let receivedEvent = false
  const unsubscribe = options.subscribe((session) => {
    if (!active) return
    receivedEvent = true
    options.onSession(session)
  })
  void withTimeout(Promise.resolve().then(options.read), options.timeoutMs).then((result) => {
    if (!active || receivedEvent) return
    if (result.error) options.onError()
    else options.onSession(result.session)
  }, () => {
    if (active && !receivedEvent) options.onError()
  })
  return () => {
    active = false
    unsubscribe()
  }
}
