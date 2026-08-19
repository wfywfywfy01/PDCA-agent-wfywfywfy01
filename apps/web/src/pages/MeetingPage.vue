<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface MeetingItem {
  id: string
  title: string
  meeting_type: string
  bucket: string
  duration_minutes: number
  brief: string
  todos: { title?: string; owner?: string; owner_name?: string; assignee?: string }[]
  participants: (string | { name?: string; display_name?: string; login?: string })[]
  source?: string
}

interface MeetingsPayload {
  ok: boolean
  date: string
  date_end?: string
  meetings: MeetingItem[]
  summary: { total: number; internal: number; external: number; duration_minutes: number; todo_count: number }
  counts: Record<string, number>
  scope?: string
  scope_message?: string
}

interface Me {
  role: string
}

const router = useRouter()
const me = ref<Me | null>(null)
const startDate = ref(todayText())
const endDate = ref('')

const payload = ref<MeetingsPayload | null>(null)
const loading = ref(true)
const error = ref('')

const showDispatch = ref(false)
const dispatchMeeting = ref<MeetingItem | null>(null)
const dispatchBusy = ref(false)
const dispatchError = ref('')
const dispatchSuccess = ref('')
const assignments = ref<{ owner: string; title: string }[]>([{ owner: '', title: '' }])

function todayText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

function qs(): string {
  const p = new URLSearchParams({ date: startDate.value })
  if (endDate.value) p.set('end_date', endDate.value)
  return p.toString()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    payload.value = await apiGet<MeetingsPayload>(`/api/meeting-center/meetings?${qs()}`)
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/meetings' } })
      return
    }
    error.value = err instanceof HttpError ? err.detail : '会议数据加载失败'
  } finally {
    loading.value = false
  }
}

function typeLabel(type: string): string {
  return type === 'external' ? '外部' : '内部'
}

const BUCKET_LABELS: Record<string, string> = {
  interview: '面试',
  report: '例会',
  customer: '客户',
}

function personText(person: string | { name?: string; display_name?: string; login?: string }): string {
  if (typeof person === 'string') return person
  return person.name || person.display_name || person.login || ''
}

function openDispatch(meeting: MeetingItem) {
  dispatchMeeting.value = meeting
  dispatchError.value = ''
  dispatchSuccess.value = ''
  assignments.value = meeting.todos.length
    ? meeting.todos.map((todo) => ({
        owner: todo.owner || todo.owner_name || todo.assignee || '',
        title: todo.title || '',
      }))
    : [{ owner: '', title: '' }]
  showDispatch.value = true
}

function addAssignment() {
  assignments.value.push({ owner: '', title: '' })
}

function removeAssignment(index: number) {
  if (assignments.value.length > 1) assignments.value.splice(index, 1)
}

async function submitDispatch() {
  if (!dispatchMeeting.value) return
  const rows = assignments.value.filter((item) => item.title.trim() && item.owner.trim())
  if (!rows.length) {
    dispatchError.value = '请至少填写一条待办（负责人 + 内容）'
    return
  }
  dispatchBusy.value = true
  dispatchError.value = ''
  try {
    await apiPost('/api/meeting-center/dispatch', {
      date: startDate.value,
      meeting_id: dispatchMeeting.value.id,
      meeting_title: dispatchMeeting.value.title,
      assignments: rows,
    })
    dispatchSuccess.value = '✅ 已派发，待办将同步到 VPS 任务'
    showDispatch.value = false
    await load()
  } catch (err) {
    dispatchError.value = err instanceof HttpError ? err.detail : '派发失败，请稍后重试'
  } finally {
    dispatchBusy.value = false
  }
}

onMounted(() => {
  load()
  apiGet<Me>('/api/auth/me')
    .then((value) => (me.value = value))
    .catch(() => undefined)
})

watch([startDate, endDate], load)
</script>

<template>
  <AppNav />
  <main class="meetings">
    <header class="head">
      <div>
        <h1>会议中心</h1>
        <p class="sub">会议记录 · 待办派发 · 闭环跟踪</p>
      </div>
      <div class="date-row">
        <input v-model="startDate" type="date" class="input" />
        <span class="sep">至</span>
        <input v-model="endDate" type="date" class="input" />
        <button v-if="endDate" type="button" class="btn" @click="endDate = ''">清除</button>
      </div>
    </header>

    <p v-if="payload?.scope_message" class="scope-note">🔒 {{ payload.scope_message }}</p>

    <div v-if="loading" class="card state">正在读取会议数据…</div>
    <div v-else-if="error" class="card state error">{{ error }}</div>

    <template v-else-if="payload">
      <section v-if="payload.summary" class="stats">
        <div class="card stat">
          <span class="k">会议总数</span>
          <span class="v">{{ payload.summary.total }}</span>
        </div>
        <div class="card stat">
          <span class="k">内部 / 外部</span>
          <span class="v small">{{ payload.summary.internal }} / {{ payload.summary.external }}</span>
        </div>
        <div class="card stat">
          <span class="k">总时长</span>
          <span class="v small">{{ payload.summary.duration_minutes }} 分钟</span>
        </div>
        <div class="card stat">
          <span class="k">待办数</span>
          <span class="v warn">{{ payload.summary.todo_count }}</span>
        </div>
      </section>

      <section class="cards">
        <article v-for="meeting in payload.meetings" :key="meeting.id" class="card meeting">
          <div class="meeting-head">
            <span class="title">{{ meeting.title }}</span>
            <span class="tag">{{ typeLabel(meeting.meeting_type) }}</span>
            <span class="tag tag-bucket">{{ BUCKET_LABELS[meeting.bucket] || meeting.bucket }}</span>
            <span class="tag tag-min">{{ meeting.duration_minutes }} 分钟</span>
          </div>
          <p v-if="meeting.brief" class="brief">{{ meeting.brief }}</p>
          <div v-if="meeting.participants.length" class="people">
            <span class="p-label">参与人：</span>
            <span v-for="(person, index) in meeting.participants" :key="index" class="chip">
              {{ personText(person) }}
            </span>
          </div>
          <div v-if="meeting.todos.length" class="todos">
            <span class="p-label">待办：</span>
            <ul>
              <li v-for="(todo, index) in meeting.todos" :key="index">
                {{ todo.title || '（无标题）' }}
                <em v-if="todo.owner || todo.owner_name || todo.assignee">
                  · {{ todo.owner || todo.owner_name || todo.assignee }}
                </em>
              </li>
            </ul>
          </div>
          <div class="meeting-actions">
            <button
              v-if="me && (me.role === 'manager' || me.role === 'admin')"
              type="button"
              class="btn btn-primary btn-sm"
              @click="openDispatch(meeting)"
            >
              派发待办
            </button>
          </div>
        </article>
        <p v-if="!payload.meetings.length" class="empty">该时段暂无会议记录（库内无数据时会自动回退 Vemory 实时拉取）</p>
      </section>
    </template>

    <div v-if="showDispatch" class="modal-backdrop" @click.self="showDispatch = false">
      <section class="card modal">
        <h2>派发待办</h2>
        <p class="sub">{{ dispatchMeeting?.title }}</p>
        <div v-if="dispatchError" class="entry-msg bad">{{ dispatchError }}</div>
        <div v-if="dispatchSuccess" class="entry-msg ok">{{ dispatchSuccess }}</div>
        <div v-for="(row, index) in assignments" :key="index" class="assign-row">
          <input v-model="row.owner" class="input" placeholder="负责人" />
          <input v-model="row.title" class="input grow" placeholder="待办内容" />
          <button type="button" class="btn btn-remove" @click="removeAssignment(index)">✕</button>
        </div>
        <button type="button" class="btn add-btn" @click="addAssignment">+ 添加一行</button>
        <div class="modal-actions">
          <button type="button" class="btn" @click="showDispatch = false">取消</button>
          <button type="button" class="btn btn-primary" :disabled="dispatchBusy" @click="submitDispatch">
            {{ dispatchBusy ? '派发中…' : '派发' }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.meetings {
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
  margin: 0 0 6px;
  font-size: 17px;
}

.sub {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.date-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sep {
  color: var(--faint);
  font-size: 13px;
}

.scope-note {
  font-size: 12px;
  color: var(--amber);
  margin: 0 0 10px;
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
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
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

.stat .v.small {
  font-size: 18px;
}

.stat .v.warn {
  color: var(--amber);
}

.cards {
  display: grid;
  gap: 12px;
}

.meeting {
  padding: 16px 18px;
}

.meeting-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.title {
  font-size: 16px;
  font-weight: 700;
  margin-right: 6px;
}

.tag {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid var(--border-strong);
  color: var(--muted);
}

.tag-bucket {
  color: var(--blue);
  border-color: rgba(78, 158, 245, 0.3);
}

.tag-min {
  color: var(--faint);
}

.brief {
  margin: 10px 0 6px;
  font-size: 13px;
  color: var(--muted);
}

.people,
.todos {
  margin: 8px 0 0;
  font-size: 13px;
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}

.p-label {
  color: var(--faint);
}

.chip {
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  font-size: 12px;
}

.todos ul {
  margin: 0;
  padding-left: 18px;
}

.todos li {
  margin: 3px 0;
}

.todos em {
  color: var(--faint);
  font-style: normal;
}

.meeting-actions {
  margin-top: 12px;
}

.btn-sm {
  padding: 6px 14px;
  font-size: 13px;
}

.empty {
  color: var(--muted);
  text-align: center;
  padding: 32px 0;
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

.assign-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.assign-row .grow {
  flex: 1;
}

.btn-remove {
  padding: 8px 10px;
  color: var(--red);
}

.add-btn {
  width: 100%;
  border-style: dashed;
  color: var(--blue);
  margin-bottom: 14px;
}

.entry-msg {
  font-size: 13px;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 12px;
}

.entry-msg.ok {
  color: var(--green);
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.entry-msg.bad {
  color: var(--red);
  background: rgba(244, 63, 94, 0.08);
  border: 1px solid rgba(244, 63, 94, 0.25);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}
</style>
