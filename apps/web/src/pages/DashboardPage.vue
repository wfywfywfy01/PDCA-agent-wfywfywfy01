<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts } from 'echarts/core'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

// 路由级代码分割保持不变：ECharts 仍按需注册，只引入本页使用的图表与组件。
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

type Period = 'day' | 'week' | 'month' | 'quarter'

interface Me {
  username: string
  display_name: string
  role: string
}

/** /api/dashboard/sell-in 与 /api/dashboard/sell-out 的统一契约。 */
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

/** /api/dashboard/overview 契约（含 merge_db_sales 追加的字段）。 */
interface OverviewPayload {
  managerName?: string
  managerRole?: string
  sellInWan?: number | null
  sellInAmount?: string | null
  sellInSub?: string
  sellOutWan?: number | null
  sellOutAmount?: string | null
  sellOutSub?: string
  dataState?: Record<string, string>
  dataSource?: Record<string, string | null>
  dataAsOf?: string | null
  dataUpdatedAt?: number
  realWalkinTotal?: number
  realWalkinStores?: number
  reportedRevenueUsd?: number | null
  reportedRevenueReviewCount?: number
  sellOutUsd?: number | null
}

interface DealerRow {
  rank: number | null
  name: string
  wan: number | null
  quantity: number
}

interface TrendRow {
  month: string
  wan: number | null
  has_data?: boolean
  snapshot_date?: string | null
  amount_state?: string
}

interface SellinSummary {
  month: string
  total_wan: number | null
  dealers: DealerRow[]
  has_data: boolean
  trend: TrendRow[]
  source?: string
  as_of?: string | null
  amount_state?: 'available' | 'stale' | 'suspect' | 'missing'
  amount_message?: string
  snapshot_date?: string | null
}

interface CustomerRow {
  level: string
  total: number
  touched: number | null
  target: number
}

interface TaskCount {
  key: string
  label: string
  value: number
}

interface TaskItem {
  owner_key?: string
  owner?: string
  title?: string
  status?: string
  priority?: string
  source?: string
  date?: string
}

interface TaskPanel {
  items?: TaskItem[]
  summary?: TaskCount[]
  scope?: string
  scope_message?: string
  source?: string
}

const router = useRouter()

const PERIODS: Array<{ value: Period; label: string }> = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季' },
]

const me = ref<Me | null>(null)
const dateText = ref(todayText())
const period = ref<Period>('month')
const sellinMonth = ref(currentMonth())

const overview = ref<OverviewPayload | null>(null)
const sellIn = ref<KpiPayload | null>(null)
const sellOut = ref<KpiPayload | null>(null)
const customers = ref<CustomerRow[] | null>(null)
const taskSummary = ref<TaskCount[] | null>(null)
const taskPanel = ref<TaskPanel | null>(null)
const dealer = ref<SellinSummary | null>(null)

const loading = ref(true)
const dealerLoading = ref(true)
const sectionErrors = ref<Record<string, string>>({})
const syncing = ref(false)
const toast = ref('')
let toastTimer: number | undefined

const chartEl = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null

const glossaryOpen = ref(false)
const glossaryCloseBtn = ref<HTMLButtonElement | null>(null)

let requestToken = 0
let dealerToken = 0

/** 顶部指标卡与分区共用的 6 个并发请求；任一失败都只影响自己那一块。 */
const SECTION_KEYS = ['overview', 'sellIn', 'sellOut', 'customers', 'taskSummary', 'taskPanel'] as const

const canSync = computed(() => !!me.value && ['manager', 'admin'].includes(me.value.role))
const pageFailed = computed(
  () => !loading.value && SECTION_KEYS.every((key) => Boolean(sectionErrors.value[key])),
)
const loadedSections = computed(
  () => SECTION_KEYS.filter((key) => !sectionErrors.value[key]).length,
)

function todayText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

function currentMonth(): string {
  return todayText().slice(0, 7)
}

function qs(extra: Record<string, string> = {}): string {
  return new URLSearchParams({ date: dateText.value, period: period.value, ...extra }).toString()
}

function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(Number(value))) return 'N/A'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function fmtDateTime(value?: string | null): string {
  if (!value) return '未知'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('zh-CN', { hour12: false })
}

function errText(err: unknown, fallback: string): string {
  return err instanceof HttpError ? err.detail : fallback
}

// ── 新鲜度 / 徽标 ─────────────────────────────────────────────────────
const STATE_LABELS: Record<string, string> = {
  live: '实时',
  available: '已核验',
  stale: '数据过期',
  partial: '部分待复核',
  suspect: '金额待核验',
  missing: '无数据',
}

function stateLabel(state?: string | null): string {
  if (!state) return '无数据'
  return STATE_LABELS[state] || state
}

function statePill(state?: string | null): string {
  if (state === 'live' || state === 'available') return 'pill-green'
  if (state === 'stale' || state === 'partial' || state === 'suspect') return 'pill-amber'
  if (state === 'missing' || !state) return 'pill-muted'
  return 'pill-blue'
}

function isDone(status?: string): boolean {
  return ['done', 'completed', 'complete', '已完成'].includes(String(status || '').trim().toLowerCase())
}

function priorityLabel(priority?: string): string {
  return { high: '高', medium: '中', normal: '普通' }[String(priority || '')] || '普通'
}

function priorityPill(priority?: string): string {
  if (priority === 'high') return 'pill-red'
  if (priority === 'medium') return 'pill-amber'
  return 'pill-muted'
}

// ── 顶部指标卡（全部取接口真实字段，缺失即 N/A） ──────────────────────
const sellInCard = computed(() => {
  const payload = sellIn.value
  const fallbackWan = overview.value?.sellInWan ?? null
  const wan = payload?.wan ?? fallbackWan
  const usedFallback = payload?.wan == null && fallbackWan != null
  // 兜底：个别数据源只给 amount（元）不给 wan，避免显示成 N/A。
  const amountYuan = wan == null && payload?.amount != null ? Number(payload.amount) : null
  const state = payload?.state || overview.value?.dataState?.sellIn
  const base = payload?.note || overview.value?.sellInSub || '当前周期没有可验证的 Sell-in 数据'
  return {
    value: wan != null ? fmtNum(wan) + ' 万' : amountYuan != null ? '¥ ' + fmtNum(amountYuan) : 'N/A',
    unit: wan != null || amountYuan != null ? 'CNY' : '',
    state,
    note: usedFallback ? '实时接口无数据，使用总览批次快照 · ' + base : (sectionErrors.value.sellIn || base),
    source: payload?.source || overview.value?.dataSource?.sellIn || '',
    asOf: payload?.as_of || overview.value?.dataAsOf || null,
    failed: Boolean(sectionErrors.value.sellIn),
  }
})

const sellOutCard = computed(() => {
  const payload = sellOut.value
  const usd = payload?.amount ?? overview.value?.sellOutUsd ?? null
  const usedFallback = payload?.amount == null && overview.value?.sellOutUsd != null
  const review = payload?.review_count ?? overview.value?.reportedRevenueReviewCount ?? 0
  const state = payload?.state || overview.value?.dataState?.sellOut
  const base = payload?.note || overview.value?.sellOutSub || '当前周期没有门店五件套回执'
  return {
    value: usd == null ? 'N/A' : '$ ' + fmtNum(usd),
    unit: usd == null ? '' : 'USD',
    state,
    review: Number(review || 0),
    note: usedFallback ? '终销接口无数据，使用总览门店上报汇总 · ' + base : (sectionErrors.value.sellOut || base),
    source: payload?.source || overview.value?.dataSource?.sellOut || '',
    asOf: payload?.as_of || null,
    failed: Boolean(sectionErrors.value.sellOut),
  }
})

const customerRows = computed(() => customers.value || [])
const customerTotal = computed(() =>
  customerRows.value.reduce((sum, row) => sum + Number(row.total || 0), 0),
)
const customerMax = computed(() =>
  Math.max(1, ...customerRows.value.map((row) => Number(row.total || 0))),
)
const customerGradeA = computed(() => {
  const row = customerRows.value.find((item) => item.level === 'A')
  return row ? Number(row.total || 0) : null
})

const taskCounts = computed<TaskCount[]>(() =>
  taskSummary.value?.length ? taskSummary.value : (taskPanel.value?.summary || []),
)
function taskCount(key: string): number | null {
  const row = taskCounts.value.find((item) => item.key === key)
  return row ? Number(row.value || 0) : null
}
const taskTotal = computed(() => taskCount('total'))
const taskDone = computed(() => taskCount('done'))
const taskRate = computed(() => {
  const total = taskTotal.value
  const done = taskDone.value
  if (total == null || done == null || total === 0) return null
  return Math.round((done / total) * 100)
})
const taskItems = computed(() => (taskPanel.value?.items || []).slice(0, 10))

const updatedAtText = computed(() => {
  const ms = overview.value?.dataUpdatedAt
  if (ms) return fmtDateTime(new Date(Number(ms)).toISOString())
  return overview.value?.dataAsOf ? fmtDateTime(overview.value.dataAsOf) : ''
})

// ── 经销商月度 Sell-in（保留原有能力） ────────────────────────────────
const dealerQuantity = computed(() =>
  (dealer.value?.dealers || []).reduce((sum, row) => sum + Number(row.quantity || 0), 0),
)
const monthOverMonth = computed<number | null>(() => {
  const rows = dealer.value?.trend || []
  if (rows.length < 2) return null
  const prior = rows[rows.length - 2]
  const current = rows[rows.length - 1]
  if (prior.wan == null || current.wan == null || prior.has_data === false || current.has_data === false) return null
  // 只有两端都是完整月末快照时才可比，避免用进行中的月份比完整月份。
  if (!prior.snapshot_date || !current.snapshot_date) return null
  const monthEnd = (value: string) => new Date(Number(value.slice(0, 4)), Number(value.slice(5, 7)), 0).getDate()
  if (Number(prior.snapshot_date.slice(8, 10)) !== monthEnd(prior.month)) return null
  if (Number(current.snapshot_date.slice(8, 10)) !== monthEnd(current.month)) return null
  const previous = Number(prior.wan)
  if (!previous) return null
  return ((Number(current.wan) - previous) / Math.abs(previous)) * 100
})
const dealerAmountWarning = computed(() => {
  const state = dealer.value?.amount_state
  if (state === 'suspect') return dealer.value?.amount_message || '当前快照金额存在疑点，暂不展示金额及排名；已记录销量仍保留。'
  if (state === 'stale') return dealer.value?.amount_message || '最新同步失败，当前展示上一次成功快照。'
  return ''
})
function sourceLabel(source?: string): string {
  return source === 'dealer_sales_db_latest_snapshot' ? 'Vertu 同步快照' : source || '—'
}
function asOfLabel(value?: string | null): string {
  return value ? '更新于 ' + fmtDateTime(value) : '更新时间未知'
}

// ── 数据加载：每个接口独立成败，互不拖垮 ─────────────────────────────
function clearSection(key: string) {
  delete sectionErrors.value[key]
}

function redirectLogin() {
  router.replace({ path: '/login', query: { next: '/dashboard' } })
}

function fail(key: string, err: unknown, fallback: string) {
  if (err instanceof HttpError && err.status === 401) {
    redirectLogin()
    return
  }
  sectionErrors.value[key] = errText(err, fallback)
}

function showToast(message: string) {
  toast.value = message
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 4000)
}

async function loadOverview(token = requestToken) {
  clearSection('overview')
  try {
    const result = await apiGet<OverviewPayload>(`/api/dashboard/overview?${qs()}`)
    if (token !== requestToken) return
    overview.value = result
  } catch (err) {
    if (token !== requestToken) return
    overview.value = null
    fail('overview', err, '总览数据加载失败，请重试')
  }
}

async function loadSellIn(token = requestToken) {
  clearSection('sellIn')
  try {
    const result = await apiGet<KpiPayload>(`/api/dashboard/sell-in?${qs()}`)
    if (token !== requestToken) return
    sellIn.value = result
  } catch (err) {
    if (token !== requestToken) return
    sellIn.value = null
    fail('sellIn', err, 'Sell-in 数据加载失败，请重试')
  }
}

async function loadSellOut(token = requestToken) {
  clearSection('sellOut')
  try {
    const result = await apiGet<KpiPayload>(`/api/dashboard/sell-out?${qs()}`)
    if (token !== requestToken) return
    sellOut.value = result
  } catch (err) {
    if (token !== requestToken) return
    sellOut.value = null
    fail('sellOut', err, 'Sell-out 数据加载失败，请重试')
  }
}

async function loadCustomers(token = requestToken) {
  clearSection('customers')
  try {
    const result = await apiGet<CustomerRow[]>('/api/customer-center/summary')
    if (token !== requestToken) return
    customers.value = Array.isArray(result) ? result : []
  } catch (err) {
    if (token !== requestToken) return
    customers.value = null
    fail('customers', err, '客户中心汇总加载失败，请重试')
  }
}

async function loadTaskSummary(token = requestToken) {
  clearSection('taskSummary')
  try {
    const result = await apiGet<TaskCount[]>(`/api/task-center/summary?date=${encodeURIComponent(dateText.value)}`)
    if (token !== requestToken) return
    taskSummary.value = Array.isArray(result) ? result : []
  } catch (err) {
    if (token !== requestToken) return
    taskSummary.value = null
    fail('taskSummary', err, '任务概览加载失败，请重试')
  }
}

async function loadTaskPanel(token = requestToken) {
  clearSection('taskPanel')
  try {
    const result = await apiGet<TaskPanel>(`/api/task-center/panel?date=${encodeURIComponent(dateText.value)}`)
    if (token !== requestToken) return
    taskPanel.value = result || { items: [], summary: [] }
  } catch (err) {
    if (token !== requestToken) return
    taskPanel.value = null
    fail('taskPanel', err, '任务面板加载失败，请重试')
  }
}

async function loadDealer() {
  const id = ++dealerToken
  dealerLoading.value = true
  clearSection('dealer')
  dealer.value = null
  chart?.dispose()
  chart = null
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(sellinMonth.value)) {
    sectionErrors.value.dealer = '请选择有效月份（格式 YYYY-MM）'
    dealerLoading.value = false
    return
  }
  try {
    const result = await apiGet<SellinSummary>(
      `/api/dealer/sellin-summary?month=${encodeURIComponent(sellinMonth.value)}`,
    )
    if (id !== dealerToken) return
    dealer.value = result
  } catch (err) {
    if (id !== dealerToken) return
    fail('dealer', err, '经销商 Sell-in 汇总加载失败，请重试')
  } finally {
    if (id === dealerToken) {
      dealerLoading.value = false
      await nextTick()
      if (id === dealerToken) renderChart()
    }
  }
}

const SECTION_RETRY: Record<string, () => void> = {
  overview: () => loadOverview(),
  sellIn: () => loadSellIn(),
  sellOut: () => loadSellOut(),
  customers: () => loadCustomers(),
  taskSummary: () => loadTaskSummary(),
  taskPanel: () => loadTaskPanel(),
  dealer: () => loadDealer(),
}

function retrySection(key: string) {
  const retry = SECTION_RETRY[key]
  if (retry) retry()
}

async function loadAll() {
  const token = ++requestToken
  loading.value = true
  sectionErrors.value = {}
  overview.value = null
  sellIn.value = null
  sellOut.value = null
  customers.value = null
  taskSummary.value = null
  taskPanel.value = null
  chart?.dispose()
  chart = null
  await Promise.all([
    loadOverview(token),
    loadSellIn(token),
    loadSellOut(token),
    loadCustomers(token),
    loadTaskSummary(token),
    loadTaskPanel(token),
    loadDealer(),
  ])
  if (token !== requestToken) return
  loading.value = false
  await nextTick()
  if (token === requestToken) renderChart()
}

async function syncData() {
  if (syncing.value || !canSync.value) return
  syncing.value = true
  try {
    const result = await apiPost<{ ok?: boolean; dataUpdatedAt?: number | null }>(
      `/api/dashboard/refresh?date=${encodeURIComponent(dateText.value)}`,
    )
    const stamp = result?.dataUpdatedAt
    showToast(stamp ? '数据同步完成 · ' + fmtDateTime(new Date(Number(stamp)).toISOString()) : '数据同步完成')
    await loadAll()
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      redirectLogin()
      return
    }
    showToast('同步失败：' + errText(err, '网络错误，请稍后重试'))
  } finally {
    syncing.value = false
  }
}

function setPeriod(next: Period) {
  if (period.value === next) return
  period.value = next
  loadAll()
}

function applyDate() {
  sellinMonth.value = dateText.value.slice(0, 7)
  loadAll()
}

/** 任务分区两个接口一起重试（概览 + 面板）。 */
function reloadTasks() {
  const token = requestToken
  loadTaskSummary(token)
  loadTaskPanel(token)
}

function barWidth(row: CustomerRow): string {
  const max = customerMax.value
  if (!max) return '0%'
  return Math.max(4, Math.round((Number(row.total || 0) / max) * 100)) + '%'
}

function previousMonth() {
  const [year, month] = sellinMonth.value.split('-').map(Number)
  if (!year || !month) return
  const target = new Date(year, month - 2, 1)
  sellinMonth.value = target.getFullYear() + '-' + String(target.getMonth() + 1).padStart(2, '0')
  loadDealer()
}

const periodLabel = computed(() => {
  const found = PERIODS.find((item) => item.value === period.value)
  return found ? found.label + '视图' : ''
})

/** 口径说明弹层内容：与后端实现保持一致，避免页面自造口径。 */
const GLOSSARY: Array<{ term: string; text: string }> = [
  {
    term: 'Sell-in（经销商进货）',
    text: '来自 /api/dashboard/sell-in。不受限账号走 vertu-cli sales 实时口径；受限账号仅支持月度，回退 dealer_sales 批次快照（万元 CNY）。',
  },
  {
    term: 'Sell-out（终端终销）',
    text: '来自 /api/dashboard/sell-out，门店五件套每日上报金额（USD）。超出复核阈值的记录不计入金额，单独以「待复核」条数展示。',
  },
  {
    term: '经销商月度汇总',
    text: '/api/dealer/sellin-summary，读取 dealer_sales 的每日月累计快照（非当日成交）。最新同步失败时展示上一次成功快照并标注「数据过期」。',
  },
  {
    term: '客户分层',
    text: '/api/customer-center/summary，customer_profiles 表按 ABCD 分级计数。触达数据源尚未接入，显示「触达未同步」而不是 0。',
  },
  {
    term: '任务完成率',
    text: '/api/task-center/summary 与 /api/task-center/panel，读 pdca_tasks 当日任务（无数据时回退 vertu 待办），并按账号权限过滤负责人。',
  },
  {
    term: '新鲜度状态',
    text: 'live 实时；stale 数据超过 36 小时或最新同步失败；suspect 金额待核验；partial 部分记录待复核；missing 无数据。',
  },
  {
    term: '数据更新时间',
    text: '/api/dashboard/overview 的 dataUpdatedAt，取自 dealer_sales.synced_at 同步时刻；无同步记录时回退数据时间或文件时间。',
  },
]

// ── ECharts：近 6 月 Sell-in 趋势（单一蓝、无渐变、无阴影） ────────────
function renderChart() {
  const rows = dealer.value?.trend || []
  if (!chartEl.value || !rows.length) {
    chart?.dispose()
    chart = null
    return
  }
  if (!chart) chart = echarts.init(chartEl.value)
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 54, right: 18, top: 28, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number | null) => (v == null ? 'N/A' : fmtNum(v) + ' 万'),
    },
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.month.slice(5) + '月'),
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.15)' } },
      axisLabel: { color: '#94a3b8' },
    },
    yAxis: {
      type: 'value',
      name: '万 CNY',
      nameTextStyle: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      axisLabel: { color: '#94a3b8' },
    },
    series: [
      {
        type: 'line',
        data: rows.map((row) => row.wan),
        smooth: false,
        connectNulls: false,
        symbolSize: 7,
        lineStyle: { color: '#4e9ef5', width: 2 },
        itemStyle: { color: '#4e9ef5' },
        areaStyle: { color: 'rgba(78,158,245,0.10)' },
      },
    ],
  })
}

function onResize() {
  chart?.resize()
}

// ── 弹层：数据口径说明（Esc / 遮罩关闭，打开时聚焦可交互元素） ─────────
function openGlossary() {
  glossaryOpen.value = true
  nextTick(() => glossaryCloseBtn.value?.focus())
}

function closeGlossary() {
  glossaryOpen.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && glossaryOpen.value) closeGlossary()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  window.addEventListener('keydown', onKeydown)
  loadAll()
  apiGet<Me>('/api/auth/me')
    .then((value) => { me.value = value })
    .catch((err: unknown) => {
      if (err instanceof HttpError && err.status === 401) redirectLogin()
    })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('keydown', onKeydown)
  if (toastTimer) window.clearTimeout(toastTimer)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <AppNav />
  <main class="page">
    <header class="page-head">
      <div>
        <h1>数据看板</h1>
        <p class="sub">
          进货 Sell-in 为 CNY 口径、终销 Sell-out 为门店五件套上报的 USD 口径；客户与任务按当前账号权限范围统计 ·
          {{ dateText }} · {{ periodLabel }}
        </p>
      </div>
      <div class="page-actions">
        <div class="field">
          <label class="field-label" for="dash-date">数据日期</label>
          <input id="dash-date" v-model="dateText" class="input date-input" type="date" @change="applyDate" />
        </div>
        <div class="field">
          <span id="dash-period-label" class="field-label">统计周期</span>
          <div class="segmented" role="group" aria-labelledby="dash-period-label">
            <button
              v-for="item in PERIODS"
              :key="item.value"
              type="button"
              :class="{ active: period === item.value }"
              :aria-pressed="period === item.value"
              @click="setPeriod(item.value)"
            >
              {{ item.label }}
            </button>
          </div>
        </div>
        <button class="btn" type="button" :disabled="loading" @click="loadAll()">
          {{ loading ? '加载中…' : '重新加载' }}
        </button>
        <button
          v-if="canSync"
          class="btn btn-primary"
          type="button"
          :disabled="syncing"
          @click="syncData"
        >
          {{ syncing ? '同步中…' : '刷新数据' }}
        </button>
        <button class="link-btn" type="button" @click="openGlossary">数据口径说明</button>
      </div>
    </header>

    <p v-if="toast" class="toast" role="status">{{ toast }}</p>

    <div v-if="pageFailed" class="card alert section" role="alert">
      <span>看板数据全部加载失败，可能是网络或服务异常（{{ loadedSections }}/{{ SECTION_KEYS.length }} 个接口成功）。</span>
      <button class="btn btn-sm" type="button" @click="loadAll()">重试</button>
    </div>

    <section v-if="loading" class="stats section" aria-busy="true" aria-label="正在加载核心指标">
      <div v-for="row in 6" :key="row" class="card skeleton-card">
        <span class="skeleton" style="width: 58%" />
        <span class="skeleton" style="width: 34%; height: 22px" />
        <span class="skeleton" style="width: 82%" />
      </div>
    </section>

    <section v-else-if="!pageFailed" class="stats section" aria-label="核心指标">
      <div class="card stat">
        <span class="stat-label">Sell-in（经销商进货）</span>
        <span class="stat-value num">
          {{ sellInCard.value }} <small v-if="sellInCard.unit">{{ sellInCard.unit }}</small>
        </span>
        <span class="stat-note">
          <span class="pill" :class="statePill(sellInCard.state)">{{ stateLabel(sellInCard.state) }}</span>
          {{ sellInCard.note }}
        </span>
      </div>
      <div class="card stat">
        <span class="stat-label">Sell-out（终端五件套上报）</span>
        <span class="stat-value num">
          {{ sellOutCard.value }} <small v-if="sellOutCard.unit">{{ sellOutCard.unit }}</small>
        </span>
        <span class="stat-note">
          <span class="pill" :class="statePill(sellOutCard.state)">{{ stateLabel(sellOutCard.state) }}</span>
          {{ sellOutCard.note }}
          <template v-if="sellOutCard.review">· {{ sellOutCard.review }} 条金额待复核未计入</template>
        </span>
      </div>
      <div class="card stat">
        <span class="stat-label">客户总数（已建档）</span>
        <span class="stat-value num">{{ customers === null ? 'N/A' : customerTotal }} <small v-if="customers !== null">家</small></span>
        <span class="stat-note">
          <template v-if="sectionErrors.customers">{{ sectionErrors.customers }}</template>
          <template v-else-if="customerRows.length">
            A 类 {{ customerGradeA ?? 0 }} 家 · 共 {{ customerRows.length }} 个等级
          </template>
          <template v-else>客户档案尚未同步，暂无分层数据</template>
        </span>
      </div>
      <div class="card stat">
        <span class="stat-label">任务完成率</span>
        <span class="stat-value num">{{ taskRate === null ? 'N/A' : taskRate + '%' }}</span>
        <span class="stat-note">
          <template v-if="sectionErrors.taskSummary && sectionErrors.taskPanel">{{ sectionErrors.taskSummary }}</template>
          <template v-else-if="taskTotal !== null">已完成 {{ taskDone ?? 0 }} / 共 {{ taskTotal }} 项（{{ dateText }}）</template>
          <template v-else>当天没有任务记录</template>
        </span>
      </div>
      <div class="card stat">
        <span class="stat-label">门店进店客流</span>
        <span class="stat-value num">
          {{ overview?.realWalkinTotal ?? 'N/A' }} <small v-if="overview?.realWalkinTotal != null">人次</small>
        </span>
        <span class="stat-note">
          <template v-if="sectionErrors.overview">{{ sectionErrors.overview }}</template>
          <template v-else>{{ overview?.realWalkinStores ?? 0 }} 家门店有回执 · 来自总览接口</template>
        </span>
      </div>
      <div class="card stat">
        <span class="stat-label">数据更新时间</span>
        <span class="stat-value small">{{ updatedAtText || 'N/A' }}</span>
        <span class="stat-note">
          <template v-if="sectionErrors.overview">{{ sectionErrors.overview }}</template>
          <template v-else>取自 dealer_sales 同步时刻（{{ overview?.dataSource?.sellIn || '未同步' }}）</template>
        </span>
      </div>
      <div class="card stat">
        <span class="stat-label">{{ sellinMonth }} 经销商销量</span>
        <span class="stat-value num">
          {{ dealer === null ? 'N/A' : dealerQuantity }} <small v-if="dealer !== null">台</small>
        </span>
        <span class="stat-note">
          <template v-if="sectionErrors.dealer">{{ sectionErrors.dealer }}</template>
          <template v-else-if="dealer?.has_data">{{ dealer.dealers.length }} 家经销商的月度快照合计</template>
          <template v-else>该月暂无快照，可在下方分区切换月份</template>
        </span>
      </div>
    </section>

    <section class="card panel section">
      <header class="section-head">
        <div>
          <h2>Sell-in / Sell-out 对比</h2>
          <p>进货按 CNY 计、终销按门店五件套上报的 USD 计，两者不做汇率换算，仅并列查看。</p>
        </div>
        <span class="pill pill-blue">{{ periodLabel }}</span>
      </header>
      <div class="compare-grid">
        <article class="compare-card">
          <header class="compare-head">
            <span class="compare-title">Sell-in 进货额</span>
            <span class="pill" :class="statePill(sellInCard.state)">{{ stateLabel(sellInCard.state) }}</span>
          </header>
          <p v-if="sectionErrors.sellIn" class="alert-inline" role="alert">
            {{ sectionErrors.sellIn }}
            <button class="btn btn-sm" type="button" @click="retrySection('sellIn')">重试</button>
          </p>
          <p class="compare-value num">
            {{ sellInCard.value }} <small v-if="sellInCard.unit">{{ sellInCard.unit }}</small>
          </p>
          <p class="compare-note">{{ sellInCard.note }}</p>
          <p class="compare-meta">
            {{ sellInCard.source || '数据源未标注' }} ·
            {{ sellInCard.asOf ? fmtDateTime(sellInCard.asOf) : '无同步时间' }}
          </p>
        </article>
        <article class="compare-card">
          <header class="compare-head">
            <span class="compare-title">Sell-out 终销</span>
            <span class="pill" :class="statePill(sellOutCard.state)">{{ stateLabel(sellOutCard.state) }}</span>
          </header>
          <p v-if="sectionErrors.sellOut" class="alert-inline" role="alert">
            {{ sectionErrors.sellOut }}
            <button class="btn btn-sm" type="button" @click="retrySection('sellOut')">重试</button>
          </p>
          <p class="compare-value num">
            {{ sellOutCard.value }} <small v-if="sellOutCard.unit">{{ sellOutCard.unit }}</small>
          </p>
          <p class="compare-note">{{ sellOutCard.note }}</p>
          <p class="compare-meta">
            {{ sellOutCard.source || '数据源未标注' }} ·
            {{ sellOutCard.asOf ? fmtDateTime(sellOutCard.asOf) : '无同步时间' }}
            <template v-if="sellOutCard.review">· {{ sellOutCard.review }} 条金额待复核</template>
          </p>
        </article>
      </div>
    </section>

    <section class="card panel section">
      <header class="section-head">
        <div>
          <h2>经销商 Sell-in 月度汇总</h2>
          <p>数据来自 Vertu 同步的每日月累计快照；只有完整月末快照之间才做环比。</p>
        </div>
        <div class="section-tools">
          <span v-if="dealer?.has_data" class="pill pill-blue num">{{ dealer.dealers.length }} 家</span>
          <div class="field">
            <label class="field-label" for="dealer-month">统计月份</label>
            <input id="dealer-month" v-model="sellinMonth" class="input month-input" type="month" @change="loadDealer" />
          </div>
        </div>
      </header>

      <div v-if="dealerLoading" aria-busy="true" aria-label="正在加载经销商月度汇总">
        <div class="mini-grid">
          <div v-for="row in 4" :key="row" class="mini skeleton-card">
            <span class="skeleton" style="width: 55%" />
            <span class="skeleton" style="width: 40%; height: 20px" />
          </div>
        </div>
        <div class="chart-block skeleton-block">
          <span class="skeleton" style="width: 30%" />
          <span class="skeleton" style="width: 100%; height: 200px" />
        </div>
      </div>

      <div v-else-if="sectionErrors.dealer" class="alert" role="alert">
        <span>{{ sectionErrors.dealer }}</span>
        <button class="btn btn-sm" type="button" @click="retrySection('dealer')">重试</button>
      </div>

      <div v-else-if="dealer && !dealer.has_data" class="empty-state">
        <h2>{{ sellinMonth }} 没有经销商 Sell-in 快照</h2>
        <p>该月尚未同步到 dealer_sales 快照，或当前账号权限范围内没有经销商数据。</p>
        <div class="empty-actions">
          <button class="btn" type="button" @click="previousMonth">查看上月</button>
          <router-link v-if="canSync" class="btn btn-primary" to="/admin/sync">前往数据同步</router-link>
          <router-link v-else class="btn btn-primary" to="/walkin">查看门店五件套</router-link>
        </div>
      </div>

      <template v-else-if="dealer">
        <p v-if="dealerAmountWarning" class="hint-warn" role="status">{{ dealerAmountWarning }}</p>
        <div class="mini-grid">
          <div class="mini">
            <span class="mini-label">当月 Sell-in 合计</span>
            <b class="num">{{ dealer.total_wan == null ? 'N/A' : fmtNum(dealer.total_wan) + ' 万' }}</b>
            <span class="mini-sub">{{ sourceLabel(dealer.source) }} · {{ asOfLabel(dealer.as_of) }}</span>
          </div>
          <div class="mini">
            <span class="mini-label">当月台数</span>
            <b class="num">{{ dealerQuantity }} 台</b>
            <span class="mini-sub">与金额使用同一批次快照</span>
          </div>
          <div class="mini">
            <span class="mini-label">较上月</span>
            <b class="num">
              {{ monthOverMonth == null ? 'N/A' : (monthOverMonth >= 0 ? '+' : '') + monthOverMonth.toFixed(1) + '%' }}
            </b>
            <span class="mini-sub">相邻两月均有月末快照时可比</span>
          </div>
          <div class="mini">
            <span class="mini-label">最新快照日期</span>
            <b class="num">{{ dealer.snapshot_date || 'N/A' }}</b>
            <span class="mini-sub">每日月累计快照，非当日成交</span>
          </div>
        </div>

        <div class="chart-block">
          <h3 class="chart-title">近 6 月 Sell-in 趋势（万 CNY）</h3>
          <div
            v-if="dealer.trend.length"
            ref="chartEl"
            class="chart"
            role="img"
            aria-label="近 6 个月经销商 Sell-in 趋势折线图"
          ></div>
          <p v-else class="hint">没有可绘制的趋势数据</p>
        </div>

        <div v-if="dealer.dealers.length" class="table-wrap">
          <table class="data-table">
            <caption class="sr-only">经销商月度 Sell-in 排行</caption>
            <thead>
              <tr>
                <th scope="col" class="hide-sm">排名</th>
                <th scope="col">订单客户（可能脱敏）</th>
                <th scope="col" class="num">台数</th>
                <th scope="col" class="num">金额（万）</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in dealer.dealers" :key="row.name + '-' + (row.rank ?? 'x')">
                <td class="hide-sm num">{{ row.rank ?? 'N/A' }}</td>
                <td>{{ row.name }}</td>
                <td class="num">{{ row.quantity }}</td>
                <td class="num">{{ row.wan == null ? 'N/A' : fmtNum(row.wan) }}</td>
              </tr>
            </tbody>
          </table>
          <footer class="table-foot">
            <span>共 {{ dealer.dealers.length }} 个订单客户名称，脱敏或未知名称不推断真实客户</span>
            <span>金额单位：万元 CNY</span>
          </footer>
        </div>
        <p v-else class="hint">该月快照没有可展示的经销商明细。</p>
      </template>
    </section>

    <section class="card panel section">
      <header class="section-head">
        <div>
          <h2>客户中心汇总</h2>
          <p>按 A/B/C/D 分层统计已建档客户；触达数据源尚未接入，显示“触达未同步”而不是 0。</p>
        </div>
        <span v-if="customerRows.length" class="pill pill-blue num">{{ customerTotal }} 家</span>
      </header>

      <div v-if="loading" class="skeleton-card" aria-busy="true" aria-label="正在加载客户中心汇总">
        <span class="skeleton" style="width: 40%" />
        <span class="skeleton" style="width: 100%; height: 14px" />
        <span class="skeleton" style="width: 100%; height: 14px" />
      </div>

      <div v-else-if="sectionErrors.customers" class="alert" role="alert">
        <span>{{ sectionErrors.customers }}</span>
        <button class="btn btn-sm" type="button" @click="retrySection('customers')">重试</button>
      </div>

      <div v-else-if="!customerRows.length" class="empty-state">
        <h2>尚未同步到客户档案</h2>
        <p>客户分层来自 customer_profiles 表，当前范围内没有记录，无法展示分层结构。</p>
        <div class="empty-actions">
          <button class="btn" type="button" @click="retrySection('customers')">重新加载</button>
          <router-link v-if="canSync" class="btn btn-primary" to="/admin/sync">前往数据同步</router-link>
          <router-link v-else class="btn btn-primary" to="/signalseller">前往获客指挥</router-link>
        </div>
      </div>

      <ul v-else class="bars">
        <li v-for="row in customerRows" :key="row.level" class="bar-row">
          <span class="bar-label">{{ row.level }} 类</span>
          <span class="bar-track">
            <span class="bar-fill" :style="{ width: barWidth(row) }"></span>
          </span>
          <span class="bar-value num">{{ row.total }}</span>
          <span class="bar-sub">
            {{ row.touched == null ? '触达未同步' : '已触达 ' + row.touched }}
            <template v-if="row.target > 0">· 目标 {{ row.target }}</template>
          </span>
        </li>
      </ul>
    </section>

    <section class="card panel section">
      <header class="section-head">
        <div>
          <h2>任务中心面板</h2>
          <p>{{ taskPanel?.scope_message || '当日 PDCA 任务完成情况，按当前账号权限范围统计。' }}</p>
        </div>
        <div class="section-tools">
          <span v-if="taskTotal !== null" class="pill pill-blue num">{{ taskDone ?? 0 }} / {{ taskTotal }}</span>
          <button class="btn btn-sm" type="button" :disabled="loading" @click="reloadTasks">刷新</button>
        </div>
      </header>

      <div v-if="loading" class="skeleton-card" aria-busy="true" aria-label="正在加载任务面板">
        <span class="skeleton" style="width: 36%" />
        <span class="skeleton" style="width: 88%" />
        <span class="skeleton" style="width: 74%" />
      </div>

      <div v-else-if="sectionErrors.taskSummary && sectionErrors.taskPanel" class="alert" role="alert">
        <span>{{ sectionErrors.taskSummary }}</span>
        <button class="btn btn-sm" type="button" @click="reloadTasks">重试</button>
      </div>

      <template v-else>
        <p v-if="sectionErrors.taskPanel" class="hint-warn">
          任务面板加载失败：{{ sectionErrors.taskPanel }}（下方汇总数字来自任务概览接口，仍然可用）
        </p>
        <p v-if="sectionErrors.taskSummary" class="hint-warn">
          任务概览加载失败：{{ sectionErrors.taskSummary }}（下方列表来自任务面板接口，仍然可用）
        </p>
        <div class="mini-grid">
          <div class="mini">
            <span class="mini-label">总任务数</span>
            <b class="num">{{ taskTotal ?? 'N/A' }}</b>
            <span class="mini-sub">{{ dateText }}</span>
          </div>
          <div class="mini">
            <span class="mini-label">已完成</span>
            <b class="num">{{ taskDone ?? 'N/A' }}</b>
            <span class="mini-sub">状态 done / completed</span>
          </div>
          <div class="mini">
            <span class="mini-label">未完成</span>
            <b class="num">{{ taskCount('undone') ?? 'N/A' }}</b>
            <span class="mini-sub">仍需跟进的条目</span>
          </div>
          <div class="mini">
            <span class="mini-label">完成率</span>
            <b class="num">{{ taskRate === null ? 'N/A' : taskRate + '%' }}</b>
            <span class="mini-sub">已完成 ÷ 总任务数</span>
          </div>
        </div>

        <ul v-if="taskItems.length" class="task-list">
          <li v-for="(item, index) in taskItems" :key="(item.title || 'task') + '-' + index" class="task-row">
            <span class="pill" :class="isDone(item.status) ? 'pill-green' : 'pill-muted'">
              {{ isDone(item.status) ? '已完成' : '未完成' }}
            </span>
            <span class="task-title">{{ item.title || '（无标题）' }}</span>
            <span class="task-owner">{{ item.owner || item.owner_key || '未指派' }}</span>
            <span class="pill" :class="priorityPill(item.priority)">{{ priorityLabel(item.priority) }}</span>
          </li>
        </ul>

        <div v-else-if="!sectionErrors.taskPanel" class="empty-state">
          <h2>{{ dateText }} 没有任务记录</h2>
          <p>任务来自 pdca_tasks 表（当日）或 vertu 待办回退源，当前范围内没有条目。</p>
          <div class="empty-actions">
            <router-link class="btn btn-primary" to="/tasks">去任务中心新建任务</router-link>
          </div>
        </div>

        <p v-else class="hint">任务列表不可用（面板接口失败），汇总数字仍来自任务概览接口。</p>

        <footer v-if="taskPanel?.items?.length" class="table-foot">
          <span>显示前 {{ taskItems.length }} / {{ taskPanel.items.length }} 条任务</span>
          <span>{{ taskPanel.source || 'task_center' }}</span>
        </footer>
      </template>
    </section>

    <div v-if="glossaryOpen" class="overlay" @click.self="closeGlossary">
      <section class="card modal" role="dialog" aria-modal="true" aria-labelledby="glossary-title">
        <header class="modal-head">
          <div>
            <h2 id="glossary-title">数据口径说明</h2>
            <p>每个指标都标注来源与新鲜度；没有可验证数据时显示 N/A，不用估算值补齐。</p>
            <p v-if="overview?.managerRole" class="hint">
              当前视图：{{ overview.managerName }} · {{ overview.managerRole }}
            </p>
          </div>
          <button
            ref="glossaryCloseBtn"
            class="btn btn-sm"
            type="button"
            aria-label="关闭数据口径说明"
            @click="closeGlossary"
          >
            关闭
          </button>
        </header>
        <dl class="glossary">
          <div v-for="item in GLOSSARY" :key="item.term" class="glossary-row">
            <dt>{{ item.term }}</dt>
            <dd>{{ item.text }}</dd>
          </div>
        </dl>
        <div class="modal-foot">
          <button class="btn btn-primary" type="button" @click="closeGlossary">知道了</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.date-input,
.month-input { width: auto; }

.stat-value.small { font-size: 15px; font-weight: 600; }
.stat-value small { font-size: 13px; font-weight: 500; color: var(--muted); }
.stat-note .pill { margin-right: 4px; }

.section-tools { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.empty-actions { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }

.alert-inline { display: flex; align-items: center; justify-content: space-between; gap: 10px; }

/* ── Sell-in / Sell-out 对比 ───────────────────────────────────────── */
.compare-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.compare-card {
  display: grid; gap: 8px; align-content: start;
  padding: 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card-2);
}
.compare-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.compare-title { font-size: 13px; color: var(--text); }
.compare-value { margin: 0; font-size: 26px; font-weight: 600; line-height: 1.15; }
.compare-value small { font-size: 13px; font-weight: 500; color: var(--muted); }
.compare-note { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
.compare-meta { margin: 0; color: var(--muted); font-size: 11px; }

/* ── 分区内的迷你指标 ──────────────────────────────────────────────── */
.mini-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-bottom: 14px; }
.mini {
  display: grid; gap: 6px; align-content: start;
  padding: 14px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card-2);
}
.mini-label { font-size: 12px; color: var(--muted); }
.mini b { font-size: 22px; font-weight: 600; }
.mini-sub { font-size: 11px; color: var(--muted); }

.chart-block { margin-bottom: 14px; }
.chart-title { margin: 0 0 8px; font-size: 13px; font-weight: 600; color: var(--muted); }
.chart { width: 100%; height: 260px; }
.skeleton-block { display: grid; gap: 10px; }

/* ── 客户分层条形 ─────────────────────────────────────────────────── */
.bars { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
.bar-row { display: grid; grid-template-columns: 52px minmax(80px, 1fr) 56px auto; align-items: center; gap: 12px; }
.bar-label { font-size: 13px; color: var(--text); }
.bar-track { height: 10px; border-radius: 999px; background: rgba(255, 255, 255, 0.06); overflow: hidden; }
.bar-fill { display: block; height: 100%; border-radius: 999px; background: var(--blue); }
.bar-value { text-align: right; font-weight: 600; }
.bar-sub { font-size: 12px; color: var(--muted); }

/* ── 任务列表 ─────────────────────────────────────────────────────── */
.task-list { list-style: none; margin: 0 0 12px; padding: 0; display: grid; gap: 8px; }
.task-row {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card-2);
}
.task-title { flex: 1 1 220px; min-width: 0; font-size: 13px; }
.task-owner { font-size: 12px; color: var(--muted); }

/* ── 表格数字列右对齐 ─────────────────────────────────────────────── */
.data-table .num { text-align: right; }

/* ── 口径说明弹层 ─────────────────────────────────────────────────── */
.glossary { margin: 0; display: grid; gap: 12px; }
.glossary-row { display: grid; gap: 3px; }
.glossary dt { font-size: 13px; font-weight: 600; }
.glossary dd { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.55; }

@media (max-width: 640px) {
  .bar-row { grid-template-columns: 44px minmax(60px, 1fr) 48px; }
  .bar-sub { grid-column: 2 / -1; }
  .chart { height: 220px; }
}
</style>
