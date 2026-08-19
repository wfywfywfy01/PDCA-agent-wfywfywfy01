<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, apiPut, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface Me {
  role: string
}

interface CustomerRow {
  dealer_name: string
  dealer_nickname?: string
  owner: string
  abcd_grade: string
  value_score: number | null
  intent_score: number | null
  silent_days: number | null
  is_overdue: boolean
  alerts: string[]
  suggested_action: string
  followup_round: string
  last_followup_date: string
  next_action: string
  status: string
  country?: string
  region?: string
  lead_source?: string
}

interface Summary {
  total: number
  by_abcd: Record<string, number>
  overdue_count: number
  silent_risk_count: number
  silent_rate_pct: number
  attention_items: { dealer_name: string; abcd_grade: string; silent_days: number | null; suggested_action: string }[]
}

interface FollowupTask {
  dealer_name: string
  owner: string
  abcd_grade: string
  silent_days: number | null
  action: string
  priority: string
}

const router = useRouter()
const me = ref<Me | null>(null)
const activeTab = ref<'customers' | 'followup' | 'outreach'>('customers')

const summary = ref<Summary | null>(null)
const customers = ref<CustomerRow[]>([])
const followups = ref<FollowupTask[]>([])
const owners = ref<string[]>([])
const ownerFilter = ref('')
const abcdFilter = ref('all')
const overdueOnly = ref(false)
const search = ref('')

const loading = ref(true)
const error = ref('')

const editCustomer = ref<CustomerRow | null>(null)
const editBusy = ref(false)
const editError = ref('')
const editForm = ref({ next_action: '', abcd_grade: '', followup_round: '', last_followup_date: '' })

const outreachCustomer = ref<CustomerRow | null>(null)
const outreachBusy = ref(false)
const outreachResult = ref('')
const outreachError = ref('')
const templateType = ref('fabe_email')

function baseParams(): string {
  const p = new URLSearchParams()
  if (ownerFilter.value) p.set('owner', ownerFilter.value)
  return p.toString()
}

async function load() {
  loading.value = true
  error.value = ''
  const base = baseParams()
  const extra = new URLSearchParams()
  if (abcdFilter.value !== 'all') extra.set('abcd', abcdFilter.value)
  if (overdueOnly.value) extra.set('overdue_only', 'true')
  const settle = await Promise.allSettled([
    apiGet<Summary>(`/api/signalseller/summary?${base}`),
    apiGet<{ items: CustomerRow[] }>(`/api/signalseller/customers?${base}&${extra}`),
    apiGet<{ items: FollowupTask[] }>(`/api/signalseller/followup-tasks?${base}`),
  ])
  const [summaryR, customersR, followupsR] = settle
  for (const r of settle) {
    if (r.status === 'rejected' && r.reason instanceof HttpError && r.reason.status === 401) {
      router.replace({ path: '/login', query: { next: '/signalseller' } })
      return
    }
  }
  if (summaryR.status === 'fulfilled') summary.value = summaryR.value
  if (customersR.status === 'fulfilled') customers.value = customersR.value.items
  if (followupsR.status === 'fulfilled') followups.value = followupsR.value.items
  if (summaryR.status === 'rejected' && customersR.status === 'rejected') {
    error.value = summaryR.reason instanceof HttpError ? summaryR.reason.detail : '获客数据加载失败'
  }
  loading.value = false
}

async function loadOwners() {
  try {
    const payload = await apiGet<{ items: string[] }>('/api/signalseller/owners')
    owners.value = payload.items || []
  } catch {
    owners.value = []
  }
}

const filteredCustomers = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return customers.value
  return customers.value.filter((row) =>
    [row.dealer_name, row.dealer_nickname, row.owner, row.country]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(q)),
  )
})

function gradeClass(grade: string): string {
  return 'g-' + (grade || 'D').toLowerCase()
}

function openEdit(customer: CustomerRow) {
  editCustomer.value = customer
  editError.value = ''
  editForm.value = {
    next_action: customer.next_action || '',
    abcd_grade: customer.abcd_grade || '',
    followup_round: customer.followup_round || '1',
    last_followup_date: customer.last_followup_date || '',
  }
}

async function submitEdit() {
  if (!editCustomer.value) return
  editBusy.value = true
  editError.value = ''
  try {
    await apiPut('/api/signalseller/customers', {
      dealer_name: editCustomer.value.dealer_name,
      next_action: editForm.value.next_action,
      abcd_grade: editForm.value.abcd_grade || undefined,
      followup_round: editForm.value.followup_round,
      last_followup_date: editForm.value.last_followup_date || undefined,
    })
    editCustomer.value = null
    await load()
  } catch (err) {
    editError.value = err instanceof HttpError ? err.detail : '更新失败，请稍后重试'
  } finally {
    editBusy.value = false
  }
}

function openOutreach(customer: CustomerRow) {
  outreachCustomer.value = customer
  outreachResult.value = ''
  outreachError.value = ''
  templateType.value = 'fabe_email'
}

async function generateOutreach() {
  if (!outreachCustomer.value) return
  outreachBusy.value = true
  outreachError.value = ''
  try {
    const payload = await apiPost<{ content?: string; text?: string; message?: string }>(
      '/api/signalseller/outreach/generate',
      {
        customer: { dealer_name: outreachCustomer.value.dealer_name },
        template_type: templateType.value,
        use_hermes: false,
      },
    )
    outreachResult.value = payload.content || payload.text || payload.message || JSON.stringify(payload)
  } catch (err) {
    outreachError.value = err instanceof HttpError ? err.detail : '生成失败，请稍后重试'
  } finally {
    outreachBusy.value = false
  }
}

onMounted(() => {
  load()
  loadOwners()
  apiGet<Me>('/api/auth/me')
    .then((value) => (me.value = value))
    .catch(() => undefined)
})
</script>

<template>
  <AppNav />
  <main class="signalseller">
    <header class="head">
      <div>
        <h1>获客指挥</h1>
        <p class="sub">ABCD 客户分层 · 跟进任务 · 触达文案（数据来自数据库）</p>
      </div>
      <div class="tabs">
        <button
          :class="['tab', { active: activeTab === 'customers' }]"
          type="button"
          @click="activeTab = 'customers'"
        >
          客户列表
        </button>
        <button
          :class="['tab', { active: activeTab === 'followup' }]"
          type="button"
          @click="activeTab = 'followup'"
        >
          跟进任务
        </button>
        <button
          :class="['tab', { active: activeTab === 'outreach' }]"
          type="button"
          @click="activeTab = 'outreach'"
        >
          触达文案
        </button>
      </div>
    </header>

    <div v-if="error" class="card state error">{{ error }}</div>

    <template v-else>
      <section v-if="summary" class="stats">
        <div class="card stat">
          <span class="k">客户总数</span>
          <span class="v">{{ summary.total }}</span>
        </div>
        <div class="card stat">
          <span class="k">A / B / C / D</span>
          <span class="v small">
            {{ summary.by_abcd.A || 0 }} / {{ summary.by_abcd.B || 0 }} /
            {{ summary.by_abcd.C || 0 }} / {{ summary.by_abcd.D || 0 }}
          </span>
        </div>
        <div class="card stat">
          <span class="k">超期未跟进</span>
          <span class="v warn">{{ summary.overdue_count }}</span>
        </div>
        <div class="card stat">
          <span class="k">沉默 ≥7 天</span>
          <span class="v warn">{{ summary.silent_risk_count }}</span>
        </div>
      </section>

      <template v-if="activeTab === 'customers'">
        <section class="toolbar card">
          <select v-if="owners.length" v-model="ownerFilter" class="input select" @change="load()">
            <option value="">全部负责人</option>
            <option v-for="name in owners" :key="name" :value="name">{{ name }}</option>
          </select>
          <select v-model="abcdFilter" class="input select" @change="load()">
            <option value="all">全部分级</option>
            <option value="A">A 类</option>
            <option value="B">B 类</option>
            <option value="C">C 类</option>
            <option value="D">D 类</option>
          </select>
          <label class="check">
            <input v-model="overdueOnly" type="checkbox" @change="load()" />
            仅超期
          </label>
          <input v-model="search" class="input search" type="search" placeholder="搜索客户名/负责人/国家…" />
        </section>

        <div v-if="loading" class="card state">正在读取客户…</div>
        <section v-else class="cards">
          <article v-for="row in filteredCustomers" :key="row.dealer_name" class="card customer">
            <div class="c-head">
              <span class="c-name">{{ row.dealer_name }}</span>
              <span :class="['grade', gradeClass(row.abcd_grade)]">{{ row.abcd_grade || '未分级' }}</span>
              <span v-if="row.is_overdue" class="overdue-tag">超期</span>
            </div>
            <div class="c-meta">
              <span>负责人 {{ row.owner || '—' }}</span>
              <span v-if="row.country">· {{ row.country }}</span>
              <span v-if="row.silent_days != null">· 沉默 {{ row.silent_days }} 天</span>
              <span v-if="row.lead_source">· 来源 {{ row.lead_source }}</span>
            </div>
            <ul v-if="row.alerts.length" class="alerts">
              <li v-for="(alert, index) in row.alerts" :key="index">⚠ {{ alert }}</li>
            </ul>
            <p class="next-action">
              <b>下一步：</b>{{ row.next_action || row.suggested_action || '—' }}
            </p>
            <div class="c-actions">
              <button
                v-if="me && me.role !== 'viewer' && me.role !== 'dealer'"
                type="button"
                class="btn btn-sm"
                @click="openEdit(row)"
              >
                更新跟进
              </button>
              <button
                v-if="me && (me.role === 'sales' || me.role === 'manager' || me.role === 'admin')"
                type="button"
                class="btn btn-primary btn-sm"
                @click="openOutreach(row)"
              >
                生成触达
              </button>
            </div>
          </article>
          <p v-if="!filteredCustomers.length" class="empty">暂无匹配客户（数据未导入时自动回退 CSV）</p>
        </section>
      </template>

      <template v-else-if="activeTab === 'followup'">
        <section class="cards">
          <article v-for="task in followups" :key="task.dealer_name" class="card followup">
            <div class="f-head">
              <span class="c-name">{{ task.dealer_name }}</span>
              <span :class="['grade', gradeClass(task.abcd_grade)]">{{ task.abcd_grade }}</span>
              <span :class="['priority', task.priority === 'HIGH' ? 'p-high' : 'p-mid']">
                {{ task.priority === 'HIGH' ? '高优先' : '中优先' }}
              </span>
            </div>
            <p class="next-action">
              沉默 {{ task.silent_days ?? '—' }} 天 · {{ task.owner || '未指派' }}
            </p>
            <p class="next-action"><b>建议动作：</b>{{ task.action }}</p>
          </article>
          <p v-if="!followups.length" class="empty">当前没有需要跟进的客户</p>
        </section>
      </template>

      <template v-else>
        <section class="card outreach-panel">
          <h2>生成触达文案</h2>
          <div class="outreach-row">
            <select v-model="outreachCustomer" class="input select">
              <option :value="null" disabled>选择客户</option>
              <option v-for="row in customers" :key="row.dealer_name" :value="row">
                {{ row.dealer_name }}
              </option>
            </select>
            <select v-model="templateType" class="input select">
              <option value="fabe_email">FABE 邮件</option>
              <option value="fabe_message">FABE 私信</option>
              <option value="spin">SPIN 问题卡</option>
            </select>
            <button
              type="button"
              class="btn btn-primary"
              :disabled="!outreachCustomer || outreachBusy"
              @click="generateOutreach"
            >
              {{ outreachBusy ? '生成中…' : '生成' }}
            </button>
          </div>
          <div v-if="outreachError" class="entry-msg bad">{{ outreachError }}</div>
          <div v-if="outreachResult" class="outreach-result">
            <pre>{{ outreachResult }}</pre>
          </div>
        </section>
      </template>
    </template>

    <div v-if="editCustomer" class="modal-backdrop" @click.self="editCustomer = null">
      <section class="card modal">
        <h2>更新跟进 · {{ editCustomer.dealer_name }}</h2>
        <div v-if="editError" class="entry-msg bad">{{ editError }}</div>
        <form class="entry-form" @submit.prevent="submitEdit">
          <label>
            ABCD 分级
            <select v-model="editForm.abcd_grade" class="input">
              <option value="">未分级</option>
              <option value="A">A</option>
              <option value="B">B</option>
              <option value="C">C</option>
              <option value="D">D</option>
            </select>
          </label>
          <label>
            跟进轮次
            <input v-model="editForm.followup_round" class="input" />
          </label>
          <label>
            最后跟进日期
            <input v-model="editForm.last_followup_date" type="date" class="input" />
          </label>
          <label class="span-2">
            下一步动作
            <input v-model="editForm.next_action" class="input" placeholder="如：周五前发送报价单" />
          </label>
          <div class="modal-actions span-2">
            <button type="button" class="btn" @click="editCustomer = null">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="editBusy">
              {{ editBusy ? '保存中…' : '保存' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<style scoped>
.signalseller {
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
  margin: 0 0 14px;
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
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
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
  font-size: 24px;
  font-weight: 700;
}

.stat .v.small {
  font-size: 16px;
}

.stat .v.warn {
  color: var(--amber);
}

.toolbar {
  padding: 12px 14px;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.select {
  width: auto;
  min-width: 130px;
}

.search {
  flex: 1;
  min-width: 200px;
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}

.cards {
  display: grid;
  gap: 12px;
}

.customer,
.followup {
  padding: 16px 18px;
}

.c-head,
.f-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.c-name {
  font-size: 16px;
  font-weight: 700;
}

.grade {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid var(--border-strong);
  color: var(--muted);
}

.g-a {
  color: var(--green);
  border-color: rgba(16, 185, 129, 0.35);
}

.g-b {
  color: var(--blue);
  border-color: rgba(78, 158, 245, 0.35);
}

.g-c {
  color: var(--amber);
  border-color: rgba(245, 158, 11, 0.35);
}

.g-d {
  color: var(--faint);
}

.overdue-tag {
  font-size: 12px;
  font-weight: 700;
  color: var(--red);
  background: rgba(244, 63, 94, 0.12);
  border-radius: 999px;
  padding: 2px 10px;
}

.c-meta {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--muted);
}

.alerts {
  margin: 10px 0 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--amber);
}

.alerts li {
  margin: 3px 0;
}

.next-action {
  margin: 10px 0 0;
  font-size: 13px;
}

.next-action b {
  color: var(--faint);
  font-weight: 500;
}

.c-actions {
  margin-top: 12px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.btn-sm {
  padding: 6px 14px;
  font-size: 13px;
}

.priority {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.p-high {
  color: var(--red);
  border: 1px solid rgba(244, 63, 94, 0.35);
}

.p-mid {
  color: var(--amber);
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.empty {
  color: var(--muted);
  text-align: center;
  padding: 32px 0;
}

.outreach-panel {
  padding: 20px 22px;
}

.outreach-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.outreach-row .select {
  min-width: 200px;
  flex: 1;
}

.outreach-result {
  margin-top: 14px;
}

.outreach-result pre {
  background: var(--card-2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  margin: 0;
  font-family: inherit;
}

.entry-msg {
  font-size: 13px;
  border-radius: 10px;
  padding: 10px 14px;
  margin: 12px 0;
}

.entry-msg.bad {
  color: var(--red);
  background: rgba(244, 63, 94, 0.08);
  border: 1px solid rgba(244, 63, 94, 0.25);
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
  max-width: 520px;
  padding: 22px 24px;
  max-height: 90vh;
  overflow: auto;
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
