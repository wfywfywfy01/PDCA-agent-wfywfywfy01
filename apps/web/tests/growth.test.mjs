import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

const html = await readFile(new URL('../../../pdca-workbench/frontend/growth.html', import.meta.url), 'utf8')
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace(/loadAssets\(\)\.catch[\s\S]*$/, '')

function page(respond) {
  const elements = Object.fromEntries([
    'aFile', 'msg', 't1', 'b1', 'r1', 'k1', 'm1', 's1', 'h1', 'c1',
    'save1', 'send1', 'push1', 'fKind', 'contents', 'statInfo', 'stats', 'unresolved',
    'g4Btn', 'seoTable', 'seoInfo', 'ga4Info',
  ].map(id => [id, { value: '', checked: false, disabled: false, textContent: '', innerHTML: '', style: {} }]))
  elements.t1.value = 'Edited subject'
  elements.b1.value = 'Edited body'
  elements.r1.value = 'first@example.invalid, second@example.invalid'
  elements.c1.querySelectorAll = () => [elements.t1, elements.b1, elements.r1, elements.k1,
    elements.save1, elements.send1, elements.push1]
  const requests = []
  const context = vm.createContext({
    ...elements,
    document: { getElementById: id => elements[id] ?? null },
    confirm: () => true,
    setTimeout: () => 1,
    clearTimeout: () => {},
    fetch: async (url, options = {}) => {
      requests.push({ url, ...options })
      const result = await respond(url, options)
      return { ok: result.status < 400, status: result.status, json: async () => result.data }
    },
  })
  vm.runInContext(script, context)
  return { elements, requests, run: source => vm.runInContext(source, context) }
}

const saved = { status: 200, data: { title: 'Edited subject', status: 'draft' } }
const stats = { status: 200, data: { rows: [], sent_today: 2, quota_used_today: 2, pending_total: 0, uncertain_total: 0 } }
const sent = { status: 200, data: {
  sent: ['first@example.invalid'], skipped: [], failed: [], pending: [], uncertain: [], cap_left: 24,
} }

for (const action of ['sendContent', 'pushContent']) {
  test(`${action} stops after save failure and retains edits`, async () => {
    const p = page(async (_url, options) => options.method === 'PUT'
      ? { status: 422, data: { detail: '正文不能为空' } } : sent)
    await p.run(`${action}(1)`)
    assert.equal(p.requests.length, 1)
    assert.equal(p.requests[0].method, 'PUT')
    assert.match(p.elements.m1.textContent, /保存失败/)
    assert.match(p.elements.m1.textContent, /正文不能为空/)
    assert.equal(p.elements.b1.value, 'Edited body')
    assert.equal(p.elements.r1.value, 'first@example.invalid, second@example.invalid')
    assert.equal(p.elements.send1.disabled, false)
  })
}

test('sending locks the card against duplicate sends and concurrent saves', async () => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  const p = page(async (url, options) => options.method === 'PUT' ? pending
    : url.endsWith('/stats') ? stats : sent)
  const first = p.run('sendContent(1)')
  try {
    assert.equal(p.elements.send1.disabled, true)
    assert.equal(p.elements.b1.disabled, true)
    assert.match(p.elements.m1.textContent, /发送中/)
    await p.run('sendContent(1)')
    await p.run('saveContent(1)')
    assert.equal(p.requests.length, 1)
  } finally {
    release(saved)
    await first
  }
  assert.equal(p.requests.filter(r => r.url.endsWith('/send')).length, 1)
  assert.equal(p.elements.send1.disabled, false)
  assert.equal(p.elements.b1.disabled, false)
})

test('successful send retains the form and reports a separate stats refresh failure', async () => {
  const p = page(async (url, options) => options.method === 'PUT' ? saved
    : url.endsWith('/stats') ? { status: 503, data: { detail: '统计暂不可用' } } : sent)
  await p.run('sendContent(1)')
  assert.equal(p.requests.some(r => r.url === '/api/growth/contents'), false)
  assert.equal(p.elements.r1.value, 'first@example.invalid, second@example.invalid')
  assert.equal(p.elements.b1.value, 'Edited body')
  assert.match(p.elements.m1.textContent, /已发 1/)
  assert.match(p.elements.m1.textContent, /统计.*刷新失败/)
  assert.equal(p.elements.s1.textContent, '已发送')
})

test('list refresh cannot replace a form while its content is being sent', async () => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  const p = page(async (url, options) => options.method === 'PUT' ? pending
    : url === '/api/growth/contents' ? { status: 200, data: [] }
      : url.endsWith('/stats') ? stats : sent)
  p.elements.contents.innerHTML = 'existing editor'
  const first = p.run('sendContent(1)')
  try {
    await p.run('loadContents()')
    assert.equal(p.elements.contents.innerHTML, 'existing editor')
  } finally {
    release(saved)
    await first
  }
})

test('pending and uncertain results stay visible without automatic retry', async () => {
  const p = page(async (url, options) => options.method === 'PUT' ? saved
    : url.endsWith('/stats') ? stats : { status: 200, data: {
      ...sent.data, sent: [], pending: ['first@example.invalid'], uncertain: ['second@example.invalid'],
    } })
  await p.run('sendContent(1)')
  assert.match(p.elements.m1.textContent, /处理中 1/)
  assert.match(p.elements.m1.textContent, /结果待核实 1/)
  assert.match(p.elements.m1.textContent, /不会自动重发/)
  assert.equal(p.requests.filter(r => r.url.endsWith('/send')).length, 1)
})

test('an interrupted send remains unconfirmed and keeps recipients', async () => {
  const p = page(async (_url, options) => {
    if (options.method === 'PUT') return saved
    throw new TypeError('Failed to fetch')
  })
  await p.run('sendContent(1)')
  assert.match(p.elements.m1.textContent, /结果待核实/)
  assert.match(p.elements.m1.textContent, /不会自动重发/)
  assert.equal(p.elements.r1.value, 'first@example.invalid, second@example.invalid')
  assert.equal(p.elements.send1.disabled, false)
})

test('manual save and review push complete without replacing the form', async () => {
  const p = page(async (_url, options) => options.method === 'PUT' ? saved : { status: 200, data: { ok: true } })
  await p.run('saveContent(1)')
  assert.match(p.elements.m1.textContent, /已保存/)
  await p.run('pushContent(1)')
  assert.match(p.elements.m1.textContent, /已推送审核群/)
  assert.equal(p.elements.s1.textContent, '已推审核')
  assert.equal(p.requests.filter(r => r.url.endsWith('/push')).length, 1)
  assert.equal(p.requests.some(r => r.method === undefined), false)
})

test('GA4 exposes stale snapshot provenance and refresh errors beside the table', async () => {
  const p = page(async () => ({ status: 200, data: {
    table: 'page\tviews\n/example\tN/A', days: 28, top: 100, topics: 3,
    fetched_at: '2026-10-20T00:00:00+00:00', age_hours: 48, stale: true, error: '同步失败',
  } }))
  await p.run('loadGa4()')
  assert.match(p.elements.ga4Info.textContent, /过期/)
  assert.match(p.elements.ga4Info.textContent, /2026-10-20T00:00:00\+00:00/)
  assert.match(p.elements.ga4Info.textContent, /同步失败/)
  assert.match(p.elements.seoTable.value, /N\/A/)
  assert.equal(p.elements.g4Btn.disabled, false)
})

test('GA4 missing metrics display N/A and request failure preserves the existing table', async () => {
  const p = page(async () => ({ status: 200, data: {} }))
  await p.run('loadGa4()')
  assert.match(p.elements.ga4Info.textContent, /N\/A/)
  assert.doesNotMatch(p.elements.ga4Info.textContent, /undefined|null/)
  const failed = page(async () => ({ status: 503, data: { detail: 'GA4 未配置' } }))
  failed.elements.seoTable.value = 'manually supplied table'
  await failed.run('loadGa4()')
  assert.equal(failed.elements.seoTable.value, 'manually supplied table')
  assert.match(failed.elements.ga4Info.textContent, /GA4 未配置/)
  assert.equal(failed.elements.g4Btn.disabled, false)
})

test('stats distinguishes confirmed sends from pending and uncertain attempts', async () => {
  const p = page(async () => ({ status: 200, data: {
    ...stats.data, sent_today: 2, quota_used_today: 5, pending_total: 3, uncertain_total: 1,
  } }))
  await p.run('loadStats()')
  assert.match(p.elements.statInfo.textContent, /今日已确认发送 2/)
  assert.match(p.elements.statInfo.textContent, /今日占用额度 5/)
  assert.match(p.elements.statInfo.textContent, /处理中 3/)
  assert.match(p.elements.statInfo.textContent, /待核实 1/)
  const missing = page(async () => ({ status: 200, data: { rows: [] } }))
  await missing.run('loadStats()')
  assert.match(missing.elements.statInfo.textContent, /今日已确认发送 N\/A/)
  assert.match(missing.elements.statInfo.textContent, /今日占用额度 N\/A/)
  assert.match(missing.elements.statInfo.textContent, /处理中 N\/A/)
  assert.match(missing.elements.statInfo.textContent, /待核实 N\/A/)
})

test('unresolved sends provide escaped mailbox evidence in a collapsed list', async () => {
  const p = page(async () => ({ status: 200, data: {
    ...stats.data, unresolved: [{
      id: 9, content_id: 7, to_addr: 'buyer@example.invalid', status: 'uncertain',
      message_id: '<delivery-9@example.invalid>', claimed_at: '2026-10-23T02:00:00+00:00',
      detail: 'timeout <script>alert("unsafe")</script>',
    }, {
      id: 10, content_id: 8, to_addr: 'next@example.invalid', status: 'pending',
      message_id: '', claimed_at: null, detail: '',
    }],
  } }))
  await p.run('loadStats()')
  const rendered = p.elements.unresolved.innerHTML
  assert.match(rendered, /<details>/)
  assert.doesNotMatch(rendered, /<details[^>]*open/)
  assert.match(rendered, /最多 100 条/)
  assert.match(rendered, /Message-ID/)
  assert.match(rendered, /人工.*核对/)
  assert.match(rendered, /不会自动重发/)
  assert.match(rendered, /<td>7<\/td>/)
  assert.match(rendered, /buyer@example\.invalid/)
  assert.match(rendered, /待核实/)
  assert.match(rendered, /处理中/)
  assert.match(rendered, /2026-10-23T02:00:00\+00:00/)
  assert.match(rendered, /&lt;delivery-9@example\.invalid&gt;/)
  assert.match(rendered, /&lt;script&gt;alert\(&quot;unsafe&quot;\)&lt;\/script&gt;/)
  assert.match(rendered, /N\/A/)
  assert.doesNotMatch(rendered, /<script>/)
})

test('empty unresolved list removes stale evidence and takes no page space', async () => {
  const p = page(async () => ({ status: 200, data: { ...stats.data, unresolved: [] } }))
  p.elements.unresolved.innerHTML = 'previous unresolved records'
  await p.run('loadStats()')
  assert.equal(p.elements.unresolved.innerHTML, '')
})
