<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AppNav from '@/components/AppNav.vue'
import { HttpError } from '@/api/client'
import { fetchBotChannels, type BotChannel } from '@/api/agentAdmin'
import BlockCard from '@/components/BlockCard.vue'
import {
  addBlock as appendBlock, agentPayload, aiStatus as fetchAiStatus, blockSchema, configChanged,
  createAgent, defaultBlock, deleteAgent, blockPositions, starterBlocks,
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

const current = computed(() => agents.value.find((item) => item.id === selectedId.value) || null)
const savedErrors = computed(() => current.value?.errors || [])
const isDraft = computed(() => selectedId.value === null)
const groupOptions = computed(() => {
  const botId = runtime.value?.bot_app_id
  if (!botId) return []
  const seen = new Set<string>()
  return channels.value
    .filter((channel) => channel.channel_type === 'group'
      && (channel.app_id || channel.bot_app_id) === botId
      && channel.channel_id)
    .filter((channel) => {
      if (seen.has(channel.channel_id)) return false
      seen.add(channel.channel_id)
      return true
    })
    .map((channel) => ({ id: channel.channel_id, label: channel.channel_name || channel.channel_id }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
})
const liveConfig = computed(() => runtime.value?.enabled && runtime.value.source === 'db')
const filteredAgents = computed(() => agents.value.filter((item) =>
  (groupLabel(item) + ' ' + item.name).toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()),
))
const groupIndices = computed(() => blockPositions(blocks.value, 'group'))
const timeIndices = computed(() => blockPositions(blocks.value, 'times'))
const conditionIndices = computed(() => blockPositions(blocks.value, 'condition'))
const ruleIndices = computed(() => blockPositions(blocks.value, 'rule'))
const extraIndices = computed(() => blocks.value.flatMap((block, index) =>
  ['group', 'times', 'condition', 'rule'].includes(block.type) ? [] : [index],
))
const previewSlots = computed(() => {
  const times = blocks.value.find((block) => block.type === 'times')
  return Array.isArray(times?.slots)
    ? times.slots.filter((slot): slot is string => typeof slot === 'string' && /^\d{2}:00$/.test(slot))
    : []
})
const jsonPending = computed(() => jsonText.value !== toJson(blocks.value))
const unsaved = computed(() => jsonPending.value || configChanged(
  current.value
    ? { name: current.value.name, timezone: current.value.timezone, note: current.value.note, blocks: current.value.blocks.blocks }
    : null,
  { name: name.value, timezone: timezone.value, note: note.value, blocks: blocks.value },
))

watch(blocks, () => { jsonText.value = toJson(blocks.value) }, { deep: true })

function describe(err: unknown): string {
  if (err instanceof HttpError) {
    const detail = (err as HttpError & { detail?: string }).detail
    return detail || err.message
  }
  return err instanceof Error ? err.message : String(err)
}

function fill(item: DuzhanAgentItem) {
  selectedId.value = item.id
  name.value = item.name
  timezone.value = item.timezone
  note.value = item.note
  enabled.value = item.enabled
  blocks.value = item.blocks.blocks.map((block) => ({ ...block }))
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
  selectedId.value = null
  name.value = ''
  timezone.value = 'Asia/Shanghai'
  note.value = ''
  enabled.value = false
  blocks.value = starterBlocks(specs.value)
  jsonText.value = toJson(blocks.value)
  preview.value = null
  rendered.value = null
  message.value = ''
  error.value = ''
  pendingDelete.value = false
  pendingTarget.value = null
  hour.value = ''
  day.value = todayInZone('Asia/Shanghai')
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
  if (jsonPending.value) {
    error.value = '先按 JSON 覆盖卡片，再保存。'
    return
  }
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
      ? '已存草稿，但配置还有 ' + saved.errors.length + ' 处问题，暂时不能启用。'
      : (liveConfig.value ? '已保存。文案和条件在下一档生效；群和时段变更需重启服务。' : '已保存。当前生产仍使用代码配置。')
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
    message.value = liveConfig.value
      ? '已更新启停状态；调度变更需要重启服务才生效。'
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
  if (selectedId.value === null) {
    error.value = '先保存，再试跑。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const result = await previewAgent(
      selectedId.value,
      day.value,
      hour.value === '' ? undefined : Number(hour.value),
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
  const previousLabel = String(blocks.value[index]?.label || '')
  blocks.value = updateBlockField(blocks.value, index, key, value)
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
  jsonError.value = ''
  try {
    blocks.value = fromJson(jsonText.value)
    message.value = '已按 JSON 覆盖中间列表。'
  } catch (err) {
    jsonError.value = err instanceof Error ? err.message : String(err)
  }
}

onMounted(load)
</script>

<template>
  <AppNav />
  <main class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">督战官 · 管理后台</p>
        <h1>群聊与规则</h1>
        <p class="sub">每个群一张卡片。按顺序设置目标群、时间、发送条件和文案。</p>
      </div>
      <div class="actions">
        <button class="btn" type="button" :disabled="busy || unsaved" @click="load">刷新</button>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="requestDraft">＋ 新建群卡片</button>
      </div>
    </header>

    <section v-if="runtime" class="mode-banner" :class="{ live: liveConfig }" role="status">
      <span class="mode-dot" aria-hidden="true"></span>
      <div>
        <strong>{{ liveConfig ? '页面配置已接管督战调度' : '当前为预备配置' }}</strong>
        <p v-if="!runtime.enabled">督战官总开关未开启。卡片可保存和试跑，暂不发送。</p>
        <p v-else-if="runtime.source === 'code'">线上仍按代码中的群清单发送。卡片可保存和试跑；切换配置来源并重启服务后才接管。</p>
        <p v-else>文案和条件在下一档生效；改群、时间或启停后，需重启服务更新定时任务。</p>
      </div>
    </section>
    <p v-if="message" class="toast" role="status">{{ message }}</p>
    <p v-if="error" class="alert alert-sticky" role="alert">{{ error }}</p>
    <div v-if="pendingTarget !== null" class="switch-warning" role="alert">
      <span>当前卡片有未保存的改动。切换后会丢失这些改动。</span>
      <div>
        <button class="btn" type="button" @click="pendingTarget = null">继续编辑</button>
        <button class="btn btn-danger" type="button" @click="discardAndSwitch">放弃改动并切换</button>
      </div>
    </div>

    <div class="layout">
      <aside class="panel list">
        <div class="panel-head">
          <h2>督战群</h2>
          <span>{{ filteredAgents.length }} / {{ agents.length }}</span>
        </div>
        <label class="search-label" for="group-search">查找群聊</label>
        <input id="group-search" v-model="search" class="search-input" type="search" placeholder="输入群名" />
        <p v-if="busy && !agents.length" class="hint">正在加载群聊配置…</p>
        <button
          v-for="item in filteredAgents"
          :key="item.id"
          class="group-row"
          type="button"
          :class="{ active: item.id === selectedId }"
          :aria-current="item.id === selectedId ? 'true' : undefined"
          :aria-label="groupLabel(item) + '｜' + (item.enabled ? '已启用' : '已停用') + (item.errors.length ? '｜' + item.errors.length + ' 处问题' : '')"
          @click="selectAgent(item)"
        >
          <span class="group-top">
            <strong>{{ groupLabel(item) }}</strong>
            <em :class="item.enabled ? 'on' : 'off'">{{ item.enabled ? '启用' : '停用' }}</em>
          </span>
          <span class="group-detail">{{ slotsLabel(item) }}</span>
          <span class="group-foot">{{ ruleCount(item) }} 条文案规则 <span v-if="item.errors.length" class="bad">{{ item.errors.length }} 处待修正</span></span>
        </button>
        <p v-if="search && !filteredAgents.length" class="hint">没有找到匹配的群。</p>
        <div v-if="!busy && !agents.length" class="empty">
          <strong>还没有群聊卡片</strong>
          <p>可新建，或把现有督战群导入为停用草稿。</p>
        </div>
        <details class="import-options"><summary>导入旧配置</summary><p class="hint">仅新增未导入的群，默认停用。</p><button class="btn btn-sm" type="button" :disabled="busy" @click="importFromCode">导入现有督战群</button></details>
      </aside>

      <div class="workspace-main">
      <section class="editor" aria-labelledby="editor-title">
        <div class="editor-head">
          <div>
            <p class="eyebrow">{{ isDraft ? '新建群配置' : enabled ? '已启用的群配置' : '已停用的群配置' }}</p>
            <h2 id="editor-title">{{ isDraft ? '新建一个督战群' : groupLabel(current!) }}</h2>
          </div>
          <span v-if="unsaved" class="draft-tag">未保存</span>
        </div>
        <section class="step" aria-labelledby="group-step">
          <div class="step-head"><span class="step-number">1</span><div><h3 id="group-step">发到哪个群</h3><p>从督战官已加入的群里选择。新建时会自动填写配置名称。</p></div></div>
          <BlockCard
            v-for="index in groupIndices" :key="'group-' + index"
            :block="blocks[index]" :spec="specs.find((item) => item.type === 'group') || { type: 'group', label: '目标群', fields: [] }"
            :index="index" :total="blocks.length" :group-options="groupOptions" :disabled="busy" locked plain
            @change="(key, value) => onFieldChange(index, key, value)"
          />
          <button v-if="!groupIndices.length" class="btn" type="button" :disabled="busy" @click="addType('group')">＋ 选择目标群</button>
          <p v-if="channelsError" class="hint">群聊列表暂不可用：{{ channelsError }}。可在目标群卡片中手动填写群 ID。</p>
        </section>

        <section class="step" aria-labelledby="time-step">
          <div class="step-head"><span class="step-number">2</span><div><h3 id="time-step">什么时间发</h3><p>可选多个档位。仅支持 10:00、15:00、20:00。当前时区：{{ timezone }}（可在高级设置修改）。</p></div></div>
          <BlockCard
            v-for="index in timeIndices" :key="'times-' + index"
            :block="blocks[index]" :spec="specs.find((item) => item.type === 'times') || { type: 'times', label: '推送档位', fields: [] }"
            :index="index" :total="blocks.length" :disabled="busy" locked plain
            @change="(key, value) => onFieldChange(index, key, value)"
          />
          <button v-if="!timeIndices.length" class="btn" type="button" :disabled="busy" @click="addType('times')">＋ 选择发送时间</button>
        </section>

        <section class="step" aria-labelledby="condition-step">
          <div class="step-head"><span class="step-number">3</span><div><h3 id="condition-step">满足什么条件才发</h3><p>可选。不加条件时，按原有群督战逻辑发送；多条条件需同时满足。</p></div></div>
          <p v-if="!conditionIndices.length" class="empty-inline">当前没有附加条件</p>
          <BlockCard
            v-for="index in conditionIndices" :key="'condition-' + index"
            :block="blocks[index]" :spec="specs.find((item) => item.type === 'condition') || { type: 'condition', label: '发送条件', fields: [] }"
            :index="index" :total="blocks.length" :disabled="busy"
            :can-move-up="canMove(index, -1)" :can-move-down="canMove(index, 1)"
            @change="(key, value) => onFieldChange(index, key, value)"
            @move="(offset) => onMove(index, offset)" @remove="() => onRemove(index)"
          />
          <button class="btn btn-add" type="button" :disabled="busy" @click="addType('condition')">＋ 添加发送条件</button>
        </section>

        <section class="step" aria-labelledby="rule-step">
          <div class="step-head"><span class="step-number">4</span><div><h3 id="rule-step">发送什么文案</h3><p>可用固定文案或 AI。多条规则从上到下匹配，首条命中生效；未命中则用原有档位文案。</p></div></div>
          <p v-if="!ruleIndices.length" class="empty-inline">当前使用原有档位文案</p>
          <BlockCard
            v-for="index in ruleIndices" :key="'rule-' + index"
            :block="blocks[index]" :spec="specs.find((item) => item.type === 'rule') || { type: 'rule', label: '文案规则', fields: [] }"
            :index="index" :total="blocks.length" :disabled="busy"
            :can-move-up="canMove(index, -1)" :can-move-down="canMove(index, 1)"
            @change="(key, value) => onFieldChange(index, key, value)"
            @move="(offset) => onMove(index, offset)" @remove="() => onRemove(index)"
          />
          <button class="btn btn-add" type="button" :disabled="busy" @click="addType('rule')">＋ 添加文案规则</button>
        </section>

        <details class="panel advanced-settings">
          <summary>高级设置与旧版积木</summary>
          <div class="meta">
            <label class="field"><span>配置名称</span><input v-model="name" type="text" maxlength="128" placeholder="例如：海外一组督战" /></label>
            <label class="field"><span>时区</span><input v-model="timezone" type="text" placeholder="Asia/Shanghai" /></label>
            <label class="field"><span>备注</span><input v-model="note" type="text" maxlength="256" placeholder="可选" /></label>
          </div>
          <p v-if="extraIndices.length" class="hint">以下旧版积木已保留，部分字段只用于结构预览，不控制实际发送。</p>
          <BlockCard
            v-for="index in extraIndices" :key="'extra-' + index"
            :block="blocks[index]"
            :spec="specs.find((item) => item.type === blocks[index].type) || { type: blocks[index].type, label: blocks[index].type, fields: [] }"
            :index="index"
            :total="blocks.length"
            :group-options="groupOptions"
            :disabled="busy" locked
            @change="(key, value) => onFieldChange(index, key, value)"
          />
        </details>

        <div class="save-row">
          <button class="btn btn-primary" type="button" :disabled="busy" @click="save">
            {{ isDraft ? '保存为停用卡片' : '保存改动' }}
          </button>
          <button
            v-if="!isDraft"
            class="btn"
            type="button"
            :disabled="busy || unsaved || (!enabled && savedErrors.length > 0)"
            @click="setEnabled(!enabled)"
          >
            {{ enabled ? '停用' : '启用' }}
          </button>
          <span class="save-hint">保存不会自动启用；启停和定时变更需重启服务。</span>
          <button v-if="!isDraft" class="btn btn-danger" type="button" :disabled="busy || unsaved" @click="removeCurrent">
            {{ pendingDelete ? '再点一次确认删除' : '删除' }}
          </button>
        </div>

        <ul v-if="savedErrors.length" class="errors">
          <li v-for="(item, index) in savedErrors" :key="index">{{ item }}</li>
        </ul>
      </section>

      <aside class="side">
        <div class="panel">
          <div class="panel-head"><h2>发送预览</h2></div>
          <p class="hint">只渲染，不向群里发消息。先保存当前卡片。</p>
          <div class="preview-fields">
            <label>预览方式
              <select v-model="previewMode">
                <option value="render">实际文案</option>
                <option value="structure">配置结构</option>
              </select>
            </label>
            <label>日期<input v-model="day" type="date" /></label>
            <label>档位
              <select v-model="hour">
                <option value="">最近档位</option>
                <option v-for="slot in previewSlots" :key="slot" :value="slot.slice(0, 2)">{{ slot }}</option>
              </select>
            </label>
          </div>
          <button class="btn" type="button" :disabled="busy || isDraft || unsaved" @click="runPreview">试跑这张卡片</button>
          <p v-if="blocks.some((block) => block.type === 'rule' && block.mode === 'ai')" class="hint">AI 试跑会调用模型并计入今日额度，不写入正式发送缓存。</p>
          <p v-if="ai" class="hint">AI 今日 {{ ai.calls }} / {{ ai.limit }} 次，缓存 {{ ai.cached }} 条</p>
          <template v-if="preview">
            <p class="hint">{{ preview.note }}</p>
            <ul class="summary"><li v-for="(line, index) in preview.summary" :key="index">{{ line }}</li></ul>
            <ul v-if="preview.errors.length" class="errors"><li v-for="(item, index) in preview.errors" :key="index">{{ item }}</li></ul>
          </template>
          <template v-if="rendered">
            <p v-if="!rendered.ok" class="alert">{{ rendered.error }}</p>
            <template v-else>
              <p class="hint">{{ rendered.note }}</p>
              <p :class="rendered.send_allowed ? 'preview-allowed' : 'preview-blocked'">
                {{ rendered.send_reason }}{{ rendered.send_allowed ? '；还需核对启用与调度状态' : '，本档不发送' }}
              </p>
              <p class="meta-line">{{ rendered.day }} {{ String(rendered.hour).padStart(2, '0') }}:00 · {{ rendered.group }}</p>
              <p v-if="(rendered.message_count || 0) > 1" class="hint">本档共 {{ rendered.message_count }} 条，按人分开发送。</p>
              <pre class="body">{{ rendered.body }}</pre>
            </template>
          </template>
        </div>
        <details class="panel advanced">
          <summary>高级：查看或粘贴 JSON</summary>
          <textarea v-model="jsonText" rows="10" spellcheck="false" aria-label="积木 JSON"></textarea>
          <p v-if="jsonPending" class="hint">JSON 修改尚未应用到卡片。</p>
          <p v-if="jsonError" class="alert">{{ jsonError }}</p>
          <button class="btn" type="button" :disabled="busy" @click="applyJson">按 JSON 覆盖卡片</button>
        </details>
      </aside>
      </div>
    </div>
  </main>
</template>

<style scoped>
.page { max-width: 1360px; padding: 28px 24px 80px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }
.page-head h1 { margin: 2px 0 5px; font-size: 25px; }
.eyebrow { margin: 0; color: var(--blue); font-size: 11px; font-weight: 700; letter-spacing: .07em; }
.sub, .hint { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.actions, .save-row, .switch-warning > div { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.mode-banner, .switch-warning { display: flex; align-items: flex-start; gap: 12px; padding: 13px 16px; margin-bottom: 16px; border: 1px solid rgba(245, 158, 11, .3); border-radius: var(--radius-md); background: rgba(245, 158, 11, .07); }
.mode-banner.live { border-color: rgba(16, 185, 129, .3); background: rgba(16, 185, 129, .07); }
.mode-banner strong { font-size: 13px; }
.mode-banner p { margin: 3px 0 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
.mode-dot { width: 8px; height: 8px; flex: none; margin-top: 5px; border-radius: 50%; background: var(--amber); }
.live .mode-dot { background: var(--green); }
.switch-warning { justify-content: space-between; align-items: center; color: var(--amber); font-size: 13px; }
.btn-danger { color: var(--red); }
.layout { display: grid; grid-template-columns: minmax(220px, 270px) minmax(0, 1fr); gap: 18px; align-items: start; }
.workspace-main { display: grid; align-content: start; gap: 14px; min-width: 0; }
.panel { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--card); padding: 16px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.panel-head h2 { margin: 0; font-size: 15px; }
.panel-head > span { color: var(--muted); font-size: 12px; }
.list { position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow: auto; }
.search-label { display: block; margin-bottom: 6px; color: var(--muted); font-size: 12px; }
.search-input { width: 100%; margin-bottom: 12px; padding: 9px 11px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface-2); color: var(--text); font: inherit; font-size: 13px; }
.group-row { display: grid; gap: 5px; width: 100%; margin-bottom: 6px; padding: 10px 11px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-2); color: var(--text); text-align: left; cursor: pointer; }
.group-row:hover, .group-row.active { border-color: var(--blue); }
.group-row.active { background: var(--blue-soft); }
.group-top { display: flex; justify-content: space-between; gap: 8px; align-items: start; }
.group-top strong { min-width: 0; font-size: 13px; line-height: 1.4; }
.group-top em { flex: none; font-size: 10px; font-style: normal; padding: 2px 6px; border-radius: 5px; }
.group-top .on { color: var(--green); background: rgba(16, 185, 129, .12); }
.group-top .off { color: var(--muted); background: rgba(255, 255, 255, .06); }
.group-detail, .group-foot { color: var(--muted); font-size: 11px; line-height: 1.4; }
.group-foot { display: flex; justify-content: space-between; gap: 6px; }
.bad { color: var(--red); }
.empty { padding: 20px 12px; border: 1px dashed var(--border-strong); border-radius: var(--radius-md); text-align: center; }
.empty strong { font-size: 13px; }
.empty p { margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
.import-options { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 12px; }
.import-options summary { color: var(--muted); cursor: pointer; font-size: 12px; }
.import-options .btn { margin-top: 8px; }
.editor, .side { display: grid; gap: 14px; }
.editor-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.editor-head h2 { margin: 3px 0 0; font-size: 18px; }
.draft-tag { padding: 4px 8px; border-radius: 5px; color: var(--amber); background: rgba(245, 158, 11, .12); font-size: 11px; }
.step { display: grid; gap: 12px; padding: 18px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--card); }
.step-head { display: flex; align-items: flex-start; gap: 11px; }
.step-number { display: grid; flex: none; place-items: center; width: 27px; height: 27px; border-radius: 8px; background: var(--blue-soft); color: var(--blue); font-weight: 700; font-size: 13px; }
.step-head h3 { margin: 1px 0 3px; font-size: 15px; }
.step-head p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.55; }
.empty-inline { margin: 0; padding: 12px; border: 1px dashed var(--border-strong); border-radius: var(--radius-md); color: var(--muted); font-size: 12px; }
.btn-add { justify-self: start; }
.advanced-settings summary { cursor: pointer; font-size: 13px; }
.advanced-settings .hint { margin: 14px 0 8px; }
.advanced-settings :deep(.block-card) { margin-top: 10px; }
.meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; padding-top: 14px; }
.field, .preview-fields label { display: grid; gap: 6px; color: var(--muted); font-size: 12px; }
.field input, .preview-fields input, .preview-fields select, .advanced textarea { width: 100%; min-width: 0; padding: 9px 10px; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--surface-2); color: var(--text); font: inherit; font-size: 13px; }
.save-row { position: sticky; bottom: 0; z-index: 2; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-1); }
.save-hint { color: var(--muted); font-size: 11px; }
.errors { margin: 0; padding: 12px 12px 12px 32px; border: 1px solid rgba(244, 63, 94, .28); border-radius: var(--radius-md); background: rgba(244, 63, 94, .08); color: var(--red); font-size: 12px; line-height: 1.7; }
.preview-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 14px 0; }
.summary { padding-left: 20px; color: var(--text); font-size: 12px; line-height: 1.7; }
.meta-line { margin: 12px 0 6px; color: var(--muted); font-size: 11px; }
.preview-allowed, .preview-blocked { margin: 10px 0 0; font-size: 12px; line-height: 1.5; }
.preview-allowed { color: var(--green); }
.preview-blocked { color: var(--amber); }
.body { max-height: 430px; overflow: auto; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-1); white-space: pre-wrap; word-break: break-word; font: inherit; font-size: 12px; line-height: 1.7; }
.advanced summary { cursor: pointer; font-size: 13px; }
.advanced textarea { margin: 14px 0 8px; font-family: ui-monospace, Consolas, monospace; }
.alert-sticky { position: sticky; top: 8px; z-index: 5; }
@media (max-width: 840px) { .page { padding: 20px 14px 48px; } .layout { grid-template-columns: 1fr; } .list { position: static; max-height: 310px; } }
@media (max-width: 560px) { .preview-fields { grid-template-columns: 1fr; } .step { padding: 14px; } }
</style>
