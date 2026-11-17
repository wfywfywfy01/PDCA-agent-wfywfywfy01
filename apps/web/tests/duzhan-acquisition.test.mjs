import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

function mount(acquisitionQueue) {
  const { descriptor } = parse(readFileSync(new URL('../src/components/DuzhanAcquisitionQueue.vue', import.meta.url), 'utf8'))
  const script = compileScript(descriptor, { id: 'acquisition-test' })
  const template = compileTemplate({ source: descriptor.template.content, filename: 'DuzhanAcquisitionQueue.vue', id: 'acquisition-test', compilerOptions: { bindingMetadata: script.bindings } })
  assert.deepEqual(template.errors, [])
  const exports = {}
  const modules = { vue: { ...vue, onMounted() {}, onBeforeUnmount() {} }, '@/api/duzhanAgents': { acquisitionQueue } }
  for (const content of [script.content, template.code]) {
    const { outputText } = ts.transpileModule(content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
    new Function('require', 'exports', outputText)((name) => { assert.ok(name in modules); return modules[name] }, exports)
  }
  const page = exports.default.setup({}, { expose() {} })
  return { page, html: () => renderToString(vue.createSSRApp({ ...exports.default, render: exports.render, setup: () => page })) }
}
const fixture = () => ({ source_tasks: { as_of: '2026-11-17T02:00:00Z', total: 101, has_more: true,
  totals: { unaccepted: 100, no_progress: 101, overdue: 0, missing_due: 0 }, by_owner: [],
  items: [{ task_id: 7, display_name: '隔离测试线索', owner_user_id: 4, owner_name: '测试销售', accepted_at: '2026-11-17T01:00:00Z',
    stage: 'pending', route: 'partner_site', source_system: 'qa', customer_stage: null, customer_stage_status: 'unlinked', next_due_at: null,
    last_progress_at: null, stored_outreach_hold: true }] }, owner_pending_replies: { total: 0, has_more: false, items: [] } })

test('receiving a lead does not invent customer progress or company identity', async () => {
  const { page, html } = mount(async () => fixture())
  await page.load()
  const text = await html()
  for (const expected of ['已接收', '尚无进展记录', '尚未关联公司', '下一步未记录', '暂停触达，先核验']) assert.ok(text.includes(expected))
})
test('failed refresh retains last successful data, labels it stale, and never changes pagination', async () => {
  let fail = false
  const { page, html } = mount(async () => { if (fail) throw new Error('读取失败'); return fixture() })
  await page.load(); fail = true; await page.load(100, 100)
  assert.equal(page.offset.value, 0); assert.equal(page.replyOffset.value, 0)
  assert.equal(page.data.value.source_tasks.total, 101)
  assert.match(await html(), /上次成功读取的数据/)
})
test('source and unresolved-message pagination stay independent without a client-supplied owner scope', async () => {
  const calls = []
  const { page } = mount(async (...args) => { calls.push(args); return fixture() })
  await page.load(100, 0); await page.load(100, 100)
  assert.deepEqual(calls, [[100, 0], [100, 100]])
})
