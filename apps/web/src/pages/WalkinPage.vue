<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface Me {
  role: string
}

interface Store {
  store_id: string
  name: string
  region: string
  country: string
}

interface SummaryResponse {
  month: string
  record_count: number
  five_kit: {
    walkin: number
    cross: number
    online: number
    recruit: number
    existing: number
    total: number
    pct: Record<string, number>
  }
  funnel: {
    total_visits: number
    touch_count: number
    use_count: number
    wechat_add_count: number
    deal_count: number
    deal_amount_yuan: number
    deal_amount_usd: number
  }
  by_dealer: {
    dealer_id: string
    dealer_name: string
    total_visits: number
    deal_count: number
    deal_amount_usd: number
    amount_requires_review: boolean
  }[]
  data_quality: { excluded_record_count: number; reason: string }
}

interface ReportItem {
  id: number
  report_date: string
  dealer_id: string
  dealer_name: string
  five_kit: { walkin: number; cross: number; online: number; recruit: number; existing: number; total: number }
  funnel: {
    deal_count: number
    deal_amount_usd: number
    touch_count: number
    wechat_add_count: number
    amount_requires_review: boolean
  }
  notes: string
  submitted_by: string
}

const router = useRouter()
const me = ref<Me | null>(null)
const activeTab = ref<'submit' | 'summary' | 'history'>('submit')

const stores = ref<Store[]>([])
const submitForm = ref({
  dealer_id: '',
  report_date: todayText(),
  walkin_visits: 0,
  cross_visits: 0,
  online_visits: 0,
  recruit_visits: 0,
  existing_visits: 0,
  touch_count: 0,
  use_count: 0,
  wechat_add_count: 0,
  deal_count: 0,
  deal_amount_yuan: 0,
  notes: '',
})
const submitBusy = ref(false)
const submitError = ref('')
const submitSuccess = ref('')

const summaryMonth = ref(currentMonth())
const summary = ref<SummaryResponse | null>(null)
const summaryLoading = ref(false)
const summaryError = ref('')

const historyMonth = ref(currentMonth())
const historyDealer = ref('')
const history = ref<ReportItem[]>([])
const historyLoading = ref(false)
const historyError = ref('')

const FIVE_KIT_FIELDS = [
  { key: 'walkin_visits', label: '直接进店' },
  { key: 'cross_visits', label: '异业介绍' },
  { key: 'online_visits', label: '线上渠道' },
  { key: 'recruit_visits', label: '招聘自带' },
  { key: 'existing_visits', label: '存量客户' },
] as const

function todayText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

function currentMonth(): string {
  return todayText().slice(0, 7)
}

async function loadStores() {
  try {
    stores.value = await apiGet<Store[]>('/api/my-stores')
    if (stores.value.length === 1) submitForm.value.dealer_id = stores.value[0].store_id
  } catch {
    stores.value = []
  }
}

async function submit() {
  submitBusy.value = true
  submitError.value = ''
  submitSuccess.value = ''
  const store = stores.value.find((item) => item.store_id === submitForm.value.dealer_id)
  try {
    await apiPost('/api/walkin-metrics', {
      ...submitForm.value,
      dealer_name: store?.name || '',
    })
    submitSuccess.value = '✅ 已保存（同店同日自动覆盖）'
    submitForm.value = {
      ...submitForm.value,
      walkin_visits: 0,
      cross_visits: 0,
      online_visits: 0,
      recruit_visits: 0,
      existing_visits: 0,
      touch_count: 0,
      use_count: 0,
      wechat_add_count: 0,
      deal_count: 0,
      deal_amount_yuan: 0,
      notes: '',
    }
  } catch (err) {
    submitError.value = err instanceof HttpError ? err.detail : '提交失败，请稍后重试'
  } finally {
    submitBusy.value = false
  }
}

async function loadSummary() {
  summaryLoading.value = true
  summaryError.value = ''
  try {
    summary.value = await apiGet<SummaryResponse>(
      `/api/walkin-metrics/summary?month=${summaryMonth.value}`,
    )
  } catch (err) {
    summaryError.value = err instanceof HttpError ? err.detail : '汇总加载失败'
  } finally {
    summaryLoading.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  historyError.value = ''
  const p = new URLSearchParams({ month: historyMonth.value })
  if (historyDealer.value) p.set('dealer_id', historyDealer.value)
  try {
    const payload = await apiGet<{ count: number; items: ReportItem[] }>(
      `/api/walkin-metrics?${p}`,
    )
    history.value = payload.items
  } catch (err) {
    historyError.value = err instanceof HttpError ? err.detail : '明细加载失败'
  } finally {
    historyLoading.value = false
  }
}

function fiveKitValue(key: string): number {
  const k = key.replace('_visits', '') as 'walkin' | 'cross' | 'online' | 'recruit' | 'existing'
  return summary.value?.five_kit[k] ?? 0
}

onMounted(async () => {
  await loadStores()
  try {
    me.value = await apiGet<Me>('/api/auth/me')
  } catch {
    me.value = null
  }
})
</script>

<template>
  <AppNav />
  <main class="walkin">
    <header class="head">
      <div>
        <h1>客流五件套</h1>
        <p class="sub">门店日报上报 · 月度汇总 · 转化漏斗（数据来自数据库）</p>
      </div>
      <div class="tabs">
        <button :class="['tab', { active: activeTab === 'submit' }]" type="button" @click="activeTab = 'submit'">
          今日上报
        </button>
        <button
          :class="['tab', { active: activeTab === 'summary' }]"
          type="button"
          @click="activeTab = 'summary'; loadSummary()"
        >
          月度汇总
        </button>
        <button
          :class="['tab', { active: activeTab === 'history' }]"
          type="button"
          @click="activeTab = 'history'; loadHistory()"
        >
          历史明细
        </button>
      </div>
    </header>

    <template v-if="activeTab === 'submit'">
      <section class="card form-card">
        <h2>今日五件套上报</h2>
        <p class="hint">零客流也要如实上报，不能把 0 当成未上报。</p>
        <div v-if="submitError" class="msg bad">{{ submitError }}</div>
        <div v-if="submitSuccess" class="msg ok">{{ submitSuccess }}</div>
        <form class="submit-form" @submit.prevent="submit">
          <label>
            门店 *
            <select v-model="submitForm.dealer_id" class="input" required>
              <option value="" disabled>选择门店</option>
              <option v-for="store in stores" :key="store.store_id" :value="store.store_id">
                {{ store.name }}（{{ store.region }}）
              </option>
            </select>
          </label>
          <label>
            上报日期
            <input v-model="submitForm.report_date" type="date" class="input" required />
          </label>
          <label v-for="field in FIVE_KIT_FIELDS" :key="field.key">
            {{ field.label }}
            <input v-model.number="submitForm[field.key]" type="number" min="0" class="input" />
          </label>
          <label>
            产品展示
            <input v-model.number="submitForm.touch_count" type="number" min="0" class="input" />
          </label>
          <label>
            体验台数
            <input v-model.number="submitForm.use_count" type="number" min="0" class="input" />
          </label>
          <label>
            留资数
            <input v-model.number="submitForm.wechat_add_count" type="number" min="0" class="input" />
          </label>
          <label>
            成交台数
            <input v-model.number="submitForm.deal_count" type="number" min="0" class="input" />
          </label>
          <label>
            Revenue（USD）
            <input v-model.number="submitForm.deal_amount_yuan" type="number" min="0" step="0.01" class="input" />
          </label>
          <label class="span-2">
            备注
            <input v-model="submitForm.notes" class="input" />
          </label>
          <div class="form-actions span-2">
            <button type="submit" class="btn btn-primary" :disabled="submitBusy">
              {{ submitBusy ? '提交中…' : '提交' }}
            </button>
          </div>
        </form>
      </section>
    </template>

    <template v-else-if="activeTab === 'summary'">
      <div class="toolbar-row">
        <input v-model="summaryMonth" type="month" class="input month-input" @change="loadSummary" />
      </div>
      <div v-if="summaryError" class="msg bad">{{ summaryError }}</div>
      <template v-else-if="summary">
        <section class="stats">
          <div class="card stat">
            <span class="k">上报记录</span>
            <span class="v">{{ summary.record_count }}</span>
          </div>
          <div class="card stat">
            <span class="k">进店总组数</span>
            <span class="v">{{ summary.five_kit.total }}</span>
          </div>
          <div class="card stat">
            <span class="k">留资</span>
            <span class="v">{{ summary.funnel.wechat_add_count }}</span>
          </div>
          <div class="card stat">
            <span class="k">成交台数</span>
            <span class="v ok">{{ summary.funnel.deal_count }}</span>
          </div>
          <div class="card stat">
            <span class="k">Revenue（USD）</span>
            <span class="v ok">$ {{ summary.funnel.deal_amount_usd.toLocaleString() }}</span>
          </div>
        </section>
        <p v-if="summary.data_quality.excluded_record_count" class="quality-warn">
          ⚠ {{ summary.data_quality.excluded_record_count }} 条记录金额超 USD 复核阈值未计入：
          {{ summary.data_quality.reason }}
        </p>
        <section class="card panel">
          <h2>五类进店构成</h2>
          <div class="kit-bars">
            <div v-for="field in FIVE_KIT_FIELDS" :key="field.key" class="kit-bar">
              <span class="kit-label">{{ field.label }}</span>
              <div class="bar">
                <i :style="{ width: (summary.five_kit.pct[field.key.replace('_visits', '')] || 0) + '%' }"></i>
              </div>
              <span class="kit-num">
                {{ fiveKitValue(field.key) }}
                （{{ summary.five_kit.pct[field.key.replace('_visits', '')] || 0 }}%）
              </span>
            </div>
          </div>
        </section>
        <section class="card panel">
          <h2>门店排行</h2>
          <table v-if="summary.by_dealer.length" class="table">
            <thead>
              <tr>
                <th>门店</th>
                <th class="num">进店</th>
                <th class="num">成交</th>
                <th class="num">Revenue（USD）</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in summary.by_dealer" :key="row.dealer_id">
                <td>
                  {{ row.dealer_name }}
                  <span v-if="row.amount_requires_review" class="review-tag">复核</span>
                </td>
                <td class="num">{{ row.total_visits }}</td>
                <td class="num">{{ row.deal_count }}</td>
                <td class="num">$ {{ row.deal_amount_usd.toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty">该月暂无上报数据</p>
        </section>
      </template>
    </template>

    <template v-else>
      <div class="toolbar-row">
        <input v-model="historyMonth" type="month" class="input month-input" @change="loadHistory" />
        <select v-model="historyDealer" class="input select" @change="loadHistory">
          <option value="">全部门店</option>
          <option v-for="store in stores" :key="store.store_id" :value="store.store_id">{{ store.name }}</option>
        </select>
      </div>
      <div v-if="historyError" class="msg bad">{{ historyError }}</div>
      <section class="card panel">
        <h2>日报明细</h2>
        <table v-if="history.length" class="table">
          <thead>
            <tr>
              <th>日期</th>
              <th>门店</th>
              <th class="num">进店</th>
              <th class="num">留资</th>
              <th class="num">成交</th>
              <th class="num">Revenue（USD）</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in history" :key="row.id">
              <td>{{ row.report_date }}</td>
              <td>{{ row.dealer_name }}</td>
              <td class="num">{{ row.five_kit.total }}</td>
              <td class="num">{{ row.funnel.wechat_add_count }}</td>
              <td class="num">{{ row.funnel.deal_count }}</td>
              <td class="num">
                $ {{ row.funnel.deal_amount_usd.toLocaleString() }}
                <span v-if="row.funnel.amount_requires_review" class="review-tag">复核</span>
              </td>
              <td class="notes">{{ row.notes || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="!historyLoading" class="empty">该月暂无上报记录</p>
      </section>
    </template>
  </main>
</template>

<style scoped>
.walkin {
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
  margin-bottom: 16px;
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

.tabs {
  display: flex;
  gap: 6px;
}

.tab {
  padding: 8px 16px;
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

.form-card,
.panel {
  padding: 20px 22px;
}

.hint {
  color: var(--amber);
  font-size: 13px;
  margin: 0 0 14px;
}

.msg {
  font-size: 13px;
  border-radius: 10px;
  padding: 10px 14px;
  margin: 0 0 14px;
}

.msg.ok {
  color: var(--green);
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.msg.bad {
  color: var(--red);
  background: rgba(244, 63, 94, 0.08);
  border: 1px solid rgba(244, 63, 94, 0.25);
}

.submit-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.submit-form label {
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}

.span-2 {
  grid-column: 1 / -1;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
}

.toolbar-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.month-input {
  width: auto;
}

.select {
  width: auto;
  min-width: 200px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
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
  font-size: 22px;
  font-weight: 700;
}

.stat .v.ok {
  color: var(--green);
}

.quality-warn {
  font-size: 13px;
  color: var(--amber);
  margin: 0 0 14px;
}

.panel {
  margin-bottom: 14px;
}

.kit-bars {
  display: grid;
  gap: 10px;
}

.kit-bar {
  display: grid;
  grid-template-columns: 90px 1fr 130px;
  gap: 10px;
  align-items: center;
  font-size: 13px;
}

.kit-label {
  color: var(--muted);
}

.kit-num {
  color: var(--muted);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.bar {
  height: 10px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 999px;
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--blue);
  border-radius: 999px;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

th {
  text-align: left;
  color: var(--muted);
  font-weight: 600;
  font-size: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}

td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--border);
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.notes {
  color: var(--muted);
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-tag {
  font-size: 11px;
  color: var(--amber);
  border: 1px solid rgba(245, 158, 11, 0.4);
  border-radius: 6px;
  padding: 1px 6px;
  margin-left: 6px;
}

.empty {
  color: var(--muted);
  text-align: center;
  padding: 24px 0;
}

@media (max-width: 640px) {
  .kit-bar {
    grid-template-columns: 80px 1fr 90px;
  }
}
</style>
