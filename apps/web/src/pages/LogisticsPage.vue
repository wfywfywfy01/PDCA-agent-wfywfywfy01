<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface Summary {
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
const loading = ref(true)
const error = ref('')

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
const confirmSf = ref('')
const confirmReason = ref('')
const confirmBusy = ref(false)

/**
 * 当前账号能否复核跨境货代。
 * @returns {boolean}
 */
function canReviewFreight(): boolean {
  return !!me.value && ['sales', 'manager', 'admin'].includes(me.value.role)
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
  loading.value = true
  error.value = ''
  const qs = params()
  const settle = await Promise.allSettled([
    apiGet<Summary>(`/api/logistics/summary?${qs}`),
    apiGet<{ items: Shipment[] }>(`/api/logistics/shipments?${qs}`),
  ])
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
  if (summaryR.status === 'rejected' && shipmentsR.status === 'rejected') {
    error.value =
      summaryR.reason instanceof HttpError ? summaryR.reason.detail : '物流数据加载失败'
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
  if (!trackQuery.value.tracking_number.trim()) return
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

function judgementClass(judgement: string): string {
  if (judgement === '异常') return 'j-bad'
  if (judgement === '正常') return 'j-ok'
  if (judgement === '运输中') return 'j-transit'
  return 'j-warn'
}

function barClass(judgement: string): string {
  if (judgement === '异常') return 'bar-bad'
  if (judgement === '正常') return 'bar-ok'
  if (judgement === '运输中') return 'bar-transit'
  return 'bar-warn'
}

onMounted(() => {
  load()
  loadDates()
  apiGet<Me>('/api/auth/me')
    .then((value) => (me.value = value))
    .catch(() => undefined)
})

async function loadFreight() {
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
    freightAvailable.value = payload.available
    freightSummary.value = payload.summary
    freightItems.value = payload.items
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/logistics' } })
      return
    }
    freightError.value = err instanceof HttpError ? err.detail : '货代台账加载失败'
  } finally {
    freightBusy.value = false
  }
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
  <main class="logistics">
    <header class="head">
      <div>
        <h1>物流中心</h1>
        <p class="sub">{{ board === 'freight' ? '日升货代预报 · 面单匹配 · 异常复核' : '经销商运单进度 · 异常核查 · 实时追踪' }}</p>
      </div>
      <button
        v-if="board === 'dealer' && me && (me.role === 'sales' || me.role === 'manager' || me.role === 'admin')"
        class="btn btn-primary"
        type="button"
        @click="showEntry = true"
      >
        录入物流单号
      </button>
    </header>

    <div class="tabs board-tabs">
      <button type="button" :class="['tab', { active: board === 'dealer' }]" @click="board = 'dealer'">经销商运单</button>
      <button
        v-if="!me || me.role !== 'dealer'"
        type="button"
        :class="['tab', { active: board === 'freight' }]"
        @click="board = 'freight'"
      >
        跨境货代
      </button>
    </div>

    <p v-if="entrySuccess" class="entry-msg ok">{{ entrySuccess }}</p>

    <template v-if="board === 'dealer'">
    <section class="toolbar card">
      <label>
        批次
        <select v-model="date" class="input select">
          <option value="all">全部</option>
          <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
        </select>
      </label>
      <div class="tabs">
        <button
          v-for="tab in STATUS_TABS"
          :key="tab.value"
          type="button"
          :class="['tab', { active: status === tab.value }]"
          @click="status = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>
      <input v-model="q" class="input search" type="search" placeholder="搜索运单号/客户/销售/状态…" />
    </section>

    <div v-if="error" class="card state error">{{ error }}</div>

    <template v-else>
      <section v-if="summary" class="stats">
        <div class="card stat">
          <span class="k">总运单</span>
          <span class="v">{{ summary.total }}</span>
        </div>
        <div class="card stat">
          <span class="k">运输中</span>
          <span class="v">{{ summary.in_transit }}</span>
        </div>
        <div class="card stat">
          <span class="k">异常/待关注</span>
          <span class="v warn">{{ summary.abnormal }}</span>
        </div>
        <div class="card stat">
          <span class="k">待核查</span>
          <span class="v warn">{{ summary.pending }}</span>
        </div>
        <div class="card stat">
          <span class="k">已签收</span>
          <span class="v ok">{{ summary.delivered }}</span>
        </div>
        <div class="card stat">
          <span class="k">签收率</span>
          <span class="v">{{ summary.delivery_rate_pct }}%</span>
        </div>
      </section>

      <section class="cards">
        <article v-for="ship in shipments" :key="ship.tracking_number" class="card shipment">
          <div class="ship-head">
            <span class="tracking">{{ ship.tracking_number }}</span>
            <span class="badge-carrier">{{ ship.carrier }}</span>
            <span :class="['judge', judgementClass(ship.judgement)]">{{ ship.judgement }}</span>
          </div>
          <div class="meta">
            <span><b>客户</b>{{ ship.customer || '—' }}</span>
            <span><b>销售</b>{{ ship.salesperson || '—' }}</span>
            <span><b>发货</b>{{ ship.ship_date }}</span>
            <span><b>在途</b>{{ ship.days_in_transit != null ? ship.days_in_transit + ' 天' : '—' }}</span>
          </div>
          <p class="status-line">
            {{ ship.current_status || '未填写当前状态' }}
            <span v-if="ship.status_source === 'auto'" class="auto-tag">官网自动</span>
          </p>
          <div class="bar"><i :class="[barClass(ship.judgement)]" :style="{ width: (ship.progress_pct || 0) + '%' }"></i></div>
          <p class="reason">{{ ship.reason }}</p>
          <div class="actions">
            <a v-if="ship.tracking_url" :href="ship.tracking_url" target="_blank" rel="noopener">官网查询 →</a>
          </div>
        </article>
        <p v-if="!loading && !shipments.length" class="empty">
          当前筛选条件下暂无运单{{ status === 'all' && date === 'all' ? '（可在上方录入物流单号）' : '' }}
        </p>
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
      <section class="toolbar card">
        <div class="tabs">
          <button
            v-for="tab in FREIGHT_TABS"
            :key="tab.value"
            type="button"
            :class="['tab', { active: freightView === tab.value }]"
            @click="freightView = tab.value"
          >
            {{ tab.label }}
          </button>
        </div>
        <input v-model="freightQ" class="input search" type="search" placeholder="搜索订单号/顺丰/国际单/录单人…" />
      </section>
      <div v-if="freightError" class="card state error">{{ freightError }}</div>
      <p v-else-if="freightBusy" class="card state">加载货代台账…</p>
      <p v-else-if="!freightAvailable" class="card state">货代台账还没同步。等服务器 09:00/15:00 跑完 logibot，或容器里执行 python /app/logibot/bot.py run。</p>
      <template v-else>
        <section v-if="freightSummary" class="stats">
          <div class="card stat"><span class="k">总票</span><span class="v">{{ freightSummary.total }}</span></div>
          <div class="card stat"><span class="k">运输/清关</span><span class="v">{{ freightSummary.in_transit }}</span></div>
          <div class="card stat"><span class="k">异常</span><span class="v warn">{{ freightSummary.exception }}</span></div>
          <div class="card stat"><span class="k">待复核</span><span class="v warn">{{ freightSummary.review }}</span></div>
          <div class="card stat"><span class="k">已出国际单</span><span class="v">{{ freightSummary.labeled }}</span></div>
          <div class="card stat"><span class="k">已签收</span><span class="v ok">{{ freightSummary.delivered }}</span></div>
        </section>
        <section class="cards">
          <article v-for="item in freightItems" :key="item.sf_tracking_no" class="card shipment">
            <div class="ship-head">
              <span class="tracking">{{ item.order_no || item.sf_tracking_no }}</span>
              <span class="badge-carrier">{{ item.carrier || '—' }}</span>
              <span v-if="item.match_level" :class="['judge', item.match_level === 'C' ? 'j-bad' : item.match_level === 'B' ? 'j-warn' : 'j-ok']">
                Level {{ item.match_level }}
              </span>
              <span :class="['judge', item.exception ? 'j-bad' : item.status === '签收已确认' ? 'j-ok' : 'j-transit']">
                {{ item.exception || item.status || '—' }}
              </span>
            </div>
            <div class="meta">
              <span><b>顺丰</b>{{ item.sf_tracking_no }}</span>
              <span><b>国际单</b>{{ item.tracking_no || '—' }}</span>
              <span><b>录单人</b>{{ item.salesperson || '—' }}</span>
              <span><b>目的地</b>{{ item.consignee || '—' }} {{ item.country }}</span>
            </div>
            <p v-if="item.last_event" class="reason">{{ item.last_event }}</p>
            <p v-if="item.match_evidence" class="reason">证据 {{ item.match_evidence }}</p>
            <div v-if="item.needs_review && canReviewFreight()" class="confirm-row">
              <template v-if="confirmSf === item.sf_tracking_no">
                <input
                  v-model="confirmReason"
                  class="input"
                  placeholder="确认原因（必填）"
                  @keyup.enter="submitConfirm(item)"
                />
                <button class="btn btn-primary" type="button" :disabled="confirmBusy" @click="submitConfirm(item)">
                  {{ confirmBusy ? '提交中…' : '提交' }}
                </button>
                <button class="btn" type="button" @click="confirmSf = ''">取消</button>
              </template>
              <button v-else class="btn btn-primary" type="button" @click="startConfirm(item)">确认关联</button>
            </div>
          </article>
          <p v-if="!freightBusy && !freightItems.length" class="empty">当前筛选下没有货代运单</p>
        </section>
      </template>
    </template>

    <div v-if="showEntry" class="modal-backdrop" @click.self="showEntry = false">
      <section class="card modal">
        <h2>录入物流单号</h2>
        <p class="sub">保存后立即进入看板（销售身份由服务器锁定）</p>
        <div v-if="entryError" class="entry-msg bad">{{ entryError }}</div>
        <form class="entry-form" @submit.prevent="submitEntry">
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
          <div class="modal-actions span-2">
            <button type="button" class="btn" @click="showEntry = false">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="entryBusy">
              {{ entryBusy ? '保存中…' : '保存' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<style scoped>
.logistics {
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
  margin: 0 0 12px;
  font-size: 15px;
  color: var(--muted);
}

.sub {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.toolbar {
  padding: 12px 14px;
  display: flex;
  gap: 14px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.toolbar label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--muted);
}

.select {
  width: auto;
  min-width: 140px;
}

.search {
  flex: 1;
  min-width: 200px;
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

.cards {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
}

.shipment {
  padding: 16px 18px;
  border-left: 4px solid var(--faint);
}

.ship-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tracking {
  font-size: 17px;
  font-weight: 700;
}

.badge-carrier {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid var(--border-strong);
  color: var(--muted);
}

.judge {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.j-ok {
  background: rgba(16, 185, 129, 0.14);
  color: var(--green);
}

.j-bad {
  background: rgba(244, 63, 94, 0.14);
  color: var(--red);
}

.j-warn {
  background: rgba(245, 158, 11, 0.14);
  color: var(--amber);
}

.j-transit {
  background: rgba(78, 158, 245, 0.14);
  color: var(--blue);
}

.meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 8px;
  margin: 12px 0;
  font-size: 13px;
  color: var(--muted);
}

.meta b {
  margin-right: 6px;
  color: var(--faint);
  font-weight: 500;
}

.status-line {
  margin: 6px 0;
  font-size: 14px;
  display: flex;
  gap: 8px;
  align-items: center;
}

.auto-tag {
  font-size: 11px;
  color: var(--blue);
  border: 1px solid rgba(78, 158, 245, 0.3);
  border-radius: 6px;
  padding: 1px 6px;
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

.actions {
  margin-top: 10px;
}

.actions a,
.actions .btn {
  font-size: 13px;
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

.actions a {
  font-size: 13px;
}

.empty {
  color: var(--muted);
  text-align: center;
  padding: 32px 0;
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

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  z-index: 20;
}

.modal {
  width: 100%;
  max-width: 560px;
  padding: 22px 24px;
  max-height: 90vh;
  overflow: auto;
}

.modal h2 {
  margin-bottom: 4px;
}

.entry-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 14px;
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

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 6px;
}

@media (max-width: 560px) {
  .entry-form {
    grid-template-columns: 1fr;
  }
}
</style>
