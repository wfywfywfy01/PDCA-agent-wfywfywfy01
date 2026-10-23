import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { test } from 'node:test'

// Execute the real setup and derived card, replacing only framework and API boundaries.
function mountDashboard(apiGet) {
  const source = readFileSync(new URL('../src/pages/DashboardPage.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
    .replace(/^import .* from .*$/gm, '')
  const names = ['ref', 'computed', 'nextTick', 'onMounted', 'onBeforeUnmount',
    'useRouter', 'apiGet', 'apiPost', 'HttpError', 'echarts',
    'LineChart', 'GridComponent', 'TooltipComponent', 'CanvasRenderer']
  const values = [
    value => ({ value }), getter => ({ get value() { return getter() } }),
    async () => {}, () => {}, () => {}, () => ({ replace() {} }),
    apiGet, async () => {}, class extends Error {}, { use() {} }, {}, {}, {}, {},
  ]
  const code = stripTypeScriptTypes(script, { mode: 'strip' })
  return new Function(...names, code + '\nreturn { loadAll, loadSellIn, sellInCard, dateText, period, loading, overview, sellIn };')(...values)
}

function deferred() {
  let resolve, reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function responses(sellIn, overview = {}) {
  return path => {
    if (path.startsWith('/api/dashboard/sell-in?')) return sellIn()
    if (path.startsWith('/api/dashboard/overview?')) return Promise.resolve(overview)
    if (path.startsWith('/api/dealer/sellin-summary?')) return Promise.resolve({ dealers: [], trend: [] })
    return Promise.resolve([])
  }
}

test('a faster overview cannot flash its snapshot while Sell-in is pending', async () => {
  const pending = deferred()
  const page = mountDashboard(responses(() => pending.promise, {
    sellInWan: 1186.09, sellInSub: '总览旧批次', dataState: { sellIn: 'live' },
    dataSource: { sellIn: 'snapshot' }, dataAsOf: '2026-10-22T21:00:00Z',
  }))
  const load = page.loadAll()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(page.overview.value.sellInWan, 1186.09)
  assert.equal(page.sellInCard.value.value, '…')
  assert.match(page.sellInCard.value.note, /加载中/)
  assert.doesNotMatch(page.sellInCard.value.note, /实时接口无数据|总览旧批次/)
  assert.equal(page.sellInCard.value.source, '')
  assert.equal(page.sellInCard.value.asOf, null)
  pending.resolve({ wan: 1166.32, amount: 11663200, state: 'live', note: '本月实时',
    source: 'vertu-cli sales +headline-kpi', as_of: '2026-10-23T11:08:07+08:00' })
  await load
  assert.equal(page.sellInCard.value.value, '1,166.32 万')
  assert.equal(page.sellInCard.value.source, 'vertu-cli sales +headline-kpi')
})

test('missing Sell-in does not borrow the overview amount or freshness metadata', async () => {
  const page = mountDashboard(responses(async () => ({ amount: null, wan: null, state: 'missing', note: '没有可核验金额' }), {
    sellInWan: 1186.09, sellInSub: '另一批次', dataState: { sellIn: 'live' },
    dataSource: { sellIn: 'snapshot' }, dataAsOf: '2026-10-22T21:00:00Z',
  }))
  await page.loadAll()
  assert.deepEqual(page.sellInCard.value, {
    value: 'N/A', unit: '', state: 'missing', note: '没有可核验金额',
    source: '', asOf: null, failed: false,
  })
})

test('failed Sell-in stays unavailable with a retryable error instead of an overview amount', async () => {
  const page = mountDashboard(responses(async () => { throw new Error('offline') }, {
    sellInWan: 1186.09, dataState: { sellIn: 'live' }, dataSource: { sellIn: 'snapshot' },
  }))
  await page.loadAll()
  assert.equal(page.sellInCard.value.value, 'N/A')
  assert.equal(page.sellInCard.value.failed, true)
  assert.match(page.sellInCard.value.note, /加载失败.*重试/)
  assert.equal(page.sellInCard.value.source, '')
  assert.equal(page.sellInCard.value.asOf, null)
})

test('verified zero and amount-only Sell-in values keep their CNY representation', async () => {
  for (const [payload, expected] of [
    [{ wan: 0, amount: 0 }, '0.00 万'],
    [{ amount: 0 }, '¥ 0.00'],
    [{ amount: 1234.56 }, '¥ 1,234.56'],
  ]) {
    const page = mountDashboard(responses(async () => ({ ...payload, state: 'live' }), { sellInWan: 1186.09 }))
    await page.loadAll()
    assert.equal(page.sellInCard.value.value, expected)
    assert.equal(page.sellInCard.value.unit, 'CNY')
    assert.equal(page.sellInCard.value.source, '')
    assert.equal(page.sellInCard.value.asOf, null)
  }
})

test('a backend-confirmed fallback preserves only its own snapshot metadata', async () => {
  const page = mountDashboard(responses(async () => ({ wan: 1180, state: 'stale',
    note: '实时查询失败，展示已核验快照', source: 'confirmed_snapshot', as_of: '2026-10-23T08:00:00Z' }), {
    sellInWan: 1186.09, dataState: { sellIn: 'live' }, dataSource: { sellIn: 'different_snapshot' },
    dataAsOf: '2026-10-22T21:00:00Z',
  }))
  await page.loadAll()
  assert.deepEqual(page.sellInCard.value, {
    value: '1,180.00 万', unit: 'CNY', state: 'stale', note: '实时查询失败，展示已核验快照',
    source: 'confirmed_snapshot', asOf: '2026-10-23T08:00:00Z', failed: false,
  })
})

test('Sell-in finishes independently while the overview remains slow', async () => {
  const pending = deferred()
  const otherResponses = responses(async () => ({ wan: 1166.32, state: 'live', note: '实时已返回' }))
  const page = mountDashboard(path => path.startsWith('/api/dashboard/overview?') ? pending.promise : otherResponses(path))
  const load = page.loadAll()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(page.loading.value, true)
  assert.equal(page.sellInCard.value.value, '1,166.32 万')
  assert.equal(page.sellInCard.value.note, '实时已返回')
  pending.resolve({ sellInWan: 1186.09 })
  await load
  assert.equal(page.sellInCard.value.value, '1,166.32 万')
})

test('an older date response cannot overwrite or finish a newer pending Sell-in request', async () => {
  const first = deferred()
  const second = deferred()
  const page = mountDashboard(responses(() => page.dateText.value === '2026-10-22' ? first.promise : second.promise))
  page.dateText.value = '2026-10-22'
  const oldLoad = page.loadAll()
  page.dateText.value = '2026-10-23'
  const newLoad = page.loadAll()
  first.resolve({ wan: 999, state: 'live', source: 'old_date' })
  await oldLoad
  assert.equal(page.sellInCard.value.value, '…')
  assert.equal(page.sellInCard.value.source, '')
  second.resolve({ wan: 1166.32, state: 'live', source: 'current_date' })
  await newLoad
  assert.equal(page.sellInCard.value.value, '1,166.32 万')
  assert.equal(page.sellInCard.value.source, 'current_date')
})

test('retrying Sell-in clears the previous amount and metadata until its response arrives', async () => {
  const pending = deferred()
  let retry = false
  const page = mountDashboard(responses(() => retry ? pending.promise : Promise.resolve({ wan: 100,
    source: 'previous_response', as_of: '2026-10-22T21:00:00Z', state: 'live' })))
  await page.loadAll()
  retry = true
  const load = page.loadSellIn()
  assert.equal(page.sellInCard.value.value, '…')
  assert.equal(page.sellInCard.value.source, '')
  assert.equal(page.sellInCard.value.asOf, null)
  pending.resolve({ wan: 1166.32, state: 'live' })
  await load
  assert.equal(page.sellInCard.value.value, '1,166.32 万')
})
