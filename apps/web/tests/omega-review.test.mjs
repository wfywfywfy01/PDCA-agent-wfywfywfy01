import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

function mountReview(apiGet = () => {}, apiPost = () => {}) {
  const source = readFileSync(new URL('../src/pages/OmegaPage.vue', import.meta.url), 'utf8')
    .replaceAll('import.meta.env.MODE', "'test'")
    .replaceAll('import.meta.env.BASE_URL', "'/'")
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: 'omega-review-test' })
  const template = compileTemplate({
    source: descriptor.template.content, filename: 'OmegaPage.vue', id: 'omega-review-test',
    compilerOptions: { bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [])
  const exports = {}
  let leaveGuard
  const stubComponent = { render: () => null }
  const modules = {
    vue: { ...vue, onMounted() {}, onBeforeUnmount() {}, watch() {} },
    'vue-router': { useRouter: () => ({ replace() {} }), onBeforeRouteLeave: (guard) => { leaveGuard = guard } },
    '@/api/client': { apiGet, apiPost, apiPatch() {}, apiRequest() {}, HttpError: class extends Error {} },
    '@/components/AppNav.vue': { default: stubComponent },
    '@/components/omega/OmegaSetup.vue': { default: stubComponent },
    '@/components/omega/OmegaMeetingMaterials.vue': { default: stubComponent },
    '@/components/omega/OmegaMemoryReview.vue': { default: stubComponent },
    '@/components/omega/OmegaProfiles.vue': { default: stubComponent },
  }
  for (const content of [script.content, template.code]) {
    const { outputText } = ts.transpileModule(content, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    })
    new Function('require', 'exports', outputText)((name) => {
      assert.ok(name in modules, `Unexpected import ${name}`)
      return modules[name]
    }, exports)
  }
  const page = exports.default.setup({}, { expose() {} })
  page.loading.value = false
  page.setupOpen.value = false
  page.me.value = { id: 1, role: 'sales' }
  return { page, leaveGuard: () => leaveGuard,
    html: () => renderToString(vue.createSSRApp({ ...exports.default, render: exports.render, setup: () => page })) }
}

function dimension(key, score) {
  return { key, score, reason: key, quotes: [{ speaker: 'sales', text: '可核验的销售原话' }] }
}

test('history navigation keeps empty states separate from older-page controls', async () => {
  const { page, html } = mountReview()
  page.sidebarTab.value = 'assignments'
  assert.match(await html(), /暂无指派练习/)
  page.assignments.value = [{ id: 'assignment-1', case_id: 'case-1', target_dimension: 'objections',
    status: 'pending', attempts: [] }]
  page.assignmentsHasMore.value = true
  assert.doesNotMatch(await html(), /暂无指派练习/)
  assert.match(await html(), /加载更早指派/)
  page.sidebarTab.value = 'sessions'
  page.sessions.value = Array.from({ length: 6 }, (_, index) => ({ id: `session-${index}`,
    case_id: 'case-1', status: 'ended' }))
  page.sessionsHasMore.value = true
  page.showAllSessions.value = true
  assert.doesNotMatch(await html(), /还没有演练记录/)
  assert.match(await html(), /加载更早记录/)
})

test('record view returns to the same card setup, while a new practice resets it', async () => {
  const { page, html } = mountReview()
  page.chosenSession.value = { id: 'session-1', status: 'ended', case_snapshot: page.blankDraft(), segments: [] }
  assert.match(await html(), /返回场景卡/)
  const setupKey = page.setupKey.value
  page.newCase(false)
  assert.equal(page.setupOpen.value, true)
  assert.equal(page.chosenSession.value, null)
  assert.equal(page.setupKey.value, setupKey)
  page.newCase()
  assert.equal(page.setupKey.value, setupKey + 1)
})

test('equal rubric ratios select the same first skill regardless of report array order', () => {
  const { page } = mountReview()
  page.chosenSession.value = { case_snapshot: { score_weights: { concessions: 12, value: 12, information: 12 } } }
  for (const dimensions of [
    [dimension('concessions', 4), dimension('value', 4), dimension('information', 6)],
    [dimension('value', 4), dimension('information', 6), dimension('concessions', 4)],
  ]) {
    page.report.value = { content: { dimensions } }
    assert.equal(page.coachingPoint.value.key, 'value', 'tied blockers use the published rubric order')
    assert.equal(page.strengthPoint.value.key, 'information')
  }
  page.report.value = { content: { dimensions: [dimension('concessions', 6), dimension('information', 6), dimension('value', 6)] } }
  assert.equal(page.coachingPoint.value.key, 'information')
  assert.equal(page.strengthPoint.value.key, 'information', 'tied strengths use the same rubric order')
})

test('report weights determine relative strengths and training percentage', () => {
  const { page } = mountReview()
  page.chosenSession.value = { case_snapshot: { score_weights: { value: 12, listening: 8 } } }
  page.report.value = { content: {
    score_weights: { listening: 20, value: 10 },
    dimensions: [dimension('value', 5), dimension('listening', 8), dimension('outcome', 0)],
  } }
  assert.equal(page.coachingPoint.value.key, 'listening')
  assert.equal(page.strengthPoint.value.key, 'value')
  assert.equal(page.focusPercent.value, 40)
})

test('microphone permission errors give actionable Chinese guidance', () => {
  const { page } = mountReview()
  assert.match(page.detail(new DOMException('Permission denied', 'NotAllowedError')), /麦克风权限被拒绝/)
  assert.match(page.detail(new DOMException('Requested device not found', 'NotFoundError')), /未找到麦克风/)
})

test('corrected speech retains its original recognition only in collapsed transcript details', async () => {
  const { page, html } = mountReview()
  const original = '今天先不急着订手单。'
  const corrected = '今天先不急着订首单。'
  page.chosenSession.value = { id: 'session', owner_id: 1, status: 'ended', case_snapshot: page.blankDraft(), segments: [
    { id: 'corrected', speaker: 'sales', text: corrected, asr_original: original },
    { id: 'unchanged', speaker: 'sales', text: '不改变的识别', asr_original: '不改变的识别' },
    { id: 'typed', speaker: 'sales', text: '文字输入没有识别原文' },
  ] }
  const rendered = await html()
  assert.ok(rendered.includes(corrected), 'the canonical transcript remains visible')
  const details = [...rendered.matchAll(/<details\b([^>]*)>([\s\S]*?)<\/details>/g)]
    .filter((match) => match[2].includes(original))
  assert.equal(details.length, 1, 'the corrected segment keeps its original recognition')
  assert.ok(!/\bopen(?:\s|=|$)/.test(details[0][1]), 'recognition history is collapsed by default')
  assert.match(details[0][2], /<summary[^>]*>查看原始识别<\/summary>/)
  assert.equal(rendered.split('查看原始识别').length - 1, 1, 'unchanged and typed segments need no history entry')
  assert.ok(!rendered.replace(details[0][0], '').includes(original), 'original recognition does not replace the canonical dialogue')
})

test('report evidence links back to the matching transcript turn', async () => {
  const { page, html } = mountReview()
  const quote = { segment_id: 'line-1', speaker: 'sales', start: 0, end: 8, text: '请核对退换条件。' }
  page.chosenSession.value = { id: 'practice-1', owner_id: 1, status: 'ended', case_snapshot: page.blankDraft(),
    segments: [{ id: 'line-1', speaker: 'sales', text: quote.text }] }
  page.report.value = { id: 'report-1', reviews: [], content: { score: { total: null, earned: 0, available: 0 },
    outcome: { status: 'unverified', reason: '尚无承诺', quotes: [] },
    dimensions: [{ key: 'objections', score: 3, reason: '需要再追问', quotes: [quote] }] } }
  const rendered = await html()
  assert.match(rendered, /id="omega-segment-line-1"/)
  assert.match(rendered, /查看第 1 条原话/)
  assert.match(rendered, /omega-quote-link/)
  assert.match(rendered, /omega-score-summary"><strong>证据不足<\/strong>/)
})

test('job status polling recovers after one network failure', async () => {
  let jobReads = 0
  const { page } = mountReview(async (path) => {
    if (path === '/api/omega/jobs/job-1') {
      if (++jobReads === 1) throw new Error('temporary network failure')
      return { id: 'job-1', status: 'succeeded', result_id: '', kind: 'turn' }
    }
    if (path === '/api/omega/sessions/session-1') return { id: 'session-1', status: 'active', segments: [] }
    throw new Error(`Unexpected request ${path}`)
  })
  page.chosenSession.value = { id: 'session-1', status: 'active' }
  page.activeJob.value = { id: 'job-1', status: 'running', kind: 'turn' }
  const originalSetTimeout = globalThis.setTimeout
  const originalClearTimeout = globalThis.clearTimeout
  let retry
  globalThis.setTimeout = (callback, delay) => { retry = { callback, delay }; return 1 }
  globalThis.clearTimeout = () => {}
  try {
    await page.pollJob()
    assert.ok(retry, 'temporary failure schedules another status check')
    assert.match(page.error.value, /temporary network failure/)
    await retry.callback()
    assert.equal(page.activeJob.value.status, 'succeeded')
    assert.equal(page.error.value, '')
  } finally {
    globalThis.setTimeout = originalSetTimeout
    globalThis.clearTimeout = originalClearTimeout
  }
})

test('a failed text reply retries the saved turn without submitting another sales message', async () => {
  const calls = []
  const { page, html } = mountReview(() => {}, async (path) => {
    calls.push(path)
    return { id: 'failed-turn', status: 'queued', result_id: '', kind: 'turn' }
  })
  page.chosenSession.value = { id: 'practice-1', owner_id: 1, status: 'active',
    case_snapshot: page.blankDraft(), segments: [{ id: 'sales-1', speaker: 'sales', text: '请谈谈库存风险。' }] }
  page.textReady.value = true
  page.activeJob.value = { id: 'failed-turn', kind: 'turn', status: 'failed', error: '模型超时' }
  assert.match(await html(), /重试对手回复/)
  await page.retryTurn()
  assert.deepEqual(calls, ['/api/omega/jobs/failed-turn/retry'])
  assert.equal(page.activeJob.value.status, 'queued')
})

test('unknown voice tail explains why an ended session cannot be scored', async () => {
  const { page, html } = mountReview()
  page.chosenSession.value = { id: 'interrupted-voice', owner_id: 1, status: 'ended',
    report_blocked: true, report_blocked_message: '语音尾稿未确认；本场不能评分', case_snapshot: page.blankDraft(),
    segments: [{ id: 'saved-1', speaker: 'sales', text: '已保存的发言' }] }
  const rendered = await html()
  assert.match(rendered, /尾稿未确认/)
  assert.doesNotMatch(rendered, /生成复盘/)
})

test('active session with unrecoverable voice tail only offers ending for partial review', async () => {
  const posts = []
  const { page, html } = mountReview(() => {}, async (path) => { posts.push(path); return {} })
  page.chosenSession.value = { id: 'timed-out-voice', owner_id: 1, status: 'active',
    voice_tail_unrecoverable: true, case_snapshot: page.blankDraft(),
    segments: [{ id: 'saved-1', speaker: 'sales', text: '已经保存的原话' }] }
  page.realtimeReady.value = true
  page.textReady.value = true
  page.textInput.value = '继续谈判'
  const rendered = await html()
  assert.match(rendered, /结束并查看部分复盘/)
  assert.match(rendered, /已保存的原话/)
  assert.doesNotMatch(rendered, /开始实时对话|继续实时对话|文字发言|重试对手回复/)
  await page.sendTurn()
  await page.startVoice()
  assert.deepEqual(posts, [])
})

test('voice capacity reached offers normal review and blocks further input', async () => {
  const posts = []
  const { page, html } = mountReview(() => {}, async (path) => { posts.push(path); return {} })
  page.chosenSession.value = { id: 'full-voice', owner_id: 1, status: 'active',
    voice_capacity_reached: true, case_snapshot: page.blankDraft(),
    segments: [{ id: 'saved-1', speaker: 'sales', text: '请确认试单条件。' }] }
  page.realtimeReady.value = true
  page.textReady.value = true
  page.voiceInterrupted.value = true
  page.textInput.value = '继续谈判'
  page.activeJob.value = { id: 'failed-turn', kind: 'turn', status: 'failed' }
  const rendered = await html()
  assert.match(rendered, /本场发言接近上限，结束并复盘/)
  assert.doesNotMatch(rendered, /继续实时对话|开始实时对话|文字发言|部分复盘|语音尾稿未确认|重试对手回复/)
  await page.sendTurn()
  await page.startVoice()
  await page.retryTurn()
  assert.deepEqual(posts, [])
})

test('a voice tail error without saved lines offers ending without promising a report', async () => {
  const { page, html } = mountReview()
  page.chosenSession.value = { id: 'empty-voice', owner_id: 1, status: 'active',
    voice_tail_unrecoverable: true, case_snapshot: page.blankDraft(), segments: [] }
  page.realtimeReady.value = true
  const rendered = await html()
  assert.match(rendered, /结束本场/)
  assert.match(rendered, /没有可复盘的原话/)
  assert.doesNotMatch(rendered, /结束并查看部分复盘|开始实时对话/)
})

test('two-minute voice warning stays visible without ending the call', async () => {
  const { page, html } = mountReview()
  page.chosenSession.value = { id: 'voice-1', owner_id: 1, status: 'active',
    case_snapshot: page.blankDraft(), segments: [] }
  page.realtimeReady.value = true
  const previous = Object.fromEntries(['navigator', 'window', 'AudioContext', 'WebSocket', 'location']
    .map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]))
  let socket
  try {
    Object.defineProperty(globalThis, 'navigator', { configurable: true,
      value: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) } } })
    globalThis.window = { AudioWorkletNode: class {} }
    globalThis.location = { protocol: 'https:', host: 'testserver' }
    globalThis.AudioContext = class {
      destination = {}
      async resume() {}
      async close() {}
      createGain() { return { gain: { value: 1 }, connect: () => ({ connect() {} }) } }
      createDynamicsCompressor() { return { threshold: {}, knee: {}, ratio: {} } }
    }
    globalThis.WebSocket = class {
      constructor() { socket = this }
      close() {}
    }
    await page.startVoice()
    await socket.onmessage({ data: JSON.stringify({ type: 'ending_soon', seconds_remaining: 120,
      message: '距离通话时长上限约 2 分钟，请尽快收尾并复盘' }) })
    assert.equal(page.voiceClosing.value, false)
    assert.equal(page.voiceConnecting.value, true)
    assert.match(await html(), /距离通话时长上限约 2 分钟/)
    page.stopVoice()
  } finally {
    for (const [name, descriptor] of Object.entries(previous)) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor)
      else delete globalThis[name]
    }
  }
})

test('server voice error waits for saved tail state before showing the recovery action', async () => {
  const initial = { id: 'voice-error', owner_id: 1, status: 'active',
    case_snapshot: null, segments: [{ id: 'saved-1', speaker: 'sales', text: '已保存的原话' }] }
  const reads = []
  const { page, html } = mountReview(async (path) => {
    reads.push(path)
    return { ...initial, voice_tail_unrecoverable: true }
  })
  initial.case_snapshot = page.blankDraft()
  page.chosenSession.value = initial
  page.realtimeReady.value = true
  page.textReady.value = true
  const previous = Object.fromEntries(['navigator', 'window', 'AudioContext', 'WebSocket', 'location']
    .map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]))
  let socket
  try {
    Object.defineProperty(globalThis, 'navigator', { configurable: true,
      value: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) } } })
    globalThis.window = { AudioWorkletNode: class {} }
    globalThis.location = { protocol: 'https:', host: 'testserver' }
    globalThis.AudioContext = class {
      destination = {}
      async resume() {}
      async close() {}
      createGain() { return { gain: { value: 1 }, connect: () => ({ connect() {} }) } }
      createDynamicsCompressor() { return { threshold: {}, knee: {}, ratio: {} } }
    }
    globalThis.WebSocket = class {
      constructor() { socket = this; this.closedByClient = false }
      close() { this.closedByClient = true }
    }
    await page.startVoice()
    await socket.onmessage({ data: JSON.stringify({ type: 'error', message: '语音连接异常' }) })
    assert.equal(socket.closedByClient, false, 'keep the socket until backend confirms the tail state')
    await socket.onmessage({ data: JSON.stringify({ type: 'closed' }) })
    await new Promise(setImmediate)
    assert.deepEqual(reads, ['/api/omega/sessions/voice-error'])
    const rendered = await html()
    assert.match(rendered, /结束并查看部分复盘/)
    assert.doesNotMatch(rendered, /开始实时对话|继续实时对话|文字发言/)
  } finally {
    page.stopVoice()
    for (const [name, descriptor] of Object.entries(previous)) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor)
      else delete globalThis[name]
    }
  }
})

test('partial voice report preserves saved quotes but has no score or supervisor outcome confirmation', async () => {
  const { page, html } = mountReview()
  const quote = { segment_id: 'saved-1', speaker: 'sales', start: 0, end: 9, text: '我们再核对库存风险。' }
  page.me.value = { id: 2, role: 'manager' }
  page.chosenSession.value = { id: 'interrupted-voice', owner_id: 1, status: 'ended', report_partial: true,
    report_warning: '语音尾稿未完成', case_snapshot: page.blankDraft(),
    segments: [{ id: 'saved-1', speaker: 'sales', text: quote.text }] }
  page.report.value = { id: 'partial-1', reviews: [], content: { evidence_status: 'incomplete',
    incomplete_reason: '语音尾稿未完成', saved_quotes: [quote], score: { total: null, earned: 0, available: 0 },
    outcome: { status: 'unverified', reason: '逐字稿不完整', quotes: [] }, dimensions: [] } }
  const rendered = await html()
  assert.match(rendered, /部分复盘，证据不完整，不能评分\/达标/)
  assert.match(rendered, /语音尾稿未完成/)
  assert.match(rendered, /我们再核对库存风险。/)
  assert.match(rendered, /查看第 1 条原话/)
  assert.doesNotMatch(rendered, /确认 AI 的目标判断|驳回 AI 的目标判断|指派针对性练习|本场综合评分/)
})

test('ending a voice session opens its saved partial report without the text model', async () => {
  const reads = []
  const posts = []
  const partial = { id: 'partial-1', reviews: [], content: { evidence_status: 'incomplete',
    incomplete_reason: '语音尾稿未完成', saved_quotes: [], score: { total: null, earned: 0, available: 0 } } }
  const { page } = mountReview(async (path) => {
    reads.push(path)
    if (path === '/api/omega/reports/partial-1') return partial
    if (['/api/omega/cases', '/api/omega/sessions', '/api/omega/assignments'].includes(path)) return []
    throw new Error(`Unexpected GET ${path}`)
  }, async (path) => {
    posts.push(path)
    if (path === '/api/omega/sessions/voice-1/finish') return { id: 'voice-1', owner_id: 1,
      status: 'ended', report_partial: true, report_blocked: false, latest_report_id: 'partial-1',
      segments: [{ id: 'saved-1', speaker: 'sales', text: '已保存的原话' }] }
    throw new Error(`Unexpected POST ${path}`)
  })
  const previousWindow = globalThis.window
  globalThis.window = { speechSynthesis: { cancel() {} } }
  try {
    page.chosenSession.value = { id: 'voice-1', owner_id: 1, status: 'active', segments: [] }
    page.textReady.value = false
    await page.finishSession()
    assert.equal(page.report.value?.id, 'partial-1')
    assert.deepEqual(posts, ['/api/omega/sessions/voice-1/finish'])
    assert.ok(reads.includes('/api/omega/reports/partial-1'))
    assert.match(page.notice.value, /部分复盘/)
  } finally { globalThis.window = previousWindow }
})

test('a normal report without full score coverage does not claim a saved total', async () => {
  const report = { id: 'report-1', reviews: [], content: {
    score: { total: null, earned: 8, available: 12 }, dimensions: [],
    outcome: { status: 'unverified', reason: '证据不足', quotes: [] },
  } }
  const ended = { id: 'practice-1', owner_id: 1, status: 'ended', latest_report_id: 'report-1', segments: [
    { id: 'saved-1', speaker: 'sales', text: '请核对库存风险。' },
  ] }
  const { page, html } = mountReview(async (path) => {
    if (path === '/api/omega/reports/report-1') return report
    if (path === '/api/omega/jobs/report-job') return { id: 'report-job', kind: 'report', status: 'succeeded', result_id: 'report-1' }
    if (path === '/api/omega/sessions/practice-1') return ended
    if (['/api/omega/cases', '/api/omega/sessions', '/api/omega/assignments'].includes(path)) return []
    throw new Error(`Unexpected GET ${path}`)
  }, async (path) => {
    if (path === '/api/omega/sessions/practice-1/finish') return ended
    throw new Error(`Unexpected POST ${path}`)
  })
  const previousWindow = globalThis.window
  globalThis.window = { speechSynthesis: { cancel() {} } }
  try {
    page.chosenSession.value = { id: 'practice-1', owner_id: 1, status: 'active', segments: ended.segments }
    await page.finishSession()
    assert.match(page.notice.value, /证据不足.*暂无总分/)
    assert.doesNotMatch(page.notice.value, /评分已保存/)
    const rendered = await html()
    assert.match(rendered, /已评分项 8 \/ 12 分/)
    assert.match(rendered, /仅已观察维度，覆盖 12\/100；暂无综合总分/)

    page.chosenSession.value = ended
    page.activeJob.value = { id: 'report-job', kind: 'report', status: 'running', result_id: '' }
    await page.pollJob()
    assert.match(page.notice.value, /证据不足.*暂无总分/)
    assert.doesNotMatch(page.notice.value, /评分已保存/)
  } finally { globalThis.window = previousWindow }
})

test('an older ended voice session can generate its partial report without the text model', async () => {
  const posts = []
  const partial = { id: 'partial-legacy', reviews: [], content: { evidence_status: 'incomplete',
    incomplete_reason: '语音尾稿未完成', saved_quotes: [], score: { total: null, earned: 0, available: 0 } } }
  const { page, html } = mountReview(async (path) => {
    if (path === '/api/omega/jobs/job-partial') return { id: 'job-partial', kind: 'report', status: 'succeeded', result_id: 'partial-legacy' }
    if (path === '/api/omega/reports/partial-legacy') return partial
    if (path === '/api/omega/sessions/legacy-voice') return { ...page.chosenSession.value, latest_report_id: 'partial-legacy' }
    if (['/api/omega/cases', '/api/omega/sessions', '/api/omega/assignments'].includes(path)) return []
    throw new Error(`Unexpected GET ${path}`)
  }, async (path) => {
    posts.push(path)
    if (path === '/api/omega/sessions/legacy-voice/reports') return { id: 'job-partial', kind: 'report', status: 'succeeded', result_id: 'partial-legacy' }
    throw new Error(`Unexpected POST ${path}`)
  })
  const previousSetTimeout = globalThis.setTimeout
  const previousClearTimeout = globalThis.clearTimeout
  globalThis.setTimeout = () => 1
  globalThis.clearTimeout = () => {}
  try {
    page.chosenSession.value = { id: 'legacy-voice', owner_id: 1, status: 'ended', report_partial: true,
      report_blocked: false, report_warning: '语音尾稿未完成', case_snapshot: page.blankDraft(),
      segments: [{ id: 'saved-1', speaker: 'sales', text: '已保存的原话' }] }
    page.textReady.value = false
    const rendered = await html()
    assert.match(rendered, /生成部分复盘/)
    assert.doesNotMatch(rendered, /复盘服务暂不可用/)
    await page.makeReport()
    assert.deepEqual(posts, ['/api/omega/sessions/legacy-voice/reports'])
    await page.pollJob()
    assert.equal(page.report.value?.id, 'partial-legacy')
  } finally {
    globalThis.setTimeout = previousSetTimeout
    globalThis.clearTimeout = previousClearTimeout
  }
})

test('voice pause waits for the backend control acknowledgement without a premature timeout', async () => {
  const { page, html } = mountReview()
  const previousWebSocket = globalThis.WebSocket
  const previousSetTimeout = globalThis.setTimeout
  const previousClearTimeout = globalThis.clearTimeout
  const timers = []
  const packets = []
  globalThis.WebSocket = { OPEN: 1 }
  globalThis.setTimeout = (callback, delay) => { timers.push({ callback, delay }); return timers.length }
  globalThis.clearTimeout = () => {}
  try {
    page.voiceSocket = { readyState: 1, send: (packet) => packets.push(JSON.parse(packet)) }
    page.voiceConnected.value = true
    page.controlVoice('pause')
    assert.equal(packets[0].action, 'pause')
    assert.equal(page.voicePhase.value, 'pausing')
    assert.ok(timers.some((timer) => timer.delay === 55000), 'backend may need 50 seconds to save the last utterance')
    assert.match(await html(), /正在保存上一句语音/)
  } finally {
    globalThis.WebSocket = previousWebSocket
    globalThis.setTimeout = previousSetTimeout
    globalThis.clearTimeout = previousClearTimeout
  }
})

test('unsaved custom meeting survives accidental new practice, history switch, and refresh', async () => {
  let reads = 0
  const { page, leaveGuard } = mountReview(async () => { reads++; throw new Error('history should stay unopened') })
    page.newCase()
    page.setupOpen.value = false
    page.caseBriefInput.value = '客户希望了解首单政策'
    page.draft.value.meeting_materials = [{ name: '首单方案', text: '内部方案', purpose: 'reference', visibility: 'shared' }]
    assert.equal(page.hasUnsavedChanges(), true)

    page.newCase()
    assert.equal(page.caseBriefInput.value, '客户希望了解首单政策')
    assert.match(page.discardPrompt.value, /尚未保存/)
    page.cancelDiscard()
    await page.openSession('older-session')
    assert.equal(reads, 0)
    assert.equal(page.chosenSession.value, null)
    page.cancelDiscard()

    const beforeUnload = { prevented: false, preventDefault() { this.prevented = true }, returnValue: undefined }
    page.warnBeforeUnload(beforeUnload)
    assert.equal(beforeUnload.prevented, true)
    assert.equal(beforeUnload.returnValue, '')
    const navigation = leaveGuard()()
    assert.match(page.discardPrompt.value, /离开会议陪练/)
    page.cancelDiscard()
    assert.equal(await navigation, false)

    const acceptedNavigation = leaveGuard()()
    page.discardAndContinue()
    assert.equal(await acceptedNavigation, true)

    page.newCase()
    page.discardAndContinue()
    assert.equal(page.caseBriefInput.value, '')
    assert.equal(page.hasUnsavedChanges(), false)
})

test('an in-flight setup save blocks parent navigation and route leave', async () => {
  let reads = 0
  const savedCase = { id: 'saved-case', kind: 'case', title: '已保存会议', draft: {} }
  const { page, leaveGuard } = mountReview(async (path) => {
    reads++
    if (path === '/api/omega/cases') return [savedCase]
    if (path === '/api/omega/sessions' || path === '/api/omega/assignments') return []
    throw new Error(`Unexpected request ${path}`)
  })
  let saving = true
  page.setupRef.value = { hasUnsavedChanges: () => false, isBusy: () => saving }
  page.setupOpen.value = true
  page.newCase()
  page.showCase({ id: 'other-case' })
  await page.openSession('other-session')
  page.toggleProfiles()
  assert.equal(page.setupOpen.value, true)
  assert.equal(page.profilesOpen.value, false)
  assert.equal(page.chosenCase.value, null)
  assert.equal(reads, 0)
  assert.match(page.notice.value, /正在保存/)
  assert.equal(leaveGuard()(), false)
  saving = false
  assert.equal(leaveGuard()(), true)
  await page.savedTemplate(savedCase.id)
  assert.equal(page.chosenCase.value?.id, savedCase.id)
  assert.equal(page.setupOpen.value, false)
})

test('declining a quick card leaves the unsaved custom meeting and creates no session', async () => {
  const requests = []
  const { page } = mountReview(() => {}, async (path) => { requests.push(path); throw new Error('should not create') })
    page.newCase()
    page.setupOpen.value = false
    page.caseBriefInput.value = '客户的真实问题和会议资料'
    await page.startQuickPractice({ title: '客户要求降价', brief: '模拟背景', stance: '模拟立场', objection: '价格', goal: '约定下一步' })
    assert.deepEqual(requests, [])
    assert.equal(page.caseBriefInput.value, '客户的真实问题和会议资料')
    assert.match(page.discardPrompt.value, /开始新练习/)
    page.cancelDiscard()
    assert.deepEqual(requests, [])
})

test('accepting a quick card opens its new session after one discard confirmation', async () => {
  const posts = []
  const { page } = mountReview(async (path) => {
    if (path === '/api/omega/cases' || path === '/api/omega/sessions' || path === '/api/omega/assignments') return []
    if (path === '/api/omega/sessions/new-session') return { id: 'new-session', owner_id: 1, status: 'active', segments: [] }
    throw new Error(`Unexpected GET ${path}`)
  }, async (path) => {
    posts.push(path)
    if (path === '/api/omega/cases') return { id: 'new-case', owner_id: 1 }
    if (path === '/api/omega/sessions') return { id: 'new-session' }
    if (path === '/api/omega/cases/new-case/confirm') return {}
    throw new Error(`Unexpected POST ${path}`)
  })
  page.setupRef.value = { hasUnsavedChanges: () => true, isBusy: () => false }
  await page.startQuickPractice({ title: '客户要求降价', brief: '模拟背景', stance: '模拟立场', objection: '价格', goal: '约定下一步' })
  assert.match(page.discardPrompt.value, /开始新练习/)
  page.discardAndContinue()
  for (let index = 0; index < 20 && page.busy.value; index++) await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(posts, ['/api/omega/cases', '/api/omega/cases/new-case/confirm', '/api/omega/sessions'])
  assert.equal(page.discardPrompt.value, '')
  assert.equal(page.chosenSession.value?.id, 'new-session')
})

test('a manager viewing a sales session does not see controls to speak as that sales user', async () => {
  const { page, html } = mountReview()
  page.me.value = { id: 2, role: 'manager' }
  page.chosenSession.value = { id: 'sales-session', owner_id: 1, status: 'active',
    mode: 'rehearsal', case_snapshot: page.blankDraft(), segments: [] }
  assert.doesNotMatch(await html(), /omega-practice-controls/)
  page.me.value = { id: 1, role: 'sales' }
  assert.match(await html(), /omega-practice-controls/)
})

test('an unreviewed outcome is an AI proposal and its assignment waits for supervisor confirmation', async () => {
  const { page, html } = mountReview()
  const assignment = { id: 'assignment-1', case_id: 'case-1', assignee_id: 1,
    target_dimension: 'outcome', pass_percent: 70, status: 'in_progress',
    baseline: { score: 15, maximum: 25, percent: 60 }, attempts: [
      { session_id: 'practice-1', result: { score: 25, maximum: 25, percent: 100 }, passed: false, outcome_review: null },
    ] }
  page.me.value = { id: 2, role: 'manager' }
  page.assignments.value = [assignment]
  page.chosenSession.value = { id: 'practice-1', owner_id: 1, assignment_id: assignment.id,
    status: 'ended', case_snapshot: page.blankDraft(), segments: [
      { id: 'line-1', speaker: 'sales', text: '客户约定周五签首单。' },
    ] }
  page.report.value = { id: 'report-1', reviews: [], content: {
    outcome: { status: 'achieved', reason: '客户承诺下单', quotes: [
      { segment_id: 'line-1', speaker: 'sales', start: 0, end: 10, text: '客户约定周五签首单。' },
    ] }, dimensions: [], score: { total: 85, earned: 85, available: 100 },
  } }
  let rendered = await html()
  assert.match(rendered, /AI 初判：达成目标（待主管确认）/)
  assert.match(rendered, /目标判断.*核对原话/s)
  assert.match(rendered, /确认 AI 的目标判断/)
  assert.match(rendered, /驳回 AI 的目标判断/)
  assert.match(rendered, /仅点评，不确认目标/)
  assert.match(rendered, /本轮 100%[^<]*待主管确认/)
  page.chosenAssignment.value = assignment
  page.chosenSession.value = null
  rendered = await html()
  assert.match(rendered, /第 1 次：25\/25（100%）[^<]*待主管确认/)
  assert.doesNotMatch(rendered, /第 1 次：25\/25（100%）[^<]*达标/)
})

test('structured supervisor verdict is sent, refreshed, and the latest verdict labels the AI outcome', async () => {
  const posts = []
  let verdict = 'confirmed'
  let commentOnly = false
  const report = () => ({ id: 'report-1', content: {
    outcome: { status: 'partial', reason: '只约定了部分', quotes: [] }, dimensions: [],
    score: { total: 65, earned: 65, available: 100 },
  }, reviews: [
    { content: { comment: '先核对原话', next_practice: '', outcome_verdict: 'confirmed' } },
    { content: { comment: '复核后驳回该判断', next_practice: '', outcome_verdict: verdict } },
    ...(commentOnly ? [{ content: { comment: '只补充练习建议', next_practice: '', outcome_verdict: null } }] : []),
  ] })
  const { page, html } = mountReview(async (path) => {
    if (path === '/api/omega/reports/report-1') return report()
    if (path === '/api/omega/cases' || path === '/api/omega/sessions' || path === '/api/omega/assignments') return []
    throw new Error(`Unexpected GET ${path}`)
  }, async (path, body) => { posts.push({ path, body }) })
  page.me.value = { id: 2, role: 'manager' }
  page.chosenSession.value = { id: 'practice-1', owner_id: 1, status: 'ended',
    case_snapshot: page.blankDraft(), segments: [] }
  page.report.value = report()
  verdict = 'rejected'
  page.report.value = report()
  assert.match(await html(), /主管已驳回：AI 初判部分达成/)
  page.reviewText.value = '核对后目标未成立'
  page.outcomeVerdictInput.value = 'confirmed'
  verdict = 'confirmed'
  await page.reviewReport()
  assert.deepEqual(posts, [{ path: '/api/omega/reports/report-1/reviews', body: {
    comment: '核对后目标未成立', next_practice: '', outcome_verdict: 'confirmed',
  } }])
  assert.equal(page.outcomeVerdictInput.value, '')
  assert.match(await html(), /主管已确认：部分达成/)
  page.reviewText.value = '只补充练习建议'
  commentOnly = true
  await page.reviewReport()
  assert.deepEqual(posts[1], { path: '/api/omega/reports/report-1/reviews', body: {
    comment: '只补充练习建议', next_practice: '',
  } })
  assert.match(await html(), /主管已确认：部分达成/)
})

test('a slow supervisor review cannot replace another report after navigation', async () => {
  const requests = []
  let page
  const oldReport = { id: 'old-report', reviews: [], content: { outcome: { status: 'achieved', reason: 'AI 初判', quotes: [] } } }
  const nextReport = { id: 'next-report', reviews: [], content: { outcome: { status: 'unverified', reason: '证据不足', quotes: [] } } }
  const mounted = mountReview(async (path) => {
    requests.push(path)
    if (path === '/api/omega/reports/old-report') return oldReport
    if (['/api/omega/cases', '/api/omega/sessions', '/api/omega/assignments'].includes(path)) return []
    throw new Error(`Unexpected GET ${path}`)
  }, async (path) => {
    requests.push(path)
    page.report.value = nextReport
  })
  page = mounted.page
  page.report.value = oldReport
  page.reviewText.value = '已核对本场原话'
  await page.reviewReport()
  assert.equal(page.report.value.id, 'next-report')
  assert.equal(page.reviewText.value, '已核对本场原话')
  assert.ok(requests.includes('/api/omega/reports/old-report'))
  assert.ok(!requests.includes('/api/omega/reports/next-report'))
})
