<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, apiPatch, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface Me {
  role: string
  display_name: string
  sales_name?: string
}

interface TaskRow {
  id: number
  task_date: string
  title: string
  owner: string
  status: string
  priority: string
  source: string
  updated_at: string
}

const router = useRouter()
const me = ref<Me | null>(null)
const dateText = ref(todayText())
const statusFilter = ref('')
const ownerFilter = ref('')
const tasks = ref<TaskRow[]>([])
const loading = ref(true)
const error = ref('')

const showCreate = ref(false)
const createBusy = ref(false)
const createError = ref('')
const createForm = ref({ title: '', owner: '', priority: 'normal' })

function todayText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

function doneCount(): number {
  return tasks.value.filter((row) => isDone(row.status)).length
}

function isDone(status: string): boolean {
  return ['done', 'completed', 'complete', '已完成'].includes(String(status || '').trim().toLowerCase())
}

async function load() {
  loading.value = true
  error.value = ''
  const p = new URLSearchParams({ date: dateText.value })
  if (statusFilter.value) p.set('status', statusFilter.value)
  if (ownerFilter.value) p.set('owner', ownerFilter.value)
  try {
    const payload = await apiGet<{ items: TaskRow[] }>(`/api/task-center/tasks?${p}`)
    tasks.value = payload.items
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/tasks' } })
      return
    }
    error.value = err instanceof HttpError ? err.detail : '任务加载失败'
  } finally {
    loading.value = false
  }
}

async function toggle(row: TaskRow) {
  const next = isDone(row.status) ? 'pending' : 'done'
  try {
    await apiPatch(`/api/task-center/tasks/${row.id}`, { status: next })
    row.status = next
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '更新失败'
  }
}

async function createTask() {
  createBusy.value = true
  createError.value = ''
  try {
    await apiPost('/api/task-center/tasks', {
      task_date: dateText.value,
      title: createForm.value.title,
      owner: createForm.value.owner,
      priority: createForm.value.priority,
    })
    showCreate.value = false
    createForm.value = { title: '', owner: '', priority: 'normal' }
    await load()
  } catch (err) {
    createError.value = err instanceof HttpError ? err.detail : '创建失败'
  } finally {
    createBusy.value = false
  }
}

function priorityClass(priority: string): string {
  if (priority === 'high') return 'p-high'
  if (priority === 'medium') return 'p-mid'
  return 'p-low'
}

function priorityLabel(priority: string): string {
  return { high: '高', medium: '中', normal: '普通' }[priority] || priority || '普通'
}

onMounted(() => {
  load()
  apiGet<Me>('/api/auth/me')
    .then((value) => (me.value = value))
    .catch(() => undefined)
})
</script>

<template>
  <AppNav />
  <main class="tasks">
    <header class="head">
      <div>
        <h1>任务中心</h1>
        <p class="sub">PDCA 任务全生命周期 · {{ tasks.length }} 项 · 已完成 {{ doneCount() }}</p>
      </div>
      <button
        v-if="me && me.role !== 'viewer' && me.role !== 'dealer'"
        class="btn btn-primary"
        type="button"
        @click="showCreate = true"
      >
        + 新建任务
      </button>
    </header>

    <section class="toolbar card">
      <input v-model="dateText" type="date" class="input date-input" @change="load" />
      <select v-model="statusFilter" class="input select" @change="load">
        <option value="">全部状态</option>
        <option value="pending">待处理</option>
        <option value="done">已完成</option>
      </select>
      <input v-model="ownerFilter" class="input search" placeholder="按负责人筛选" @change="load" />
    </section>

    <div v-if="error" class="card state error">{{ error }}</div>
    <div v-else-if="loading" class="card state">正在读取任务…</div>

    <section v-else class="cards">
      <article v-for="row in tasks" :key="row.id" class="card task" :class="{ done: isDone(row.status) }">
        <label class="check-row">
          <input type="checkbox" :checked="isDone(row.status)" @change="toggle(row)" />
          <span class="t-title">{{ row.title }}</span>
        </label>
        <div class="t-meta">
          <span :class="['priority', priorityClass(row.priority)]">{{ priorityLabel(row.priority) }}</span>
          <span class="owner">{{ row.owner || '未指派' }}</span>
          <span class="source">{{ row.source || 'workbench' }}</span>
        </div>
      </article>
      <p v-if="!tasks.length" class="empty">当日暂无任务，点击右上角新建</p>
    </section>

    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <section class="card modal">
        <h2>新建任务 · {{ dateText }}</h2>
        <div v-if="createError" class="msg bad">{{ createError }}</div>
        <form class="entry-form" @submit.prevent="createTask">
          <label class="span-2">
            任务标题 *
            <input v-model="createForm.title" class="input" required placeholder="如：跟进 A 类客户 XXX" />
          </label>
          <label>
            负责人
            <input v-model="createForm.owner" class="input" placeholder="留空 = 未指派" />
          </label>
          <label>
            优先级
            <select v-model="createForm.priority" class="input">
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="normal">普通</option>
            </select>
          </label>
          <div class="modal-actions span-2">
            <button type="button" class="btn" @click="showCreate = false">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="createBusy">
              {{ createBusy ? '创建中…' : '创建' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<style scoped>
.tasks {
  max-width: 900px;
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
  font-size: 16px;
}

.sub {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.toolbar {
  padding: 12px 14px;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.date-input {
  width: auto;
}

.select {
  width: auto;
  min-width: 130px;
}

.search {
  flex: 1;
  min-width: 160px;
}

.state {
  padding: 40px;
  text-align: center;
  color: var(--muted);
}

.state.error {
  color: var(--red);
}

.cards {
  display: grid;
  gap: 10px;
}

.task {
  padding: 14px 18px;
}

.task.done {
  opacity: 0.6;
}

.check-row {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.check-row input {
  width: 16px;
  height: 16px;
  accent-color: var(--blue);
}

.t-title {
  font-size: 15px;
  font-weight: 600;
}

.task.done .t-title {
  text-decoration: line-through;
  color: var(--muted);
}

.t-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 0 0 26px;
  font-size: 12px;
  color: var(--muted);
}

.priority {
  padding: 1px 8px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 11px;
}

.p-high {
  color: var(--red);
  border: 1px solid rgba(244, 63, 94, 0.35);
}

.p-mid {
  color: var(--amber);
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.p-low {
  color: var(--faint);
  border: 1px solid var(--border-strong);
}

.empty {
  color: var(--muted);
  text-align: center;
  padding: 28px 0;
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
  max-width: 480px;
  padding: 22px 24px;
}

.msg {
  font-size: 13px;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 12px;
}

.msg.bad {
  color: var(--red);
  background: rgba(244, 63, 94, 0.08);
  border: 1px solid rgba(244, 63, 94, 0.25);
}

.entry-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
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

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
