import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

function mountReview() {
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
    vue: { ...vue, onMounted() {}, onBeforeUnmount() {}, watch() {} },
    'vue-router': { useRouter: () => ({ replace() {} }) },
    '@/api/client': { apiGet() {}, apiPost() {}, apiPatch() {}, apiRequest() {}, HttpError: class extends Error {} },
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
