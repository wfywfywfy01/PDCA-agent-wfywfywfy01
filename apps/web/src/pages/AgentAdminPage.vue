<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import AppNav from '@/components/AppNav.vue'
import { HttpError } from '@/api/client'
import {
  createBot as apiCreateBot,
  fetchBotChannels,
  fetchBots,
  fetchPdcaAgents,
  setBotVisibility,
  type BotChannel,
  type BotCreatePayload,
  type HermesProfile,
  type ImBot,
  type ModelRoutingRow,
  type PdcaAgent,
} from '@/api/agentAdmin'

type Tab = 'bots' | 'agents'
type VisibilityFilter = 'all' | 'public' | 'private'
type SortKey = 'recent' | 'name' | 'created'

const tab = ref<Tab>('bots')

// ── 机器人 ────────────────────────────────────────────────────────────────
const bots = ref<ImBot[]>([])
const channels = ref<BotChannel[]>([])
const botsLoading = ref(true)
const botsError = ref('')
const channelsError = ref('')
const search = ref('')
const visibility = ref<VisibilityFilter>('all')
const sortKey = ref<SortKey>('recent')
const busyAppId = ref('')
const copiedAppId = ref('')
const brokenAvatars = ref<Set<string>>(new Set())
const VPS_ORIGIN = 'https://vps.vertu.cn'

// ── 智能体 ────────────────────────────────────────────────────────────────
const agents = ref<PdcaAgent[]>([])
const routing = ref<ModelRoutingRow[]>([])
const hermesProfiles = ref<HermesProfile[]>([])
const hermesRoot = ref<string | null>(null)
const agentsLoading = ref(false)
const agentsError = ref('')
const agentsLoaded = ref(false)

// ── 弹层 ──────────────────────────────────────────────────────────────────
const createOpen = ref(false)
const createSaving = ref(false)
const createError = ref('')
const createForm = ref<BotCreatePayload>({ name: '', bot_key: '', description: '', webhook_url: '', public: false })
const createNameInput = ref<HTMLInputElement | null>(null)
const channelsOpen = ref<ImBot | null>(null)
const confirmTarget = ref<{ bot: ImBot; next: boolean } | null>(null)
const notice = ref('')
let noticeTimer: number | undefined

const CHANNEL_TYPE_LABELS: Record<string, string> = { group: '群聊', bot_dm: '机器人私聊', org: '组织群', channel: '频道' }

function channelAppId(channel: BotChannel): string {
  return String(channel.app_id ?? channel.bot_app_id ?? channel.bot_key ?? '')
}

const channelCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const channel of channels.value) {
    const key = channelAppId(channel)
    if (!key) continue
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return counts
})

const channelsFor = computed(() => {
  const bot = channelsOpen.value
  if (!bot) return []
  return channels.value.filter((channel) => channelAppId(channel) === bot.app_id)
})

function channelsOf(bot: ImBot): number {
  return channelCounts.value.get(bot.app_id) ?? 0
}

/** 头像地址：优先签名地址；相对路径补 VPS 域名；取不到时回退首字母。 */
function avatarSrc(bot: ImBot): string | null {
  const raw = (bot.avatar_signed_url || bot.avatar_display_url || '').trim()
  if (!raw) return null
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw
  if (raw.startsWith('/')) return VPS_ORIGIN + raw
  return null
}

function markAvatarBroken(id: string) {
  const next = new Set(brokenAvatars.value)
  next.add(id)
  brokenAvatars.value = next
}

const visibleBots = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  const rows = bots.value.filter((bot) => {
    if (visibility.value === 'public' && !bot.is_public) return false
    if (visibility.value === 'private' && bot.is_public) return false
    if (!keyword) return true
    return [bot.name, bot.app_id, bot.description].some((field) => (field ?? '').toLowerCase().includes(keyword))
  })
  return [...rows].sort((a, b) => {
    if (sortKey.value === 'name') return a.name.localeCompare(b.name, 'zh-Hans-CN')
    if (sortKey.value === 'created') return timestamp(b.created_at) - timestamp(a.created_at)
    return timestamp(b.last_used_at) - timestamp(a.last_used_at)
  })
})

const stats = computed(() => {
  const total = bots.value.length
  const isPublic = bots.value.filter((bot) => bot.is_public).length
  const withAgent = bots.value.filter((bot) => bot.agent_enabled).length
  const joined = new Set(channels.value.map(channelAppId).filter(Boolean)).size
  return { total, isPublic, private: total - isPublic, withAgent, joined }
})

const activeBotCount = computed(() => bots.value.filter((bot) => bot.active).length)

function timestamp(value: string | null | undefined): number {
  if (!value) return 0
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

function fmtDateTime(value: string | null | undefined): string {
  if (!value) return '从未使用'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function fmtRelative(value: string | null | undefined): string {
  const time = timestamp(value)
  if (!time) return '从未使用'
  const diff = Date.now() - time
  const minute = 60_000
  if (diff < minute) return '刚刚'
  if (diff < 60 * minute) return Math.floor(diff / minute) + ' 分钟前'
  if (diff < 24 * 60 * minute) return Math.floor(diff / (60 * minute)) + ' 小时前'
  const days = Math.floor(diff / (24 * 60 * minute))
  if (days < 30) return days + ' 天前'
  return fmtDateTime(value)
}

function showNotice(message: string) {
  notice.value = message
  if (noticeTimer) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 4000)
}

function describeError(err: unknown, fallback: string): string {
  return err instanceof HttpError ? err.detail : fallback
}
// ── 数据加载 ──────────────────────────────────────────────────────────────
async function loadBots() {
  botsLoading.value = true
  botsError.value = ''
  try {
    const payload = await fetchBots()
    bots.value = payload.items ?? []
  } catch (err) {
    botsError.value = describeError(err, '机器人列表加载失败')
  } finally {
    botsLoading.value = false
  }
}

async function loadChannels() {
  channelsError.value = ''
  try {
    const payload = await fetchBotChannels()
    channels.value = payload.items ?? []
  } catch (err) {
    channelsError.value = describeError(err, '群聊数据加载失败')
  }
}

async function loadAgents(force = false) {
  if (agentsLoaded.value && !force) return
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const payload = await fetchPdcaAgents()
    agents.value = payload.agents ?? []
    routing.value = payload.model_routing ?? []
    hermesProfiles.value = payload.hermes_profiles ?? []
    hermesRoot.value = payload.hermes_profiles_root
    agentsLoaded.value = true
  } catch (err) {
    agentsError.value = describeError(err, '智能体状态加载失败')
  } finally {
    agentsLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadBots(), loadChannels()])
  showNotice('机器人数据已刷新')
}

async function switchTab(next: Tab) {
  tab.value = next
  if (next === 'agents') await loadAgents()
}

// ── 操作 ──────────────────────────────────────────────────────────────────
function requestVisibility(bot: ImBot) {
  confirmTarget.value = { bot, next: !bot.is_public }
}

async function applyVisibility() {
  const target = confirmTarget.value
  if (!target) return
  confirmTarget.value = null
  busyAppId.value = target.bot.app_id
  try {
    await setBotVisibility(target.bot.app_id, target.next)
    showNotice('「' + target.bot.name + '」已设为' + (target.next ? '公开' : '仅自己可见'))
    await loadBots()
  } catch (err) {
    botsError.value = describeError(err, '公开范围调整失败')
  } finally {
    busyAppId.value = ''
  }
}

async function openCreate() {
  createOpen.value = true
  createError.value = ''
  await nextTick()
  createNameInput.value?.focus()
}

function closeCreate() {
  createOpen.value = false
  createError.value = ''
}

function closeOverlays() {
  channelsOpen.value = null
  confirmTarget.value = null
  closeCreate()
}

async function submitCreate() {
  if (createSaving.value) return
  const name = (createForm.value.name ?? '').trim()
  if (!name) {
    createError.value = '请填写机器人名称'
    return
  }
  createSaving.value = true
  createError.value = ''
  try {
    const payload: BotCreatePayload = { name, public: createForm.value.public }
    const botKey = (createForm.value.bot_key ?? '').trim()
    const description = (createForm.value.description ?? '').trim()
    const webhook = (createForm.value.webhook_url ?? '').trim()
    if (botKey) payload.bot_key = botKey
    if (description) payload.description = description
    if (webhook) payload.webhook_url = webhook
    await apiCreateBot(payload)
    closeCreate()
    createForm.value = { name: '', bot_key: '', description: '', webhook_url: '', public: false }
    showNotice('机器人「' + name + '」创建成功')
    await loadBots()
  } catch (err) {
    createError.value = describeError(err, '创建失败')
  } finally {
    createSaving.value = false
  }
}

async function copyAppId(bot: ImBot) {
  try {
    await navigator.clipboard.writeText(bot.app_id)
    copiedAppId.value = bot.app_id
    window.setTimeout(() => { if (copiedAppId.value === bot.app_id) copiedAppId.value = '' }, 1600)
  } catch {
    showNotice('复制失败，请手动选择 app_id')
  }
}

const anyOverlayOpen = computed(() => createOpen.value || !!channelsOpen.value || !!confirmTarget.value)

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (confirmTarget.value) confirmTarget.value = null
  else if (createOpen.value) closeCreate()
  else if (channelsOpen.value) channelsOpen.value = null
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await Promise.all([loadBots(), loadChannels()])
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (noticeTimer) window.clearTimeout(noticeTimer)
})
</script>
<template>
  <AppNav />
  <main class="agent-admin">
    <header class="page-head">
      <div>
        <h1>Agent 管理</h1>
        <p class="sub">管理我创建的 IM 机器人与 PDCA 智能体 · 机器人数据由 vertu-cli 实时读取</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" :disabled="botsLoading" @click="refreshAll">{{ botsLoading ? '刷新中…' : '刷新' }}</button>
        <button class="btn btn-primary" type="button" @click="openCreate">+ 创建机器人</button>
      </div>
    </header>

    <p v-if="notice" class="toast" role="status">{{ notice }}</p>

    <nav class="tabs" role="tablist" aria-label="Agent 管理分区">
      <button
        class="tab"
        type="button"
        role="tab"
        :aria-selected="tab === 'bots'"
        :class="{ active: tab === 'bots' }"
        @click="switchTab('bots')"
      >
        IM 机器人
        <span class="tab-count">{{ stats.total }}</span>
      </button>
      <button
        class="tab"
        type="button"
        role="tab"
        :aria-selected="tab === 'agents'"
        :class="{ active: tab === 'agents' }"
        @click="switchTab('agents')"
      >
        PDCA 智能体
        <span class="tab-count">{{ agents.length || '—' }}</span>
      </button>
    </nav>

    <!-- ── IM 机器人 ───────────────────────────────────────────────── -->
    <template v-if="tab === 'bots'">
      <section class="stats" aria-label="机器人概览">
        <div class="card stat">
          <span class="stat-label">机器人总数</span>
          <span class="stat-value num">{{ stats.total }}</span>
          <span class="stat-note">{{ activeBotCount }} 个启用中</span>
        </div>
        <div class="card stat">
          <span class="stat-label">公开 / 私有</span>
          <span class="stat-value num">{{ stats.isPublic }} / {{ stats.private }}</span>
          <span class="stat-note">公开可被其他群管理员添加</span>
        </div>
        <div class="card stat">
          <span class="stat-label">已加入会话</span>
          <span class="stat-value num">{{ channels.length }}</span>
          <span class="stat-note">{{ stats.joined }} 个机器人有会话</span>
        </div>
        <div class="card stat">
          <span class="stat-label">挂载智能体</span>
          <span class="stat-value num">{{ stats.withAgent }}</span>
          <span class="stat-note">启用 agent 回复的机器人</span>
        </div>
      </section>

      <section class="toolbar card">
        <div class="field grow">
          <label class="field-label" for="bot-search">搜索</label>
          <input id="bot-search" v-model="search" class="input" type="search" placeholder="名称 / app_id / 说明" />
        </div>
        <div class="field">
          <span class="field-label">可见性</span>
          <div class="segmented" role="group" aria-label="按可见性筛选">
            <button type="button" :class="{ active: visibility === 'all' }" @click="visibility = 'all'">全部 {{ stats.total }}</button>
            <button type="button" :class="{ active: visibility === 'public' }" @click="visibility = 'public'">公开 {{ stats.isPublic }}</button>
            <button type="button" :class="{ active: visibility === 'private' }" @click="visibility = 'private'">私有 {{ stats.private }}</button>
          </div>
        </div>
        <div class="field">
          <label class="field-label" for="bot-sort">排序</label>
          <select id="bot-sort" v-model="sortKey" class="input select">
            <option value="recent">最近使用</option>
            <option value="name">名称</option>
            <option value="created">创建时间</option>
          </select>
        </div>
      </section>

      <div v-if="botsError" class="card alert" role="alert">
        <span>{{ botsError }}</span>
        <button class="btn btn-sm" type="button" @click="loadBots">重试</button>
      </div>
      <p v-if="channelsError && !botsError" class="hint-warn">群聊数据暂不可用：{{ channelsError }}（其余信息不受影响）</p>

      <div v-if="botsLoading" class="card table-card" aria-busy="true" aria-label="正在加载机器人">
        <div v-for="row in 5" :key="row" class="skeleton-row">
          <span class="sk sk-avatar" />
          <span class="sk sk-line" />
          <span class="sk sk-line short" />
        </div>
      </div>

      <div v-else-if="!bots.length" class="card empty-state">
        <h2>还没有机器人</h2>
        <p>创建机器人后，就能在 IM 群聊或私聊里以它的身份接收和发送消息。</p>
        <button class="btn btn-primary" type="button" @click="openCreate">+ 创建第一个机器人</button>
      </div>

      <div v-else-if="!visibleBots.length" class="card empty-state">
        <h2>没有匹配的机器人</h2>
        <p>当前搜索词或筛选条件下没有结果。</p>
        <button class="btn" type="button" @click="search = ''; visibility = 'all'">清空筛选</button>
      </div>

      <section v-else class="card table-card">
        <table>
          <caption class="sr-only">我的 IM 机器人列表</caption>
          <thead>
            <tr>
              <th scope="col">机器人</th>
              <th scope="col" class="col-desc">说明</th>
              <th scope="col">可见性</th>
              <th scope="col" class="col-channels">会话</th>
              <th scope="col" class="col-used">最近使用</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="bot in visibleBots" :key="bot.id">
              <td>
                <div class="bot">
                  <img
                    v-if="avatarSrc(bot) && !brokenAvatars.has(bot.id)"
                    class="avatar"
                    :src="avatarSrc(bot) || ''"
                    alt=""
                    loading="lazy"
                    referrerpolicy="no-referrer"
                    @error="markAvatarBroken(bot.id)"
                  />
                  <span v-else class="avatar avatar-fallback" aria-hidden="true">{{ bot.name.slice(0, 1) }}</span>
                  <div class="bot-text">
                    <span class="bot-name">
                      {{ bot.name }}
                      <span v-if="bot.agent_enabled" class="pill pill-blue">智能体</span>
                      <span v-if="!bot.active" class="pill pill-muted">已停用</span>
                    </span>
                    <button
                      class="app-id"
                      type="button"
                      :aria-label="'复制 ' + bot.name + ' 的 app_id'"
                      @click="copyAppId(bot)"
                    >
                      <span class="mono">{{ bot.app_id }}</span>
                      <span class="copy-hint">{{ copiedAppId === bot.app_id ? '已复制' : '复制' }}</span>
                    </button>
                  </div>
                </div>
              </td>
              <td class="col-desc"><span class="desc">{{ bot.description || '—' }}</span></td>
              <td>
                <button
                  class="switch"
                  type="button"
                  role="switch"
                  :aria-checked="bot.is_public"
                  :aria-label="bot.name + ' 可见性'"
                  :disabled="busyAppId === bot.app_id"
                  @click="requestVisibility(bot)"
                >
                  <span class="switch-track" aria-hidden="true"><span class="switch-thumb" /></span>
                  <span class="switch-text">{{ bot.is_public ? '公开' : '私有' }}</span>
                </button>
              </td>
              <td class="col-channels">
                <button
                  class="link-btn num"
                  type="button"
                  :disabled="!channelsOf(bot)"
                  @click="channelsOpen = bot"
                >
                  {{ channelsOf(bot) }}
                </button>
              </td>
              <td class="col-used" :title="fmtDateTime(bot.last_used_at)">
                <span class="num">{{ fmtRelative(bot.last_used_at) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <footer class="table-foot">
          <span>显示 {{ visibleBots.length }} / {{ bots.length }} 个机器人</span>
          <span v-if="channels.length">会话数据 {{ channels.length }} 条</span>
        </footer>
      </section>
    </template>
    <!-- ── PDCA 智能体 ─────────────────────────────────────────────── -->
    <template v-else>
      <div v-if="agentsError" class="card alert" role="alert">
        <span>{{ agentsError }}</span>
        <button class="btn btn-sm" type="button" @click="loadAgents(true)">重试</button>
      </div>

      <div v-if="agentsLoading" class="grid-cards" aria-busy="true" aria-label="正在加载智能体">
        <div v-for="row in 6" :key="row" class="card skeleton-card">
          <span class="sk sk-line" />
          <span class="sk sk-line short" />
        </div>
      </div>

      <template v-else>
        <section class="panel card">
          <header class="panel-head">
            <div>
              <h2>PDCA 智能体分工</h2>
              <p>与 AGENTS.md《Agent 分工》一致，共 {{ agents.length }} 个角色。</p>
            </div>
            <button class="btn btn-sm" type="button" @click="loadAgents(true)">刷新</button>
          </header>
          <ul class="agent-grid">
            <li v-for="agent in agents" :key="agent.key" class="agent">
              <div class="agent-top">
                <h3>{{ agent.name }}</h3>
                <span class="pill" :class="agent.status === 'active' ? 'pill-green' : 'pill-amber'">
                  {{ agent.status === 'active' ? '运行中' : '规划中' }}
                </span>
              </div>
              <code class="agent-key">{{ agent.key }}</code>
              <p class="agent-role">{{ agent.role }}</p>
              <div class="agent-out">
                <span v-for="out in agent.outputs" :key="out" class="chip mono">{{ out }}</span>
              </div>
            </li>
          </ul>
        </section>

        <div class="split">
          <section class="panel card">
            <header class="panel-head">
              <div>
                <h2>模型路由</h2>
                <p>文本任务走 DeepSeek flash，图像/视觉走本地 Qwen 网关。</p>
              </div>
            </header>
            <ul class="routing">
              <li v-for="rule in routing" :key="rule.task">
                <div class="routing-top">
                  <strong>{{ rule.label }}</strong>
                  <span class="pill" :class="rule.configured ? 'pill-green' : 'pill-muted'">
                    {{ rule.configured ? '已配置' : '未配置' }}
                  </span>
                </div>
                <dl class="kv">
                  <div><dt>供应商</dt><dd class="mono">{{ rule.provider || '—' }}</dd></div>
                  <div><dt>模型</dt><dd class="mono">{{ rule.model || '—' }}</dd></div>
                </dl>
                <p v-if="!rule.configured" class="hint">未读到环境变量，按约定默认使用 {{ rule.default_note }}。</p>
              </li>
            </ul>
          </section>

          <section class="panel card">
            <header class="panel-head">
              <div>
                <h2>本机 Hermes 档案</h2>
                <p class="mono break">{{ hermesRoot || '未检测到 profiles 目录' }}</p>
              </div>
            </header>
            <ul v-if="hermesProfiles.length" class="hermes">
              <li v-for="profile in hermesProfiles" :key="profile.name">
                <span class="hermes-name">{{ profile.name }}</span>
                <span class="pill" :class="profile.soul_exists ? 'pill-green' : 'pill-muted'">SOUL.md {{ profile.soul_exists ? '有' : '缺' }}</span>
                <span class="pill" :class="profile.env_exists ? 'pill-green' : 'pill-muted'">.env {{ profile.env_exists ? '有' : '缺' }}</span>
              </li>
            </ul>
            <p v-else class="hint">本机未检测到 Hermes profiles 目录。</p>
          </section>
        </div>
      </template>
    </template>

    <!-- ── 弹层 ─────────────────────────────────────────────────────── -->
    <div v-if="anyOverlayOpen" class="overlay" @click.self="closeOverlays">
      <section
        v-if="channelsOpen"
        class="card modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="channels-title"
      >
        <header class="modal-head">
          <div>
            <h2 id="channels-title">{{ channelsOpen.name }} · 已加入会话</h2>
            <p>{{ channelsFor.length }} 个会话，数据来自 vertu-cli im +bot-channels。</p>
          </div>
          <button class="btn btn-sm" type="button" @click="channelsOpen = null">关闭</button>
        </header>
        <ul v-if="channelsFor.length" class="channel-list">
          <li v-for="channel in channelsFor" :key="String(channel.channel_id)">
            <div class="channel-main">
              <span class="channel-name">{{ channel.channel_name || '（未命名会话）' }}</span>
              <span class="pill" :class="channel.channel_type === 'group' ? 'pill-blue' : 'pill-muted'">
                {{ CHANNEL_TYPE_LABELS[String(channel.channel_type)] || channel.channel_type || '会话' }}
              </span>
            </div>
            <div class="channel-meta">
              <span class="mono">{{ channel.channel_id }}</span>
              <span v-if="channel.joined_at" class="num">{{ fmtRelative(String(channel.joined_at)) }}加入</span>
            </div>
          </li>
        </ul>
        <p v-else class="hint">该机器人还没有加入任何会话。</p>
      </section>

      <form
        v-else-if="createOpen"
        class="card modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-title"
        @submit.prevent="submitCreate"
      >
        <header class="modal-head">
          <div>
            <h2 id="create-title">创建机器人</h2>
            <p>经 vertu-cli im +bot-create 创建，保存后立即可用。</p>
          </div>
          <button class="btn btn-sm" type="button" @click="closeCreate">取消</button>
        </header>
        <p v-if="createError" class="alert-inline" role="alert">{{ createError }}</p>
        <div class="form-grid">
          <label class="span-2">
            <span class="field-label">名称 *</span>
            <input ref="createNameInput" v-model="createForm.name" class="input" maxlength="64" placeholder="如：海外日报播报员" />
          </label>
          <label>
            <span class="field-label">唯一 key（可选）</span>
            <input v-model="createForm.bot_key" class="input" maxlength="64" placeholder="字母/数字/-/_" />
          </label>
          <label>
            <span class="field-label">Webhook（可选）</span>
            <input v-model="createForm.webhook_url" class="input" maxlength="300" placeholder="https://…" />
          </label>
          <label class="span-2">
            <span class="field-label">说明（可选）</span>
            <input v-model="createForm.description" class="input" maxlength="500" placeholder="这个机器人负责什么" />
          </label>
        </div>
        <label class="check">
          <input v-model="createForm.public" type="checkbox" />
          <span>公开：允许其他群管理员把它添加到自己的群</span>
        </label>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="closeCreate">取消</button>
          <button class="btn btn-primary" type="submit" :disabled="createSaving">{{ createSaving ? '创建中…' : '创建机器人' }}</button>
        </footer>
      </form>

      <section v-else-if="confirmTarget" class="card modal modal-sm" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">调整可见性</h2>
        <p>
          把「{{ confirmTarget.bot.name }}」设为
          <strong>{{ confirmTarget.next ? '公开' : '仅自己可见' }}</strong>？
          <span v-if="confirmTarget.next">公开后其他群管理员可以把它添加到自己的群。</span>
        </p>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="confirmTarget = null">取消</button>
          <button class="btn btn-primary" type="button" @click="applyVisibility">确认调整</button>
        </footer>
      </section>
    </div>
  </main>
</template>
<style scoped>
.agent-admin { max-width: 1240px; margin: 0 auto; padding: 24px 20px 64px; }

/* 页头 */
.page-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.page-head h1 { margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }
.sub { margin: 0; color: var(--muted); font-size: 13px; }
.page-actions { display: flex; gap: 10px; align-items: center; }

/* 提示条 */
.toast {
  position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%);
  margin: 0; padding: 10px 18px; border-radius: 999px; z-index: 70;
  background: var(--card-2); border: 1px solid var(--border-strong);
  color: var(--text); font-size: 13px;
}

/* 分区切换 */
.tabs { display: flex; gap: 6px; padding: 4px; border-radius: 12px; background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border); width: fit-content; margin-bottom: 18px; }
.tab {
  display: inline-flex; align-items: center; gap: 8px; padding: 9px 16px;
  border: none; border-radius: 9px; background: transparent; color: var(--muted);
  font-size: 13px; cursor: pointer; transition: background-color 0.15s, color 0.15s;
}
.tab.active { background: var(--blue-soft); color: var(--blue); font-weight: 600; }
.tab-count { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: rgba(255, 255, 255, 0.08); font-variant-numeric: tabular-nums; }
.tab.active .tab-count { background: rgba(78, 158, 245, 0.22); }

/* 概览卡 */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat { padding: 16px; display: grid; gap: 4px; }
.stat-label { color: var(--muted); font-size: 12px; }
.stat-value { font-size: 26px; font-weight: 600; line-height: 1.15; }
.stat-note { color: var(--muted); font-size: 12px; }

/* 工具栏 */
.toolbar { display: flex; flex-wrap: wrap; gap: 14px; padding: 14px 16px; margin-bottom: 16px; align-items: flex-end; }
.field { display: grid; gap: 6px; }
.field.grow { flex: 1 1 240px; min-width: 200px; }
.field-label { color: var(--muted); font-size: 12px; }
.select { cursor: pointer; }
.segmented { display: inline-flex; border: 1px solid var(--border-strong); border-radius: 10px; overflow: hidden; }
.segmented button {
  padding: 9px 13px; border: none; background: transparent; color: var(--muted);
  font-size: 12px; cursor: pointer; font-variant-numeric: tabular-nums;
  transition: background-color 0.15s, color 0.15s;
}
.segmented button + button { border-left: 1px solid var(--border); }
.segmented button.active { background: var(--blue-soft); color: var(--blue); font-weight: 600; }

/* 状态与骨架 */
.alert { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 16px; margin-bottom: 16px; color: var(--red); background: rgba(244, 63, 94, 0.08); border-color: rgba(244, 63, 94, 0.28); }
.hint-warn { margin: 0 0 14px; color: var(--amber); font-size: 13px; }
.hint { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
.table-card { padding: 0; overflow: hidden; }
.skeleton-row { display: flex; align-items: center; gap: 14px; padding: 15px 16px; border-bottom: 1px solid var(--border); }
.skeleton-row:last-child { border-bottom: none; }
.sk { display: block; background: rgba(255, 255, 255, 0.06); border-radius: 6px; height: 12px; }
.sk-avatar { width: 36px; height: 36px; border-radius: 10px; }
.sk-line { flex: 1 1 auto; }
.sk-line.short { flex: 0 1 180px; }
.skeleton-card { padding: 18px; display: grid; gap: 10px; }
.empty-state { padding: 44px 24px; text-align: center; }
.empty-state h2 { margin: 0 0 8px; font-size: 16px; }
.empty-state p { margin: 0 0 16px; color: var(--muted); font-size: 13px; }

/* 表格 */
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 13px 16px; border-bottom: 1px solid var(--border); vertical-align: middle; }
th { color: var(--muted); font-size: 12px; font-weight: 500; }
tbody tr:hover { background: rgba(255, 255, 255, 0.02); }
tbody tr:last-child td { border-bottom: none; }
.table-foot { display: flex; justify-content: space-between; gap: 12px; padding: 10px 16px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--border); }
.bot { display: flex; align-items: center; gap: 11px; }
.avatar { width: 36px; height: 36px; border-radius: 10px; object-fit: cover; flex: 0 0 auto; background: rgba(255, 255, 255, 0.06); }
.avatar-fallback { display: grid; place-items: center; background: var(--blue-soft); color: var(--blue); font-weight: 600; }
.bot-text { display: grid; gap: 3px; min-width: 0; }
.bot-name { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; }
.app-id { display: inline-flex; align-items: center; gap: 6px; min-height: 24px; padding: 3px 0; border: none; background: transparent; color: var(--muted); font-size: 11px; cursor: pointer; }
.app-id:hover { color: var(--blue); }
.app-id:hover .copy-hint, .app-id:focus-visible .copy-hint { opacity: 1; }
.copy-hint { opacity: 0; color: var(--blue); transition: opacity 0.15s; }
.desc { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: var(--muted); font-size: 13px; }

/* 可见性开关 */
.switch { display: inline-flex; align-items: center; gap: 8px; min-height: 24px; padding: 2px 0; border: none; background: transparent; cursor: pointer; }
.switch:disabled { opacity: 0.5; cursor: progress; }
.switch-track { position: relative; width: 34px; height: 20px; border-radius: 999px; background: rgba(255, 255, 255, 0.14); transition: background-color 0.15s; }
.switch-thumb { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform 0.15s ease-out; }
.switch[aria-checked='true'] .switch-track { background: var(--blue); }
.switch[aria-checked='true'] .switch-thumb { transform: translateX(14px); }
.switch-text { font-size: 12px; color: var(--muted); }
.link-btn { min-height: 24px; padding: 3px 0; border: none; background: transparent; color: var(--blue); font-size: 13px; cursor: pointer; }
.link-btn:disabled { color: var(--faint); cursor: default; }

/* 徽标 */
.pill { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; border: 1px solid transparent; }
.pill-blue { background: var(--blue-soft); color: var(--blue); }
.pill-green { background: rgba(16, 185, 129, 0.12); color: var(--green); }
.pill-amber { background: rgba(245, 158, 11, 0.12); color: var(--amber); }
.pill-muted { background: rgba(148, 163, 184, 0.12); color: var(--muted); }
.chip { display: inline-flex; margin: 0 6px 6px 0; padding: 2px 8px; border-radius: 6px; border: 1px solid var(--border); color: var(--muted); font-size: 11px; }

/* 智能体面板 */
.panel { padding: 18px; margin-bottom: 16px; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 14px; }
.panel-head h2 { margin: 0 0 4px; font-size: 16px; }
.panel-head p { margin: 0; color: var(--muted); font-size: 13px; }
.agent-grid { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.agent { padding: 14px; border: 1px solid var(--border); border-radius: var(--radius); background: rgba(255, 255, 255, 0.02); }
.agent-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.agent-top h3 { margin: 0; font-size: 14px; }
.agent-key { display: block; margin: 5px 0 9px; color: var(--muted); font-size: 11px; }
.agent-role { margin: 0 0 10px; color: var(--muted); font-size: 13px; }
.split { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.routing { list-style: none; margin: 0; padding: 0; }
.routing li { padding: 14px 0; border-bottom: 1px solid var(--border); }
.routing li:first-child { padding-top: 0; }
.routing li:last-child { border-bottom: none; padding-bottom: 0; }
.routing-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 13px; }
.kv { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 10px 0 0; }
.kv dt { color: var(--muted); font-size: 11px; }
.kv dd { margin: 3px 0 0; font-size: 12px; word-break: break-all; }
.hermes { list-style: none; margin: 0; padding: 0; }
.hermes li { display: flex; align-items: center; gap: 8px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.hermes li:last-child { border-bottom: none; }
.hermes-name { flex: 1 1 auto; font-size: 13px; }

/* 弹层 */
.overlay { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 20px; background: rgba(4, 6, 12, 0.66); }
.modal { width: min(720px, 100%); max-height: 86vh; overflow: auto; padding: 20px; }
.modal-sm { width: min(430px, 100%); }
.modal-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 14px; }
.modal-head h2 { margin: 0 0 4px; font-size: 16px; }
.modal-head p { margin: 0; color: var(--muted); font-size: 13px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.form-grid label { display: grid; gap: 6px; }
.form-grid .span-2 { grid-column: span 2; }
.check { display: flex; align-items: center; gap: 9px; margin-top: 14px; color: var(--muted); font-size: 13px; cursor: pointer; }
.alert-inline { margin: 0 0 14px; padding: 10px 12px; border-radius: 10px; background: rgba(244, 63, 94, 0.1); color: var(--red); font-size: 13px; }
.channel-list { list-style: none; margin: 0; padding: 0; }
.channel-list li { padding: 12px 0; border-bottom: 1px solid var(--border); }
.channel-list li:last-child { border-bottom: none; }
.channel-main { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.channel-name { font-size: 13px; font-weight: 600; }
.channel-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 5px; color: var(--muted); font-size: 11px; }

/* 工具类 */
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.num { font-variant-numeric: tabular-nums; }
.break { word-break: break-all; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

.btn-sm { padding: 6px 12px; font-size: 12px; }

.btn:focus-visible, .tab:focus-visible, .switch:focus-visible, .link-btn:focus-visible,
.app-id:focus-visible, .segmented button:focus-visible, .check input:focus-visible {
  outline: 2px solid var(--blue); outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .tab, .segmented button, .switch-track, .switch-thumb, .copy-hint { transition: none; }
}

@media (max-width: 860px) {
  .col-desc { display: none; }
}
@media (max-width: 640px) {
  .agent-admin { padding: 16px 12px 48px; }
  .page-head { align-items: stretch; }
  .page-actions { width: 100%; }
  .page-actions .btn { flex: 1; }
  .col-used { display: none; }
  .form-grid { grid-template-columns: 1fr; }
  .form-grid .span-2 { grid-column: span 1; }
  .kv { grid-template-columns: 1fr; }
}
</style>
