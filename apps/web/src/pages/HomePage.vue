<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import { loadSections, type SectionResult } from '@/api/load-sections'
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
  review_count?: number
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
  closure: { reported: number; expected: number; complete: boolean; report_date: string }
}

interface CustomerRow {
  level: string
  total: number
  touched: number | null
  target: number
}

const router = useRouter()
const me = ref<Me | null>(null)
const period = ref('month')
const dateText = ref(workDate())

const sellIn = ref<KpiPayload | null>(null)
const sellOut = ref<KpiPayload | null>(null)
const today = ref<TodayPayload | null>(null)
const customers = ref<CustomerRow[] | null>(null)

const loading = ref(true)
const error = ref('')
const sectionErrors = ref<Record<string, string>>({})
let loadId = 0
const syncing = ref(false)
const syncMessage = ref('')

const ALL_PERIODS = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季' },
]
const periods = computed(() => me.value?.role === 'admin' ? ALL_PERIODS : ALL_PERIODS.filter((item) => item.value === 'month'))
const PERIOD_LABELS: Record<string, string> = { day: '当日', week: '本周', month: '本月', quarter: '本季' }
const periodLabel = computed(() => PERIOD_LABELS[period.value] || '本月')

const FACT_LABELS: Record<string, string> = {
  walkin_visits: 'T-1 进店',
  walkin_reported: 'T-1 已填报门店',
  logistics_attention: '物流异常/待核查',
}

const visibleFacts = computed(() =>
  Object.entries(today.value?.facts || {}).filter(([key]) => key !== 'store_count' && key !== 'walkin_missing'),
)

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
  const id = ++loadId
  loading.value = true
  error.value = ''
  sectionErrors.value = {}
  sellIn.value = null
  sellOut.value = null
  today.value = null
  customers.value = null
  const keys = ['账号', 'sellIn', 'sellOut', 'today', 'customers']
  const applyResult = (index: number, result: SectionResult<unknown>) => {
    if (id !== loadId) return
    if (result.status === 'rejected' && result.reason instanceof HttpError && result.reason.status === 401) {
      router.replace({ path: '/login', query: { next: '/' } })
      return
    }
    if (result.status === 'fulfilled') {
      if (index === 0) me.value = result.value as Me
      if (index === 1) sellIn.value = result.value as KpiPayload
      if (index === 2) sellOut.value = result.value as KpiPayload
      if (index === 3) today.value = result.value as TodayPayload
      if (index === 4) customers.value = result.value as CustomerRow[]
    }
    if (result.status === 'rejected') {
      sectionErrors.value[keys[index]] = result.reason instanceof HttpError ? result.reason.detail : '加载失败，请重试'
    }
  }
  const settle = await loadSections<unknown>([
    () => apiGet<Me>('/api/auth/me'),
    () => apiGet<KpiPayload>(`/api/dashboard/sell-in?${qs()}`),
    () => apiGet<KpiPayload>(`/api/dashboard/sell-out?${qs()}`),
    () => apiGet<TodayPayload>(`/api/workbench/today?${qs()}`),
    () => apiGet<CustomerRow[]>('/api/customer-center/summary'),
  ], applyResult)
  if (id !== loadId) return
  const [meR] = settle

  const rejected = settle.find(
    (r): r is PromiseRejectedResult =>
      r.status === 'rejected' && r.reason instanceof HttpError && r.reason.status === 401,
  )
  if (rejected) {
    router.replace({ path: '/login', query: { next: '/' } })
    return
  }
  if (meR?.status === 'rejected') {
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
    await apiPost(`/api/dashboard/refresh?date=${encodeURIComponent(dateText.value)}`)
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
  if (state === 'live') return 'status info'
  if (state === 'stale' || state === 'partial') return 'status warn'
  return 'status danger'
}

function badgeLabel(state?: string): string {
  if (state === 'live') return '实时'
  if (state === 'stale') return '数据过期'
  if (state === 'partial') return '部分金额待复核'
  return '缺失'
}

function factLabel(state: string): string {
  return { available: '已核验', mixed: '含历史记录', historical: '历史记录', degraded: '数据源异常', stale: '数据过期' }[state] || '数据不可用'
}

function factBadgeClass(state: string): string {
  if (state === 'available') return 'status ok'
  if (['stale', 'mixed', 'historical'].includes(state)) return 'status warn'
  return 'status danger'
}

function kpiAmount(p: KpiPayload | null): string {
  if (!p) return loading.value ? '…' : 'N/A'
  if (p.wan != null) return p.wan + ' 万'
  if (p.amount != null) return p.currency === 'USD' ? '$ ' + p.amount.toLocaleString() : '¥ ' + p.amount.toLocaleString()
  return 'N/A'
}

onMounted(loadAll)
</script>

<template>
  <AppNav />
  <main class="page home-page">
      <header class="page-head home-head">
        <div>
          <h1>经营驾驶舱</h1>
          <p class="sub">
            {{ dateText }} · {{ me ? (me.display_name || me.username) : '加载中' }}
            <span v-if="today"> · T-1（{{ today.closure.report_date }}）已收到 {{ today.closure.reported }} 家门店填报</span>
          </p>
        </div>
        <div class="page-actions home-actions">
          <div v-if="periods.length > 1" class="segmented" role="group" aria-label="统计周期">
            <button
              v-for="p in periods"
              :key="p.value"
              type="button"
              :class="{ active: period === p.value }"
              :aria-pressed="period === p.value"
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

      <p v-if="syncMessage" class="toast" role="status">{{ syncMessage }}</p>

      <div v-if="error" class="card alert" role="alert">
        <span>{{ error }}</span>
        <button class="btn btn-sm" type="button" @click="loadAll()">重试</button>
      </div>

      <template v-else>
        <section class="home-overview" aria-labelledby="home-performance-title">
          <div class="home-section-title">
            <h2 id="home-performance-title">业绩概览</h2>
            <span>{{ periodLabel }}</span>
          </div>
          <div class="home-performance">
            <article class="card home-kpi">
              <div class="home-kpi-top">
                <span class="home-kpi-label">Sell-in <small>进货额</small></span>
                <span v-if="!loading || sellIn" :class="badgeClass(sellIn?.state)">{{ badgeLabel(sellIn?.state) }}</span>
              </div>
              <strong class="home-kpi-value num">{{ kpiAmount(sellIn) }}</strong>
              <p class="home-kpi-note">{{ sectionErrors.sellIn || sellIn?.note || (loading ? '加载中…' : '数据不可用') }}</p>
            </article>
            <article class="card home-kpi">
              <div class="home-kpi-top">
                <span class="home-kpi-label">Sell-out <small>终销额</small></span>
                <span v-if="!loading || sellOut" :class="badgeClass(sellOut?.state)">{{ badgeLabel(sellOut?.state) }}</span>
              </div>
              <strong class="home-kpi-value num">{{ kpiAmount(sellOut) }}</strong>
              <p class="home-kpi-note">{{ sectionErrors.sellOut || sellOut?.note || (loading ? '加载中…' : '数据不可用') }}</p>
              <p v-if="sellOut?.review_count" class="home-kpi-review">{{ sellOut.review_count }} 条待复核金额未计入</p>
            </article>
          </div>
        </section>

        <section class="home-operations" aria-labelledby="home-operations-title">
          <div class="home-section-title">
            <h2 id="home-operations-title">昨日运营</h2>
            <span v-if="today">{{ today.closure.report_date }}</span>
          </div>
          <div class="home-facts">
            <article v-for="[key, fact] in visibleFacts" :key="key" class="home-fact">
              <span class="home-fact-label">{{ FACT_LABELS[key] || key }}</span>
              <div class="home-fact-main">
                <strong class="num">{{ fact.state === 'available' ? (fact.value ?? 'N/A') : 'N/A' }}</strong>
                <span :class="factBadgeClass(fact.state)">{{ factLabel(fact.state) }}</span>
              </div>
              <p v-if="fact.message" class="home-fact-note">{{ fact.message }}</p>
            </article>
            <p v-if="!visibleFacts.length" class="home-panel-state">
              {{ sectionErrors.today ? `运营数据加载失败：${sectionErrors.today}` : loading ? '运营数据加载中…' : '暂无可用的运营数据' }}
            </p>
          </div>
        </section>

        <div class="home-panels">
          <section class="card home-panel" aria-labelledby="home-actions-title">
            <header class="section-head">
              <div>
                <h2 id="home-actions-title">当前待处理</h2>
                <p>系统识别的待处理事项</p>
              </div>
              <span v-if="today?.actions?.length" class="home-count num">{{ today.actions.length }} 项</span>
            </header>
            <p v-if="sectionErrors.today" class="home-panel-state" role="alert">待处理事项加载失败：{{ sectionErrors.today }}</p>
            <div v-else-if="today?.actions?.length" class="home-action-list">
              <component
                :is="action.href ? 'a' : 'div'"
                v-for="(action, index) in today.actions"
                :key="index"
                class="home-action"
                :href="action.href || undefined"
              >
                <span class="home-action-index num" aria-hidden="true">{{ index + 1 }}</span>
                <span class="home-action-copy">
                  <strong>{{ action.title }}</strong>
                  <span>{{ action.message }}</span>
                </span>
                <svg v-if="action.href" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M5 12h14m-6-6 6 6-6 6" />
                </svg>
              </component>
            </div>
            <p v-else-if="loading" class="home-panel-state">加载中…</p>
            <p v-else-if="today" class="home-panel-state">当前没有已识别的待处理异常</p>
            <p v-else class="home-panel-state">待处理事项暂不可用</p>
          </section>

          <section class="card home-panel" aria-labelledby="home-customers-title">
            <header class="section-head">
              <div>
                <h2 id="home-customers-title">客户分层</h2>
                <p>仅统计已建档客户，触达数为最近同步口径</p>
              </div>
            </header>
            <p v-if="sectionErrors.customers" class="home-panel-state" role="alert">客户分层加载失败：{{ sectionErrors.customers }}</p>
            <table v-else-if="customers?.length" class="home-customer-table">
              <thead><tr><th scope="col">类别</th><th scope="col">客户数</th><th scope="col">触达 / 目标</th></tr></thead>
              <tbody>
                <tr v-for="row in customers" :key="row.level">
                  <th scope="row">{{ row.level }} 类</th>
                  <td class="home-customer-number num">{{ row.total }}</td>
                  <td class="home-customer-progress">
                    {{ row.touched != null || row.target > 0 ? `${row.touched ?? '未同步'} / ${row.target}` : '尚未接入' }}
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else-if="customers" class="home-panel-state">暂无客户分层数据，请检查客户资料同步</p>
            <p v-else class="home-panel-state">加载中…</p>
          </section>
        </div>
      </template>
  </main>
</template>

<style scoped>
.home-head { align-items: center; margin-bottom: var(--sp-6); }
.home-head .sub { line-height: 1.5; }
.home-actions { margin-left: auto; }
.home-overview, .home-operations { margin-bottom: var(--sp-6); }
.home-section-title { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); margin-bottom: var(--sp-3); }
.home-section-title h2 { margin: 0; color: var(--text-1); font-size: 14px; font-weight: 600; }
.home-section-title > span { color: var(--text-3); font-size: 12px; }
.home-performance { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--sp-3); }
.home-kpi { min-width: 0; min-height: 168px; padding: var(--sp-6); display: flex; flex-direction: column; align-items: flex-start; }
.home-kpi:first-child { border-top: 2px solid var(--info); }
.home-kpi-top { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); width: 100%; }
.home-kpi-label { color: var(--text-1); font-size: 14px; font-weight: 600; }
.home-kpi-label small { margin-left: var(--sp-2); color: var(--text-3); font-size: 12px; font-weight: 400; }
.home-kpi-value { margin-top: var(--sp-5); color: var(--text-1); font-size: clamp(32px, 2.6vw, 42px); line-height: 1; letter-spacing: -0.035em; }
.home-kpi-note, .home-kpi-review { margin: var(--sp-3) 0 0; color: var(--text-2); font-size: 12px; line-height: 1.45; }
.home-kpi-review { margin-top: var(--sp-1); color: var(--warn); }
.home-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: var(--radius-lg); background: var(--surface-1); }
.home-fact { min-width: 0; padding: var(--sp-4) var(--sp-5); }
.home-fact + .home-fact { border-left: 1px solid var(--line); }
.home-fact-label { color: var(--text-2); font-size: 12px; }
.home-fact-main { display: flex; align-items: baseline; gap: var(--sp-3); margin-top: var(--sp-2); flex-wrap: wrap; }
.home-fact-main strong { color: var(--text-1); font-size: 26px; line-height: 1; }
.home-fact-note { margin: var(--sp-2) 0 0; color: var(--text-3); font-size: 12px; line-height: 1.45; }
.home-panels { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: var(--sp-3); align-items: start; }
.home-panel { min-width: 0; overflow: hidden; }
.home-panel .section-head { align-items: center; margin: 0; padding: var(--sp-5); border-bottom: 1px solid var(--line); }
.home-panel .section-head h2 { margin-bottom: var(--sp-1); font-size: 16px; }
.home-panel .section-head p { color: var(--text-3); font-size: 12px; line-height: 1.4; }
.home-count { color: var(--text-3); font-size: 12px; white-space: nowrap; }
.home-action { display: grid; grid-template-columns: 24px minmax(0, 1fr) 16px; align-items: start; gap: var(--sp-3); padding: var(--sp-4) var(--sp-5); color: var(--text-1); border-bottom: 1px solid var(--line); }
.home-action:last-child { border-bottom: 0; }
a.home-action:hover { background: var(--surface-hover); }
.home-action-index { color: var(--text-3); font-size: 12px; padding-top: 2px; }
.home-action-copy { display: grid; gap: var(--sp-1); min-width: 0; }
.home-action-copy strong { font-size: 13px; font-weight: 600; }
.home-action-copy > span { color: var(--text-2); font-size: 12px; line-height: 1.45; }
.home-action svg { width: 16px; height: 16px; margin-top: 2px; color: var(--text-3); }
.home-panel-state { margin: 0; padding: var(--sp-5); color: var(--text-2); font-size: 13px; line-height: 1.5; }
.home-customer-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.home-customer-table th, .home-customer-table td { padding: 16px var(--sp-5); text-align: left; border-bottom: 1px solid var(--line); }
.home-customer-table tr > :first-child { width: 24%; }
.home-customer-table tr > :nth-child(2) { width: 24%; }
.home-customer-table thead th { padding-top: 12px; padding-bottom: 12px; color: var(--text-3); font-size: 11px; font-weight: 400; }
.home-customer-table tbody th { color: var(--text-1); font-size: 13px; font-weight: 600; }
.home-customer-table tbody tr:last-child > * { border-bottom: 0; }
.home-customer-number { color: var(--text-1); font-size: 20px; font-weight: 600; }
.home-customer-progress { color: var(--text-2); font-size: 12px; }

@media (max-width: 900px) {
  .home-panels { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .home-head { align-items: flex-start; gap: var(--sp-4); }
  .home-actions { margin-left: 0; }
  .home-actions .btn { flex: 0 0 auto; }
  .home-performance { grid-template-columns: 1fr; }
  .home-kpi { min-height: 0; padding: var(--sp-5); }
  .home-kpi-value { margin-top: var(--sp-4); font-size: 34px; }
  .home-facts { grid-template-columns: 1fr; }
  .home-fact + .home-fact { border-left: 0; border-top: 1px solid var(--line); }
  .home-fact { padding: var(--sp-3) var(--sp-4); }
  .home-panel .section-head, .home-action, .home-panel-state { padding-left: var(--sp-4); padding-right: var(--sp-4); }
  .home-customer-table th, .home-customer-table td { padding-left: var(--sp-4); padding-right: var(--sp-4); }
}
</style>
