<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface Me {
  role: string
}

interface SyncResult {
  date?: string
  [key: string]: unknown
}

interface ModuleInfo {
  path: string
  dir_exists: boolean
  index_html_exists: boolean
}

interface Diagnostics {
  mvp_root: string
  mvp_root_exists: boolean
  repo_root: string
  repo_root_exists: boolean
  modules: Record<string, ModuleInfo>
  legacy_bridge_probe: { ok: boolean; today_text?: string; error?: string | null }
  database: { mode: string; connected: boolean; pg_host: string; pg_database: string }
  auth_mode: string
  secure_cookies: boolean
  trust_proxy_headers: boolean
  vps_login_url: string
}

interface DiagRow {
  label: string
  value: string
  ok: boolean
  note: string
}

const router = useRouter()
const me = ref<Me | null>(null)
const busy = ref(false)
const result = ref<SyncResult | null>(null)
const error = ref('')
const finishedAt = ref('')
const notice = ref('')
const diag = ref<Diagnostics | null>(null)
const diagLoading = ref(true)
const diagError = ref('')
const diagForbidden = ref(false)

const STEP_LABELS: Record<string, string> = {
  vps_dealer_sales: '经销商 Sell-in（vertu-cli → DB）',
  dealer_sales: '经销商 Sell-in 写入结果',
  pdca_tasks: '待办任务（CSV → DB）',
  daily_reports: '日报/报告（outputs → DB）',
  meetings: '会议（Vemory → DB）',
  vemory_todos: '会议待办（Vemory）',
}

const canSync = computed(() => !!me.value && ['manager', 'admin'].includes(me.value.role))

const diagRows = computed<DiagRow[]>(() => {
  const data = diag.value
  if (!data) return []
  const modules = Object.entries(data.modules || {})
  const readyModules = modules.filter(([, info]) => info.dir_exists && info.index_html_exists).length
  const rows: DiagRow[] = [
    {
      label: '数据库',
      value: data.database?.connected ? '已连接' : '未连接',
      ok: !!data.database?.connected,
      note: (data.database?.mode || '') + ' · ' + (data.database?.pg_host || '') + '/' + (data.database?.pg_database || ''),
    },
    {
      label: 'vertu-cli 凭据',
      value: data.legacy_bridge_probe?.ok ? '可用' : '不可用',
      ok: !!data.legacy_bridge_probe?.ok,
      note: data.legacy_bridge_probe?.ok ? data.legacy_bridge_probe?.today_text || '' : data.legacy_bridge_probe?.error || '未通过自检',
    },
    {
      label: 'MVP 目录',
      value: data.mvp_root_exists ? '存在' : '缺失',
      ok: !!data.mvp_root_exists,
      note: data.mvp_root || '',
    },
    {
      label: '仓库目录',
      value: data.repo_root_exists ? '存在' : '缺失',
      ok: !!data.repo_root_exists,
      note: data.repo_root || '',
    },
    {
      label: '业务模块',
      value: readyModules + ' / ' + modules.length + ' 就绪',
      ok: modules.length > 0 && readyModules === modules.length,
      note: modules.filter(([, info]) => !(info.dir_exists && info.index_html_exists)).map(([name]) => name).join('、') || '全部模块产物齐备',
    },
    {
      label: '认证模式',
      value: data.auth_mode || '—',
      ok: true,
      note: '安全 Cookie：' + (data.secure_cookies ? '开启' : '关闭') + ' · 代理头信任：' + (data.trust_proxy_headers ? '开启' : '关闭'),
    },
  ]
  return rows
})

const diagSummary = computed(() => {
  const rows = diagRows.value
  return { total: rows.length, ok: rows.filter((row) => row.ok).length }
})

function fmt(value: unknown): string {
  if (typeof value === 'number') return value + ' 条'
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value ?? '—')
}

function stepOk(value: unknown): boolean {
  if (typeof value === 'number') return Number.isFinite(value) && value >= 0
  if (value && typeof value === 'object') {
    const step = value as { status?: string; ok?: boolean; errors?: unknown[]; error?: unknown }
    return !step.error && !step.errors?.length && (step.status === 'ok' || step.ok === true)
  }
  return value === 'ok'
}

function resultRows(): { key: string; label: string; value: unknown }[] {
  if (!result.value) return []
  return Object.entries(result.value)
    .filter(([key]) => key !== 'date')
    .map(([key, value]) => ({ key, label: STEP_LABELS[key] || key, value }))
}

function showNotice(message: string) {
  notice.value = message
  window.setTimeout(() => { if (notice.value === message) notice.value = '' }, 4000)
}

async function loadDiagnostics() {
  diagLoading.value = true
  diagError.value = ''
  diagForbidden.value = false
  try {
    diag.value = await apiGet<Diagnostics>('/api/admin/diagnostics')
  } catch (err) {
    if (err instanceof HttpError && err.status === 403) {
      diagForbidden.value = true
      diag.value = null
    } else {
      diagError.value = err instanceof HttpError ? err.detail : '自检信息读取失败'
    }
  } finally {
    diagLoading.value = false
  }
}

async function runSync() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await apiPost<SyncResult>('/api/admin/sync', {})
    finishedAt.value = new Date().toLocaleTimeString('zh-CN')
    showNotice('数据同步已完成')
    await loadDiagnostics()
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '同步失败，请稍后重试'
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  loadDiagnostics()
  try {
    me.value = await apiGet<Me>('/api/auth/me')
  } catch {
    me.value = null
  }
})
</script>
<template>
  <AppNav />
  <main class="page">
    <header class="page-head">
      <div>
        <h1>数据同步</h1>
        <p class="sub">手动刷新业务数据；部署自检反映当前运行环境的真实状态。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" :disabled="diagLoading" @click="loadDiagnostics">
          {{ diagLoading ? '自检中…' : '刷新自检' }}
        </button>
        <button
          v-if="canSync"
          class="btn btn-primary"
          type="button"
          :disabled="busy"
          @click="runSync"
        >
          {{ busy ? '同步中…（约 1 分钟）' : '立即同步' }}
        </button>
      </div>
    </header>

    <p v-if="notice" class="toast" role="status">{{ notice }}</p>

    <div v-if="me && !canSync" class="card alert" role="alert">
      <span>当前账号（{{ me.role }}）无同步权限，需 manager 或 admin。</span>
    </div>

    <section class="stats" aria-label="环境自检概要">
      <div class="card stat">
        <span class="stat-label">自检通过</span>
        <span class="stat-value num">{{ diag ? diagSummary.ok + ' / ' + diagSummary.total : '—' }}</span>
        <span class="stat-note">数据库、凭据、目录与模块</span>
      </div>
      <div class="card stat">
        <span class="stat-label">数据库</span>
        <span class="stat-value num">{{ diag ? (diag.database?.connected ? '正常' : '异常') : '—' }}</span>
        <span class="stat-note">{{ diag?.database?.mode || '需管理员权限' }}</span>
      </div>
      <div class="card stat">
        <span class="stat-label">vertu-cli</span>
        <span class="stat-value num">{{ diag ? (diag.legacy_bridge_probe?.ok ? '可用' : '不可用') : '—' }}</span>
        <span class="stat-note">业务数据取数依赖</span>
      </div>
      <div class="card stat">
        <span class="stat-label">最近同步</span>
        <span class="stat-value num">{{ finishedAt || '本次未执行' }}</span>
        <span class="stat-note">{{ result?.date || '点击「立即同步」执行' }}</span>
      </div>
    </section>

    <section class="panel card">
      <header class="section-head">
        <div>
          <h2>部署自检</h2>
          <p>来自 /api/admin/diagnostics，反映当前进程的真实运行环境。</p>
        </div>
      </header>
      <div v-if="diagForbidden" class="card-alert-note">
        <p class="hint">部署自检需要系统管理员（admin）权限，当前账号为 {{ me?.role || '未知' }}；同步数据仍可正常执行。</p>
      </div>
      <div v-else-if="diagError" class="alert" role="alert">
        <span>{{ diagError }}</span>
        <button class="btn btn-sm" type="button" @click="loadDiagnostics">重试</button>
      </div>
      <div v-else-if="diagLoading" class="skeleton-rows" aria-busy="true">
        <div v-for="row in 4" :key="row" class="skeleton-row">
          <span class="skeleton" style="width: 120px" />
          <span class="skeleton" style="flex: 1" />
        </div>
      </div>
      <div v-else-if="diagRows.length" class="table-wrap">
        <table class="data-table">
          <thead>
            <tr><th scope="col">检查项</th><th scope="col">状态</th><th scope="col">说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in diagRows" :key="row.label">
              <td><strong>{{ row.label }}</strong></td>
              <td>
                <span class="pill" :class="row.ok ? 'pill-green' : 'pill-red'">{{ row.value }}</span>
              </td>
              <td class="mono break">{{ row.note || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state">
        <h2>暂无自检数据</h2>
        <p>点击「刷新自检」重新读取运行环境状态。</p>
        <button class="btn" type="button" @click="loadDiagnostics">刷新自检</button>
      </div>
    </section>

    <section class="panel card">
      <header class="section-head">
        <div>
          <h2>同步结果</h2>
          <p>{{ result?.date ? result.date + ' · ' + finishedAt : '执行同步后显示各数据源的写入结果' }}</p>
        </div>
      </header>
      <div v-if="error" class="alert" role="alert">
        <span>{{ error }}</span>
        <button class="btn btn-sm" type="button" :disabled="busy" @click="runSync">重试</button>
      </div>
      <div v-else-if="busy" class="skeleton-rows" aria-busy="true">
        <div v-for="row in 4" :key="row" class="skeleton-row">
          <span class="skeleton" style="width: 160px" />
          <span class="skeleton" style="flex: 1" />
        </div>
      </div>
      <div v-else-if="resultRows().length" class="table-wrap">
        <table class="data-table">
          <thead>
            <tr><th scope="col">步骤</th><th scope="col">结果</th><th scope="col">状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in resultRows()" :key="row.key">
              <td>{{ row.label }}</td>
              <td class="num">{{ fmt(row.value) }}</td>
              <td>
                <span class="pill" :class="stepOk(row.value) ? 'pill-green' : 'pill-red'">
                  {{ stepOk(row.value) ? '正常' : '失败' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state">
        <h2>本次尚未执行同步</h2>
        <p>同步会刷新经销商 Sell-in、待办任务、日报与会议数据，约需 1 分钟。</p>
        <button v-if="canSync" class="btn btn-primary" type="button" :disabled="busy" @click="runSync">立即同步</button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.skeleton-rows { display: grid; }
:deep(.skeleton-row:last-child) { border-bottom: none; }
.card-alert-note { padding: 12px 14px; border: 1px dashed var(--border-strong); border-radius: var(--radius); margin-bottom: 12px; }
.card-alert-note .hint { margin: 0; }
</style>

