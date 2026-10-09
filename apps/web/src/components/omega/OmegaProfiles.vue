<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiGet, HttpError } from '@/api/client'

const props = defineProps<{ salesId: number }>()
const kind = ref<'sales' | 'dealer' | 'opportunity'>('sales')
const dealerId = ref('')
const opportunityId = ref('')
const dealers = ref<Array<{ dealer_id: string; name: string }>>([])
const opportunities = ref<Array<{ id: string; title: string }>>([])
const entries = ref<Array<{ id: string; section: string; value: string; classification: string; source_session_id: string; created_at: string; quotes: Array<{ text: string }> }>>([])
const error = ref('')
const loading = ref(false)
let token = 0
let dealerToken = 0
const emit = defineEmits<{ openSession: [id: string] }>()
const classifications: Record<string, string> = { source_fact: '原话事实', inference: 'AI 推断', seller_note: '销售补充' }
async function load() {
  const current = ++token
  entries.value = []
  error.value = ''
  const subject = kind.value === 'sales' ? String(props.salesId) : kind.value === 'dealer' ? dealerId.value : opportunityId.value
  if (!subject) { loading.value = false; return }
  loading.value = true
  try {
    const result = await apiGet<{ entries: typeof entries.value }>(`/api/omega/profiles?kind=${kind.value}&subject_id=${encodeURIComponent(subject)}`)
    if (current === token) entries.value = result.entries
  } catch (err) { if (current === token) error.value = err instanceof HttpError ? err.detail : '读取档案失败，请重试' }
  finally { if (current === token) loading.value = false }
}
watch([kind, opportunityId, () => props.salesId], () => void load())
watch(dealerId, async (id) => {
  const current = ++dealerToken
  opportunityId.value = ''; opportunities.value = []
  void load()
  if (id) {
    try {
      const rows = await apiGet<typeof opportunities.value>(`/api/omega/opportunities?dealer_id=${encodeURIComponent(id)}`)
      if (current === dealerToken) opportunities.value = rows
    } catch (err) { if (current === dealerToken) error.value = err instanceof HttpError ? err.detail : '读取事项失败' }
  }
})
onMounted(async () => {
  void load()
  try { dealers.value = (await apiGet<{ dealers: typeof dealers.value }>('/api/knowledge/scope')).dealers }
  catch (err) { error.value = err instanceof HttpError ? err.detail : '读取客户列表失败' }
})
onBeforeUnmount(() => { token++; dealerToken++ })
</script>

<template>
  <section class="card profiles"><h2>已确认的档案</h2><p>每位销售、代理和合作事项分别保存。只展示你有权查看、且已确认生效的记录。</p>
    <div class="tabs" role="group" aria-label="档案类型"><button v-for="(name,value) in {sales:'我的成长',dealer:'代理档案',opportunity:'合作事项'}" :key="value" class="btn" type="button" :aria-pressed="kind === value" @click="kind = value">{{ name }}</button></div>
    <label v-if="kind !== 'sales'">代理<select v-model="dealerId"><option value="">请选择</option><option v-for="dealer in dealers" :key="dealer.dealer_id" :value="dealer.dealer_id">{{ dealer.name }}</option></select></label>
    <label v-if="kind === 'opportunity' && dealerId">合作事项<select v-model="opportunityId"><option value="">请选择</option><option v-for="row in opportunities" :key="row.id" :value="row.id">{{ row.title }}</option></select></label>
    <p v-if="error" role="alert">{{ error }} <button class="btn btn-sm" type="button" @click="load">重试</button></p><p v-if="loading" role="status">正在读取…</p>
    <p v-else-if="!entries.length">暂无已确认记录。</p>
    <article v-for="entry in entries" :key="entry.id"><small>{{ classifications[entry.classification] || entry.classification }} · {{ new Date(entry.created_at).toLocaleDateString() }}</small><p>{{ entry.value }}</p><details><summary>查看来源证据</summary><blockquote v-for="(quote, index) in entry.quotes" :key="index">{{ quote.text }}</blockquote><button class="btn btn-sm btn-ghost" type="button" @click="emit('openSession', entry.source_session_id)">打开原始会话</button></details></article>
  </section>
</template>

<style scoped>
.profiles { padding: 24px; } h2 { margin-top: 0; } .profiles > p,small { color: var(--muted); font-size: 13px; line-height: 1.6; } .tabs { display: flex; gap: 8px; margin: 20px 0; flex-wrap: wrap; } button[aria-pressed=true] { border-color: var(--blue); background: var(--blue-soft); } label { display: grid; gap: 8px; margin-bottom: 16px; } select { min-height: 44px; } article { padding: 16px 0; border-top: 1px solid var(--border); } article p { line-height: 1.7; white-space: pre-wrap; } summary { cursor: pointer; min-height: 32px; font-size: 12px; } blockquote { padding-left: 12px; border-left: 2px solid var(--blue); margin-left: 0; } @media(max-width:600px) { .profiles { padding: 16px; } }
</style>
