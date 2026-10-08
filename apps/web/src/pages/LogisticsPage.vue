<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'
import { useEscapeClose } from '@/composables/use-escape-close'

interface Summary {
  source_state?: string
  total: number
  delivered: number
  in_transit: number
  abnormal: number
  pending: number
  open: number
  delivery_rate_pct: number
  attention_items: { tracking_number: string; customer: string; judgement: string; reason: string }[]
}

interface Shipment {
  data_source?: string
  tracking_number: string
  carrier: string
  customer: string
  salesperson: string
  ship_date: string
  current_status: string
  expected_status?: string
  judgement: string
  reason: string
  progress_pct: number
  tracking_url: string
  is_delivered: boolean
  days_in_transit: number | null
  status_source?: string
  note?: string
}

interface Me {
  role: string
}

type Board = 'dealer' | 'freight'

interface FreightSummary {
  total: number
  in_transit: number
  exception: number
  review: number
  delivered: number
  labeled: number
}

interface FreightItem {
  order_no: string
  sf_tracking_no: string
  tracking_no: string
  carrier: string
  salesperson: string
  consignee: string
  country: string
  status: string
  lifecycle: string
  exception: string
  match_level: string
  match_evidence: string
  last_event: string
  needs_review: boolean
}

const router = useRouter()
const me = ref<Me | null>(null)
const board = ref<Board>('dealer')
const dates = ref<string[]>([])
const date = ref('all')
const status = ref('all')
const q = ref('')

const summary = ref<Summary | null>(null)
const shipments = ref<Shipment[]>([])
const activeShipment = ref<Shipment | null>(null)
const loading = ref(true)
const error = ref('')
let loadId = 0
let freightLoadId = 0

const trackQuery = ref({ carrier: 'UPS', tracking_number: '' })
const trackBusy = ref(false)
const trackResult = ref<{ text?: string; status_text?: string; error?: string } | null>(null)

const showEntry = ref(false)
const entryBusy = ref(false)
const entryError = ref('')
const entrySuccess = ref('')
const entryForm = ref({
  tracking_number: '',
  carrier: 'UPS',
  customer: '',
  ship_date: todayText(),
  current_status: '',
  expected_status: '',
  note: '',
})

function todayText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

async function submitEntry() {
  entryBusy.value = true
  entryError.value = ''
  entrySuccess.value = ''
  try {
    await apiPost('/api/logistics/shipments', entryForm.value)
    entrySuccess.value = '✅ 已保存，看板即时可见'
    showEntry.value = false
    entryForm.value = {
      tracking_number: '',
      carrier: 'UPS',
      customer: '',
      ship_date: todayText(),
      current_status: '',
      expected_status: '',
      note: '',
    }
    await load()
  } catch (err) {
    entryError.value = err instanceof HttpError ? err.detail : '保存失败，请稍后重试'
  } finally {
    entryBusy.value = false
  }
}

const STATUS_TABS = [
  { value: 'all', label: '全部' },
  { value: 'attention', label: '异常/待关注' },
  { value: 'transit', label: '运输中' },
  { value: 'delivered', label: '已签收' },
]

const CARRIERS = ['UPS', 'FedEx', 'DHL', 'SF']
const FREIGHT_TABS = [
  { value: 'all', label: '全部' },
  { value: 'review', label: '待复核' },
  { value: 'exception', label: '异常' },
]

const freightView = ref('all')
const freightQ = ref('')
const freightSummary = ref<FreightSummary | null>(null)
const freightItems = ref<FreightItem[]>([])
const freightAvailable = ref(true)
const freightBusy = ref(false)
const freightError = ref('')
const freightMsg = ref('')
const activeFreight = ref<FreightItem | null>(null)
const confirmSf = ref('')
const confirmReason = ref('')
const confirmBusy = ref(false)
const showOperations = ref(false)

/**
 * 当前账号能否复核跨境货代。
 * @returns {boolean}
 */
function canReviewFreight(): boolean {
  return !!me.value && ['sales', 'manager', 'admin'].includes(me.value.role)
}

function canOpenOperations(): boolean {
  return !!me.value && ['manager', 'admin'].includes(me.value.role)
}

/**
 * 打开某票的复核输入。
 * @param {FreightItem} item
 */
function startConfirm(item: FreightItem) {
  confirmSf.value = item.sf_tracking_no
  confirmReason.value = ''
}

/**
 * 提交 C 级/待人工确认。
 * @param {FreightItem} item
 */
async function submitConfirm(item: FreightItem) {
  const reason = confirmReason.value.trim()
  if (reason.length < 2) {
    freightError.value = '确认原因至少 2 个字'
    return
  }
  confirmBusy.value = true
  freightError.value = ''
  freightMsg.value = ''
  try {
    await apiPost('/api/logistics/freight/confirm', {
      sf_tracking_no: item.sf_tracking_no,
      reason,
    })
    freightMsg.value = `已确认 ${item.sf_tracking_no}`
    confirmSf.value = ''
    confirmReason.value = ''
    activeFreight.value = null
    await loadFreight()
  } catch (err) {
    freightError.value = err instanceof HttpError ? err.detail : '复核失败'
  } finally {
    confirmBusy.value = false
  }
}

function params() {
  const p = new URLSearchParams()
  if (date.value !== 'all') p.set('date', date.value)
  if (status.value !== 'all') p.set('status', status.value)
  if (q.value.trim()) p.set('q', q.value.trim())
  return p.toString()
}

async function load() {
  const id = ++loadId
  loading.value = true
  error.value = ''
  summary.value = null
  shipments.value = []
  const qs = params()
  const settle = await Promise.allSettled([
    apiGet<Summary>(`/api/logistics/summary?${qs}`),
    apiGet<{ items: Shipment[] }>(`/api/logistics/shipments?${qs}`),
  ])
  if (id !== loadId) return
  const [summaryR, shipmentsR] = settle
  for (const r of settle) {
    if (
      r.status === 'rejected' &&
      r.reason instanceof HttpError &&
      r.reason.status === 401
    ) {
      router.replace({ path: '/login', query: { next: '/logistics' } })
      return
    }
  }
  if (summaryR.status === 'fulfilled') summary.value = summaryR.value
  if (shipmentsR.status === 'fulfilled') shipments.value = shipmentsR.value.items
  const rejected = settle.find((result): result is PromiseRejectedResult => result.status === 'rejected')
  if (rejected) {
    error.value = rejected.reason instanceof HttpError ? rejected.reason.detail : '物流数据加载失败，请重试'
  }
  loading.value = false
}

async function loadDates() {
  try {
    const payload = await apiGet<{ items: string[] }>('/api/logistics/dates')
    dates.value = payload.items || []
  } catch {
    dates.value = []
  }
}

async function singleTrack() {
  if (trackBusy.value || !trackQuery.value.tracking_number.trim()) return
  trackBusy.value = true
  trackResult.value = null
  try {
    const payload = await apiGet<{ text?: string; status_text?: string; error?: string }>(
      `/api/logistics/track?carrier=${encodeURIComponent(trackQuery.value.carrier)}&tracking_number=${encodeURIComponent(trackQuery.value.tracking_number.trim())}`,
    )
    trackResult.value = payload
  } catch (err) {
    trackResult.value = {
      error: err instanceof HttpError ? err.detail : '查询失败，请稍后重试',
    }
  } finally {
    trackBusy.value = false
  }
}

function matchPill(level: string): string {
  if (level === 'A') return 'pill-green'
  if (level === 'B') return 'pill-amber'
  if (level === 'C') return 'pill-red'
  return 'pill-muted'
}

function closeFreightDrawer() {
  activeFreight.value = null
  confirmSf.value = ''
  confirmReason.value = ''
}

function statusLabel(value: string): string {
  return STATUS_TABS.find((tab) => tab.value === value)?.label || value
}

function judgeStatus(judgement: string): string {
  if (judgement === '异常') return 'danger'
  if (judgement === '正常') return 'ok'
  if (judgement === '运输中') return 'info'
  return 'warn'
}

function barClass(judgement: string): string {
  if (judgement === '异常') return 'bar-bad'
  if (judgement === '正常') return 'bar-ok'
  if (judgement === '运输中') return 'bar-transit'
  return 'bar-warn'
}

useEscapeClose(() => {
  if (activeShipment.value) activeShipment.value = null
  else if (activeFreight.value) closeFreightDrawer()
  else if (showEntry.value) showEntry.value = false
})

onMounted(() => {
  load()
  loadDates()
  apiGet<Me>('/api/auth/me')
    .then((value) => (me.value = value))
    .catch(() => undefined)
})

async function loadFreight() {
  const id = ++freightLoadId
  freightBusy.value = true
  freightError.value = ''
  const p = new URLSearchParams()
  if (freightView.value !== 'all') p.set('view', freightView.value)
  if (freightQ.value.trim()) p.set('q', freightQ.value.trim())
  try {
    const payload = await apiGet<{
      available: boolean
      summary: FreightSummary
      items: FreightItem[]
    }>(`/api/logistics/freight?${p.toString()}`)
    if (id !== freightLoadId) return
    freightAvailable.value = payload.available
    freightSummary.value = payload.summary
    freightItems.value = payload.items
  } catch (err) {
    if (id !== freightLoadId) return
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/logistics' } })
      return
    }
    freightError.value = err instanceof HttpError ? err.detail : '货代台账加载失败'
  } finally {
    if (id === freightLoadId) freightBusy.value = false
  }
}

function sourceMessage(state?: string): string {
  const labels: Record<string, string> = {
    mixed: '部分运单来自历史记录，请结合每票来源核对。',
    historical: '当前仅有历史运单，不能据此判断实时物流情况。',
    degraded: '物流数据库暂不可用，以下仅为历史记录，实时统计为 N/A。',
    missing: '物流数据源暂不可用，统计为 N/A。',
  }
  return labels[state || ''] || ''
}

function summaryValue(value: number | undefined): string | number {
  return ['historical', 'degraded', 'missing'].includes(summary.value?.source_state || '') ? 'N/A' : value ?? 'N/A'
}

watch([date, status, q], () => {
  if (board.value === 'dealer') load()
})
watch([freightView, freightQ], () => {
  if (board.value === 'freight') loadFreight()
})
watch(board, (next) => {
  if (next === 'freight') loadFreight()
})
watch(me, (value) => {
  if (value?.role === 'dealer' && board.value === 'freight') board.value = 'dealer'
})
</script>

<template>
  <AppNav />
  <main class="page">
    <header class="page-head">
      <div>
        <h1>物流中心</h1>
        <p class="sub">{{ board === 'freight' ? '日升货代预报 · 面单匹配 · 异常复核' : '经销商运单进度 · 异常核查 · 实时追踪' }}</p>
      </div>
      <div class="head-actions">
        <button
          v-if="board === 'dealer' && me && (me.role === 'sales' || me.role === 'manager' || me.role === 'admin')"
          class="btn btn-primary"
          type="button"
          @click="showEntry = true"
        >
          录入物流单号
        </button>
        <button
          v-if="canOpenOperations()"
          class="btn"
          type="button"
          @click="showOperations = !showOperations"
        >
          {{ showOperations ? '收起运营后台' : '打开运营后台' }}
        </button>
      </div>
    </header>

    <div class="tabs board-tabs">
      <button type="button" :class="['tab', { active: board === 'dealer' }]" @click="board = 'dealer'">经销商运单</button>
      <button
        v-if="me && me.role !== 'dealer'"
        type="button"
        :class="['tab', { active: board === 'freight' }]"
        @click="board = 'freight'"
      >
        跨境货代
      </button>
    </div>

    <section v-if="showOperations" class="card operations-panel">
      <div class="operations-head">
        <div>
          <h2>物流运营后台</h2>
          <p class="sub">订单、异常待办、通知、运营日报和权限管理</p>
        </div>
        <div class="operations-actions">
          <a class="btn" href="/logistics-admin/orders" target="_blank" rel="noopener">新窗口打开</a>
          <button class="btn" type="button" @click="showOperations = false">收起</button>
        </div>
      </div>
      <iframe
        class="operations-frame"
        src="/logistics-admin/orders"
        title="物流运营后台"
        loading="lazy"
      ></iframe>
    </section>

    <p v-if="entrySuccess" class="entry-msg ok">{{ entrySuccess }}</p>

    <template v-if="board === 'dealer'">
    <section class="filterbar" aria-label="运单筛选">
      <label class="sr-only" for="log-batch">批次</label>
      <select id="log-batch" v-model="date" class="input select">
        <option value="all">全部批次</option>
        <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
      </select>
      <button
        v-for="tab in STATUS_TABS"
        :key="tab.value"
        type="button"
        class="chip-filter"
        :class="{ on: status === tab.value }"
        @click="status = tab.value"
      >
        {{ tab.label }}
      </button>
      <button
        v-if="status !== 'all' || date !== 'all' || q"
        type="button"
        class="chip-filter"
        @click="status = 'all'; date = 'all'; q = ''"
      >
        清除筛选
      </button>
      <span class="spacer" />
      <input
        v-model="q"
        class="input filter-search"
        type="search"
        placeholder="搜索运单号/客户/销售/状态…"
        aria-label="搜索运单"
      />
    </section>

    <div v-if="loading" class="card state">正在读取物流数据…</div>
    <div v-else-if="error" class="card state error">{{ error }}</div>

    <template v-else>
      <p v-if="sourceMessage(summary?.source_state)" class="entry-msg" role="status">{{ sourceMessage(summary?.source_state) }}</p>
      <section v-if="summary" class="stats">
        <div class="card stat">
          <span class="k">总运单</span>
          <span class="v">{{ summaryValue(summary.total) }}</span>
        </div>
        <div class="card stat">
          <span class="k">运输中</span>
          <span class="v">{{ summaryValue(summary.in_transit) }}</span>
        </div>
        <div class="card stat">
          <span class="k">异常/待关注</span>
          <span class="v warn">{{ summaryValue(summary.abnormal) }}</span>
        </div>
        <div class="card stat">
          <span class="k">待核查</span>
          <span class="v warn">{{ summaryValue(summary.pending) }}</span>
        </div>
        <div class="card stat">
          <span class="k">已签收</span>
          <span class="v ok">{{ summaryValue(summary.delivered) }}</span>
        </div>
        <div class="card stat">
          <span class="k">签收率</span>
          <span class="v">{{ summaryValue(summary.delivery_rate_pct) }}{{ summaryValue(summary.delivery_rate_pct) === 'N/A' ? '' : '%' }}</span>
        </div>
      </section>

      <section v-if="shipments.length" class="table-shell">
        <div class="table-scroll">
          <table class="grid">
            <thead>
              <tr>
                <th>运单号</th>
                <th>承运商</th>
                <th>客户</th>
                <th>销售</th>
                <th>发货日期</th>
                <th class="num">在途</th>
                <th>当前状态</th>
                <th>判定</th>
                <th><span class="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ship in shipments" :key="ship.tracking_number">
                <td class="mono">
                  {{ ship.tracking_number }}
                  <span v-if="ship.data_source === 'csv_history'" class="chip">历史记录</span>
                </td>
                <td>{{ ship.carrier || '—' }}</td>
                <td>{{ ship.customer || '—' }}</td>
                <td>{{ ship.salesperson || '—' }}</td>
                <td class="num">{{ ship.ship_date || '—' }}</td>
                <td class="num">{{ ship.days_in_transit != null ? ship.days_in_transit + ' 天' : '—' }}</td>
                <td class="cell-status">
                  {{ ship.current_status || '未填写当前状态' }}
                  <span v-if="ship.status_source === 'auto'" class="chip">官网自动</span>
                </td>
                <td><span class="status" :class="judgeStatus(ship.judgement)">{{ ship.judgement }}</span></td>
                <td>
                  <div class="row-actions">
                    <button
                      class="icon-btn"
                      type="button"
                      :aria-label="'查看运单详情 ' + ship.tracking_number"
                      @click="activeShipment = ship"
                    >
                      详情
                    </button>
                    <a
                      v-if="ship.tracking_url"
                      class="icon-btn"
                      :href="ship.tracking_url"
                      target="_blank"
                      rel="noopener"
                      :aria-label="'在承运商官网查询 ' + ship.tracking_number"
                    >
                      ↗
                    </a>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <footer class="table-foot-bar">
          <span>{{ shipments.length }} 条运单</span>
          <span class="muted">{{ status === 'all' ? '全部状态' : statusLabel(status) }} · {{ date === 'all' ? '全部批次' : date }}</span>
        </footer>
      </section>
      <section v-else class="card empty-state">
        <h2>当前筛选条件下暂无运单</h2>
        <p>可以切换批次或状态，或先录入一条物流单号；录入后立即进入看板。</p>
        <button
          v-if="me && (me.role === 'sales' || me.role === 'manager' || me.role === 'admin')"
          class="btn btn-primary"
          type="button"
          @click="showEntry = true"
        >
          录入物流单号
        </button>
      </section>

      <section class="card track-box">
        <h2>单票实时查询</h2>
        <div class="track-row">
          <select v-model="trackQuery.carrier" class="input select">
            <option v-for="carrier in CARRIERS" :key="carrier" :value="carrier">{{ carrier }}</option>
          </select>
          <input
            v-model="trackQuery.tracking_number"
            class="input"
            placeholder="输入运单号"
            @keyup.enter="singleTrack"
          />
          <button class="btn btn-primary" type="button" :disabled="trackBusy" @click="singleTrack">
            {{ trackBusy ? '查询中…' : '查询' }}
          </button>
        </div>
        <div v-if="trackResult" class="track-result" :class="{ bad: trackResult.error }">
          {{ trackResult.error || trackResult.status_text || trackResult.text || '无结果' }}
        </div>
      </section>
    </template>
    </template>

    <template v-if="board === 'freight'">
      <p v-if="freightMsg" class="entry-msg ok">{{ freightMsg }}</p>
      <section class="filterbar" aria-label="货代台账筛选">
        <button
          v-for="tab in FREIGHT_TABS"
          :key="tab.value"
          type="button"
          class="chip-filter"
          :class="{ on: freightView === tab.value }"
          @click="freightView = tab.value"
        >
          {{ tab.label }}
        </button>
        <button
          v-if="freightView !== 'all' || freightQ"
          type="button"
          class="chip-filter"
          @click="freightView = 'all'; freightQ = ''"
        >
          清除筛选
        </button>
        <span class="spacer" />
        <input
          v-model="freightQ"
          class="input filter-search"
          type="search"
          placeholder="搜索订单号/顺丰/国际单/录单人…"
          aria-label="搜索货代台账"
        />
      </section>
      <div v-if="freightError" class="card state error">{{ freightError }}</div>
      <p v-else-if="freightBusy" class="card state">加载货代台账…</p>
      <p v-else-if="!freightAvailable" class="card state">货代台账尚未同步，请稍后刷新；持续无数据时联系管理员。</p>
      <template v-else>
        <section v-if="freightSummary" class="stats">
          <div class="card stat"><span class="k">总票</span><span class="v">{{ freightSummary.total }}</span></div>
          <div class="card stat"><span class="k">运输/清关</span><span class="v">{{ freightSummary.in_transit }}</span></div>
          <div class="card stat"><span class="k">异常</span><span class="v warn">{{ freightSummary.exception }}</span></div>
          <div class="card stat"><span class="k">待复核</span><span class="v warn">{{ freightSummary.review }}</span></div>
          <div class="card stat"><span class="k">已出国际单</span><span class="v">{{ freightSummary.labeled }}</span></div>
          <div class="card stat"><span class="k">已签收</span><span class="v ok">{{ freightSummary.delivered }}</span></div>
        </section>
        <section v-if="freightItems.length" class="table-shell">
          <div class="table-scroll">
            <table class="grid">
              <thead>
                <tr>
                  <th>订单号</th>
                  <th>顺丰单号</th>
                  <th>国际单号</th>
                  <th>承运商</th>
                  <th>录单人</th>
                  <th>目的地</th>
                  <th>状态</th>
                  <th>匹配</th>
                  <th><span class="sr-only">操作</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in freightItems" :key="item.sf_tracking_no">
                  <td class="mono">{{ item.order_no || '—' }}</td>
                  <td class="mono">{{ item.sf_tracking_no }}</td>
                  <td class="mono">{{ item.tracking_no || '—' }}</td>
                  <td>{{ item.carrier || '—' }}</td>
                  <td>{{ item.salesperson || '—' }}</td>
                  <td>{{ item.consignee || '—' }}<span class="muted"> {{ item.country }}</span></td>
                  <td>
                    <span class="status" :class="item.exception ? 'danger' : item.status === '签收已确认' ? 'ok' : 'info'">
                      {{ item.exception || item.status || '—' }}
                    </span>
                  </td>
                  <td>
                    <span v-if="item.match_level" class="pill" :class="matchPill(item.match_level)">
                      Level {{ item.match_level }}
                    </span>
                    <span v-if="item.needs_review" class="chip">待复核</span>
                  </td>
                  <td>
                    <div class="row-actions">
                      <button
                        class="icon-btn"
                        type="button"
                        :aria-label="'查看货代运单详情 ' + item.sf_tracking_no"
                        @click="activeFreight = item"
                      >
                        详情
                      </button>
                      <button
                        v-if="item.needs_review && canReviewFreight()"
                        class="icon-btn"
                        type="button"
                        :aria-label="'确认关联 ' + item.sf_tracking_no"
                        @click="startConfirm(item); activeFreight = item"
                      >
                        复核
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <footer class="table-foot-bar">
            <span>{{ freightItems.length }} 条货代运单</span>
            <span class="muted">{{ freightView === 'all' ? '全部' : freightView === 'review' ? '待复核' : '异常' }}</span>
          </footer>
        </section>
        <section v-else-if="!freightBusy" class="card empty-state">
          <h2>当前筛选下没有货代运单</h2>
          <p>切换筛选或稍后刷新；台账尚未同步时请联系管理员。</p>
          <button class="btn" type="button" @click="loadFreight()">重新加载</button>
        </section>
      </template>
    </template>

    <template v-if="activeFreight">
      <div class="drawer-backdrop" @click="closeFreightDrawer" />
      <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="freight-title">
        <header class="drawer-head">
          <div>
            <h2 id="freight-title" class="mono">{{ activeFreight.order_no || activeFreight.sf_tracking_no }}</h2>
            <p>顺丰 {{ activeFreight.sf_tracking_no }} · {{ activeFreight.carrier || '—' }}</p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭货代运单详情" @click="closeFreightDrawer">✕</button>
        </header>
        <div class="drawer-body">
          <dl class="kv-list">
            <div><dt>国际单号</dt><dd class="mono">{{ activeFreight.tracking_no || '—' }}</dd></div>
            <div><dt>录单人</dt><dd>{{ activeFreight.salesperson || '—' }}</dd></div>
            <div><dt>收货人</dt><dd>{{ activeFreight.consignee || '—' }}</dd></div>
            <div><dt>国家</dt><dd>{{ activeFreight.country || '—' }}</dd></div>
            <div><dt>状态</dt><dd>{{ activeFreight.status || '—' }}</dd></div>
            <div><dt>生命周期</dt><dd>{{ activeFreight.lifecycle || '—' }}</dd></div>
            <div><dt>异常</dt><dd>{{ activeFreight.exception || '—' }}</dd></div>
            <div><dt>匹配级别</dt><dd>Level {{ activeFreight.match_level || '—' }}</dd></div>
          </dl>
          <p v-if="activeFreight.last_event" class="reason">{{ activeFreight.last_event }}</p>
          <p v-if="activeFreight.match_evidence" class="reason">匹配证据 {{ activeFreight.match_evidence }}</p>
          <div v-if="activeFreight.needs_review && canReviewFreight()" class="confirm-row">
            <input
              v-model="confirmReason"
              class="input"
              placeholder="确认原因（必填，至少 2 字）"
              @keyup.enter="submitConfirm(activeFreight)"
            />
            <button class="btn btn-primary" type="button" :disabled="confirmBusy" @click="submitConfirm(activeFreight)">
              {{ confirmBusy ? '提交中…' : '确认关联' }}
            </button>
          </div>
        </div>
        <footer class="drawer-foot">
          <button class="btn" type="button" @click="closeFreightDrawer">关闭</button>
        </footer>
      </aside>
    </template>

    <template v-if="activeShipment">
      <div class="drawer-backdrop" @click="activeShipment = null" />
      <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="shipment-title">
        <header class="drawer-head">
          <div>
            <h2 id="shipment-title" class="mono">{{ activeShipment.tracking_number }}</h2>
            <p>{{ activeShipment.carrier }} · 判定 {{ activeShipment.judgement }}</p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭运单详情" @click="activeShipment = null">✕</button>
        </header>
        <div class="drawer-body">
          <div class="bar"><i :class="[barClass(activeShipment.judgement)]" :style="{ width: (activeShipment.progress_pct || 0) + '%' }"></i></div>
          <dl class="kv-list">
            <div><dt>客户</dt><dd>{{ activeShipment.customer || '—' }}</dd></div>
            <div><dt>销售</dt><dd>{{ activeShipment.salesperson || '—' }}</dd></div>
            <div><dt>发货日期</dt><dd class="num">{{ activeShipment.ship_date || '—' }}</dd></div>
            <div><dt>在途天数</dt><dd class="num">{{ activeShipment.days_in_transit != null ? activeShipment.days_in_transit + ' 天' : '—' }}</dd></div>
            <div><dt>当前状态</dt><dd>{{ activeShipment.current_status || '未填写当前状态' }}</dd></div>
            <div><dt>预期状态</dt><dd>{{ activeShipment.expected_status || '—' }}</dd></div>
            <div><dt>状态来源</dt><dd>{{ activeShipment.status_source === 'auto' ? '承运商官网自动抓取' : '人工录入' }}</dd></div>
            <div><dt>数据来源</dt><dd>{{ activeShipment.data_source === 'csv_history' ? '历史记录导入' : '系统台账' }}</dd></div>
            <div><dt>备注</dt><dd>{{ activeShipment.note || '—' }}</dd></div>
          </dl>
          <p class="reason">{{ activeShipment.reason }}</p>
        </div>
        <footer class="drawer-foot">
          <a
            v-if="activeShipment.tracking_url"
            class="btn"
            :href="activeShipment.tracking_url"
            target="_blank"
            rel="noopener"
          >
            官网查询
          </a>
          <button class="btn btn-primary" type="button" @click="activeShipment = null">关闭</button>
        </footer>
      </aside>
    </template>

    <template v-if="showEntry">
      <div class="drawer-backdrop" @click="showEntry = false" />
      <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="entry-title">
        <header class="drawer-head">
          <div>
            <h2 id="entry-title">录入物流单号</h2>
            <p>保存后立即进入看板（销售身份由服务器锁定）</p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭录入抽屉" @click="showEntry = false">✕</button>
        </header>
        <form id="logistics-entry-form" class="drawer-body entry-form" @submit.prevent="submitEntry">
          <p v-if="entryError" class="entry-msg bad span-2">{{ entryError }}</p>
          <label>
            物流单号 *
            <input v-model="entryForm.tracking_number" class="input" required />
          </label>
          <label>
            承运商
            <select v-model="entryForm.carrier" class="input">
              <option v-for="carrier in CARRIERS" :key="carrier" :value="carrier">{{ carrier }}</option>
            </select>
          </label>
          <label>
            客户
            <input v-model="entryForm.customer" class="input" />
          </label>
          <label>
            发货日期
            <input v-model="entryForm.ship_date" type="date" class="input" />
          </label>
          <label>
            当前状态
            <input v-model="entryForm.current_status" class="input" placeholder="不知道可留空" />
          </label>
          <label>
            预期状态
            <input v-model="entryForm.expected_status" class="input" />
          </label>
          <label class="span-2">
            备注
            <input v-model="entryForm.note" class="input" />
          </label>
        </form>
        <footer class="drawer-foot">
          <button type="button" class="btn" @click="showEntry = false">取消</button>
          <button type="submit" form="logistics-entry-form" class="btn btn-primary" :disabled="entryBusy">
            {{ entryBusy ? '保存中…' : '保存' }}
          </button>
        </footer>
      </aside>
    </template>
  </main>
</template>

<style scoped>
.logistics {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}

.head-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.operations-panel {
  margin: 16px 0 20px;
  overflow: hidden;
}

.operations-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--border);
}

.operations-head h2 {
  margin: 0;
  font-size: 17px;
}

.operations-head .sub {
  margin: 4px 0 0;
}

.operations-actions {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
}

.operations-frame {
  display: block;
  width: 100%;
  min-height: 820px;
  border: 0;
  background: #f6f8fa;
}

h1 {
  margin: 0 0 4px;
  font-size: 24px;
}

h2 {
  margin: 0 0 12px;
  font-size: 15px;
  color: var(--muted);
}

.sub {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.select {
  width: auto;
  min-width: 140px;
}

.tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.board-tabs {
  margin: 0 0 14px;
}

.tab {
  padding: 7px 14px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
}

.tab.active {
  background: var(--blue-soft);
  border-color: rgba(78, 158, 245, 0.3);
  color: var(--blue);
  font-weight: 600;
}

.state {
  padding: 40px;
  text-align: center;
  color: var(--muted);
}

.state.error {
  color: var(--red);
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.stat {
  padding: 14px;
  display: grid;
  gap: 6px;
}

.stat .k {
  font-size: 12px;
  color: var(--muted);
}

.stat .v {
  font-size: 24px;
  font-weight: 700;
}

.stat .v.warn {
  color: var(--amber);
}

.stat .v.ok {
  color: var(--green);
}

.bar {
  height: 8px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 999px;
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
}

.bar-ok {
  background: var(--green);
}

.bar-bad {
  background: var(--red);
}

.bar-warn {
  background: var(--amber);
}

.bar-transit {
  background: var(--blue);
}

.reason {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.confirm-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
  align-items: center;
}

.confirm-row .input {
  flex: 1;
  min-width: 180px;
}

.track-box {
  padding: 18px 20px;
}

.track-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.track-row .input {
  flex: 1;
  min-width: 180px;
}

.track-result {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: var(--green);
}

.track-result.bad {
  background: rgba(244, 63, 94, 0.08);
  border-color: rgba(244, 63, 94, 0.25);
  color: var(--red);
}

.entry-msg {
  font-size: 13px;
  margin: 0 0 12px;
}

.entry-msg.ok {
  color: var(--green);
}

.entry-msg.bad {
  color: var(--red);
  background: rgba(244, 63, 94, 0.1);
  border: 1px solid rgba(244, 63, 94, 0.3);
  border-radius: 10px;
  padding: 10px 14px;
}

.entry-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-content: start;
  gap: 12px;
}

.entry-form label {
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}

.span-2 {
  grid-column: 1 / -1;
}

@media (max-width: 560px) {
  .entry-form {
    grid-template-columns: 1fr;
  }
}
</style>
