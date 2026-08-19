<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface Me {
  username: string
  display_name: string
  role: string
}

interface KpiPayload {
  amount: number | null
  wan: number | null
  note: string
  as_of?: string | null
  source?: string | null
  state?: string
  currency?: string
}

interface Fact {
  value: number | null
  state: string
  source: string
  message?: string
}

interface ActionItem {
  priority: string
  title: string
  message: string
  href: string
}

interface TodayPayload {
  date: string
  facts: Record<string, Fact>
  actions: ActionItem[]
  closure: { reported: number; expected: number; complete: boolean }
}

interface CustomerRow {
  level: string
  total: number
  touched: number | null
  target: number
}

const router = useRouter()
const me = ref<Me | null>(null)
const period = ref('day')
const dateText = ref(workDate())

const sellIn = ref<KpiPayload | null>(null)
const sellOut = ref<KpiPayload | null>(null)
const today = ref<TodayPayload | null>(null)
const customers = ref<CustomerRow[] | null>(null)

const loading = ref(true)
const error = ref('')
const syncing = ref(false)
const syncMessage = ref('')

const PERIODS = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季' },
]

const FACT_LABELS: Record<string, string> = {
  walkin_visits: '今日进店',
  walkin_reported: '已上报门店',
  walkin_missing: '未上报门店',
  logistics_attention: '物流异常/待核查',
}

function workDate(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

function qs(extra: Record<string, string> = {}): string {
  const params = new URLSearchParams({ date: dateText.value, period: period.value, ...extra })
  return params.toString()
}

async function loadAll() {
  loading.value = true
  error.value = ''
  const settle = await Promise.allSettled([
    apiGet<Me>('/api/auth/me'),
    apiGet<KpiPayload>(`/api/dashboard/sell-in?${qs()}`),
    apiGet<KpiPayload>(`/api/dashboard/sell-out?${qs()}`),
    apiGet<TodayPayload>(`/api/workbench/today?${qs()}`),
    apiGet<CustomerRow[]>('/api/customer-center/summary'),
  ])
  const [meR, sellInR, sellOutR, todayR, customersR] = settle

  if (meR.status === 'fulfilled') me.value = meR.value
  if (sellInR.status === 'fulfilled') sellIn.value = sellInR.value
  if (sellOutR.status === 'fulfilled') sellOut.value = sellOutR.value
  if (todayR.status === 'fulfilled') today.value = todayR.value
  if (customersR.status === 'fulfilled') customers.value = customersR.value

  const rejected = settle.find(
    (r): r is PromiseRejectedResult =>
      r.status === 'rejected' && r.reason instanceof HttpError && r.reason.status === 401,
  )
  if (rejected) {
    router.replace({ path: '/login', query: { next: '/' } })
    return
  }
  if (meR.status === 'rejected') {
    error.value =
      meR.reason instanceof HttpError ? meR.reason.detail : '工作台数据加载失败，请稍后重试'
  }
  loading.value = false
}

async function syncData() {
  if (me.value?.role !== 'admin' && me.value?.role !== 'manager') return
  syncing.value = true
  syncMessage.value = '⏳ 正在同步数据…（约 1 分钟）'
  try {
    await apiPost('/api/dashboard/refresh', { date: dateText.value })
    syncMessage.value = '✅ 同步完成'
    await loadAll()
  } catch (err) {
    syncMessage.value = '❌ 同步失败：' + (err instanceof HttpError ? err.detail : '网络错误')
  } finally {
    syncing.value = false
    setTimeout(() => (syncMessage.value = ''), 4000)
  }
}

function badgeClass(state?: string): string {
  if (state === 'live') return 'badge badge-live'
  if (state === 'stale') return 'badge badge-stale'
  return 'badge badge-missing'
}

function badgeLabel(state?: string): string {
  if (state === 'live') return '实时'
  if (state === 'stale') return '数据过期'
  return '缺失'
}

function factBadgeClass(state: string): string {
  if (state === 'available') return 'badge badge-live'
  if (state === 'stale') return 'badge badge-stale'
  return 'badge badge-missing'
}

function kpiAmount(p: KpiPayload | null): string {
  if (!p) return '—'
  if (p.wan != null) return p.wan + ' 万'
  if (p.amount != null) return p.currency === 'USD' ? '$ ' + p.amount.toLocaleString() : '¥ ' + p.amount.toLocaleString()
  return '—'
}

onMounted(loadAll)
</script>

<template>
  <AppNav />
  <main class="cockpit">
    <header class="head">
      <div>
        <h1>经营驾驶舱</h1>
        <p class="sub">
          {{ me ? (me.display_name || me.username) : '…' }} · {{ dateText }} ·
          <span v-if="today">{{ today.closure.reported }}/{{ today.closure.expected }} 门店已上报</span>
        </p>
      </div>
      <div class="head-actions">
        <div class="period-switch">
          <button
            v-for="p in PERIODS"
            :key="p.value"
            type="button"
            :class="['chip', { active: period === p.value }]"
            @click="period = p.value; loadAll()"
          >
            {{ p.label }}
          </button>
        </div>
        <button
          v-if="me && (me.role === 'admin' || me.role === 'manager')"
          class="btn btn-primary"
          type="button"
          :disabled="syncing"
          @click="syncData"
        >
          {{ syncing ? '同步中…' : '同步数据' }}
        </button>
      </div>
    </header>

    <p v-if="syncMessage" class="sync-msg">{{ syncMessage }}</p>

    <div v-if="error" class="card error-card">{{ error }}</div>

    <section v-else class="kpi-grid">
      <div class="card kpi">
        <span class="kpi-label">Sell-in（进货）</span>
        <span class="kpi-value">{{ kpiAmount(sellIn) }}</span>
        <span class="kpi-note">
          <span :class="badgeClass(sellIn?.state)">{{ badgeLabel(sellIn?.state) }}</span>
          {{ sellIn?.note || '加载中…' }}
        </span>
      </div>
      <div class="card kpi">
        <span class="kpi-label">Sell-out（终销）</span>
        <span class="kpi-value">{{ kpiAmount(sellOut) }}</span>
        <span class="kpi-note">
          <span :class="badgeClass(sellOut?.state)">{{ badgeLabel(sellOut?.state) }}</span>
          {{ sellOut?.note || '加载中…' }}
        </span>
      </div>
      <div v-for="(fact, key) in today?.facts || {}" :key="key" class="card kpi">
        <span class="kpi-label">{{ FACT_LABELS[key] || key }}</span>
        <span class="kpi-value">{{ fact.state === 'available' ? (fact.value ?? '—') : '—' }}</span>
        <span class="kpi-note">
          <span :class="factBadgeClass(fact.state)">
            {{ fact.state === 'available' ? '正常' : '未同步' }}
          </span>
          来源：{{ fact.source }}
        </span>
      </div>
    </section>

    <div class="two-col">
      <section class="card panel">
        <h2>今日待处理</h2>
        <template v-if="today?.actions?.length">
          <a
            v-for="(action, index) in today.actions"
            :key="index"
            class="action-row"
            :href="action.href || undefined"
          >
            <strong>{{ action.title }}</strong>
            <span>{{ action.message }}</span>
          </a>
        </template>
        <p v-else class="empty">当前没有已识别的待处理异常</p>
      </section>

      <section class="card panel">
        <h2>客户分层</h2>
        <div v-if="customers?.length" class="customer-grid">
          <article v-for="row in customers" :key="row.level" class="customer-card">
            <span class="c-label">{{ row.level }} 类</span>
            <b>{{ row.total }}</b>
            <span class="c-sub">触达 {{ row.touched != null ? row.touched : '未同步' }} / 目标 {{ row.target }}</span>
          </article>
        </div>
        <p v-else-if="customers" class="empty">暂无客户分层数据</p>
        <p v-else class="empty">加载中…</p>
      </section>
    </div>
  </main>
</template>

<style scoped>
.cockpit {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

h1 {
  margin: 0 0 4px;
  font-size: 24px;
}

h2 {
  margin: 0 0 14px;
  font-size: 15px;
  color: var(--muted);
}

.sub {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.period-switch {
  display: flex;
  gap: 4px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px;
}

.chip {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 999px;
  cursor: pointer;
}

.chip.active {
  background: var(--blue-soft);
  color: var(--blue);
  font-weight: 600;
}

.sync-msg {
  color: var(--amber);
  font-size: 13px;
  margin: 0 0 10px;
}

.error-card {
  padding: 32px;
  text-align: center;
  color: var(--red);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.kpi {
  padding: 16px 18px;
  display: grid;
  gap: 8px;
}

.kpi-label {
  font-size: 12px;
  color: var(--muted);
}

.kpi-value {
  font-size: 26px;
  font-weight: 700;
}

.kpi-note {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
  flex-wrap: wrap;
}

.two-col {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 16px;
}

.panel {
  padding: 20px 22px;
}

.action-row {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 10px;
  color: var(--text);
  transition: background 0.15s;
}

.action-row:hover {
  background: rgba(78, 158, 245, 0.08);
}

.action-row span {
  color: var(--muted);
  font-size: 13px;
}

.customer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.customer-card {
  background: var(--card-2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
  display: grid;
  gap: 6px;
}

.c-label {
  font-size: 12px;
  color: var(--blue);
}

.customer-card b {
  font-size: 24px;
}

.c-sub {
  font-size: 12px;
  color: var(--muted);
}

.empty {
  color: var(--muted);
  font-size: 13px;
  padding: 8px 0;
}

@media (max-width: 760px) {
  .two-col {
    grid-template-columns: 1fr;
  }
}
</style>
