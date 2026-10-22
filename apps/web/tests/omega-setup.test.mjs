import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

function mountSetup({ apiGet = async () => [], apiPost } = {}) {
  const source = readFileSync(new URL('../src/components/omega/OmegaSetup.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: 'omega-setup-test' })
  const exports = {}
  const requests = []
  const modules = {
    vue: { ...vue, onMounted() {} },
    '@/api/client': {
      apiGet,
      apiPost: async (path, body) => {
        requests.push({ path, body })
        return apiPost ? apiPost(path, body) : { case_id: 'case-b', session_id: 'session-b' }
      },
      HttpError: class extends Error {},
    },
    './OmegaMeetingMaterials.vue': { default: { render: () => null } },
    './omega-types': { meetingNames: {}, usageNames: {} },
  }
  const { outputText } = ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  new Function('require', 'exports', outputText)((name) => {
    assert.ok(name in modules, `Unexpected import ${name}`)
    return modules[name]
  }, exports)
  const page = exports.default.setup({ realtimeReady: true, multiVoiceReady: true, manager: false }, { expose() {}, emit() {} })
  return { page, requests }
}

function card(id, topic = '', dealerId = '', opportunityId = null) {
  return { id, current_version: 1, draft: {
    title: id, meeting_type: 'negotiation', meeting_topic: topic,
    dealer_id: dealerId, opportunity_id: opportunityId, meeting_materials: [],
    goal: { success_condition: '争取下一步' },
  } }
}

test('switching scenario cards does not send previous meeting topic or materials', async () => {
  const { page, requests } = mountSetup()
  page.choose(card('card-a'))
  page.meetingTopic.value = 'A 的临时命题'
  page.materials.value = [{ name: 'A 的内部资料', text: 'A 的客户信息', purpose: 'reference', visibility: 'shared' }]

  page.choose(card('card-b', 'B 的预设命题'))
  assert.equal(page.selected.value.id, 'card-a')
  page.confirmAndContinue()
  assert.equal(page.meetingTopic.value, 'B 的预设命题')
  assert.deepEqual(page.materials.value, [])

  await page.start(false)
  assert.equal(requests[0].path, '/api/omega/template-starts')
  assert.equal(requests[0].body.template_id, 'card-b')
  assert.equal(requests[0].body.overrides.meeting_topic, 'B 的预设命题')
  assert.deepEqual(requests[0].body.overrides.meeting_materials, [])
})

test('choosing a card preserves its opportunity until the dealer is changed', async () => {
  const { page, requests } = mountSetup()
  page.choose(card('card-c', '', 'dealer-c', 'opportunity-c'))
  await vue.nextTick()
  assert.equal(page.opportunityId.value, 'opportunity-c')

  await page.start(false)
  assert.equal(requests[0].body.opportunity_id, 'opportunity-c')

  page.dealerId.value = 'dealer-other'
  await vue.nextTick()
  assert.equal(page.opportunityId.value, '')
})

test('an accidental card change keeps unsaved meeting materials', () => {
  const { page } = mountSetup()
    page.choose(card('card-a'))
    page.meetingTopic.value = 'A 的临时命题'
    page.materials.value = [{ name: 'A 的资料', text: '客户背景', purpose: 'reference', visibility: 'shared' }]
    assert.equal(page.hasUnsavedChanges(), true)

    page.choose(card('card-b'))
    assert.equal(page.selected.value.id, 'card-a')
    assert.equal(page.materials.value.length, 1)
    assert.match(page.discardPrompt.value, /尚未保存/)

    page.cancelConfirmation()
    assert.equal(page.materials.value.length, 1)
    page.choose(card('card-b'))
    page.confirmAndContinue()
    assert.equal(page.selected.value.id, 'card-b')
    assert.equal(page.meetingTopic.value, '')
    assert.deepEqual(page.materials.value, [])
    assert.equal(page.hasUnsavedChanges(), false)
})

test('saving a team preset does not silently discard temporary uploaded materials', async () => {
  const { page, requests } = mountSetup()
    page.choose(card('card-a'))
    page.materials.value = [{ name: '临时资料', text: '本次会议专用', purpose: 'reference', visibility: 'shared' }]
    await page.saveTemplate()
    assert.deepEqual(requests, [])
    assert.equal(page.materials.value.length, 1)
    assert.match(page.discardPrompt.value, /临时命题和资料不会保存/)
    page.cancelConfirmation()
    assert.equal(page.materials.value.length, 1)
})

test('scenario controls cannot change while a save request is pending', async () => {
  let finishSave
  const { page, requests } = mountSetup({
    apiPost: () => new Promise(resolve => { finishSave = resolve }),
  })
  page.choose(card('card-a'))
  const saving = page.start(false, true)
  assert.equal(page.busy.value, true)
  page.choose(card('card-b'))
  page.selectUsage('rehearsal')
  page.selectGroup('other')
  assert.equal(page.selected.value.id, 'card-a')
  assert.equal(page.usage.value, 'training')
  assert.equal(page.cardGroup.value, 'cooperation')
  assert.equal(requests[0].body.overrides.meeting_topic, '')
  finishSave({ case_id: 'saved-case', session_id: null })
  await saving
  assert.equal(page.busy.value, false)
})

test('saving a personal preset displays the newly selected card in its group', async () => {
  const first = { ...card('built-in'), card_group: 'cooperation' }
  const saved = { ...card('saved-case'), card_group: 'other' }
  const { page } = mountSetup({
    apiGet: async () => [first, saved],
    apiPost: async (path) => path === '/api/omega/cases' ? { id: saved.id } : {},
  })
  page.choose(first)
  page.cardGroup.value = 'cooperation'
  await page.saveTemplate()
  assert.equal(page.selected.value.id, saved.id)
  assert.equal(page.cardGroup.value, 'other')
  assert.ok(page.groupCards.value.some(row => row.id === saved.id))
})
