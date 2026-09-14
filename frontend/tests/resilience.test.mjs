import assert from 'node:assert/strict'
import { test } from 'node:test'
import { assertPublicBuildEnvironment, validateAuthConfiguration } from '../src/lib/authConfiguration.ts'
import { boundedEnvNumber } from '../src/lib/deploymentValues.ts'
import { watchSession, withTimeout } from '../src/lib/sessionLifecycle.ts'
import { publicBooleanFlag, resolveApiBaseUrl, resolveRuntimeMode } from '../src/lib/runtimeMode.ts'

const publicTestKey = 'sb_publishable_fixture_not_a_real_key'
const jwt = (role) => `test.${Buffer.from(JSON.stringify({ role })).toString('base64url')}.test`

test('local demo mode requires an explicit true flag', () => {
  for (const value of [undefined, '', 'false', '0', 'yes', ' true-ish ']) {
    assert.equal(publicBooleanFlag(value), false)
  }
  assert.equal(publicBooleanFlag('true'), true)
  assert.equal(publicBooleanFlag(' TRUE '), true)
})

test('runtime modes are explicit and conflicting flags fail closed', () => {
  assert.equal(resolveRuntimeMode('online', undefined), 'online')
  assert.equal(resolveRuntimeMode('offline-judge', undefined), 'offline-judge')
  assert.equal(resolveRuntimeMode(undefined, 'true'), 'offline-judge')
  assert.throws(() => resolveRuntimeMode('preview', undefined), /VITE_APP_MODE/)
  assert.throws(() => resolveRuntimeMode('online', 'true'), /Conflicting runtime flags/)
})

test('offline judge API traffic is restricted to the serving origin', () => {
  assert.equal(resolveApiBaseUrl(undefined, 'offline-judge'), '/api/v1')
  assert.equal(resolveApiBaseUrl('/api/v1/', 'offline-judge'), '/api/v1')
  for (const value of ['//remote.example/api', 'https://api.example/api', 'http://localhost:8000/api']) {
    assert.throws(() => resolveApiBaseUrl(value, 'offline-judge'), /same-origin/)
  }
})

test('online API targets require safe HTTPS or loopback HTTP', () => {
  assert.equal(resolveApiBaseUrl('https://api.example/v1/', 'online'), 'https://api.example/v1')
  assert.equal(resolveApiBaseUrl('http://localhost:8000/api/v1', 'online'), 'http://localhost:8000/api/v1')
  for (const value of ['javascript:alert(1)', 'http://remote.example/api', 'https://user:pass@api.example/v1', 'https://api.example/v1?key=x']) {
    assert.throws(() => resolveApiBaseUrl(value, 'online'), /VITE_API_BASE_URL/)
  }
})

test('missing and whitespace configuration fail safely', () => {
  assert.ok(validateAuthConfiguration(undefined, undefined).error)
  assert.ok(validateAuthConfiguration(' ', ' ').error)
})

test('malformed and unsafe project URLs fail without throwing', () => {
  for (const url of ['bad-url', 'javascript:alert(1)', 'http://remote.example', 'https://user:pass@project.example', 'https://project.example?key=x', 'https://project.example#fragment', 'https://project.supabase.co/path', 'https://your-project.supabase.co']) {
    assert.ok(validateAuthConfiguration(url, publicTestKey).error, url)
  }
})

test('build blocks known private credentials and credential-bearing URLs before bundling', () => {
  for (const value of ['sb_' + 'secret_not_a_real_key', jwt('service_role'), 'https://user:password@auth.test']) {
    assert.throws(() => assertPublicBuildEnvironment({ VITE_SUPABASE_ANON_KEY: value }), /Refusing to bundle/)
    assert.throws(() => assertPublicBuildEnvironment({ VITE_OTHER: value }), /Refusing to bundle/)
  }
  assert.doesNotThrow(() => assertPublicBuildEnvironment({}))
  assert.doesNotThrow(() => assertPublicBuildEnvironment({ VITE_SUPABASE_ANON_KEY: publicTestKey }))
  assert.doesNotThrow(() => assertPublicBuildEnvironment({ VITE_SUPABASE_ANON_KEY: jwt('anon') }))
  assert.doesNotThrow(() => assertPublicBuildEnvironment({ SUPABASE_SECRET_KEY: 'sb_' + 'secret_server_only' }))
})

test('HTTPS, custom project domains and loopback development are accepted', () => {
  for (const url of ['https://project.supabase.co', 'https://auth.example.org', 'http://localhost:54321', 'http://127.0.0.1:54321', 'http://[::1]:54321']) {
    assert.equal(validateAuthConfiguration(url, publicTestKey).error, null, url)
  }
})

test('only public key types are accepted; diagnostics do not echo secrets', () => {
  assert.equal(validateAuthConfiguration('https://project.example', jwt('anon')).error, null)
  for (const key of ['not-a-real-api-key-fixture', 'sb_publishable_', 'sb_secret_fixture', jwt('service_role'), jwt('authenticated')]) {
    const result = validateAuthConfiguration('https://project.example', key)
    assert.ok(result.error)
    assert.ok(!result.error.includes(key))
  }
})

test('deployment number validation prevents empty values, invalid map coordinates and tight polling', () => {
  for (const value of [undefined, '', ' ', 'NaN', 'Infinity', '-1', '0', '999', '3600001']) {
    assert.equal(boundedEnvNumber(value, 15000, 1000, 3600000), 15000)
  }
  assert.equal(boundedEnvNumber('2000', 15000, 1000, 3600000), 2000)
  assert.equal(boundedEnvNumber('91', 21, -90, 90), 21)
  assert.equal(boundedEnvNumber('0', 21, -90, 90), 0)
})

test('authentication waits resolve and reject normally', async () => {
  assert.equal(await withTimeout(Promise.resolve('token'), 20), 'token')
  await assert.rejects(withTimeout(Promise.reject(new Error('network unavailable')), 20), /network unavailable/)
})

test('stalled authentication has a bounded wait', async () => {
  await assert.rejects(withTimeout(new Promise(() => {}), 5), /timed out/)
})

const flush = () => new Promise((resolve) => setImmediate(resolve))

test('initial session reads publish an actual session', async () => {
  const values = []
  const stop = watchSession({
    read: async () => ({ session: 'actual-session' }),
    subscribe: () => () => {},
    onSession: (value) => values.push(value),
    onError: () => assert.fail('unexpected failure'),
    timeoutMs: 20,
  })
  await flush()
  assert.deepEqual(values, ['actual-session'])
  stop()
})

test('a sign-out event wins over an older startup session', async () => {
  let complete
  let event
  const values = []
  const pending = new Promise((resolve) => { complete = resolve })
  const stop = watchSession({
    read: () => pending,
    subscribe: (callback) => { event = callback; return () => {} },
    onSession: (value) => values.push(value),
    onError: () => assert.fail('unexpected failure'),
    timeoutMs: 20,
  })
  event(null)
  complete({ session: 'stale-session' })
  await flush()
  assert.deepEqual(values, [null])
  stop()
})

test('rejected, failed and stalled session reads leave the loading state', async () => {
  for (const read of [
    async () => { throw new Error('offline') },
    async () => ({ session: null, error: new Error('expired') }),
    () => new Promise(() => {}),
  ]) {
    let failed
    const failure = new Promise((resolve) => { failed = resolve })
    const stop = watchSession({ read, subscribe: () => () => {}, onSession: () => assert.fail('unexpected session'), onError: failed, timeoutMs: 5 })
    await failure
    stop()
  }
})

test('late session results do not update an unmounted screen', async () => {
  let complete
  let unsubscribed = false
  const pending = new Promise((resolve) => { complete = resolve })
  const stop = watchSession({
    read: () => pending,
    subscribe: () => () => { unsubscribed = true },
    onSession: () => assert.fail('updated after unmount'),
    onError: () => assert.fail('updated after unmount'),
    timeoutMs: 20,
  })
  stop()
  complete({ session: 'late-session' })
  await flush()
  assert.equal(unsubscribed, true)
})
