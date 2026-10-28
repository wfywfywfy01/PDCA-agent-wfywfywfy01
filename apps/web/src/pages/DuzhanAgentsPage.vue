<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { timeStage } from '@/api/duzhanBlocks'
import { genericStarterBlocks, modeOf, cloneTemplate, stages, updateStageSlot, type GroupOptionsResponse } from '@/api/duzhanWorkspace'
import DuzhanTaskPolicy from '@/components/DuzhanTaskPolicy.vue'
import AppNav from '@/components/AppNav.vue'
import { HttpError } from '@/api/client'
import { fetchBotChannels, type BotChannel } from '@/api/agentAdmin'
import BlockCard from '@/components/BlockCard.vue'
import DuzhanMonthlyMetrics from '@/components/DuzhanMonthlyMetrics.vue'
import {
  addBlock as appendBlock, agentPayload, aiStatus as fetchAiStatus, blockSchema, configChanged,
  createAgent, defaultBlock, deleteAgent, blockPositions, starterBlocks, groupOptions as fetchGroupOptions,
  fromJson, listAgents, moveBlock, nameForSelectedGroup, previewAgent, removeBlock, runtimeStatus as fetchRuntimeStatus,
  seedFromCode, toJson, toggleAgent,
  updateAgent, updateBlockField,
  type Block,
  type BlockTypeSpec,
  type AiStatus,
  type DuzhanAgentItem,
  type PreviewMode,
  type PreviewResult,
  type RenderPreviewResult,
  type DuzhanRuntimeStatus,
} from '@/api/duzhanAgents'

function todayInZone(zone: string): string {
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date())
}

const specs = ref<BlockTypeSpec[]>([])
const agents = ref<DuzhanAgentItem[]>([])
const selectedId = ref<number | null>(null)
const blocks = ref<Block[]>([])
const name = ref('')
const timezone = ref('Asia/Shanghai')
const note = ref('')
const enabled = ref(false)
const jsonText = ref(toJson(blocks.value))
const jsonError = ref('')
const preview = ref<PreviewResult | null>(null)
const rendered = ref<RenderPreviewResult | null>(null)
const previewMode = ref<PreviewMode>('render')
const day = ref(todayInZone('Asia/Shanghai'))
const hour = ref('')
const busy = ref(false)
const message = ref('')
const error = ref('')
const pendingDelete = ref(false)
const ai = ref<AiStatus | null>(null)
const runtime = ref<DuzhanRuntimeStatus | null>(null)
const channels = ref<BotChannel[]>([])
const channelsError = ref('')
const pendingTarget = ref<number | 'new' | null>(null)
const search = ref('')
const metricsEditor = ref<InstanceType<typeof DuzhanMonthlyMetrics> | null>(null)
const metricsDirty = ref(false)
const step = ref(1)
const draftBaseline = ref('')
const statusFilter = ref('all')
const directory = ref<GroupOptionsResponse | null>(null)
const directoryError = ref('')
const directoryBusy = ref(false)
const form = ref<HTMLFormElement | null>(null)
const isTasks = computed(() => modeOf(blocks.value) === 'group_tasks')
const taskPolicyIndex = computed(() => blocks.value.findIndex(block => block.type === 'task_policy'))
const selectedDirectoryGroup = computed(() => directory.value?.items.find(item => item.channel_id === selectedChannelId.value))
const selectedMembers = computed(() => selectedDirectoryGroup.value?.members || [])
const selectedGroupName = computed(() => String(blocks.value.find(block => block.type === 'group')?.label || '尚未选择群聊'))
const enabledCount = computed(() => agents.value.filter(item => item.enabled).length)
const publisherNames = computed(() => {
  const ids = blocks.value[taskPolicyIndex.value]?.publisher_user_ids
  return Array.isArray(ids) ? ids.map(id => selectedMembers.value.find(member => member.user_id === id)?.name || '成员 ' + id) : []
})
const exclusionsCount = computed(() => {
  const ids = blocks.value[taskPolicyIndex.value]?.excluded_user_ids
  return Array.isArray(ids) ? ids.length : 0
})
const conditionSpec = computed(() => {
  const spec = specs.value.find(item => item.type === 'condition') || { type: 'condition', label: '提醒条件', fields: [] }
  return !isTasks.value ? spec : { ...spec, fields: spec.fields.map(field => field.key === 'key'
    ? { ...field, options: (field.options || []).filter(key => ['workday', 'holiday'].includes(key)) } : field) }
})

const current = computed(() => agents.value.find((item) => item.id === selectedId.value) || null)
const savedErrors = computed(() => current.value?.errors || [])
const isDraft = computed(() => selectedId.value === null)
const groupOptions = computed(() => {
  if (isTasks.value) return (directory.value?.items || []).map(item => ({id:item.channel_id, label:item.label, disabled:item.available === false, reason:item.reason}))
  const botId = runtime.value?.bot_app_id
  if (!botId) return []
  const supported = new Set(runtime.value?.supported_channel_ids || [])
  const seen = new Set<string>()
  return channels.value
    .filter((channel) => channel.channel_type === 'group'
      && (channel.app_id || channel.bot_app_id) === botId
      && channel.channel_id
      && supported.has(channel.channel_id))
    .filter((channel) => {
      if (seen.has(channel.channel_id)) return false
      seen.add(channel.channel_id)
      return true
    })
    .map((channel) => ({ id: channel.channel_id, label: channel.channel_name || channel.channel_id }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
})
const selectedPlaneEnabled = computed(() =>
  isTasks.value ? runtime.value?.group_tasks_enabled : current.value?.renderer.startsWith('ctob') ? runtime.value?.ctob_enabled : runtime.value?.enabled,
)
const liveConfig = computed(() => selectedPlaneEnabled.value && (isTasks.value || runtime.value?.source === 'db'))
const filteredAgents = computed(() => agents.value.filter((item) =>
  (statusFilter.value === 'all' || item.enabled === (statusFilter.value === 'enabled')) && (groupLabel(item) + ' ' + item.name).toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()),
))
const groupIndices = computed(() => blockPositions(blocks.value, 'group'))
const timeIndices = computed(() => blockPositions(blocks.value, 'times'))
const conditionIndices = computed(() => blockPositions(blocks.value, 'condition'))
const ruleIndices = computed(() => blockPositions(blocks.value, 'rule'))
const selectedChannelId = computed(() => String(blocks.value.find((block) => block.type === 'group')?.channel_id || ''))
const departmentMembers = computed(() => runtime.value?.department_rosters?.[selectedChannelId.value] || [])
const departmentTaskOnlyMembers = computed(() => runtime.value?.department_task_only_rosters?.[selectedChannelId.value] || [])
const extraIndices = computed(() => blocks.value.flatMap((block, index) =>
  ['group', 'times', 'condition', 'rule', 'task_policy'].includes(block.type)
    || (block.type === 'people' && departmentMembers.value.length) ? [] : [index],
))
const previewSlots = computed(() => {
  const times = blocks.value.find((block) => block.type === 'times')
  return Array.isArray(times?.slots)
    ? times.slots.filter((slot): slot is string => typeof slot === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(slot))
    : []
})
const jsonPending = computed(() => jsonText.value !== toJson(blocks.value))
const unsaved = computed(() => metricsDirty.value || jsonPending.value || (isDraft.value ? JSON.stringify({name: name.value, timezone: timezone.value, note: note.value, blocks: blocks.value}) !== draftBaseline.value : configChanged(
  current.value
    ? { name: current.value.name, timezone: current.value.timezone, note: current.value.note, blocks: current.value.blocks.blocks }
    : null,
  { name: name.value, timezone: timezone.value, note: note.value, blocks: blocks.value },
)))

watch(blocks, () => { jsonText.value = toJson(blocks.value); preview.value = null; rendered.value = null }, { deep: true })

function describe(err: unknown): string {
  if (err instanceof HttpError) {
    const detail = (err as HttpError & { detail?: string }).detail
    return detail || err.message
  }
  return err instanceof Error ? err.message : String(err)
}

function fill(item: DuzhanAgentItem) {
  metricsDirty.value = false
  selectedId.value = item.id
  name.value = item.name
  timezone.value = item.timezone
  note.value = item.note
  enabled.value = item.enabled
  blocks.value = JSON.parse(JSON.stringify(item.blocks.blocks))
  jsonText.value = toJson(blocks.value)
  preview.value = null
  rendered.value = null
  pendingDelete.value = false
  jsonError.value = ''
  pendingTarget.value = null
  hour.value = ''
  day.value = todayInZone(item.timezone)
  message.value = ''
  error.value = ''
}

function startDraft() {
  step.value = 1
  metricsDirty.value = false
  selectedId.value = null
  name.value = ''
  timezone.value = 'Asia/Shanghai'
  note.value = ''
  enabled.value = false
  blocks.value = genericStarterBlocks()
  jsonText.value = toJson(blocks.value)
  preview.value = null
  rendered.value = null
  message.value = ''
  error.value = ''
  pendingDelete.value = false
  pendingTarget.value = null
  hour.value = ''
  day.value = todayInZone('Asia/Shanghai')
  draftBaseline.value = JSON.stringify({name: name.value, timezone: timezone.value, note: note.value, blocks: blocks.value})
}

function selectAgent(item: DuzhanAgentItem) {
  if (item.id === selectedId.value) return
  if (unsaved.value) {
    pendingTarget.value = item.id
    return
  }
  fill(item)
}

function requestDraft() {
  if (unsaved.value) {
    pendingTarget.value = 'new'
    return
  }
  startDraft()
}

function discardAndSwitch() {
  const target = pendingTarget.value
  pendingTarget.value = null
  if (target === 'new') startDraft()
  else if (target !== null) {
    const item = agents.value.find((row) => row.id === target)
    if (item) fill(item)
  }
}

function groupBlock(item: DuzhanAgentItem): Block | undefined {
  return item.blocks.blocks.find((block) => block.type === 'group')
}

function groupLabel(item: DuzhanAgentItem): string {
  const group = groupBlock(item)
  return String(group?.label || groupOptions.value.find((option) => option.id === group?.channel_id)?.label || item.name)
}

function slotsLabel(item: DuzhanAgentItem): string {
  const times = item.blocks.blocks.find((block) => block.type === 'times')
  return Array.isArray(times?.slots) && times.slots.length ? times.slots.join(' · ') : '未设定时段'
}

function ruleCount(item: DuzhanAgentItem): number {
  return item.blocks.blocks.filter((block) => block.type === 'rule').length
}

async function reload(keepId: number | null) {
  agents.value = (await listAgents()).items
  const next = agents.value.find((item) => item.id === keepId)
  if (next) fill(next)
}

async function loadAiStatus() {
  try {
    ai.value = await fetchAiStatus()
  } catch {
    ai.value = null  // 用量看板拿不到不影响配置
  }
}

async function load() {
  busy.value = true
  error.value = ''
  channelsError.value = ''
  try {
    const [schema, rows, status] = await Promise.all([blockSchema(), listAgents(), fetchRuntimeStatus()])
    specs.value = schema.blocks
    agents.value = rows.items
    runtime.value = status
    const selected = agents.value.find((item) => item.id === selectedId.value) || agents.value[0]
    if (selected) fill(selected)
    else startDraft()
    void loadAiStatus()
    void loadDirectory()
    try {
      channels.value = (await fetchBotChannels()).items
    } catch (err) {
      channelsError.value = describe(err)
    }
  } catch (err) {
    error.value = describe(err)
  } finally {
    busy.value = false
  }
}

async function save() {
  if (!name.value.trim() || !selectedChannelId.value) { step.value = 1; error.value = '请选择目标群并填写配置名称。'; return false }
  if (jsonPending.value) {
    error.value = '先按 JSON 覆盖卡片，再保存。'
    return
  }
  if (metricsDirty.value && !await metricsEditor.value?.save()) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const payload = agentPayload({ name: name.value, timezone: timezone.value, note: note.value, blocks: blocks.value })
    const saved = selectedId.value === null
      ? await createAgent(payload)
      : await updateAgent(selectedId.value, payload)
    await reload(saved.id)
    message.value = saved.errors.length
      ? '已保存，另有 ' + saved.errors.length + ' 处配置待修正，暂时不能启用。'
      : isTasks.value ? '已保存。启用后的配置会在一分钟内被调度器读取。' : (liveConfig.value ? '已保存。月度指标、文案和条件在下次检查生效；业务群与时段变更仍需重启服务。' : '已保存。当前业务督战未使用这份配置发送。')
    return true
  } catch (err) {
    error.value = describe(err)
  } finally {
    busy.value = false
  }
}

async function setEnabled(next: boolean) {
  if (selectedId.value === null) return
  if (unsaved.value) {
    error.value = '先保存当前改动，再启用或停用。'
    return
  }
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const saved = await toggleAgent(selectedId.value, next)
    await reload(saved.id)
    message.value = isTasks.value ? (next ? '已启用，将按配置时间执行。' : '已暂停，后续时段不再执行。') : liveConfig.value
      ? '已更新启停状态；业务群调度变更需要重启服务才生效。'
      : '已更新启停状态；当前生产仍使用代码配置。'
  } catch (err) {
    error.value = describe(err)
  } finally {
    busy.value = false
  }
}

async function removeCurrent() {
  if (selectedId.value === null) return
  if (!pendingDelete.value) {
    pendingDelete.value = true
    return
  }
  busy.value = true
  error.value = ''
  try {
    await deleteAgent(selectedId.value)
    selectedId.value = null
    agents.value = (await listAgents()).items
    if (agents.value.length) fill(agents.value[0])
    else startDraft()
    message.value = '已删除。'
  } catch (err) {
    error.value = describe(err)
  } finally {
    busy.value = false
    pendingDelete.value = false
  }
}

async function runPreview() {
  if (selectedId.value === null || unsaved.value) {
    error.value = '先保存当前改动，再预览。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const result = await previewAgent(
      selectedId.value,
      day.value,
      hour.value || undefined,
      previewMode.value,
    )
    if (previewMode.value === 'render') {
      rendered.value = result as RenderPreviewResult
      preview.value = null
      if (blocks.value.some((block) => block.type === 'rule' && block.mode === 'ai')) await loadAiStatus()
    } else {
      preview.value = result as PreviewResult
      rendered.value = null
    }
  } catch (err) {
    error.value = describe(err)
  } finally {
    busy.value = false
  }
}

async function importFromCode() {
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await seedFromCode()
    agents.value = (await listAgents()).items
    if (selectedId.value === null && !unsaved.value && agents.value.length) fill(agents.value[0])
    message.value = '导入完成：新增 ' + result.created.length + ' 条（默认停用），跳过 ' + result.skipped.length + ' 条同名。'
  } catch (err) {
    error.value = describe(err)
  } finally {
    busy.value = false
  }
}

function onAddBlock(spec: BlockTypeSpec) {
  if (spec.multiple === false && blocks.value.some((block) => block.type === spec.type)) return
  blocks.value = appendBlock(blocks.value, defaultBlock(spec))
}

function onFieldChange(index: number, key: string, value: unknown) {
  if (metricsDirty.value && blocks.value[index]?.type === 'group') {
    error.value = '请先保存本月指标，再更换目标群。'
    return
  }
  const previousLabel = String(blocks.value[index]?.label || '')
  if (isTasks.value && blocks.value[index]?.type === 'group' && key === 'channel_id' && value !== selectedChannelId.value) {
    blocks.value = blocks.value.map(block => block.type === 'task_policy' ? { ...block, publisher_user_ids: [], excluded_user_ids: [] } : block)
  }
  blocks.value = updateBlockField(blocks.value, index, key, value)
  if (blocks.value[index]?.type === 'group' && key === 'channel_id' && departmentMembers.value.length) {
    blocks.value = blocks.value.map((block) => block.type === 'people'
      ? { ...block, names: [...departmentMembers.value] } : block)
  }
  if (selectedId.value === null && blocks.value[index]?.type === 'group' && key === 'label') {
    name.value = nameForSelectedGroup(name.value, previousLabel, String(value || ''))
  }
}

function onMove(index: number, offset: number) {
  const positions = blockPositions(blocks.value, blocks.value[index].type)
  const target = positions[positions.indexOf(index) + offset]
  if (target !== undefined) blocks.value = moveBlock(blocks.value, index, target)
}

function canMove(index: number, offset: number): boolean {
  const positions = blockPositions(blocks.value, blocks.value[index].type)
  return positions[positions.indexOf(index) + offset] !== undefined
}

function addType(type: string) {
  const spec = specs.value.find((item) => item.type === type)
  if (spec) onAddBlock(spec)
}

function onRemove(index: number) {
  blocks.value = removeBlock(blocks.value, index)
}

function applyJson() {
  if (metricsDirty.value) {
    error.value = '请先保存本月指标，再覆盖卡片。'
    return
  }
  jsonError.value = ''
  try {
    blocks.value = fromJson(jsonText.value)
    message.value = '已按 JSON 覆盖中间列表。'
  } catch (err) {
    jsonError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadDirectory() {
  directoryBusy.value = true
  directoryError.value = ''
  try { directory.value = await fetchGroupOptions(); directoryError.value = directory.value.error || '' }
  catch (err) { directoryError.value = describe(err) }
  finally { directoryBusy.value = false }
}
function chooseGroup(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  if (!groupIndices.value.length) addType('group')
  const index = groupIndices.value[0]
  onFieldChange(index, 'channel_id', id)
  onFieldChange(index, 'label', groupOptions.value.find(option => option.id === id)?.label || '')
}
function chooseTemplate(mode: 'group_tasks' | 'business') {
  if (selectedChannelId.value || !isDraft.value) return
  blocks.value = mode === 'group_tasks' ? genericStarterBlocks() : starterBlocks(specs.value)
  draftBaseline.value = JSON.stringify({name: name.value, timezone: timezone.value, note: note.value, blocks: blocks.value})
}
function copyTemplate() {
  if (unsaved.value) { error.value = '先保存当前改动，再复用规则。'; return }
  const copied = cloneTemplate(blocks.value)
  startDraft()
  blocks.value = copied
  message.value = '已复制规则。请选择新的群和成员；新卡片默认暂停。'
}
function stageSlot(key: string): string { return previewSlots.value.find(slot => timeStage(slot) === key) || '' }
function setStage(key: string, value: string | null) {
  try { blocks.value = updateStageSlot(blocks.value, key, value); error.value = '' }
  catch (err) { error.value = describe(err) }
}
async function saveAndPreview() {
  if (unsaved.value || isDraft.value) { if (!await save()) return }
  step.value = 3
  await runPreview()
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (unsaved.value) { event.preventDefault(); event.returnValue = '' }
}
onBeforeRouteLeave(() => {
  if (!unsaved.value) return true
  error.value = '当前有未保存的改动，请先保存再离开。'
  return false
})
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load() })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<template>
  <AppNav />
  <main class="page duzhan-page">
    <header class="page-head">
      <div><p class="eyebrow">VPS / 群协作</p><h1>督战工作台<span class="title-tag">按群配置</span></h1><p class="sub">把群里的任务，跟到有结果。规则配一次，按时自动检查。</p></div>
      <div class="actions"><button class="btn" type="button" :disabled="busy || unsaved" @click="load">刷新</button><button class="btn btn-primary" type="button" :disabled="busy" @click="requestDraft">＋ 新建督战</button></div>
    </header>

    <p v-if="message" class="notice success" role="status">{{ message }}</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <div v-if="pendingTarget !== null" class="notice warning" role="alert"><span>当前配置有未保存的改动。</span><div class="actions"><button class="btn" type="button" @click="pendingTarget = null">继续编辑</button><button class="btn" type="button" @click="discardAndSwitch">放弃改动并切换</button></div></div>

    <div class="workspace">
      <aside class="group-list" aria-label="督战群列表">
        <div class="list-heading"><h2>我的督战群</h2><span>{{ agents.length }}</span></div>
        <label class="sr-only" for="group-search">搜索督战群</label><input id="group-search" v-model="search" class="control search" type="search" placeholder="搜索群名称…" />
        <div class="list-filters" aria-label="按状态筛选"><button v-for="filter in [{ key: 'all', label: '全部' }, { key: 'enabled', label: '已启用' }, { key: 'paused', label: '已暂停' }]" :key="filter.key" type="button" :aria-pressed="statusFilter === filter.key" @click="statusFilter = filter.key">{{ filter.label }}</button></div>
        <p v-if="busy && !agents.length" class="hint list-empty" role="status">正在读取群配置…</p>
        <div class="group-scroll">
          <button v-for="item in filteredAgents" :key="item.id" class="group-row" type="button" :class="{ selected: item.id === selectedId }" :aria-current="item.id === selectedId ? 'true' : undefined" :disabled="busy" @click="selectAgent(item)">
            <span class="group-avatar" aria-hidden="true">{{ groupLabel(item).slice(0, 1) }}</span><span class="group-copy"><strong>{{ groupLabel(item) }}</strong><small>{{ modeOf(item.blocks.blocks) === 'group_tasks' ? '任务闭环' : '业务督战' }} · {{ item.enabled ? '已启用' : '已暂停' }}</small><small v-if="item.errors.length" class="error-text">{{ item.errors.length }} 项待完善</small></span><span class="state-dot" :class="{ on: item.enabled }" aria-hidden="true"></span>
          </button>
          <p v-if="!busy && !filteredAgents.length" class="hint list-empty">{{ agents.length ? '没有符合条件的群。' : '还没有督战群，点击“新建督战”开始。' }}</p>
        </div>
        <div class="list-foot"><span>{{ enabledCount }} 个已启用</span><span>{{ agents.length - enabledCount }} 个已暂停</span></div>
        <details class="legacy-import"><summary>导入已有业务群</summary><p class="hint">只新增停用草稿，已有配置保持不变。</p><button class="btn btn-sm" type="button" :disabled="busy || unsaved" @click="importFromCode">导入业务群</button></details>
      </aside>

      <div class="workspace-content">
        <section class="editor" aria-labelledby="editor-title" :aria-busy="busy">
          <header class="editor-head"><div><p class="eyebrow">{{ isDraft ? '新建督战' : isTasks ? '通用群任务' : '部门业务督战' }}</p><h2 id="editor-title">{{ isDraft ? '让一个群开始有序跟进' : selectedGroupName }}</h2></div><span class="status-tag" :class="{ unsaved, on: enabled && !unsaved }">{{ isDraft ? '草稿' : unsaved ? '未保存' : enabled ? '已启用' : '已暂停' }}</span></header>
          <nav class="steps" aria-label="配置步骤"><button v-for="item in [{ n: 1, title: '群与人员' }, { n: 2, title: '规则与时间' }, { n: 3, title: '预览与启用' }]" :key="item.n" type="button" :aria-current="step === item.n ? 'step' : undefined" @click="step = item.n"><span>{{ item.n }}</span>{{ item.title }}</button></nav>

          <div v-show="step === 1" class="step-body">
            <section v-if="isDraft" class="section"><div class="section-heading"><h3>这次督战什么？</h3><p>选择适合这个群的方式。</p></div><div class="template-grid">
              <button class="template" :class="{ chosen: isTasks }" type="button" :disabled="busy || !!selectedChannelId" :aria-pressed="isTasks" @click="chooseTemplate('group_tasks')"><span class="template-symbol" aria-hidden="true">✓</span><strong>群任务闭环<span>通用</span></strong><p>跟进指定发布人的任务，核对成员提交，提醒未完成事项。</p><small>适合项目群、工作群、专项任务群</small></button>
              <button class="template" :class="{ chosen: !isTasks }" type="button" :disabled="busy || !!selectedChannelId" :aria-pressed="!isTasks" @click="chooseTemplate('business')"><span class="template-symbol" aria-hidden="true">↗</span><strong>部门业绩督战</strong><p>按部门追业绩目标、待办和 MTO，沿用已接入的业务数据。</p><small>适合现有经销商业务群</small></button>
            </div></section>

            <section class="section"><div class="section-heading"><h3>连接群聊</h3><p>选择督战机器人已加入、能够读取消息的 VPS 群。</p></div>
              <form ref="form" class="group-form" @submit.prevent="save">
                <label class="field">目标群<select class="control" aria-label="目标群" :value="selectedChannelId" :disabled="busy || metricsDirty || (isTasks && directoryBusy)" required @change="chooseGroup"><option value="">{{ isTasks && directoryBusy ? '正在读取 VPS 群…' : '选择一个群聊' }}</option><option v-for="option in groupOptions" :key="option.id" :value="option.id" :disabled="'disabled' in option && !!option.disabled">{{ option.label }}{{ 'reason' in option && option.reason ? ' · ' + option.reason : '' }}</option><option v-if="selectedChannelId && !groupOptions.some(option => option.id === selectedChannelId)" :value="selectedChannelId">{{ selectedGroupName }}（需复核连接）</option></select></label>
                <label class="field">配置名称<input v-model="name" class="control" type="text" maxlength="128" required :disabled="busy" placeholder="选群后自动填写，也可以改名" /></label>
              </form>
              <div v-if="isTasks" class="connection" :class="{ connected: selectedDirectoryGroup?.bot_joined && selectedDirectoryGroup?.available !== false }"><span class="connection-icon" aria-hidden="true">{{ selectedDirectoryGroup?.bot_joined && selectedDirectoryGroup?.available !== false ? '✓' : '○' }}</span><div><strong>{{ selectedDirectoryGroup?.bot_joined && selectedDirectoryGroup?.available !== false ? '群连接已就绪' : selectedChannelId ? '等待验证群连接' : '选择群聊后检查连接' }}</strong><p>{{ selectedDirectoryGroup?.reason || (selectedDirectoryGroup ? '已读取 ' + selectedMembers.length + ' 位群成员；启用前会再次检查权限。' : '群没有出现时，先由群管理员添加督战机器人，再刷新列表。') }}</p></div><button class="text-button" type="button" :disabled="directoryBusy" @click="loadDirectory">{{ directoryBusy ? '读取中…' : '刷新群列表' }}</button></div>
              <p v-if="isTasks && directoryError" class="notice error" role="alert">群列表读取失败：{{ directoryError }}。输入的配置仍然保留。</p><p v-else-if="!isTasks && channelsError" class="notice warning" role="status">业务群列表读取失败：{{ channelsError }}</p>
            </section>

            <section v-if="isTasks && taskPolicyIndex >= 0 && selectedChannelId" class="section"><div class="section-heading"><h3>跟谁发布的任务，提醒哪些人？</h3><p>按任务中明确的负责人跟进；全员任务使用当前群成员。</p></div><DuzhanTaskPolicy :key="selectedChannelId" :block="blocks[taskPolicyIndex]" :members="selectedMembers" :disabled="busy || !selectedChannelId || directoryBusy" @change="(key, value) => onFieldChange(taskPolicyIndex, key, value)" /></section>
            <section v-else-if="departmentMembers.length" class="section"><div class="section-heading"><h3>部门成员</h3><p>每个时段汇总为一条，业绩按整个部门统计。</p></div><div class="member-chips"><span v-for="member in departmentMembers" :key="member">{{ member }}<small v-if="departmentTaskOnlyMembers.includes(member)">仅追待办</small></span></div><p v-if="departmentTaskOnlyMembers.length" class="hint">“仅追待办”成员计入部门业绩，暂停 MTO 等专项催办。</p></section>
            <div class="step-actions"><span class="hint">新配置保存后默认暂停。</span><button class="btn btn-primary" type="button" :disabled="!selectedChannelId" @click="step = 2">下一步：规则与时间 →</button></div>
          </div>

          <div v-show="step === 2" class="step-body">
            <section class="section"><div class="section-heading"><h3>一天怎么跟进</h3><p>{{ isTasks ? '早上提醒任务，晚上核对实际提交；中午提醒可选。' : '早上追目标和待办，中午简单提醒，晚上详细检查闭环。' }}</p></div>
              <div class="schedule-grid"><article v-for="stage in stages" :key="stage.key" class="schedule" :class="{ active: !!stageSlot(stage.key) }"><label class="schedule-toggle"><input type="checkbox" :checked="!!stageSlot(stage.key)" :disabled="busy" @change="setStage(stage.key, ($event.target as HTMLInputElement).checked ? stage.defaultTime : null)" /><strong>{{ stage.label }}</strong><span>{{ stageSlot(stage.key) ? '开启' : '关闭' }}</span></label><p>{{ stage.key === '早追' ? (isTasks ? '列出待完成任务和截止时间。' : '目标、当天与本周待办、MTO。') : stage.key === '中追' ? '简短催办，提醒继续推进。' : '核对提交证据，追未闭环事项。' }}</p><label class="sr-only" :for="'stage-' + stage.key">{{ stage.label }}时间</label><input :id="'stage-' + stage.key" type="time" step="60" :min="stage.min" :max="stage.max" :value="stageSlot(stage.key)" :disabled="busy || !stageSlot(stage.key)" @change="setStage(stage.key, ($event.target as HTMLInputElement).value)" /><small>{{ stage.min }} – {{ stage.max }}</small></article></div>
              <label class="timezone">时区 <select v-model="timezone" class="control" :disabled="busy || current?.renderer.startsWith('ctob')"><option>Asia/Shanghai</option><option>Europe/Paris</option><option>Asia/Dubai</option><option>America/New_York</option><option>UTC</option><option v-if="!['Asia/Shanghai', 'Europe/Paris', 'Asia/Dubai', 'America/New_York', 'UTC'].includes(timezone)">{{ timezone }}</option></select></label>
            </section>

            <DuzhanMonthlyMetrics v-if="departmentMembers.length && !isTasks" :key="String(selectedId) + selectedChannelId" ref="metricsEditor" :channel-id="selectedChannelId" :initial-month="todayInZone(timezone).slice(0, 7)" :disabled="busy" :active="runtime?.source === 'db'" :metric-members="departmentMembers.length - departmentTaskOnlyMembers.length" @dirty="metricsDirty = $event" @saved="rendered = null; preview = null" />

            <section v-if="isTasks" class="section"><div class="section-heading"><h3>闭环判断</h3><p>保留原任务、负责人、截止时间与提交证据。</p></div><ol class="evidence-flow"><li><span>1</span><div><strong>读取指定发布人的任务</strong><p>从群消息识别任务和负责人。</p></div></li><li><span>2</span><div><strong>核对群里的实际提交</strong><p>“已交”不等于证据齐全，提交状态与最终验收分开。</p></div></li><li><span>3</span><div><strong>追未完成，保留待确认</strong><p>采集失败或消息不完整时标记待确认，不直接认定未提交。</p></div></li></ol></section>

            <details class="option-section" :open="conditionIndices.length > 0"><summary>提醒条件<span>{{ conditionIndices.length ? conditionIndices.length + ' 条条件' : '使用默认规则' }}</span></summary><p class="hint">多条条件需要同时满足。{{ isTasks ? '可按工作日或节假日筛选。' : '默认按现有业务工作日规则执行。' }}</p><BlockCard v-for="index in conditionIndices" :key="'condition-' + index" :block="blocks[index]" :spec="conditionSpec" :index="index" :total="blocks.length" :disabled="busy" @change="(key, value) => onFieldChange(index, key, value)" @remove="onRemove(index)" /><button class="text-button" type="button" :disabled="busy" @click="addType('condition')">＋ 添加提醒条件</button></details>

            <details v-if="!isTasks" class="option-section" :open="ruleIndices.length > 0"><summary>自定义提醒重点<span>{{ ruleIndices.length ? ruleIndices.length + ' 条规则' : '默认早简晚详' }}</span></summary><p class="hint">只修改提醒中的“本档动作”。业务数据和闭环结果仍由系统核对。</p><BlockCard v-for="index in ruleIndices" :key="'rule-' + index" :block="blocks[index]" :spec="specs.find(item => item.type === 'rule') || { type: 'rule', label: '提醒重点', fields: [] }" :index="index" :total="blocks.length" :disabled="busy" :can-move-up="canMove(index, -1)" :can-move-down="canMove(index, 1)" @change="(key, value) => onFieldChange(index, key, value)" @move="offset => onMove(index, offset)" @remove="onRemove(index)" /><button class="text-button" type="button" :disabled="busy" @click="addType('rule')">＋ 添加固定文案 / AI 重点</button></details>
            <div class="step-actions"><button class="btn" type="button" @click="step = 1">← 群与人员</button><button class="btn btn-primary" type="button" :disabled="busy" @click="saveAndPreview">保存并预览 →</button></div>
          </div>

          <div v-show="step === 3" class="step-body">
            <section class="section"><div class="section-heading"><h3>先看看会发什么</h3><p>预览使用已采集的数据，不向群里发送消息。</p></div><div class="preview-controls"><label class="field">日期<input v-model="day" class="control" type="date" /></label><label class="field">时间<select v-model="hour" class="control"><option value="">最近时段</option><option v-for="slot in previewSlots" :key="slot" :value="slot">{{ slot }}</option></select></label><label class="field">预览内容<select v-model="previewMode" class="control"><option value="render">群消息</option><option value="structure">配置检查</option></select></label><button class="btn" type="button" :disabled="busy" @click="saveAndPreview">{{ unsaved || isDraft ? '保存并预览' : '刷新预览' }}</button></div>
              <div v-if="!preview && !rendered" class="preview-empty"><span aria-hidden="true">▤</span><strong>提醒内容将在这里出现</strong><p>首次使用还没有任务台账时，预览会显示待确认。</p></div>
              <template v-if="rendered"><p v-if="!rendered.ok" class="notice error" role="alert">{{ rendered.error }}</p><template v-else><p class="hint">{{ rendered.note }}</p><div class="message-preview"><header><span class="bot-avatar" aria-hidden="true">督</span><div><strong>督战官</strong><small>{{ rendered.group }} · {{ rendered.day }} {{ rendered.slot }}</small></div><span class="preview-label">预览</span></header><pre>{{ rendered.body || '暂无已采集的任务。首次执行后再查看证据。' }}</pre></div><p class="preview-reason" :class="{ allowed: rendered.send_allowed }">{{ rendered.send_reason }}{{ rendered.send_allowed ? '；实际发送还需启用且到达执行时间。' : '。' }}</p></template></template>
              <template v-if="preview"><p class="hint">{{ preview.note }}</p><ul class="summary-lines"><li v-for="(line, index) in preview.summary" :key="index">{{ line }}</li></ul><ul v-if="preview.errors.length" class="validation-errors"><li v-for="(item, index) in preview.errors" :key="index">{{ item }}</li></ul></template>
              <p v-if="blocks.some(block => block.type === 'rule' && block.mode === 'ai')" class="hint">AI 文案预览会调用模型并使用额度。{{ ai ? '今日 ' + ai.calls + ' / ' + ai.limit + ' 次' : '' }}</p>
            </section>
            <section class="activation"><div><h3>{{ enabled ? '督战已启用' : '确认后再启用' }}</h3><p>{{ isTasks ? '保存不会自动启用。启用后，配置会在一分钟内被调度器读取。' : '此为业务督战，改群、时间或启停后仍需重启服务更新定时任务。' }}</p></div><button class="btn" :class="enabled ? '' : 'btn-primary'" type="button" :disabled="busy || isDraft || unsaved || (!enabled && (savedErrors.length > 0 || !liveConfig))" @click="setEnabled(!enabled)">{{ enabled ? '暂停督战' : '启用督战' }}</button></section>
            <p v-if="runtime && !liveConfig" class="notice warning">{{ !selectedPlaneEnabled ? '这类督战的调度总开关未开启，可保存和预览，暂不发送。' : '业务督战仍使用代码配置，需切换到后台配置后生效。' }}</p>
          </div>

          <footer class="editor-footer"><div><strong>{{ isDraft ? '尚未保存' : unsaved ? '有改动待保存' : '配置已保存' }}</strong><span>{{ isTasks ? '通用任务配置 · 按群独立生效' : '业务配置 · 保留部门数据口径' }}</span></div><div class="actions"><button v-if="step > 1" class="btn" type="button" :disabled="busy" @click="step--">上一步</button><button class="btn btn-primary" type="button" :disabled="busy || (!unsaved && !isDraft)" @click="save">{{ busy ? '处理中…' : isDraft ? '保存草稿' : '保存改动' }}</button></div></footer>
        </section>

        <aside class="config-summary" aria-label="当前规则摘要"><div class="summary-heading"><span class="summary-mark" aria-hidden="true">✓</span><h2>这张卡片会做什么</h2></div><dl><dt>目标群</dt><dd>{{ selectedGroupName }}</dd><dt>督战方式</dt><dd>{{ isTasks ? '任务闭环' : '部门业务督战' }}</dd><dt>{{ isTasks ? '任务发布人' : '部门成员' }}</dt><dd>{{ isTasks ? publisherNames.join('、') || '尚未选择' : departmentMembers.join('、') || '沿用群的业务名单' }}</dd><template v-if="isTasks"><dt>排除人员</dt><dd>{{ exclusionsCount ? exclusionsCount + ' 人不参与催办' : '未设置排除人员' }}</dd></template><dt>执行时间</dt><dd>{{ previewSlots.join(' / ') || '尚未设置' }}<small>{{ timezone }}</small></dd></dl><p class="summary-foot">{{ isTasks ? '早间提醒 · 晚间核证据' : '早间规划 · 午间轻催 · 晚间复盘' }}</p><p v-if="!isDraft" class="hint">{{ current?.updated_at ? '最近保存：' + new Date(current.updated_at).toLocaleString('zh-CN') : '' }}</p><button v-if="!isDraft" class="btn" type="button" :disabled="busy || unsaved" @click="copyTemplate">复用规则到新群</button></aside>

        <div class="advanced-area"><ul v-if="savedErrors.length" class="validation-errors" role="alert"><li v-for="(item, index) in savedErrors" :key="index">{{ item }}</li></ul><details class="advanced"><summary>更多设置与兼容配置</summary><label class="field">备注<input v-model="note" class="control" type="text" maxlength="256" :disabled="busy" /></label><p v-if="extraIndices.length" class="hint">以下旧版配置保留原值。数据源、策略与额外收件人字段仅用于结构说明，不扩展实际采集或发送范围。</p><BlockCard v-for="index in extraIndices" :key="index" :block="blocks[index]" :spec="specs.find(item => item.type === blocks[index].type) || { type: blocks[index].type, label: blocks[index].type, fields: [] }" :index="index" :total="blocks.length" :disabled="busy" locked @change="(key, value) => onFieldChange(index, key, value)" /><details><summary>维护人员：配置 JSON</summary><textarea v-model="jsonText" class="control json" rows="8" spellcheck="false" aria-label="配置 JSON"></textarea><p v-if="jsonPending" class="hint">JSON 修改尚未应用。</p><p v-if="jsonError" class="error-text" role="alert">{{ jsonError }}</p><button class="btn" type="button" :disabled="busy" @click="applyJson">应用到卡片</button></details><div v-if="!isDraft" class="delete-row"><button class="text-button danger" type="button" :disabled="busy || unsaved" @click="removeCurrent">{{ pendingDelete ? '确认删除这张配置' : '删除配置' }}</button><button v-if="pendingDelete" class="text-button" type="button" @click="pendingDelete = false">取消</button></div></details></div>
      </div>
    </div>
  </main>
</template>

<style scoped src="../styles/duzhan-workspace.css"></style>
