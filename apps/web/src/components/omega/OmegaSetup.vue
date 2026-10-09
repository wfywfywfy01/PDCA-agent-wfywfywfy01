<script setup lang="ts">
import { computed, onMounted, ref, toRaw, watch } from 'vue'
import { apiGet, apiPost, HttpError } from '@/api/client'
import { meetingNames, usageNames, type TemplateDraft, type TemplateRow, type TemplateStart, type Usage } from './omega-types'

const props = defineProps<{ manager: boolean; multiVoiceReady: boolean; realtimeReady: boolean }>()
const emit = defineEmits<{ started: [result: TemplateStart, autoVoice: boolean]; custom: []; prepareVoice: []; cancelVoicePreparation: [] }>()
const templates = ref<TemplateRow[]>([])
const selected = ref<TemplateRow | null>(null)
const draft = ref<TemplateDraft | null>(null)
const usage = ref<Usage>('training')
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
let opportunityRequest = 0
let pendingLaunch: { body: string; key: string } | undefined
const visible = computed(() => templates.value.filter(row => row.available_usages?.includes(usage.value) || !row.draft.usage || row.draft.usage === usage.value))
const hasMultiple = computed(() => (draft.value?.participants?.length || 0) > 1)
const canStartVoice = computed(() => props.realtimeReady && (!hasMultiple.value || props.multiVoiceReady) && usage.value !== 'real_review')
function message(err: unknown) { return err instanceof HttpError ? err.detail : err instanceof Error ? err.message : '请求失败，请重试' }
function choose(row: TemplateRow) {
  selected.value = row
  draft.value = structuredClone(toRaw(row.draft))
  dealerId.value = row.draft.dealer_id || ''
  opportunityId.value = row.draft.opportunity_id || ''
  adjusting.value = false
  error.value = ''
  notice.value = ''
}
async function load() {
  error.value = ''
  loading.value = true
  try {
    templates.value = await apiGet<TemplateRow[]>('/api/omega/templates')
    const next = visible.value[0]
    if (next) choose(next)
  } catch (err) { error.value = message(err) }
  finally { loading.value = false }
}
watch(usage, () => { selected.value = null; draft.value = null; const next = visible.value[0]; if (next) choose(next) })
watch(dealerId, async (id) => {
  const request = ++opportunityRequest
  opportunityId.value = ''
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
async function start(autoVoice = false) {
  if (!draft.value || !selected.value || busy.value) return
  busy.value = true
  error.value = ''
  if (autoVoice) emit('prepareVoice')
  const reserved = new Set(['kind', 'dealer_id', 'opportunity_id', 'source_template_version_id', 'usage', 'simulation'])
  const original = selected.value.draft as unknown as Record<string, unknown>
  const overrides = Object.fromEntries(Object.entries(draft.value).filter(([name, value]) => !reserved.has(name) && JSON.stringify(value) !== JSON.stringify(original[name])))
  const payload = { template_id: selected.value.id, template_version: selected.value.current_version,
    usage: usage.value, dealer_id: dealerId.value, opportunity_id: opportunityId.value || null, overrides }
  const fingerprint = JSON.stringify(payload)
  if (pendingLaunch?.body !== fingerprint) pendingLaunch = { body: fingerprint, key: crypto.randomUUID() }
  try {
    const result = await apiPost<TemplateStart>('/api/omega/template-starts', { ...payload, request_key: pendingLaunch.key })
    pendingLaunch = undefined
    emit('started', result, autoVoice)
  } catch (err) { error.value = message(err); if (autoVoice) emit('cancelVoicePreparation') }
  finally { busy.value = false }
}
async function saveTemplate() {
  if (!draft.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const row = await apiPost<{ id: string }>('/api/omega/cases', { ...draft.value, kind: 'template', usage: usage.value,
      source_template_version_id: selected.value?.case_version_id || null,
      dealer_id: dealerId.value, opportunity_id: opportunityId.value || null })
    await apiPost(`/api/omega/cases/${row.id}/confirm`)
    await load()
    const saved = templates.value.find(item => item.id === row.id)
    if (saved) choose(saved)
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
    <header><p class="eyebrow">准备一场有目标的对话</p><h2 id="omega-setup-title">今天要练什么？</h2><p class="muted">选好场景直接开始。背景、对手和目标已经备好，你可以随时调整。</p></header>
    <div class="usages" role="group" aria-label="会议用途">
      <button v-for="(name, value) in usageNames" :key="value" type="button" :aria-pressed="usage === value" @click="usage = value">{{ name }}<small>{{ value === 'training' ? '练基本功' : value === 'rehearsal' ? '为真实客户做准备' : '从真实会议找改进' }}</small></button>
    </div>
    <p v-if="error" role="alert" class="alert">{{ error }}</p><p v-if="notice" role="status" class="muted">{{ notice }}</p>
    <p v-if="loading" role="status">正在读取场景卡…</p>
    <div v-else-if="!visible.length" class="empty"><p>当前用途还没有预设。</p><button class="btn" type="button" @click="emit('custom')">描述场景并创建</button><button v-if="error" class="btn btn-ghost" type="button" @click="load">重新读取</button></div>
    <div v-else class="scenarios" role="group" aria-label="场景卡">
      <button v-for="row in visible" :key="row.id" type="button" :aria-pressed="selected?.id === row.id" @click="choose(row)"><span class="eyebrow">{{ meetingNames[row.draft.meeting_type || 'negotiation'] || '谈判练习' }}</span><strong>{{ row.title }}</strong><span>{{ row.draft.goal.success_condition }}</span><small>{{ row.draft.simulation === false ? '真实背景' : '模拟场景' }} · {{ (row.draft.participants?.length || 1) > 1 ? '多人对手' : '一位主谈' }}</small></button>
    </div>
    <template v-if="draft">
      <div v-if="usage !== 'training' || dealerId" class="client-fields">
        <label>本场代理<select v-model="dealerId"><option value="">不关联代理</option><option v-for="dealer in dealers" :key="dealer.dealer_id" :value="dealer.dealer_id">{{ dealer.name }}</option></select></label>
        <label v-if="dealerId">合作事项<select v-model="opportunityId"><option value="">暂不关联事项</option><option v-for="row in opportunities" :key="row.id" :value="row.id">{{ row.title }}</option></select></label>
        <details v-if="dealerId"><summary>新建合作事项</summary><label>事项名称<input v-model.trim="opportunityTitle" maxlength="200" placeholder="例如：迪拜门店首批订单"></label><button class="btn btn-sm" type="button" :disabled="busy || !opportunityTitle" @click="addOpportunity">保存事项</button></details>
      </div>
      <dl class="brief"><div><dt>当前阶段</dt><dd>{{ draft.stage_summary || '开始沟通，先弄清对方顾虑。' }}</dd></div><div><dt>本场目标</dt><dd>{{ draft.goal.success_condition }}</dd></div><div><dt>我方底线</dt><dd>{{ draft.goal.hard_limits.join('；') }}</dd></div></dl>
      <button class="btn btn-ghost" type="button" :aria-expanded="adjusting" aria-controls="omega-blocks" @click="adjusting = !adjusting">{{ adjusting ? '收起调整' : '调整这张场景卡' }}</button>
      <form id="omega-blocks" v-show="adjusting" class="blocks" @submit.prevent="saveTemplate">
        <fieldset><legend>1 · 用途与会议类型</legend><label>场景名称<input v-model.trim="draft.title" required minlength="2" maxlength="200"></label><label>会议类型<select v-model="draft.meeting_type"><option v-for="(name, value) in meetingNames" :key="value" :value="value">{{ name }}</option></select></label></fieldset>
        <fieldset><legend>2 · 当前阶段</legend><label>一句话说明目前进展<textarea v-model.trim="draft.stage_summary" rows="2" maxlength="1000"></textarea></label></fieldset>
        <fieldset><legend>3 · 双方背景</legend><label>双方已知背景<textarea v-model.trim="draft.public_brief" rows="3" minlength="5" required></textarea></label><label>对手立场<textarea v-model.trim="draft.counterparty_brief" rows="2" minlength="5" required></textarea></label><label>销售私有信息<textarea v-model.trim="draft.seller_private" rows="2" placeholder="仅教练可见，不提供给对手"></textarea></label></fieldset>
        <fieldset><legend>4 · 对手与参会人</legend><p class="muted">默认一位主谈。需要采购、财务等共同参与时，可增加角色。</p><div v-for="(person, index) in draft.participants || []" :key="person.id" class="person"><label>姓名<input v-model.trim="person.name" required maxlength="100"></label><label>职位<input v-model.trim="person.role" required maxlength="100"></label><label>关注点<textarea :value="person.concerns.join('\n')" rows="2" @input="person.concerns = ($event.target as HTMLTextAreaElement).value.split('\n').filter(Boolean)"></textarea></label><label>此人知道的事实<textarea :value="person.known_facts.join('\n')" rows="2" @input="person.known_facts = ($event.target as HTMLTextAreaElement).value.split('\n').filter(Boolean)"></textarea></label><label>决策权限<input v-model.trim="person.decision_authority" maxlength="500"></label><button v-if="index > 0" class="btn btn-sm btn-ghost" type="button" @click="draft.participants?.splice(index, 1)">移除此人</button></div><button class="btn btn-sm" type="button" :disabled="(draft.participants?.length || 0) >= 3" @click="addParticipant">添加参会人</button></fieldset>
        <fieldset><legend>5 · 目标与底线</legend><label>本场要争取什么<textarea v-model.trim="draft.goal.success_condition" rows="2" minlength="5" required></textarea></label><label>理想结果<input v-model.trim="draft.goal.ideal" required minlength="2"></label><label>最低可接受结果<input v-model.trim="draft.goal.minimum" required minlength="2"></label><label>不能越过的底线（每行一条）<textarea :value="draft.goal.hard_limits.join('\n')" rows="2" required @input="draft.goal.hard_limits = ($event.target as HTMLTextAreaElement).value.split('\n').filter(Boolean)"></textarea></label></fieldset>
        <button class="btn" type="submit" :disabled="busy">{{ manager ? '保存为团队预设' : '保存为我的预设' }}</button>
      </form>
      <p v-if="hasMultiple && !multiVoiceReady && usage !== 'real_review'" class="muted" role="status">当前语音服务尚未通过多人能力验证。可先切回一位主谈，或使用文字演练。</p>
      <footer><span class="muted">{{ usage === 'real_review' ? '下一步选择真实会议并核对说话人。' : '对手会追问、施压，原话自动保存，结束后 AI 复盘。' }}</span><div class="start-actions"><button v-if="canStartVoice" class="btn btn-ghost" type="button" :disabled="busy || loading" @click="start(false)">文字开练</button><button class="btn btn-primary" type="button" :disabled="busy || loading" @click="start(canStartVoice)">{{ busy ? '准备中…' : usage === 'real_review' ? '选择会议' : canStartVoice ? '语音开练' : '用这张卡开练' }}</button></div></footer>
    </template>
    <div class="custom"><button class="btn btn-ghost btn-sm" type="button" @click="emit('custom')">一句话描述自定义场景</button></div>
  </section>
</template>

<style scoped>
.setup { padding: 24px; } h2 { margin: 4px 0 8px; font-size: 24px; } .eyebrow { font-size: 11px; color: var(--muted); margin: 0; } .muted { color: var(--muted); line-height: 1.6; font-size: 13px; } .usages { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin: 24px 0; } .usages button,.scenarios button { border: 1px solid var(--border); color: var(--text); background: var(--card-2); border-radius: 8px; padding: 16px; text-align: left; cursor: pointer; min-height: 48px; } button[aria-pressed=true] { border-color: var(--blue); background: var(--blue-soft); } small { display: block; color: var(--muted); margin-top: 8px; font-size: 11px; } .scenarios { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; } .scenarios strong { display: block; margin: 8px 0; font-size: 17px; } .scenarios span:not(.eyebrow) { font-size: 13px; line-height: 1.6; } .brief { padding: 16px; background: var(--card-2); margin: 24px 0 8px; border-radius: 8px; } .brief div + div { margin-top: 12px; } dt { font-size: 11px; color: var(--muted); } dd { margin: 4px 0 0; line-height: 1.6; } .client-fields { display: grid; gap: 12px; margin-top: 16px; } label { display: grid; gap: 6px; font-size: 13px; margin-bottom: 12px; } input,select,textarea { width: 100%; min-height: 44px; } .blocks { display: grid; gap: 16px; margin: 16px 0; } fieldset { border: 1px solid var(--border); border-radius: 8px; padding: 16px; min-width: 0; } legend { padding: 0 8px; font-weight: 600; } .person { border-top: 1px solid var(--border); padding-top: 12px; margin-bottom: 12px; } footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; border-top: 1px solid var(--border); padding-top: 20px; margin-top: 20px; } footer .btn { flex-shrink: 0; min-height: 48px; } .alert { color: var(--red); } .custom { margin-top: 16px; } button:focus-visible,summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; } button:disabled { opacity: .55; cursor: wait; } @media (max-width: 600px) { .setup { padding: 16px; } .usages { gap: 6px; margin: 16px 0; } .usages button { padding: 12px 8px; font-size: 13px; } .scenarios { grid-template-columns: 1fr; } footer { flex-direction: column; align-items: stretch; } }
.start-actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
