import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

function mountReview({ api = {}, beforeUnmount = () => {} } = {}) {
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
  const stubComponent = { render: () => null }
  const modules = {
    vue: { ...vue, onMounted() {}, onBeforeUnmount: beforeUnmount, watch() {} },
    'vue-router': { useRouter: () => ({ replace() {} }) },
    '@/api/client': { apiGet() {}, apiPost() {}, apiPatch() {}, apiRequest() {}, HttpError: class extends Error {}, ...api },
    '@/components/AppNav.vue': { default: stubComponent },
    '@/components/omega/OmegaSetup.vue': { default: stubComponent },
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
  return { page, html: () => renderToString(vue.createSSRApp({ ...exports.default, render: exports.render, setup: () => page })) }
}

function dimension(key, score) {
  return { key, score, reason: key, quotes: [{ speaker: 'sales', text: '可核验的销售原话' }] }
}

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


test('report polling recovers safely and ignores stale asynchronous results', async (t) => {
  const nativeSetTimeout = globalThis.setTimeout
  const nativeClearTimeout = globalThis.clearTimeout
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const timers = new Map()
  let nextTimer = 1
  globalThis.setTimeout = (callback, delay) => {
    const id = nextTimer++
    timers.set(id, { callback, delay })
    return id
  }
  globalThis.clearTimeout = (id) => timers.delete(id)
  Object.defineProperty(globalThis, 'window', { value: { speechSynthesis: { cancel() {} } }, configurable: true })
  class PollHttpError extends Error {
    constructor(status) { super(`HTTP ${status}`); this.status = status; this.detail = `HTTP ${status}` }
  }
  function deferred() {
    let resolve, reject
    const promise = new Promise((yes, no) => { resolve = yes; reject = no })
    return { promise, resolve, reject }
  }
  function mountPoll(apiGet) {
    let unmount
    const mounted = mountReview({ api: { apiGet, HttpError: PollHttpError }, beforeUnmount: (callback) => { unmount = callback } })
    const { page } = mounted
    page.chosenSession.value = { id: 'session', owner_id: 1, status: 'ended', case_snapshot: page.blankDraft(), segments: [
      { id: 'sales', speaker: 'sales', text: '完整保留的本场原话' },
    ] }
    page.activeJob.value = { id: 'job-A', kind: 'report', status: 'running' }
    page.textReady.value = true
    page.notice.value = '正在生成复盘，请稍候。'
    return { ...mounted, unmount }
  }
  async function advanceRecovery() {
    assert.equal(timers.size, 1, 'one recovery timer remains scheduled')
    const [id, timer] = timers.entries().next().value
    assert.equal(timer.delay, 3000, 'transient failures back off for three seconds')
    timers.delete(id)
    await timer.callback()
  }
  const check = async (name, body) => {
    await t.test(name, async () => {
      timers.clear()
      try { await body() } finally { timers.clear() }
    })
  }
  try {
    await check('same job survives network and HTTP 503 failures and exposes terminal retry', async () => {
      const calls = []
      const { page, html } = mountPoll(async (url) => {
        calls.push(url)
        if (calls.length === 1) throw new TypeError('网络暂不可用')
        if (calls.length === 2) throw new PollHttpError(503)
        return { id: 'job-A', kind: 'report', status: 'failed', error: '复盘事实核验未通过' }
      })
      await page.pollJob()
      assert.equal(page.error.value, '网络暂不可用')
      await advanceRecovery()
      assert.equal(page.error.value, 'HTTP 503')
      await advanceRecovery()
      assert.deepEqual(calls, Array(3).fill('/api/omega/jobs/job-A'))
      assert.equal(page.activeJob.value.status, 'failed')
      assert.equal(page.error.value, '复盘事实核验未通过')
      assert.equal(page.notice.value, '', 'terminal failure clears the generating notice')
      assert.equal(timers.size, 0, 'terminal jobs stop polling')
      const rendered = await html()
      const retry = rendered.match(/<button\b([^>]*)>重试复盘<\/button>/)
      assert.ok(retry, 'the real template offers retry after terminal failure')
      assert.doesNotMatch(retry[1], /\bdisabled(?:\s|=|$)/, 'retry is enabled for a complete ended session')
      assert.ok(!rendered.includes('正在生成复盘，请稍候。'))
    })

    for (const preserveNewError of [false, true]) {
      await check(`successful recovery ${preserveNewError ? 'preserves a newer UI error' : 'clears only its own transient error'}`, async () => {
        let count = 0
        const { page } = mountPoll(async () => {
          if (++count === 1) throw new TypeError('临时连接失败')
          return { id: 'job-A', kind: 'report', status: 'running' }
        })
        await page.pollJob()
        if (preserveNewError) page.error.value = '另一项操作失败'
        await advanceRecovery()
        assert.equal(page.error.value, preserveNewError ? '另一项操作失败' : '')
        assert.equal(timers.size, 1)
        assert.equal([...timers.values()][0].delay, 1200, 'normal polling resumes after recovery')
      })
    }

    for (const status of [401, 403, 404]) {
      await check(`HTTP ${status} stops without fabricating a terminal job`, async () => {
        let calls = 0
        const { page } = mountPoll(async () => { calls++; throw new PollHttpError(status) })
        await page.pollJob()
        assert.equal(calls, 1)
        assert.equal(timers.size, 0)
        assert.equal(page.activeJob.value.status, 'running', 'an HTTP error is not a backend job failure')
        assert.equal(page.error.value, `HTTP ${status}`)
        assert.equal(page.notice.value, '')
      })
    }

    await check('a normal successful poll preserves unrelated UI errors', async () => {
      const { page } = mountPoll(async () => ({ id: 'job-A', kind: 'report', status: 'running' }))
      page.error.value = '另一项操作失败'
      await page.pollJob()
      assert.equal(page.error.value, '另一项操作失败')
    })

    for (const staleAction of ['new-job', 'unmount']) {
      await check(`${staleAction} ignores a delayed network failure`, async () => {
        const request = deferred()
        const { page, unmount } = mountPoll(() => request.promise)
        const pending = page.pollJob()
        if (staleAction === 'new-job') page.activeJob.value = { id: 'job-B', kind: 'report', status: 'running' }
        else unmount()
        page.error.value = '当前界面的错误'
        page.notice.value = '当前界面的提示'
        request.reject(new TypeError('旧请求失败'))
        await pending
        assert.equal(page.error.value, '当前界面的错误')
        assert.equal(page.notice.value, '当前界面的提示')
        assert.equal(timers.size, 0, 'stale failures cannot restart polling')
      })

      for (const stage of ['report', 'session', 'lists']) {
        await check(`${staleAction} ignores delayed successful ${stage} data`, async () => {
          const request = deferred()
          const reached = deferred()
          const { page, unmount } = mountPoll((url) => {
            if (url === '/api/omega/jobs/job-A') return { id: 'job-A', kind: 'report', status: 'succeeded', result_id: 'report-A' }
            if (url === '/api/omega/reports/report-A') {
              if (stage === 'report') { reached.resolve(); return request.promise }
              return { id: 'report-A', content: {} }
            }
            if (url === '/api/omega/sessions/session') {
              if (stage === 'session') { reached.resolve(); return request.promise }
              return { id: 'session', owner_id: 1, status: 'ended', case_snapshot: page.blankDraft(), segments: [] }
            }
            assert.ok(['/api/omega/cases', '/api/omega/sessions', '/api/omega/assignments'].includes(url))
            reached.resolve()
            return request.promise
          })
          const pending = page.pollJob()
          await reached.promise
          if (staleAction === 'new-job') page.activeJob.value = { id: 'job-B', kind: 'report', status: 'running' }
          else unmount()
          page.chosenSession.value = { ...page.chosenSession.value, marker: 'current-session' }
          page.report.value = { id: 'report-current', content: {} }
          page.cases.value = [{ id: 'case-current' }]
          page.sessions.value = [{ id: 'session-current' }]
          page.assignments.value = [{ id: 'assignment-current' }]
          page.error.value = '当前界面的错误'
          page.notice.value = '当前界面的提示'
          request.resolve(stage === 'report' ? { id: 'report-old', content: {} }
            : stage === 'session' ? { id: 'session', marker: 'old-session' } : [{ id: 'old-list-data' }])
          await pending
          assert.equal(page.chosenSession.value.marker, 'current-session')
          assert.equal(page.report.value.id, 'report-current')
          assert.deepEqual(page.cases.value, [{ id: 'case-current' }])
          assert.deepEqual(page.sessions.value, [{ id: 'session-current' }])
          assert.deepEqual(page.assignments.value, [{ id: 'assignment-current' }])
          assert.equal(page.error.value, '当前界面的错误')
          assert.equal(page.notice.value, '当前界面的提示')
          assert.equal(timers.size, 0)
        })
      }
    }
  } finally {
    globalThis.setTimeout = nativeSetTimeout
    globalThis.clearTimeout = nativeClearTimeout
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow)
    else delete globalThis.window
  }
})
