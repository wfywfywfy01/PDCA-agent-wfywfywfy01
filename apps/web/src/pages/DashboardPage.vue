<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECharts } from 'echarts/core'
import { useRouter } from 'vue-router'
import { apiGet, HttpError } from '@/api/client'
import AppNav from '@/components/AppNav.vue'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

interface DealerRow {
  rank: number
  name: string
  wan: number
  quantity: number
}

interface TrendRow {
  month: string
  wan: number
}

interface SellinSummary {
  month: string
  total_wan: number
  dealers: DealerRow[]
  has_data: boolean
  trend: TrendRow[]
  source?: string
  as_of?: string | null
}

const router = useRouter()
const month = ref(currentMonth())
const data = ref<SellinSummary | null>(null)
const loading = ref(true)
const error = ref('')
const chartEl = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null

const totalQuantity = computed(() =>
  data.value?.dealers.reduce((sum, row) => sum + Number(row.quantity || 0), 0) || 0,
)
const monthOverMonth = computed<number | null>(() => {
  const rows = data.value?.trend || []
  if (rows.length < 2) return null
  const previous = Number(rows[rows.length - 2].wan || 0)
  if (!previous) return null
  return ((Number(rows[rows.length - 1].wan || 0) - previous) / previous) * 100
})

function sourceLabel(source?: string): string {
  return source === 'dealer_sales_db_latest_snapshot' ? 'Vertu 同步快照' : source || '—'
}

function asOfLabel(value?: string | null): string {
  if (!value) return '更新时间未知'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '更新时间未知' : `更新于 ${parsed.toLocaleString()}`
}

function currentMonth(): string {
  const d = new Date()
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiGet<SellinSummary>(`/api/dealer/sellin-summary?month=${month.value}`)
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/dashboard' } })
      return
    }
    error.value = err instanceof HttpError ? err.detail : '数据加载失败，请稍后重试'
  } finally {
    loading.value = false
    await nextTick()
    renderChart()
  }
}

function renderChart() {
  if (!chartEl.value || !data.value?.trend?.length) {
    chart?.dispose()
    chart = null
    return
  }
  if (!chart) {
    chart = echarts.init(chartEl.value)
  }
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 46, right: 16, top: 24, bottom: 28 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => v + ' 万' },
    xAxis: {
      type: 'category',
      data: data.value.trend.map((row) => row.month.slice(5) + '月'),
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.15)' } },
      axisLabel: { color: '#94a3b8' },
    },
    yAxis: {
      type: 'value',
      name: '万',
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      axisLabel: { color: '#94a3b8' },
    },
    series: [
      {
        type: 'line',
        data: data.value.trend.map((row) => row.wan),
        smooth: true,
        symbolSize: 7,
        lineStyle: { color: '#4e9ef5', width: 2.5 },
        itemStyle: { color: '#4e9ef5' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(78,158,245,0.28)' },
            { offset: 1, color: 'rgba(78,158,245,0.02)' },
          ]),
        },
      },
    ],
  })
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})

watch(month, load)
</script>

<template>
  <AppNav />
  <main class="dashboard">
    <header class="head">
      <div>
        <h1>数据看板</h1>
        <p class="sub">经销商进货（Sell-in）· 月度汇总与近 6 月趋势</p>
      </div>
      <input v-model="month" class="input month-picker" type="month" />
    </header>

    <div v-if="loading" class="card state">正在读取 {{ month }} 数据…</div>
    <div v-else-if="error" class="card state error">{{ error }}</div>

    <template v-else-if="data">
      <section class="kpi-row">
        <div class="card kpi">
          <span class="kpi-label">当月 Sell-in 合计</span>
          <span class="kpi-value">{{ data.total_wan }} <small>万</small></span>
          <span class="kpi-note">{{ sourceLabel(data.source) }} · {{ asOfLabel(data.as_of) }}</span>
        </div>
        <div class="card kpi">
          <span class="kpi-label">有业绩经销商</span>
          <span class="kpi-value">{{ data.dealers.length }} <small>家</small></span>
          <span class="kpi-note">可下钻查看排名与金额</span>
        </div>
        <div class="card kpi">
          <span class="kpi-label">当月台数</span>
          <span class="kpi-value">{{ totalQuantity }} <small>台</small></span>
          <span class="kpi-note">与金额使用同一快照</span>
        </div>
        <div class="card kpi">
          <span class="kpi-label">较上月</span>
          <span class="kpi-value">
            {{ monthOverMonth == null ? 'N/A' : `${monthOverMonth >= 0 ? '+' : ''}${monthOverMonth.toFixed(1)}%` }}
          </span>
          <span class="kpi-note">基于最近两个月末快照</span>
        </div>
      </section>

      <section class="card chart-card">
        <h2>近 6 月 Sell-in 趋势</h2>
        <div v-if="data.trend.length" ref="chartEl" class="chart"></div>
        <p v-else class="empty">暂无趋势数据</p>
      </section>

      <section class="card table-card">
        <h2>经销商排行</h2>
        <table v-if="data.dealers.length" class="table">
          <thead>
            <tr>
              <th>排名</th>
              <th>经销商</th>
              <th class="num">台数</th>
              <th class="num">金额（万）</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="dealer in data.dealers" :key="dealer.name + dealer.rank">
              <td>{{ dealer.rank }}</td>
              <td class="name">{{ dealer.name }}</td>
              <td class="num">{{ dealer.quantity }}</td>
              <td class="num">{{ dealer.wan }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">当月暂无经销商业绩数据（可能尚未同步）</p>
      </section>
    </template>
  </main>
</template>

<style scoped>
.dashboard {
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

.month-picker {
  width: auto;
  color-scheme: dark;
}

.state {
  padding: 40px;
  text-align: center;
  color: var(--muted);
}

.state.error {
  color: var(--red);
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.kpi {
  padding: 16px 18px;
  display: grid;
  gap: 8px;
}

.kpi-label {
  font-size: 12px;
  color: var(--muted);
}

.kpi-value {
  font-size: 28px;
  font-weight: 700;
}

.kpi-value small {
  font-size: 13px;
  color: var(--muted);
  font-weight: 500;
}

.kpi-note {
  font-size: 12px;
  color: var(--muted);
}

.chart-card,
.table-card {
  padding: 20px 22px;
  margin-bottom: 16px;
}

.chart {
  height: 280px;
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

.name {
  font-weight: 600;
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.empty {
  color: var(--muted);
  font-size: 13px;
  padding: 8px 0;
}
</style>
