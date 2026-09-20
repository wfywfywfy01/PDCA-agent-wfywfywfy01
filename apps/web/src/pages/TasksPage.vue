<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
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
let loadId = 0
const updating = ref(new Set<number>())
const canWrite = computed(() => !!me.value && ['sales', 'manager', 'admin'].includes(me.value.role))

const pendingCount = computed(() => tasks.value.filter((row) => !isDone(row.status)).length)
const highCount = computed(() => tasks.value.filter((row) => !isDone(row.status) && row.priority === 'high').length)
const completionRate = computed(() => (tasks.value.length ? Math.round((doneCount() / tasks.value.length) * 100) : 0))
const PRIORITY_PILLS: Record<string, string> = { high: 'pill-red', medium: 'pill-amber', normal: 'pill-muted' }

function priorityPill(priority: string): string {
  return PRIORITY_PILLS[priority] || 'pill-muted'
}

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
  const id = ++loadId
  loading.value = true
  error.value = ''
  tasks.value = []
  const p = new URLSearchParams({ date: dateText.value })
  if (statusFilter.value) p.set('status', statusFilter.value)
  if (ownerFilter.value) p.set('owner', ownerFilter.value)
  try {
    const payload = await apiGet<{ items: TaskRow[] }>(`/api/task-center/tasks?${p}`)
    if (id === loadId) tasks.value = payload.items
  } catch (err) {
    if (id !== loadId) return
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/tasks' } })
      return
    }
    error.value = err instanceof HttpError ? err.detail : '任务加载失败'
  } finally {
    if (id === loadId) loading.value = false
  }
}

async function toggle(row: TaskRow) {
  if (!canWrite.value || updating.value.has(row.id)) return
  updating.value.add(row.id)
  const next = isDone(row.status) ? 'pending' : 'done'
  try {
    await apiPatch(`/api/task-center/tasks/${row.id}`, { status: next })
    row.status = next
    if (statusFilter.value && statusFilter.value !== next) tasks.value = tasks.value.filter((item) => item.id !== row.id)
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '更新失败'
  } finally {
    updating.value.delete(row.id)
  }
}

async function createTask() {
  if (createBusy.value || !canWrite.value) return
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

const titleInput = ref<HTMLInputElement | null>(null)

async function openCreate() {
  showCreate.value = true
  await nextTick()
  titleInput.value?.focus()
}

function closeCreate() {
  showCreate.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && showCreate.value) closeCreate()
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKeydown)
  apiGet<Me>('/api/auth/me')
    .then((value) => (me.value = value))
    .catch(() => undefined)
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <AppNav />
  <main class="page">
    <header class="page-head">
      <div>
        <h1>任务中心</h1>
        <p class="sub">PDCA 任务全生命周期 · {{ dateText }} · 共 {{ tasks.length }} 项</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="load">刷新</button>
        <button
          v-if="me && me.role !== 'viewer' && me.role !== 'dealer'"
          class="btn btn-primary"
          type="button"
          @click="openCreate"
        >
          + 新建任务
        </button>
      </div>
    </header>

    <section class="stats" aria-label="任务概览">
      <div class="card stat">
        <span class="stat-label">全部任务</span>
        <span class="stat-value num">{{ tasks.length }}</span>
        <span class="stat-note">{{ dateText }}</span>
      </div>
      <div class="card stat">
        <span class="stat-label">待处理</span>
        <span class="stat-value num">{{ pendingCount }}</span>
        <span class="stat-note">尚未完成的条目</span>
      </div>
      <div class="card stat">
        <span class="stat-label">已完成</span>
        <span class="stat-value num">{{ doneCount() }}</span>
        <span class="stat-note">完成率 {{ completionRate }}%</span>
      </div>
      <div class="card stat">
        <span class="stat-label">高优先级</span>
        <span class="stat-value num">{{ highCount }}</span>
        <span class="stat-note">未完成的高优先级任务</span>
      </div>
    </section>

    <section class="card toolbar">
      <div class="field">
        <label class="field-label" for="task-date">日期</label>
        <input id="task-date" v-model="dateText" type="date" class="input date-input" @change="load" />
      </div>
      <div class="field">
        <label class="field-label" for="task-status">状态</label>
        <select id="task-status" v-model="statusFilter" class="input select" @change="load">
          <option value="">全部状态</option>
          <option value="pending">待处理</option>
          <option value="done">已完成</option>
        </select>
      </div>
      <div class="field grow">
        <label class="field-label" for="task-owner">负责人</label>
        <input id="task-owner" v-model="ownerFilter" class="input" placeholder="按负责人筛选，留空为全部" @change="load" />
      </div>
    </section>

    <div v-if="error" class="card alert" role="alert">
      <span>{{ error }}</span>
      <button class="btn btn-sm" type="button" @click="load">重试</button>
    </div>

    <div v-else-if="loading" class="task-grid" aria-busy="true" aria-label="正在读取任务">
      <div v-for="row in 4" :key="row" class="card skeleton-card">
        <span class="skeleton" style="width: 70%" />
        <span class="skeleton" style="width: 40%" />
      </div>
    </div>

    <div v-else-if="!tasks.length" class="card empty-state">
      <h2>当前筛选条件下没有任务</h2>
      <p>换个日期或清空负责人筛选，也可以直接新建一条任务。</p>
      <button
        v-if="me && me.role !== 'viewer' && me.role !== 'dealer'"
        class="btn btn-primary"
        type="button"
        @click="openCreate"
      >
        + 新建任务
      </button>
    </div>

    <section v-else class="task-grid">
      <article v-for="row in tasks" :key="row.id" class="card task" :class="{ done: isDone(row.status) }">
        <label class="task-check">
          <input
            type="checkbox"
            :checked="isDone(row.status)"
            :disabled="!canWrite || updating.has(row.id)"
            :aria-label="'标记完成：' + row.title"
            @change="toggle(row)"
          />
          <span class="task-title">{{ row.title }}</span>
        </label>
        <div class="task-meta">
          <span class="pill" :class="priorityPill(row.priority)">{{ priorityLabel(row.priority) }}</span>
          <span class="meta-item">{{ row.owner || '未指派' }}</span>
          <span class="meta-item faint">{{ row.source || 'workbench' }}</span>
        </div>
      </article>
    </section>

    <div v-if="showCreate" class="overlay" @click.self="closeCreate">
      <section class="card modal" role="dialog" aria-modal="true" aria-labelledby="task-create-title">
        <header class="modal-head">
          <div>
            <h2 id="task-create-title">新建任务</h2>
            <p>归属日期 {{ dateText }}，创建后可在列表中勾选完成。</p>
          </div>
          <button class="btn btn-sm" type="button" @click="closeCreate">取消</button>
        </header>
        <p v-if="createError" class="alert-inline" role="alert">{{ createError }}</p>
        <form class="form-grid" @submit.prevent="createTask">
          <label class="span-2">
            <span class="field-label">任务标题 *</span>
            <input ref="titleInput" v-model="createForm.title" class="input" required placeholder="如：跟进 A 类客户 XXX" />
          </label>
          <label v-if="me?.role !== 'sales'">
            <span class="field-label">负责人</span>
            <input v-model="createForm.owner" class="input" placeholder="留空 = 未指派" />
          </label>
          <label>
            <span class="field-label">优先级</span>
            <select v-model="createForm.priority" class="input">
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="normal">普通</option>
            </select>
          </label>
          <div class="modal-foot span-2">
            <button type="button" class="btn" @click="closeCreate">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="createBusy">
              {{ createBusy ? '创建中…' : '创建任务' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; padding: 14px 16px; margin-bottom: 16px; }
.date-input { width: auto; }
.select { width: auto; min-width: 130px; }

.task-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.task { padding: 16px; display: grid; gap: 12px; border-left: 3px solid var(--border-strong); }
.task.done { opacity: 0.62; border-left-color: var(--green); }
.task-check { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; }
.task-check input { margin-top: 3px; width: 16px; height: 16px; accent-color: var(--blue); }
.task-title { font-size: 14px; font-weight: 600; line-height: 1.45; }
.task.done .task-title { text-decoration: line-through; color: var(--muted); }
.task-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12px; }
.meta-item { color: var(--muted); }
</style>
