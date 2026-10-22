<script setup lang="ts">
import { computed, nextTick, onMounted, ref, toRaw, watch } from 'vue'
import { apiGet, apiPost, HttpError } from '@/api/client'
import OmegaMeetingMaterials from './OmegaMeetingMaterials.vue'
import { meetingNames, usageNames, type MeetingMaterial, type TemplateDraft, type TemplateRow, type TemplateStart, type Usage } from './omega-types'

const props = defineProps<{ manager: boolean; multiVoiceReady: boolean; realtimeReady: boolean }>()
const emit = defineEmits<{ started: [result: TemplateStart, autoVoice: boolean]; saved: [caseId: string]; custom: []; prepareVoice: []; cancelVoicePreparation: [] }>()
const templates = ref<TemplateRow[]>([])
const selected = ref<TemplateRow | null>(null)
const draft = ref<TemplateDraft | null>(null)
const usage = ref<Usage>('training')
const cardGroup = ref('cooperation')
const groupNames: Record<string, string> = { cooperation: '合作', training: '培训', operation: '经营', other: '临时', drill: '专项' }
const meetingTopic = ref('')
const materials = ref<MeetingMaterial[]>([])
const materialsBusy = ref(false)
const dealerId = ref('')
const opportunityId = ref('')
const dealers = ref<Array<{ dealer_id: string; name: string }>>([])
const opportunities = ref<Array<{ id: string; title: string }>>([])
const opportunityTitle = ref('')
const adjusting = ref(false)
const busy = ref(false)
const loading = ref(true)
const error = ref('')
const notice = ref('')
const discardPrompt = ref('')
const discardButton = ref<HTMLButtonElement | null>(null)
let pendingDiscardAction: (() => void | Promise<void>) | null = null
let opportunityRequest = 0
let pendingLaunch: { body: string; key: string } | undefined
let savedSetup = ''
const visible = computed(() => templates.value.filter(row => row.available_usages?.includes(usage.value) || !row.draft.usage || row.draft.usage === usage.value))
const groups = computed(() => Object.keys(groupNames).filter(group => visible.value.some(row => (row.card_group || 'other') === group)))
const groupCards = computed(() => visible.value.filter(row => (row.card_group || 'other') === cardGroup.value))
const hasMultiple = computed(() => (draft.value?.participants?.length || 0) > 1)
const canStartVoice = computed(() => props.realtimeReady && (!hasMultiple.value || props.multiVoiceReady) && usage.value !== 'real_review')
function message(err: unknown) { return err instanceof HttpError ? err.detail : err instanceof Error ? err.message : '请求失败，请重试' }
function setupSnapshot() {
  return JSON.stringify({ card: selected.value?.id, usage: usage.value, draft: draft.value,
    meetingTopic: meetingTopic.value, materials: materials.value, dealerId: dealerId.value,
    opportunityId: opportunityId.value, opportunityTitle: opportunityTitle.value })
}
function hasUnsavedChanges() { return !!selected.value && savedSetup !== setupSnapshot() }
function requestConfirmation(message: string, action: () => void | Promise<void>) {
  discardPrompt.value = message
  pendingDiscardAction = action
  void nextTick(() => discardButton.value?.focus())
}
function cancelConfirmation() { discardPrompt.value = ''; pendingDiscardAction = null }
function confirmAndContinue() {
  const action = pendingDiscardAction
  cancelConfirmation()
  try { if (action) void Promise.resolve(action()).catch(err => { error.value = message(err) }) }
  catch (err) { error.value = message(err) }
}
defineExpose({ hasUnsavedChanges, isBusy: () => busy.value })
function choose(row: TemplateRow, force = false) {
  if (busy.value && !force) return
  if (!force && selected.value?.id === row.id) return
  if (!force && hasUnsavedChanges()) {
    requestConfirmation('本次会议设置尚未保存。切换场景卡会丢失填写的内容和资料。', () => choose(row, true))
    return
  }
  cancelConfirmation()
  selected.value = row
  draft.value = structuredClone(toRaw(row.draft))
  meetingTopic.value = row.draft.meeting_topic || ''
  materials.value = []
  dealerId.value = row.draft.dealer_id || ''
  opportunityId.value = row.draft.opportunity_id || ''
  opportunityTitle.value = ''
  adjusting.value = false
  error.value = ''
  notice.value = ''
  savedSetup = setupSnapshot()
}
async function load() {
  error.value = ''
  loading.value = true
  try {
    templates.value = await apiGet<TemplateRow[]>('/api/omega/templates')
    const next = visible.value[0]
    if (next) { cardGroup.value = next.card_group || 'other'; choose(next, true) }
  } catch (err) { error.value = message(err) }
  finally { loading.value = false }
}
watch(usage, () => { selected.value = null; draft.value = null; const next = visible.value[0]; if (next) { cardGroup.value = next.card_group || 'other'; choose(next, true) } })
function selectUsage(next: Usage) {
  if (busy.value) return
  if (usage.value === next) return
  if (hasUnsavedChanges()) {
    requestConfirmation('本次会议设置尚未保存。切换会议用途会丢失填写的内容和资料。', () => { usage.value = next })
    return
  }
  usage.value = next
}
function selectGroup(group: string) {
  if (busy.value) return
  if (group === cardGroup.value) return
  if (hasUnsavedChanges()) {
    requestConfirmation('本次会议设置尚未保存。切换会议分类会丢失填写的内容和资料。', () => selectGroupConfirmed(group))
    return
  }
  selectGroupConfirmed(group)
}
function selectGroupConfirmed(group: string) {
  cardGroup.value = group
  const next = groupCards.value[0]
  if (next) choose(next, true)
}
watch(dealerId, async (id) => {
  const request = ++opportunityRequest
  if (id !== selected.value?.draft.dealer_id || opportunityId.value !== selected.value?.draft.opportunity_id) opportunityId.value = ''
  opportunities.value = []
  if (!id) return
  try {
    const rows = await apiGet<Array<{ id: string; title: string }>>(`/api/omega/opportunities?dealer_id=${encodeURIComponent(id)}`)
    if (request === opportunityRequest) opportunities.value = rows
  } catch (err) { if (request === opportunityRequest) error.value = message(err) }
})
async function addOpportunity() {
  if (!dealerId.value || !opportunityTitle.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const row = await apiPost<{ id: string; title: string }>('/api/omega/opportunities', { dealer_id: dealerId.value, title: opportunityTitle.value.trim() })
    opportunities.value.push(row)
    opportunityId.value = row.id
    opportunityTitle.value = ''
  } catch (err) { error.value = message(err) }
  finally { busy.value = false }
}
function addParticipant() {
  if (!draft.value || (draft.value.participants?.length || 0) >= 3) return
  if (!draft.value.participants?.length) draft.value.participants = [{ id: 'lead', name: draft.value.buyer_name || '主谈对手', role: draft.value.buyer_role || '负责人', is_primary: true, concerns: [], known_facts: [], decision_authority: '未明确，需在沟通中澄清' }]
  draft.value.participants.push({ id: crypto.randomUUID(), name: '参会人', role: '采购', is_primary: false, concerns: [], known_facts: [], decision_authority: '未明确，需在沟通中澄清' })
}
async function start(autoVoice = false, saveOnly = false) {
  if (!draft.value || !selected.value || busy.value || materialsBusy.value) return
  if (draft.value.meeting_type === 'custom' && !meetingTopic.value.trim()) { error.value = '临时会议请先写本次命题'; return }
  if (materials.value.some(item => !item.text.trim())) { error.value = '资料提取文字不能为空'; return }
  busy.value = true
  error.value = ''
  if (autoVoice) emit('prepareVoice')
  const reserved = new Set(['kind', 'dealer_id', 'opportunity_id', 'source_template_version_id', 'usage', 'simulation', 'meeting_topic', 'meeting_materials'])
  const original = selected.value.draft as unknown as Record<string, unknown>
  const overrides = Object.fromEntries(Object.entries(draft.value).filter(([name, value]) => !reserved.has(name) && JSON.stringify(value) !== JSON.stringify(original[name])))
  overrides.meeting_topic = meetingTopic.value.trim()
  overrides.meeting_materials = materials.value
  const payload = { template_id: selected.value.id, template_version: selected.value.current_version,
    usage: usage.value, dealer_id: dealerId.value, opportunity_id: opportunityId.value || null,
    ...(saveOnly ? { save_only: true } : {}), overrides }
  const fingerprint = JSON.stringify(payload)
  if (pendingLaunch?.body !== fingerprint) pendingLaunch = { body: fingerprint, key: crypto.randomUUID() }
  try {
    const result = await apiPost<TemplateStart>('/api/omega/template-starts', { ...payload, request_key: pendingLaunch.key })
    pendingLaunch = undefined
    savedSetup = setupSnapshot()
    if (saveOnly) emit('saved', result.case_id)
    else emit('started', result, autoVoice)
  } catch (err) { error.value = message(err); if (autoVoice) emit('cancelVoicePreparation') }
  finally { busy.value = false }
}
async function saveTemplate(confirmed = false) {
  if (!draft.value || busy.value || materialsBusy.value) return
  if (!confirmed && (materials.value.length || meetingTopic.value !== (selected.value?.draft.meeting_topic || ''))) {
    requestConfirmation('临时命题和资料不会保存进团队预设。继续后只保存场景卡内容。', () => saveTemplate(true))
    return
  }
  busy.value = true
  error.value = ''
  try {
    const row = await apiPost<{ id: string }>('/api/omega/cases', { ...draft.value, kind: 'template', usage: usage.value,
      source_template_version_id: selected.value?.case_version_id || null,
      dealer_id: dealerId.value, opportunity_id: opportunityId.value || null })
    await apiPost(`/api/omega/cases/${row.id}/confirm`)
    await load()
    const saved = templates.value.find(item => item.id === row.id)
    if (saved) { cardGroup.value = saved.card_group || 'other'; choose(saved, true) }
    notice.value = props.manager ? '团队预设已保存。' : '我的预设已保存。'
  } catch (err) { error.value = message(err) }
  finally { busy.value = false }
}
onMounted(async () => {
  await load()
  try { dealers.value = (await apiGet<{ dealers: Array<{ dealer_id: string; name: string }> }>('/api/knowledge/scope')).dealers }
  catch (err) { notice.value = `客户列表暂不可用，仍可使用模拟预设。${message(err)}` }
})
</script>

<template>
  <section class="card setup" aria-labelledby="omega-setup-title">
    <header><p class="eyebrow">准备一场有目标的对话</p><h2 id="omega-setup-title">今天要练哪场会？</h2><p class="muted">选会议卡直接开始；本次命题和资料可以临时补充。</p></header>
    <fieldset class="setup-fields" :disabled="busy">
    <div class="usages" role="group" aria-label="会议用途">
      <button v-for="(name, value) in usageNames" :key="value" type="button" :disabled="materialsBusy" :aria-pressed="usage === value" @click="selectUsage(value)">{{ name }}<small>{{ value === 'training' ? '练基本功' : value === 'rehearsal' ? '为真实客户做准备' : '从真实会议找改进' }}</small></button>
    </div>
    <div v-if="discardPrompt" class="setup-confirm" role="region" aria-label="确认操作"><p>{{ discardPrompt }}</p><div><button ref="discardButton" class="btn btn-primary" type="button" @click="confirmAndContinue">继续，丢弃未保存内容</button><button class="btn btn-ghost" type="button" @click="cancelConfirmation">继续编辑</button></div></div>
    <p v-if="error" role="alert" class="alert">{{ error }}</p><p v-if="notice" role="status" class="muted">{{ notice }}</p>
    <p v-if="loading" role="status">正在读取场景卡…</p>
    <div v-else-if="!visible.length" class="empty"><p>当前用途还没有预设。</p><button class="btn" type="button" @click="emit('custom')">描述场景并创建</button><button v-if="error" class="btn btn-ghost" type="button" @click="load">重新读取</button></div>
    <template v-else>
      <nav class="card-groups" aria-label="会议分类"><button v-for="group in groups" :key="group" type="button" :disabled="materialsBusy" :aria-pressed="cardGroup === group" @click="selectGroup(group)">{{ groupNames[group] }}</button></nav>
      <div class="scenarios" role="group" aria-label="场景卡">
      <div v-for="row in groupCards" :key="row.id" class="scenario-card" :class="{ selected: selected?.id === row.id }">
        <button class="scenario-choice" type="button" :disabled="materialsBusy" :aria-pressed="selected?.id === row.id" @click="choose(row)"><span class="eyebrow">{{ meetingNames[row.draft.meeting_type || 'negotiation'] || '谈判练习' }}</span><strong>{{ row.title }}</strong><span>{{ row.draft.buyer_objections?.[0] || row.draft.goal.success_condition }}</span><small>{{ row.draft.simulation === false ? '真实背景' : '模拟场景' }} · {{ (row.draft.participants?.length || 1) > 1 ? '多人对手' : '一位主谈' }}</small></button>
        <div v-if="selected?.id === row.id && draft" class="scenario-actions">
          <p class="muted">本场目标：{{ draft.goal.success_condition }}</p>
          <div class="start-actions"><button v-if="canStartVoice" class="btn btn-ghost" type="button" :disabled="busy || materialsBusy" @click="start(false)">文字开练</button><button class="btn btn-primary" type="button" :disabled="busy || materialsBusy" @click="start(canStartVoice)">{{ busy || materialsBusy ? '准备中…' : usage === 'real_review' ? '选择会议' : canStartVoice ? '语音开练' : '用这张卡开练' }}</button></div>
          <div class="draft-actions"><button class="btn" type="button" :disabled="busy || materialsBusy" @click="start(false, true)">保存本次设置</button><span class="muted">{{ hasUnsavedChanges() ? '填写的内容尚未保存；直接开练也会自动保存。' : '保存后可在任务列表继续。' }}</span></div>
          <details class="meeting-sources" :open="row.draft.meeting_type === 'custom'"><summary>本次命题与资料{{ materials.length ? ` · ${materials.length} 份` : row.draft.meeting_type === 'custom' ? '（请填写命题）' : '（可选）' }}</summary>
            <div v-if="row.suggested_topics?.length" class="topic-chips" role="group" aria-label="推荐命题"><button v-for="topic in row.suggested_topics" :key="topic" type="button" :aria-pressed="meetingTopic === topic" @click="meetingTopic = topic">{{ topic }}</button></div>
            <label>本次会议命题<textarea v-model.trim="meetingTopic" rows="2" maxlength="500" :placeholder="row.draft.meeting_type === 'custom' ? '必填：这场会要解决什么问题？' : '选一个重点，或写下本场要解决的问题'"></textarea></label>
            <OmegaMeetingMaterials v-model="materials" :hint="row.material_hint" :disabled="busy" @busy="materialsBusy = $event" />
          </details>
        </div>
      </div>
    </div>
    </template>
    <template v-if="draft">
      <div v-if="usage !== 'training' || dealerId" class="client-fields">
        <label>本场代理<select v-model="dealerId"><option value="">不关联代理</option><option v-for="dealer in dealers" :key="dealer.dealer_id" :value="dealer.dealer_id">{{ dealer.name }}</option></select></label>
        <label v-if="dealerId">合作事项<select v-model="opportunityId"><option value="">暂不关联事项</option><option v-for="row in opportunities" :key="row.id" :value="row.id">{{ row.title }}</option></select></label>
        <details v-if="dealerId"><summary>新建合作事项</summary><label>事项名称<input v-model.trim="opportunityTitle" maxlength="200" placeholder="例如：迪拜门店首批订单"></label><button class="btn btn-sm" type="button" :disabled="busy || !opportunityTitle" @click="addOpportunity">保存事项</button></details>
      </div>
      <dl class="brief"><div><dt>当前阶段</dt><dd>{{ draft.stage_summary || '开始沟通，先弄清对方顾虑。' }}</dd></div><div><dt>本场目标</dt><dd>{{ draft.goal.success_condition }}</dd></div><div><dt>我方底线</dt><dd>{{ draft.goal.hard_limits.join('；') }}</dd></div></dl>
      <button class="btn btn-ghost" type="button" :aria-expanded="adjusting" aria-controls="omega-blocks" @click="adjusting = !adjusting">{{ adjusting ? '收起调整' : '调整这张场景卡' }}</button>
      <form id="omega-blocks" v-show="adjusting" class="blocks" @submit.prevent="saveTemplate()">
        <fieldset><legend>1 · 用途与会议类型</legend><label>场景名称<input v-model.trim="draft.title" required minlength="2" maxlength="200"></label><label>会议类型<select v-model="draft.meeting_type"><option v-for="(name, value) in meetingNames" :key="value" :value="value">{{ name }}</option></select></label></fieldset>
        <fieldset><legend>2 · 当前阶段</legend><label>一句话说明目前进展<textarea v-model.trim="draft.stage_summary" rows="2" maxlength="1000"></textarea></label></fieldset>
        <fieldset><legend>3 · 双方背景</legend><label>双方已知背景<textarea v-model.trim="draft.public_brief" rows="3" minlength="5" required></textarea></label><label>对手立场<textarea v-model.trim="draft.counterparty_brief" rows="2" minlength="5" required></textarea></label><label>销售私有信息<textarea v-model.trim="draft.seller_private" rows="2" placeholder="仅教练可见，不提供给对手"></textarea></label></fieldset>
        <fieldset><legend>4 · 对手与参会人</legend><p class="muted">默认一位主谈。需要采购、财务等共同参与时，可增加角色。</p><div v-for="(person, index) in draft.participants || []" :key="person.id" class="person"><label>姓名<input v-model.trim="person.name" required maxlength="100"></label><label>职位<input v-model.trim="person.role" required maxlength="100"></label><label>关注点<textarea :value="person.concerns.join('\n')" rows="2" @input="person.concerns = ($event.target as HTMLTextAreaElement).value.split('\n').filter(Boolean)"></textarea></label><label>此人知道的事实<textarea :value="person.known_facts.join('\n')" rows="2" @input="person.known_facts = ($event.target as HTMLTextAreaElement).value.split('\n').filter(Boolean)"></textarea></label><label>决策权限<input v-model.trim="person.decision_authority" maxlength="500"></label><button v-if="index > 0" class="btn btn-sm btn-ghost" type="button" @click="draft.participants?.splice(index, 1)">移除此人</button></div><button class="btn btn-sm" type="button" :disabled="(draft.participants?.length || 0) >= 3" @click="addParticipant">添加参会人</button></fieldset>
        <fieldset><legend>5 · 目标与底线</legend><label>本场要争取什么<textarea v-model.trim="draft.goal.success_condition" rows="2" minlength="5" required></textarea></label><label>理想结果<input v-model.trim="draft.goal.ideal" required minlength="2"></label><label>最低可接受结果<input v-model.trim="draft.goal.minimum" required minlength="2"></label><label>不能越过的底线（每行一条）<textarea :value="draft.goal.hard_limits.join('\n')" rows="2" required @input="draft.goal.hard_limits = ($event.target as HTMLTextAreaElement).value.split('\n').filter(Boolean)"></textarea></label></fieldset>
        <button class="btn" type="submit" :disabled="busy || materialsBusy">{{ manager ? '保存为团队预设' : '保存为我的预设' }}</button>
      </form>
      <p v-if="hasMultiple && !multiVoiceReady && usage !== 'real_review'" class="muted" role="status">当前语音服务尚未通过多人能力验证。可先切回一位主谈，或使用文字演练。</p>
      <footer><span class="muted">{{ usage === 'real_review' ? '下一步选择真实会议并核对说话人。' : '模拟参会人会追问，原话自动保存，结束后 AI 复盘。' }}</span></footer>
    </template>
    <div class="custom"><button class="btn btn-ghost btn-sm" type="button" @click="emit('custom')">一句话描述自定义场景</button></div>
    </fieldset>
  </section>
</template>

<style scoped>
.setup .setup-fields { border: 0; margin: 0; padding: 0; min-width: 0; }
.setup { padding: 24px; } h2 { margin: 4px 0 8px; font-size: 24px; } .eyebrow { font-size: 11px; color: var(--muted); margin: 0; } .muted { color: var(--muted); line-height: 1.6; font-size: 13px; } .usages { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin: 24px 0; } .usages button,.scenario-card { border: 1px solid var(--border); color: var(--text); background: var(--card-2); border-radius: 8px; padding: 16px; text-align: left; min-height: 48px; } .usages button { cursor: pointer; } .usages button[aria-pressed=true],.scenario-card.selected { border-color: var(--blue); background: var(--blue-soft); } small { display: block; color: var(--muted); margin-top: 8px; font-size: 11px; } .scenarios { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; } .scenario-choice { display: block; width: 100%; padding: 0; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; } .scenario-choice strong { display: block; margin: 8px 0; font-size: 17px; } .scenario-choice span:not(.eyebrow) { font-size: 13px; line-height: 1.6; } .scenario-actions { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); } .scenario-actions p { margin: 0 0 10px; } .brief { padding: 16px; background: var(--card-2); margin: 24px 0 8px; border-radius: 8px; } .brief div + div { margin-top: 12px; } dt { font-size: 11px; color: var(--muted); } dd { margin: 4px 0 0; line-height: 1.6; } .client-fields { display: grid; gap: 12px; margin-top: 16px; } label { display: grid; gap: 6px; font-size: 13px; margin-bottom: 12px; } input,select,textarea { width: 100%; min-height: 44px; } .blocks { display: grid; gap: 16px; margin: 16px 0; } fieldset { border: 1px solid var(--border); border-radius: 8px; padding: 16px; min-width: 0; } legend { padding: 0 8px; font-weight: 600; } .person { border-top: 1px solid var(--border); padding-top: 12px; margin-bottom: 12px; } footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; border-top: 1px solid var(--border); padding-top: 20px; margin-top: 20px; } footer .btn { flex-shrink: 0; min-height: 48px; } .alert { color: var(--red); } .custom { margin-top: 16px; } button:focus-visible,summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; } button:disabled { opacity: .55; cursor: wait; } @media (max-width: 600px) { .setup { padding: 16px; } .usages { gap: 6px; margin: 16px 0; } .usages button { padding: 12px 8px; font-size: 13px; } .scenarios { grid-template-columns: 1fr; } footer { flex-direction: column; align-items: stretch; } }
.start-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.start-actions .btn { min-height: 44px; }
.card-groups { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.card-groups button,.topic-chips button { min-height: 44px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--card-2); color: var(--text); cursor: pointer; }
.card-groups button[aria-pressed=true],.topic-chips button[aria-pressed=true] { border-color: var(--blue); background: var(--blue-soft); }
.meeting-sources { margin-top: 12px; } .meeting-sources summary { cursor: pointer; min-height: 44px; padding-top: 10px; color: var(--blue); }
.meeting-sources label { margin-top: 8px; } .topic-chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.draft-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; }
.draft-actions .btn { min-height: 44px; border: 1px solid var(--blue); background: var(--blue-soft); color: var(--text); padding: 0 14px; }
.setup-confirm { margin: 12px 0; padding: 14px; border: 1px solid var(--blue); border-radius: 8px; background: var(--blue-soft); }
.setup-confirm p { margin: 0 0 10px; line-height: 1.5; }
.setup-confirm > div { display: flex; flex-wrap: wrap; gap: 8px; }
.setup-confirm .btn { min-height: 44px; }
@media (max-width: 600px) { .setup header .muted { margin: 4px 0 0; line-height: 1.4; } .usages { margin: 12px 0; } .scenario-card { padding: 12px; } .scenario-choice strong { margin: 4px 0; } .scenario-actions { margin-top: 8px; padding-top: 8px; } .scenario-actions p { display: none; } .start-actions .btn { flex: 1; } }
@media (max-width: 600px) { .card-groups { flex-wrap: nowrap; overflow-x: auto; white-space: nowrap; margin: 8px 0; } .card-groups button { flex: none; } }
@media (max-width: 600px) { .draft-actions .btn { width: 100%; } }
</style>
