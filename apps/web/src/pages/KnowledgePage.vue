<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppNav from '@/components/AppNav.vue'
import { apiGet, apiPost, HttpError } from '@/api/client'

interface Dealer { store_id: string; name: string; dealer_id: string }
interface Scope { enabled: boolean; scope: string; dealers: Dealer[]; can_export_original: boolean }
interface Citation {
  asset_id?: string; asset_version_id?: string; title?: string; original_name?: string; version_number?: number
  page_start?: number | null; page_end?: number | null
  timestamp_start?: number | null; timestamp_end?: number | null
}
interface Result {
  asset_id: string; asset_version_id?: string; text: string; category: string; sensitivity: string
  semantic_similarity: number | null; lexical_score: number | null
  retrieval_kind?: string; suggested_caption?: string; citation: Citation
}
interface Answer { status: string; answer: string; citations: Citation[]; evidence_count: number; model?: string }

const router = useRouter()
const scope = ref<Scope | null>(null)
const mode = ref<'evidence' | 'answer'>('evidence')
const query = ref('')
const dealerId = ref('')
const category = ref('')
const busy = ref(false)
const error = ref('')
const results = ref<Result[]>([])
const answer = ref<Answer | null>(null)
const exportDialog = ref<HTMLDialogElement | null>(null)
const exportRow = ref<Result | null>(null)
const exportPassword = ref('')
const exportReason = ref('')
const exportBusy = ref(false)
const exportError = ref('')

const categories: Record<string, string> = {
  dealer_profile: '经销商档案', contract_compliance: '合同与合规', store_display: '门店陈列',
  product_policy: '产品与政策', sales_inventory: '销售与库存', marketing_training: '市场与培训',
  communications: '沟通记录', logistics_after_sales: '物流与售后', finance_settlement: '财务结算',
  media: '图片与媒体', unclassified: '未分类',
}
const sensitivity: Record<string, string> = { internal: '内部', confidential: '保密', restricted: '受限' }
const imagePattern = /\.(?:jpe?g|png|webp)$/i

const hasOutput = computed(() => results.value.length > 0 || answer.value !== null)

function timeText(value?: number | null): string {
  const seconds = Math.max(0, Math.floor(Number(value) || 0))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

function citationLocation(item: Citation): string {
  if (item.timestamp_start != null) {
    return `${timeText(item.timestamp_start)}-${timeText(item.timestamp_end ?? item.timestamp_start)}`
  }
  if (item.page_start != null) {
    return item.page_end && item.page_end !== item.page_start
      ? `第 ${item.page_start}-${item.page_end} 页` : `第 ${item.page_start} 页`
  }
  return ''
}

function scoreText(row: Result): string {
  if (row.retrieval_kind === 'image_semantic' && row.semantic_similarity != null) {
    return `画面匹配 ${Math.round(row.semantic_similarity * 100)}%`
  }
  if (row.lexical_score != null) return '关键词命中'
  if (row.semantic_similarity != null) return `语义相似 ${Math.round(row.semantic_similarity * 100)}%`
  return '相关证据'
}

function previewUrl(assetId?: string, versionId?: string): string {
  const path = `/api/knowledge/assets/${encodeURIComponent(assetId || '')}/content`
  return versionId ? `${path}?${new URLSearchParams({ asset_version_id: versionId })}` : path
}

async function loadScope() {
  try {
    scope.value = await apiGet<Scope>('/api/knowledge/scope')
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/knowledge' } })
      return
    }
    error.value = err instanceof HttpError ? err.detail : '资料库范围读取失败'
  }
}

async function submit() {
  const value = query.value.trim()
  if (!value) return
  busy.value = true
  error.value = ''
  results.value = []
  answer.value = null
  const body = {
    query: value,
    dealer_id: dealerId.value || undefined,
    category: category.value || undefined,
    top_k: mode.value === 'evidence' ? 8 : 6,
  }
  try {
    if (mode.value === 'answer') {
      answer.value = await apiPost<Answer>('/api/knowledge/answers', body)
    } else {
      const payload = await apiPost<{ items: Result[] }>('/api/knowledge/search', body)
      results.value = payload.items || []
    }
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/knowledge' } })
      return
    }
    error.value = err instanceof HttpError ? err.detail : '资料检索失败'
  } finally {
    busy.value = false
  }
}

function openExport(row: Result) {
  exportRow.value = row
  exportPassword.value = ''
  exportReason.value = ''
  exportError.value = ''
  exportDialog.value?.showModal()
}

function closeExport() {
  if (exportBusy.value) return
  exportPassword.value = ''
  exportDialog.value?.close()
}

async function downloadOriginal() {
  const row = exportRow.value
  const reason = exportReason.value.trim()
  if (!row || exportBusy.value || reason.length < 10 || !exportPassword.value) return
  exportBusy.value = true
  exportError.value = ''
  try {
    await apiPost('/api/knowledge/reauth', { password: exportPassword.value })
    exportPassword.value = ''
    const grantResponse = await fetch('/api/knowledge/exports', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ asset_id: row.asset_id, reason, confirmation: 'export-original' }),
    })
    const grant = await grantResponse.json()
    if (!grantResponse.ok) throw new Error(grant.detail || '原件导出授权失败')
    const response = await fetch(`/api/knowledge/exports/${encodeURIComponent(grant.export_id)}/download`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ export_token: grant.download_token }),
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(payload.detail || '原件导出失败')
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    const filename = response.headers.get('content-disposition')?.match(/filename\*=UTF-8''([^;]+)/)?.[1]
    link.download = filename ? decodeURIComponent(filename) : row.citation.original_name || 'knowledge-asset'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    exportDialog.value?.close()
  } catch (err) {
    exportError.value = err instanceof Error ? err.message : '原件导出失败'
  } finally {
    exportPassword.value = ''
    exportBusy.value = false
  }
}

onMounted(loadScope)
</script>

<template>
  <AppNav />
  <main class="knowledge">
    <header class="page-head">
      <div>
        <p class="eyebrow">DEALER KNOWLEDGE</p>
        <h1>经销商资料库</h1>
        <p class="sub">按当前账号的数据范围检索，结果脱敏并保留文件、页码或时间戳引用。</p>
      </div>
      <span :class="['service', scope?.enabled ? 'online' : 'offline']">
        {{ scope?.enabled ? '服务已连接' : '服务未启用' }}
      </span>
    </header>

    <form class="query-panel" @submit.prevent="submit">
      <div class="mode" aria-label="查询模式">
        <button type="button" :class="{ active: mode === 'evidence' }" @click="mode = 'evidence'">查证据</button>
        <button type="button" :class="{ active: mode === 'answer' }" @click="mode = 'answer'">AI 回答</button>
      </div>
      <div class="filters">
        <label>
          <span>经销商范围</span>
          <select v-model="dealerId" class="input">
            <option value="">全部可见资料</option>
            <option v-for="dealer in scope?.dealers || []" :key="dealer.dealer_id" :value="dealer.dealer_id">
              {{ dealer.name }}
            </option>
          </select>
        </label>
        <label>
          <span>资料分类</span>
          <select v-model="category" class="input">
            <option value="">全部分类</option>
            <option v-for="(label, key) in categories" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
      </div>
      <div class="search-row">
        <label class="sr-only" for="knowledge-query">查询内容</label>
        <input id="knowledge-query" v-model="query" class="input search" type="search" maxlength="500"
          autocomplete="off" placeholder="例如：找 VMG 发布会中适合社媒发布的现场照片" />
        <button class="btn btn-primary submit" type="submit" :disabled="busy || !scope?.enabled || !query.trim()">
          {{ busy ? '处理中' : mode === 'answer' ? '生成回答' : '检索' }}
        </button>
      </div>
    </form>

    <div v-if="error" class="notice error" role="alert">{{ error }}</div>
    <div v-else-if="busy" class="notice" role="status">正在读取已处理资料...</div>
    <div v-else-if="!hasOutput" class="notice">查询结果只显示当前账号有权访问的资料。图片为带水印预览，原件仅管理员可导出。</div>

    <section v-if="answer" class="answer" aria-labelledby="answer-title">
      <div class="section-head">
        <h2 id="answer-title">AI 回答</h2>
        <span>{{ answer.evidence_count }} 条证据</span>
      </div>
      <p class="answer-text">{{ answer.answer }}</p>
      <ol v-if="answer.citations.length" class="citation-list">
        <li v-for="(item, index) in answer.citations" :key="`${item.asset_id}-${index}`">
          <a v-if="item.asset_id" :href="previewUrl(item.asset_id, item.asset_version_id)" target="_blank" rel="noopener">
            {{ item.title || item.original_name }}
          </a>
          <span v-else>{{ item.title || item.original_name }}</span>
          <small>{{ item.original_name }} {{ citationLocation(item) }}</small>
        </li>
      </ol>
    </section>

    <section v-if="results.length" class="results" aria-labelledby="results-title">
      <div class="section-head">
        <h2 id="results-title">检索结果</h2>
        <span>{{ results.length }} 项</span>
      </div>
      <article v-for="(row, index) in results" :key="`${row.asset_id}-${index}`" class="result">
        <a v-if="imagePattern.test(row.citation.original_name || '')" class="preview" :href="previewUrl(row.asset_id, row.citation.asset_version_id || row.asset_version_id)" target="_blank" rel="noopener">
          <img :src="previewUrl(row.asset_id, row.citation.asset_version_id || row.asset_version_id)" :alt="`${row.citation.title || row.citation.original_name} 预览`" loading="lazy" />
        </a>
        <div class="result-body">
          <div class="result-head">
            <h3>{{ row.citation.title || row.citation.original_name || '未命名资料' }}</h3>
            <span class="score">{{ scoreText(row) }}</span>
          </div>
          <p>{{ row.text }}</p>
          <blockquote v-if="row.suggested_caption">{{ row.suggested_caption }}</blockquote>
          <div class="meta">
            <span>{{ row.citation.original_name }}</span>
            <span>v{{ row.citation.version_number || 1 }}</span>
            <span>{{ categories[row.category] || row.category }}</span>
            <span>{{ sensitivity[row.sensitivity] || row.sensitivity }}</span>
            <span v-if="citationLocation(row.citation)">{{ citationLocation(row.citation) }}</span>
          </div>
          <a class="export" :href="previewUrl(row.asset_id, row.citation.asset_version_id || row.asset_version_id)" target="_blank" rel="noopener">查看引用</a>
          <button v-if="scope?.can_export_original" class="export" type="button" @click="openExport(row)">导出原件</button>
        </div>
      </article>
    </section>
    <dialog ref="exportDialog" class="export-dialog" aria-labelledby="export-title" @cancel.prevent="closeExport">
      <form @submit.prevent="downloadOriginal">
        <h2 id="export-title">下载原件</h2>
        <label>管理员密码<input v-model="exportPassword" class="input" type="password" autocomplete="current-password" required :disabled="exportBusy" /></label>
        <label>下载原因<textarea v-model="exportReason" class="input" minlength="10" maxlength="500" required :disabled="exportBusy"></textarea></label>
        <p v-if="exportError" role="alert">{{ exportError }}</p>
        <div class="export-actions">
          <button type="button" class="btn" :disabled="exportBusy" @click="closeExport">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="exportBusy">{{ exportBusy ? '处理中' : '验证并下载' }}</button>
        </div>
      </form>
    </dialog>
  </main>
</template>

<style scoped>
.knowledge { max-width: 1180px; margin: 0 auto; padding: 28px 20px 72px; }
.page-head, .section-head, .result-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; }
.eyebrow { margin: 0 0 6px; color: var(--red); font-size: 11px; font-weight: 700; }
h1 { margin: 0; font-size: 28px; }
.sub { margin: 7px 0 0; color: var(--muted); font-size: 13px; }
.service { margin-top: 8px; font-size: 12px; color: var(--muted); }
.service::before { content: ''; display: inline-block; width: 7px; height: 7px; margin-right: 7px; border-radius: 50%; background: var(--red); }
.service.online::before { background: var(--green); }
.query-panel { margin-top: 24px; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 18px 0; }
.mode { display: inline-flex; border: 1px solid var(--border-strong); margin-bottom: 16px; }
.mode button { min-width: 96px; border: 0; border-right: 1px solid var(--border-strong); padding: 8px 16px; background: transparent; color: var(--muted); cursor: pointer; }
.mode button:last-child { border-right: 0; }
.mode button.active { background: var(--blue-soft); color: var(--blue); font-weight: 700; }
.filters { display: grid; grid-template-columns: repeat(2, minmax(0, 260px)); gap: 12px; margin-bottom: 12px; }
.filters label { display: grid; gap: 6px; color: var(--muted); font-size: 12px; }
.search-row { display: flex; gap: 10px; }
.search { min-width: 0; }
.submit { flex: 0 0 112px; }
.notice { border-left: 2px solid var(--blue); margin-top: 18px; padding: 12px 14px; background: rgba(78,158,245,.07); color: var(--muted); font-size: 13px; }
.notice.error { border-color: var(--red); color: var(--red); background: rgba(244,63,94,.07); }
.answer, .results { margin-top: 30px; }
.section-head { align-items: center; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.section-head h2 { margin: 0; font-size: 15px; }
.section-head span { color: var(--muted); font-size: 12px; }
.answer-text { font-size: 15px; line-height: 1.8; white-space: pre-wrap; }
.citation-list { margin: 18px 0 0; padding-left: 24px; color: var(--muted); }
.citation-list li { margin: 8px 0; }
.citation-list small { display: block; margin-top: 3px; color: var(--faint); }
.result { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 20px; padding: 20px 0; border-bottom: 1px solid var(--border); }
.preview { display: block; width: 220px; aspect-ratio: 4 / 3; background: var(--card); overflow: hidden; }
.preview img { width: 100%; height: 100%; object-fit: cover; display: block; }
.result-body { min-width: 0; }
.result-head h3 { margin: 0; font-size: 15px; overflow-wrap: anywhere; }
.score { color: var(--muted); font-size: 12px; flex: 0 0 auto; }
.result-body > p { margin: 10px 0; color: #cbd5e1; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
blockquote { margin: 12px 0; padding: 10px 12px; border-left: 2px solid var(--amber); background: rgba(245,158,11,.06); color: #dbe3ef; font-size: 13px; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--faint); font-size: 11px; overflow-wrap: anywhere; }
.export { display: inline-block; margin: 12px 16px 0 0; padding: 0; border: 0; background: none; color: var(--blue); cursor: pointer; font-size: 12px; }
.export-dialog { box-sizing: border-box; width: 440px; max-width: calc(100% - 28px); border: 1px solid var(--border); border-radius: 8px; background: var(--card); color: var(--text); padding: 24px; }
.export-dialog::backdrop { background: rgba(0,0,0,.6); }
.export-dialog h2 { margin: 0 0 18px; font-size: 18px; }
.export-dialog label { display: grid; gap: 6px; margin: 14px 0; font-size: 13px; }
.export-dialog textarea { min-height: 90px; resize: vertical; }
.export-dialog p { color: var(--red); overflow-wrap: anywhere; }
.export-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
@media (max-width: 700px) {
  .knowledge { padding: 20px 14px 48px; }
  .page-head { display: block; }
  .filters { grid-template-columns: 1fr; }
  .search-row { align-items: stretch; }
  .submit { flex-basis: 96px; padding-inline: 10px; }
  .result { grid-template-columns: 1fr; }
  .preview { width: 100%; max-width: 440px; }
}
</style>
