import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { ref } from 'vue'
import * as audio from '../src/pages/meetingAudio.ts'

function mountSetup(apiGet) {
  const source = readFileSync(new URL('../src/pages/MeetingPage.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: 'meeting-test' })
  const { outputText } = ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  const exports = {}
  const modules = {
    vue: { ref, defineComponent: (options) => options, onMounted() {}, watch() {} },
    'vue-router': { useRouter: () => ({ replace() {} }) },
    '@/api/client': { apiGet, apiPost() {}, HttpError: class extends Error {} },
    '@/components/AppNav.vue': { default: {} },
    './meetingAudio': audio,
  }
  new Function('require', 'exports', outputText)((name) => {
    assert.ok(name in modules, `Unexpected import ${name}`)
    return modules[name]
  }, exports)
  return exports.default.setup({}, { expose() {} })
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

test('late meeting detail never replaces the selected meeting', async () => {
  const first = deferred()
  const page = mountSetup((url) => url.includes('meeting_id=A') ? first.promise
    : Promise.resolve({ meeting: { title: 'B', audio_url: 'https://example.invalid/B.mp3' } }))
  const old = page.openVemoryDetail({ meeting_id: 'A' })
  await page.openVemoryDetail({ meeting_id: 'B' })
  first.resolve({ meeting: { title: 'A', audio_url: 'https://example.invalid/A.mp3' } })
  await old
  assert.equal(page.detail.value.title, 'B')
  assert.equal(page.audioLinks.value[0].meeting_id, 'B')
})

test('late audio fallback never attaches to another meeting', async () => {
  const pendingAudio = deferred()
  const requestedAudio = deferred()
  const page = mountSetup((url) => {
    if (url.includes('audio-links')) {
      requestedAudio.resolve()
      return pendingAudio.promise
    }
    return Promise.resolve({ meeting: url.includes('meeting_id=A') ? { title: 'A' }
      : { title: 'B', audio_url: 'https://example.invalid/B.mp3' } })
  })
  const old = page.openVemoryDetail({ meeting_id: 'A', date: '2026-09-20' })
  await requestedAudio.promise
  await page.openVemoryDetail({ meeting_id: 'B' })
  pendingAudio.resolve({ links: [{ meeting_id: 'A', audio_url: 'https://example.invalid/A.mp3' }] })
  await old
  assert.equal(page.audioLinks.value[0].meeting_id, 'B')
})

test('late date query never replaces the current meeting list', async () => {
  const first = deferred()
  const page = mountSetup((url) => url.includes('2026-09-20') ? first.promise
    : Promise.resolve({ total: 1, meetings: [{ meeting_id: 'B' }] }))
  page.startDate.value = '2026-09-20'
  const old = page.loadVemory()
  page.startDate.value = '2026-09-21'
  await page.loadVemory()
  first.resolve({ total: 1, meetings: [{ meeting_id: 'A' }] })
  await old
  assert.equal(page.vemory.value.meetings[0].meeting_id, 'B')
})

test('closing a detail discards its pending response', async () => {
  const pending = deferred()
  const page = mountSetup(() => pending.promise)
  const request = page.openVemoryDetail({ meeting_id: 'A' })
  page.closeVemoryDetail()
  pending.resolve({ meeting: { title: 'A', audio_url: 'https://example.invalid/A.mp3' } })
  await request
  assert.equal(page.detailOpen.value, false)
  assert.equal(page.detail.value, null)
  assert.deepEqual(page.audioLinks.value, [])
})

test('invalid date range cancels pending list without issuing another request', async () => {
  const pending = deferred()
  let calls = 0
  const page = mountSetup(() => { calls++; return pending.promise })
  const request = page.loadVemory()
  page.startDate.value = '2026-09-22'
  page.endDate.value = '2026-09-21'
  await page.load()
  pending.resolve({ total: 1, meetings: [{ meeting_id: 'A' }] })
  await request
  assert.equal(calls, 1)
  assert.equal(page.vemory.value, null)
  assert.equal(page.vemoryLoading.value, false)
  assert.ok(page.error.value)
})
