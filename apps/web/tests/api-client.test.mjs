import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { apiGet, apiPost, apiRequest, HttpError } from '../src/api/client.ts'

const originalFetch = globalThis.fetch
const originalWindow = globalThis.window
afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalWindow === undefined) delete globalThis.window
  else globalThis.window = originalWindow
})

test('authenticated JSON writes retain the original-export idempotency header', async () => {
  globalThis.fetch = async (path, init) => {
    assert.equal(path, '/api/knowledge/exports')
    assert.equal(init.credentials, 'include')
    assert.equal(init.cache, 'no-store')
    assert.equal(init.headers.get('Content-Type'), 'application/json')
    assert.equal(init.headers.get('Idempotency-Key'), 'test-request-unique')
    assert.deepEqual(JSON.parse(init.body), { reason: 'QA purpose only' })
    return Response.json({ export_id: 'test' })
  }
  assert.deepEqual(await apiPost('/api/knowledge/exports', { reason: 'QA purpose only' },
    new Headers({ 'Idempotency-Key': 'test-request-unique' })), { export_id: 'test' })
})

test('validation errors remain readable and never echo submitted secrets', async () => {
  globalThis.fetch = async () => Response.json({ detail: [
    { loc: ['body', 'password'], msg: 'Value is too short', input: 'must-not-appear' },
  ] }, { status: 422 })
  await assert.rejects(apiPost('/api/auth/login', {}), (error) => {
    assert.ok(error instanceof HttpError)
    assert.equal(error.detail, 'password: Value is too short')
    assert.ok(!error.message.includes('must-not-appear'))
    return true
  })
})

test('an expired protected API session requests login', async () => {
  const events = []
  globalThis.window = { dispatchEvent: (event) => events.push(event.type) }
  globalThis.fetch = async () => Response.json({ detail: '未登录' }, { status: 401 })
  await assert.rejects(apiGet('/api/my-stores'), { status: 401 })
  assert.deepEqual(events, ['pdca-session-expired'])
})

test('incorrect login, password-change and reauthentication stay in their forms', async () => {
  const events = []
  globalThis.window = { dispatchEvent: (event) => events.push(event.type) }
  globalThis.fetch = async () => Response.json({ detail: '密码验证失败' }, { status: 401 })
  for (const path of ['/api/auth/login', '/api/auth/change-password', '/api/knowledge/reauth']) {
    await assert.rejects(apiPost(path, {}), { status: 401 })
  }
  assert.deepEqual(events, [])
})

test('non-JSON proxy failure gets an actionable HTTP error', async () => {
  globalThis.fetch = async () => new Response('upstream unavailable', { status: 502 })
  await assert.rejects(apiGet('/api/dashboard/sell-in'), { status: 502, message: 'HTTP 502' })
})

test('download responses remain binary for the two-step export flow', async () => {
  globalThis.fetch = async () => new Response('QA-file-content', { headers: { 'Content-Type': 'application/octet-stream' } })
  assert.equal(await (await apiRequest('/api/knowledge/exports/test/download', { method: 'POST' })).text(), 'QA-file-content')
})
