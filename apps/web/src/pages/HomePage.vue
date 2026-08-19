<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, HttpError } from '@/api/client'

interface Me {
  username: string
  display_name: string
  role: string
}

interface Fact {
  value: number | null
  state: 'available' | 'missing' | string
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
  closure: { reported: number; expected: number; complete: boolean }
}

const router = useRouter()
const me = ref<Me | null>(null)
const today = ref<TodayPayload | null>(null)
const error = ref('')
const loading = ref(true)

const FACT_LABELS: Record<string, string> = {
  walkin_visits: '今日进店',
  walkin_reported: '已上报门店',
  walkin_missing: '未上报门店',
  logistics_attention: '物流异常/待核查',
}

onMounted(async () => {
  try {
    me.value = await apiGet<Me>('/api/auth/me')
    today.value = await apiGet<TodayPayload>('/api/workbench/today')
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/' } })
      return
    }
    error.value = err instanceof HttpError ? err.detail : '数据加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
})

function badgeClass(state: string): string {
  if (state === 'available') return 'badge badge-live'
  if (state === 'stale') return 'badge badge-stale'
  return 'badge badge-missing'
}
</script>

<template>
  <main class="home-wrap">
    <header class="topbar">
      <div>
        <h1>今日工作台</h1>
        <p v-if="me" class="sub">
          {{ me.display_name || me.username }} · {{ today?.date || '—' }}
        </p>
      </div>
      <span v-if="me" class="badge badge-live">{{ me.role }}</span>
    </header>

    <div v-if="loading" class="card state-card">正在读取今日数据…</div>
    <div v-else-if="error" class="card state-card error">{{ error }}</div>

    <template v-else-if="today">
      <section class="card facts-card">
        <h2>事实</h2>
        <div v-for="(fact, key) in today.facts" :key="key" class="fact-row">
          <span class="fact-name">{{ FACT_LABELS[key] || key }}</span>
          <span class="fact-value">
            <template v-if="fact.state === 'available'">{{ fact.value ?? '—' }}</template>
            <template v-else>未同步</template>
          </span>
          <span class="fact-source">
            <span class="badge" :class="badgeClass(fact.state)">
              {{ fact.state === 'available' ? '正常' : fact.state === 'stale' ? '过期' : '缺失' }}
            </span>
            来源：{{ fact.source }}
            <template v-if="fact.message"> · {{ fact.message }}</template>
          </span>
        </div>
      </section>

      <section class="card actions-card">
        <h2>待处理</h2>
        <a
          v-for="(action, index) in today.actions"
          :key="index"
          class="action-row"
          :href="action.href || undefined"
        >
          <strong>{{ action.title }}</strong>
          <span>{{ action.message }}</span>
        </a>
      </section>
    </template>
  </main>
</template>

<style scoped>
.home-wrap {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
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

.state-card {
  padding: 40px;
  text-align: center;
  color: var(--muted);
}

.state-card.error {
  color: var(--red);
}

.facts-card,
.actions-card {
  padding: 20px 22px;
  margin-bottom: 16px;
}

.fact-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px 16px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}

.fact-row:last-child {
  border-bottom: none;
}

.fact-name {
  color: var(--text);
  font-weight: 600;
}

.fact-value {
  font-size: 22px;
  font-weight: 700;
}

.fact-source {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
}

.action-row {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 10px;
  color: var(--text);
  transition: background 0.15s;
}

.action-row:hover {
  background: rgba(78, 158, 245, 0.08);
}

.action-row span {
  color: var(--muted);
  font-size: 13px;
}
</style>
