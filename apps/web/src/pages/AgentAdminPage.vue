<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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

const tab = ref<'bots' | 'agents'>('bots')
const bots = ref<ImBot[]>([])
const channels = ref<BotChannel[]>([])
const agents = ref<PdcaAgent[]>([])
const hermesRoot = ref<string | null>(null)
const hermesProfiles = ref<HermesProfile[]>([])
const routing = ref<ModelRoutingRow[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')
const busyAppId = ref('')
const createOpen = ref(false)
const createSaving = ref(false)
const channelsOpen = ref<ImBot | null>(null)
const channelsFor = computed(() => channels.value.filter(c => {
  const app = channelsOpen.value
  if (!app) return false
  const candidate = c.bot_app_id ?? c.app_id ?? c.bot_key
  return candidate === app.app_id || candidate === app.id || candidate === 'user-robot-' + app.app_id
}))

const createForm = ref<BotCreatePayload>({ name: '', bot_key: '', description: '', webhook_url: '', public: false })

function fmtDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function loadBots() {
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchBots()
    bots.value = payload.items || []
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '机器人列表加载失败'
  } finally {
    loading.value = false
  }
}

async function loadChannels() {
  try {
    const payload = await fetchBotChannels()
    channels.value = payload.items || []
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '群聊列表加载失败'
  }
}

async function loadAgents() {
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchPdcaAgents()
    agents.value = payload.agents || []
    hermesRoot.value = payload.hermes_profiles_root
    hermesProfiles.value = payload.hermes_profiles || []
    routing.value = payload.model_routing || []
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '智能体状态加载失败'
  } finally {
    loading.value = false
  }
}

async function switchTab(next: 'bots' | 'agents') {
  tab.value = next
  notice.value = ''
  error.value = ''
  if (next === 'bots') await loadBots()
  else await loadAgents()
}

async function toggleVisibility(bot: ImBot) {
  if (busyAppId.value) return
  const target = !bot.is_public
  if (!window.confirm('将「' + bot.name + '」设为' + (target ? '公开' : '仅自己可见') + '？')) return
  busyAppId.value = bot.app_id
  error.value = ''
  notice.value = ''
  try {
    await setBotVisibility(bot.app_id, target)
    notice.value = '「' + bot.name + '」公开范围已更新'
    await loadBots()
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '公开范围调整失败'
  } finally {
    busyAppId.value = ''
  }
}

async function submitCreate() {
  if (createSaving.value) return
  if (!createForm.value.name.trim()) {
    error.value = '请填写机器人名称'
    return
  }
  createSaving.value = true
  error.value = ''
  notice.value = ''
  try {
    const payload: BotCreatePayload = { name: createForm.value.name.trim(), public: createForm.value.public }
    if (createForm.value.bot_key?.trim()) payload.bot_key = createForm.value.bot_key.trim()
    if (createForm.value.description?.trim()) payload.description = createForm.value.description.trim()
    if (createForm.value.webhook_url?.trim()) payload.webhook_url = createForm.value.webhook_url.trim()
    await apiCreateBot(payload)
    notice.value = '机器人「' + payload.name + '」创建成功'
    createOpen.value = false
    createForm.value = { name: '', bot_key: '', description: '', webhook_url: '', public: false }
    await loadBots()
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '创建失败'
  } finally {
    createSaving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadBots(), loadChannels()])
})
</script>
<template>
  <AppNav />
  <main class="page">
    <header class="head">
      <div>
        <h1>Agent 管理后台</h1>
        <p>管理我创建的 IM 机器人与 PDCA 智能体。</p>
      </div>
      <div class="tabs" role="tablist">
        <button type="button" class="tab" :class="{ active: tab === 'bots' }" @click="switchTab('bots')">IM 机器人</button>
        <button type="button" class="tab" :class="{ active: tab === 'agents' }" @click="switchTab('agents')">PDCA 智能体</button>
      </div>
    </header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message ok" role="status">{{ notice }}</p>

    <div v-if="loading" class="card state" aria-busy="true">正在加载…</div>

    <!-- 机器人 -->
    <section v-else-if="tab === 'bots'" class="cards">
      <div class="card panel">
        <div class="section-title">
          <div><h2>我的机器人（{{ bots.length }}）</h2><p>数据实时来自 vertu-cli im +bots。</p></div>
          <div class="row">
            <button class="btn" type="button" @click="loadBots">刷新</button>
            <button class="btn btn-primary" type="button" @click="createOpen = true">创建机器人</button>
          </div>
        </div>
        <div v-if="bots.length" class="table-wrap">
          <table>
            <thead><tr><th>机器人</th><th>说明</th><th>公开范围</th><th>智能体</th><th>最近使用</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="bot in bots" :key="bot.id">
                <td>
                  <div class="bot-cell">
                    <img v-if="bot.avatar_display_url" class="avatar" :src="bot.avatar_display_url" :alt="bot.name" />
                    <div><strong>{{ bot.name }}</strong><small class="mono">{{ bot.app_id }}</small></div>
                  </div>
                </td>
                <td class="desc">{{ bot.description || '—' }}</td>
                <td><span class="badge" :class="bot.is_public ? 'badge-green' : 'badge-grey'">{{ bot.is_public ? '公开' : '仅自己可见' }}</span></td>
                <td><span class="badge" :class="bot.agent_enabled ? 'badge-blue' : 'badge-grey'">{{ bot.agent_enabled ? bot.agent_model || '已启用' : '未启用' }}</span></td>
                <td class="muted">{{ fmtDate(bot.last_used_at) }}</td>
                <td>
                  <div class="row">
                    <button class="btn btn-sm" type="button" :disabled="busyAppId === bot.app_id" @click="toggleVisibility(bot)">{{ bot.is_public ? '设为私有' : '设为公开' }}</button>
                    <button class="btn btn-sm" type="button" @click="channelsOpen = bot">群聊</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="state">暂无机器人，点击「创建机器人」开始。</div>
      </div>
    </section>

    <!-- 智能体 -->
    <section v-else class="cards">
      <div class="card panel">
        <div class="section-title">
          <div><h2>PDCA 智能体（{{ agents.length }}）</h2><p>分工以 AGENTS.md《Agent 分工》为准。</p></div>
          <button class="btn" type="button" @click="loadAgents">刷新</button>
        </div>
        <div v-if="agents.length" class="table-wrap">
          <table>
            <thead><tr><th>智能体</th><th>职责</th><th>输出位置</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="agent in agents" :key="agent.key">
                <td><strong>{{ agent.name }}</strong><small class="mono block">{{ agent.key }}</small></td>
                <td class="desc">{{ agent.role }}</td>
                <td><code v-for="out in agent.outputs" :key="out" class="out">{{ out }}</code></td>
                <td><span class="badge" :class="agent.status === 'active' ? 'badge-green' : 'badge-amber'">{{ agent.status === 'active' ? '运行中' : '规划中' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card panel">
        <div class="section-title"><div><h2>模型路由</h2><p>只读快照：文本走 DeepSeek flash，视觉走本地 Qwen 网关。</p></div></div>
        <div v-if="routing.length" class="table-wrap">
          <table>
            <thead><tr><th>任务类型</th><th>供应商</th><th>模型</th><th>配置状态</th></tr></thead>
            <tbody>
              <tr v-for="rule in routing" :key="rule.task">
                <td><strong>{{ rule.label }}</strong></td>
                <td class="mono">{{ rule.provider || '未配置' }}</td>
                <td class="mono">{{ rule.model || '未配置' }}</td>
                <td><span class="badge" :class="rule.configured ? 'badge-green' : 'badge-amber'">{{ rule.configured ? '已配置' : '未配置' }}</span><small v-if="!rule.configured" class="muted"> 默认 {{ rule.default_note }}</small></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card panel">
        <div class="section-title"><div><h2>本机 Hermes 档案</h2><p>{{ hermesRoot || '未检测到 Hermes profiles 目录' }}</p></div></div>
        <div v-if="hermesProfiles.length" class="table-wrap">
          <table>
            <thead><tr><th>档案名</th><th>SOUL.md</th><th>.env</th></tr></thead>
            <tbody>
              <tr v-for="profile in hermesProfiles" :key="profile.name">
                <td><strong>{{ profile.name }}</strong></td>
                <td><span class="badge" :class="profile.soul_exists ? 'badge-green' : 'badge-grey'">{{ profile.soul_exists ? '存在' : '缺失' }}</span></td>
                <td><span class="badge" :class="profile.env_exists ? 'badge-green' : 'badge-grey'">{{ profile.env_exists ? '存在' : '缺失' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="state">本机未检测到 Hermes profiles。</div>
      </div>
    </section>

    <!-- 群聊弹层 -->
    <div v-if="channelsOpen" class="overlay" role="dialog" aria-modal="true" aria-label="机器人群聊">
      <div class="modal card">
        <div class="section-title"><div><h2>{{ channelsOpen.name }} · 已加入群聊（{{ channelsFor.length }}）</h2></div><button class="btn btn-sm" type="button" @click="channelsOpen = null">关闭</button></div>
        <div v-if="channelsFor.length" class="table-wrap">
          <table><thead><tr><th>群聊</th><th>类型</th><th>ID</th></tr></thead><tbody>
            <tr v-for="channel in channelsFor" :key="String(channel.channel_id)"><td><strong>{{ channel.channel_name || '（未命名）' }}</strong></td><td>{{ channel.channel_type || '—' }}</td><td class="mono">{{ channel.channel_id }}</td></tr>
          </tbody></table>
        </div>
        <div v-else class="state">该机器人尚未加入任何群聊。</div>
      </div>
    </div>

    <!-- 创建机器人弹层 -->
    <div v-if="createOpen" class="overlay" role="dialog" aria-modal="true" aria-label="创建机器人">
      <form class="modal card" @submit.prevent="submitCreate">
        <div class="section-title"><div><h2>创建机器人</h2><p>经 vertu-cli im +bot-create 创建，立即生效。</p></div><button class="btn btn-sm" type="button" @click="createOpen = false">取消</button></div>
        <div class="fields">
          <label>名称 *<input v-model="createForm.name" class="input" maxlength="64" required placeholder="如：海外日报播报员" /></label>
          <label>唯一 key（可选）<input v-model="createForm.bot_key" class="input" maxlength="64" placeholder="字母/数字/-/_，3-64 位" /></label>
          <label class="span2">说明（可选）<input v-model="createForm.description" class="input" maxlength="500" placeholder="这个机器人做什么" /></label>
          <label class="span2">Webhook（可选）<input v-model="createForm.webhook_url" class="input" maxlength="300" placeholder="https://..." /></label>
        </div>
        <label class="switch"><input v-model="createForm.public" type="checkbox" /> 公开（允许其他群管理员添加）</label>
        <div class="row end"><button class="btn btn-primary" type="submit" :disabled="createSaving">{{ createSaving ? '创建中…' : '创建' }}</button></div>
      </form>
    </div>
  </main>
</template>
<style scoped>
.page { max-width: 1180px; margin: 0 auto; padding: 24px 20px 60px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 18px; flex-wrap: wrap; }
.head h1 { margin: 0 0 5px; font-size: 24px; }
.head p { margin: 0; color: var(--muted); font-size: 13px; }
.tabs { display: flex; gap: 6px; }
.tab { padding: 8px 18px; border-radius: 999px; border: 1px solid var(--border); background: transparent; color: var(--muted); font-size: 13px; cursor: pointer; }
.tab.active { background: var(--blue-soft); color: var(--blue); border-color: transparent; font-weight: 600; }
.cards { display: grid; gap: 16px; }
.panel { padding: 18px; }
.section-title { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 12px; }
.section-title h2 { margin: 0 0 4px; font-size: 16px; }
.section-title p { margin: 0; color: var(--muted); font-size: 13px; }
.row { display: flex; gap: 8px; align-items: center; }
.row.end { justify-content: flex-end; margin-top: 14px; }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
th { color: var(--muted); }
.bot-cell { display: flex; align-items: center; gap: 10px; min-width: 180px; }
.avatar { width: 34px; height: 34px; border-radius: 8px; object-fit: cover; background: var(--border); }
.desc { color: var(--muted); max-width: 260px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.block { display: block; margin-top: 3px; color: var(--muted); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; border: 1px solid transparent; }
.badge-green { background: rgba(16,185,129,.12); color: var(--green); }
.badge-grey { background: rgba(148,163,184,.12); color: var(--muted); }
.badge-blue { background: var(--blue-soft); color: var(--blue); }
.badge-amber { background: rgba(245,158,11,.12); color: var(--amber); }
.out { display: inline-block; margin: 0 6px 4px 0; font-size: 12px; }
.message { padding: 10px 14px; border-radius: var(--radius); }
.error { color: var(--red); background: rgba(244,63,94,.1); }
.ok { color: var(--green); background: rgba(16,185,129,.1); }
.state { padding: 32px; text-align: center; color: var(--muted); }
.overlay { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: grid; place-items: center; z-index: 40; padding: 20px; }
.modal { width: min(680px, 100%); max-height: 84vh; overflow: auto; padding: 20px; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin: 14px 0 10px; }
.fields label { display: grid; gap: 7px; color: var(--muted); font-size: 13px; }
.fields .span2 { grid-column: span 2; }
.switch { display: block; font-size: 14px; margin-top: 6px; }
.muted { color: var(--muted); }
@media (max-width: 600px) {
  .page { padding: 16px 12px 40px; }
  .fields { grid-template-columns: 1fr; }
  .fields .span2 { grid-column: span 1; }
  .head { align-items: stretch; flex-direction: column; }
}
</style>


