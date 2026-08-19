<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

interface Me {
  role: string
}

interface SyncResult {
  date?: string
  [key: string]: unknown
}

const router = useRouter()
const me = ref<Me | null>(null)
const busy = ref(false)
const result = ref<SyncResult | null>(null)
const error = ref('')
const finishedAt = ref('')

const STEP_LABELS: Record<string, string> = {
  vps_dealer_sales: '经销商 Sell-in（vertu-cli → DB）',
  dealer_sales: '经销商 Sell-in（文件回退）',
  pdca_tasks: '待办任务（CSV → DB）',
  daily_reports: '日报/报告（outputs → DB）',
  meetings: '会议（Vemory → DB）',
}

function fmt(value: unknown): string {
  if (typeof value === 'number') return `${value} 条`
  return String(value ?? '—')
}

function stepOk(value: unknown): boolean {
  return typeof value === 'number' || !String(value).startsWith('error:')
}

async function runSync() {
  busy.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await apiPost<SyncResult>('/api/admin/sync', {})
    finishedAt.value = new Date().toLocaleTimeString('zh-CN')
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '同步失败，请稍后重试'
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    me.value = await apiGet<Me>('/api/auth/me')
  } catch {
    me.value = null
  }
})
</script>

<template>
  <AppNav />
  <main class="admin">
    <header class="head">
      <div>
        <h1>数据同步</h1>
        <p class="sub">手动触发 vertu-cli / 文件 → 数据库全量同步（每日 06:00 自动执行）</p>
      </div>
      <button
        v-if="me && (me.role === 'manager' || me.role === 'admin')"
        class="btn btn-primary"
        type="button"
        :disabled="busy"
        @click="runSync"
      >
        {{ busy ? '同步中…（约 1 分钟）' : '立即同步' }}
      </button>
    </header>

    <div v-if="me && me.role !== 'manager' && me.role !== 'admin'" class="card state">
      当前账号无同步权限（需 manager/admin）
    </div>

    <div v-if="error" class="card state error">{{ error }}</div>

    <section v-if="result" class="card result-card">
      <h2>同步结果 <span class="time">{{ result.date }} · {{ finishedAt }}</span></h2>
      <table class="table">
        <thead>
          <tr>
            <th>步骤</th>
            <th class="num">结果</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(value, key) in result" :key="key">
            <template v-if="key !== 'date'">
              <td>{{ STEP_LABELS[key] || key }}</td>
              <td class="num">{{ fmt(value) }}</td>
              <td>
                <span :class="['badge', stepOk(value) ? 'badge-live' : 'badge-missing']">
                  {{ stepOk(value) ? '正常' : '失败' }}
                </span>
              </td>
            </template>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-else-if="!busy" class="card state">
      点击「立即同步」执行全量数据同步：Sell-in、待办、日报、会议将刷新进数据库，
      各页面数据实时来自数据库，无需其他操作。
    </section>
  </main>
</template>

<style scoped>
.admin {
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
  margin: 0 0 14px;
  font-size: 15px;
  color: var(--muted);
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

.result-card {
  padding: 20px 22px;
}

.time {
  font-size: 12px;
  color: var(--faint);
  font-weight: 400;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
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
  padding: 10px;
  border-bottom: 1px solid var(--border);
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
