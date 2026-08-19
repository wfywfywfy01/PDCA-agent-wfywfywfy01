<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface Me {
  role: string
}

interface ModuleItem {
  id: string
  title: string
  description?: string
}

interface Track {
  day: number
  title: string
  modules: ModuleItem[]
}

interface Curriculum {
  title: string
  tracks: Track[]
  pass_criteria: Record<string, unknown>
}

interface Progress {
  username: string
  total_days: number
  total_modules: number
  completed_modules: number
  completed_module_ids: string[]
  progress_pct: number
  current_day: number
  graduated: boolean
}

const router = useRouter()
const me = ref<Me | null>(null)
const curriculum = ref<Curriculum | null>(null)
const progress = ref<Progress | null>(null)
const loading = ref(true)
const error = ref('')
const checkingIn = ref('')
const actionMessage = ref('')

async function load() {
  loading.value = true
  error.value = ''
  const settle = await Promise.allSettled([
    apiGet<Curriculum>('/api/onboarding/curriculum'),
    apiGet<Progress>('/api/onboarding/progress'),
  ])
  const [curriculumR, progressR] = settle
  for (const r of settle) {
    if (r.status === 'rejected' && r.reason instanceof HttpError && r.reason.status === 401) {
      router.replace({ path: '/login', query: { next: '/onboarding' } })
      return
    }
  }
  if (curriculumR.status === 'fulfilled') curriculum.value = curriculumR.value
  if (progressR.status === 'fulfilled') progress.value = progressR.value
  if (curriculumR.status === 'rejected' && progressR.status === 'rejected') {
    error.value =
      curriculumR.reason instanceof HttpError ? curriculumR.reason.detail : '培训数据加载失败'
  }
  loading.value = false
}

function isDone(moduleId: string): boolean {
  return progress.value?.completed_module_ids.includes(moduleId) ?? false
}

function isCurrentDay(day: number): boolean {
  return progress.value?.current_day === day
}

async function checkIn(track: Track, moduleItem: ModuleItem) {
  if (isDone(moduleItem.id)) return
  checkingIn.value = moduleItem.id
  actionMessage.value = ''
  try {
    const payload = await apiPost<{ ok: boolean; progress_pct?: number; graduated?: boolean }>(
      '/api/onboarding/complete',
      { module_id: moduleItem.id, day: track.day },
    )
    if (payload.ok) {
      actionMessage.value = `✅ ${moduleItem.title} 打卡完成`
      await load()
    }
  } catch (err) {
    actionMessage.value = '❌ ' + (err instanceof HttpError ? err.detail : '打卡失败，请稍后重试')
  } finally {
    checkingIn.value = ''
  }
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
  <main class="onboarding">
    <header class="head">
      <div>
        <h1>{{ curriculum?.title || '新人培训' }}</h1>
        <p class="sub">5 天上岗路径 · 模块打卡 · 进度跟踪</p>
      </div>
      <span v-if="progress?.graduated" class="badge badge-live">已毕业</span>
      <span v-else class="badge badge-stale">培训中</span>
    </header>

    <div v-if="error" class="card state error">{{ error }}</div>
    <div v-else-if="loading" class="card state">正在读取课表…</div>

    <template v-else-if="progress && curriculum">
      <section class="card progress-card">
        <div class="progress-head">
          <span>
            完成 {{ progress.completed_modules }}/{{ progress.total_modules }} 模块 ·
            当前第 {{ progress.current_day }} 天
          </span>
          <b>{{ progress.progress_pct }}%</b>
        </div>
        <div class="bar">
          <i :style="{ width: progress.progress_pct + '%' }"></i>
        </div>
      </section>

      <p v-if="actionMessage" class="msg">{{ actionMessage }}</p>

      <section v-for="track in curriculum.tracks" :key="track.day" class="card track">
        <div class="track-head">
          <h2>D{{ track.day }} · {{ track.title }}</h2>
          <span v-if="isCurrentDay(track.day)" class="current-tag">当前进度</span>
        </div>
        <div class="modules">
          <article
            v-for="moduleItem in track.modules"
            :key="moduleItem.id"
            class="module"
            :class="{ done: isDone(moduleItem.id) }"
          >
            <div>
              <span class="m-title">{{ moduleItem.title }}</span>
              <p v-if="moduleItem.description" class="m-desc">{{ moduleItem.description }}</p>
            </div>
            <button
              v-if="!isDone(moduleItem.id)"
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="checkingIn === moduleItem.id || !me || me.role === 'viewer' || me.role === 'dealer'"
              @click="checkIn(track, moduleItem)"
            >
              {{ checkingIn === moduleItem.id ? '打卡中…' : '打卡完成' }}
            </button>
            <span v-else class="done-tag">✓ 已完成</span>
          </article>
        </div>
      </section>
    </template>
  </main>
</template>

<style scoped>
.onboarding {
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
  margin-bottom: 16px;
}

h1 {
  margin: 0 0 4px;
  font-size: 24px;
}

h2 {
  margin: 0;
  font-size: 16px;
}

.sub {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.state {
  padding: 40px;
  text-align: center;
  color: var(--muted);
}

.state.error {
  color: var(--red);
}

.progress-card {
  padding: 16px 20px;
  margin-bottom: 14px;
}

.progress-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  margin-bottom: 10px;
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
  transition: width 0.3s;
}

.msg {
  font-size: 13px;
  color: var(--green);
  margin: 0 0 12px;
}

.track {
  padding: 18px 20px;
  margin-bottom: 14px;
}

.track-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.current-tag {
  font-size: 11px;
  color: var(--blue);
  border: 1px solid rgba(78, 158, 245, 0.35);
  border-radius: 999px;
  padding: 2px 10px;
}

.modules {
  display: grid;
  gap: 10px;
}

.module {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--card-2);
  border: 1px solid var(--border);
}

.module.done {
  opacity: 0.65;
}

.m-title {
  font-size: 14px;
  font-weight: 600;
}

.m-desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.btn-sm {
  padding: 6px 14px;
  font-size: 13px;
  flex-shrink: 0;
}

.done-tag {
  color: var(--green);
  font-size: 13px;
  flex-shrink: 0;
}
</style>
