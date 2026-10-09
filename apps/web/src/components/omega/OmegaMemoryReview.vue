<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { apiGet, apiPost, HttpError } from '@/api/client'

type Item = { id: string; profile_id: string; section: string; before?: string; value: string; classification: string; quotes: Array<{ text: string }> }
type Proposal = { id: string; revision: number; status: string; can_apply: boolean; payload: { items: Item[] } }
const props = defineProps<{ reportId: string }>()
const proposal = ref<Proposal | null>(null)
const generation = ref<{ status: string; error?: string }>({ status: 'queued' })
const accepted = ref<string[]>([])
const edits = ref<Record<string, string>>({})
const busy = ref(false)
const error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let token = 0
let attempts = 0
let pendingApply: { body: string; key: string } | undefined
const names: Record<string, string> = { source_fact: '原话事实', inference: 'AI 推断', seller_note: '销售补充' }
function message(err: unknown) { return err instanceof HttpError ? err.detail : err instanceof Error ? err.message : '请求失败，请重试' }
async function load(reset = false) {
  const current = token
  const id = props.reportId
  try {
    const result = await apiGet<{ proposal: Proposal | null; generation: { status: string; error?: string } }>(`/api/omega/reports/${id}/memory-proposal`)
    if (current !== token) return
    const changed = result.proposal?.id !== proposal.value?.id || result.proposal?.revision !== proposal.value?.revision
    proposal.value = result.proposal
    generation.value = result.generation
    if (changed || reset) { accepted.value = result.proposal?.payload.items.map(item => item.id) || []; edits.value = {}; pendingApply = undefined }
    if (!result.proposal && ['queued', 'running'].includes(result.generation.status)) {
      if (attempts++ < 120) timer = setTimeout(() => void load(), 1500)
      else error.value = '档案建议仍未完成，可以重新检查。评分和原话已保存。'
    }
  } catch (err) { if (current === token) error.value = message(err) }
}
async function action(kind: 'apply' | 'dismiss' | 'refresh') {
  const row = proposal.value
  if (!row || busy.value) return
  busy.value = true
  error.value = ''
  const current = token
  const payload = { expected_revision: row.revision,
    ...(kind === 'apply' ? { accept_ids: accepted.value, edited_values: Object.fromEntries(Object.entries(edits.value).filter(([id]) => accepted.value.includes(id))) } : {}) }
  const fingerprint = JSON.stringify([row.id, kind, payload])
  if (pendingApply?.body !== fingerprint) pendingApply = { body: fingerprint, key: crypto.randomUUID() }
  try {
    await apiPost(`/api/omega/memory-proposals/${row.id}/${kind}`, { ...payload, request_key: pendingApply.key })
    if (current === token) { pendingApply = undefined; await load(kind === 'refresh') }
  } catch (err) {
    if (current === token) error.value = err instanceof HttpError && err.status === 409 ? '档案有新变化，请刷新建议，核对后重新确认。' : message(err)
  } finally { if (current === token) busy.value = false }
}
async function retry() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  const current = token
  const id = props.reportId
  try { await apiPost(`/api/omega/reports/${id}/memory-proposal/retry`, { request_key: crypto.randomUUID() }); if (current === token) { attempts = 0; await load() } }
  catch (err) { if (current === token) error.value = message(err) }
  finally { if (current === token) busy.value = false }
}
watch(() => props.reportId, () => {
  token++
  if (timer) clearTimeout(timer)
  proposal.value = null; accepted.value = []; edits.value = {}; error.value = ''; busy.value = false; attempts = 0; pendingApply = undefined
  void load()
}, { immediate: true })
onBeforeUnmount(() => { token++; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="memory" aria-labelledby="omega-memory-title">
    <h4 id="omega-memory-title">这次要记住什么</h4>
    <p class="muted">对话和评分已存档。以下建议经销售确认后，才会带入以后的练习。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="proposal?.status === 'pending'">
      <p v-if="!proposal.payload.items.length">本场没有适合写入长期档案的新信息。</p>
      <div v-for="item in proposal.payload.items" :key="item.id" class="memory-item">
        <label class="accept"><input v-model="accepted" type="checkbox" :value="item.id" :disabled="!proposal.can_apply || busy"><span>{{ edits[item.id] ?? item.value }}</span></label>
        <small>{{ names[edits[item.id] !== undefined ? 'seller_note' : item.classification] || item.classification }}</small>
        <details><summary>核对原话与修改</summary><p v-if="item.before">原档案：{{ item.before }}</p><blockquote v-for="(quote, index) in item.quotes" :key="index">{{ quote.text }}</blockquote><label v-if="proposal.can_apply">调整记录<textarea :value="edits[item.id] ?? item.value" maxlength="2000" @input="edits[item.id] = ($event.target as HTMLTextAreaElement).value"></textarea></label><p class="muted">修改后的内容标为销售补充；AI 推断不会变成客户原话。</p></details>
      </div>
      <div v-if="proposal.can_apply" class="actions"><button class="btn btn-primary" type="button" :disabled="busy || !accepted.length" @click="action('apply')">{{ busy ? '处理中…' : '确认并更新档案' }}</button><button class="btn btn-ghost" type="button" :disabled="busy" @click="action('dismiss')">本次不记</button><button v-if="error" class="btn btn-ghost" type="button" :disabled="busy" @click="action('refresh')">刷新建议</button></div>
      <p v-else class="muted">由本场销售核对并确认档案变化。</p>
    </template>
    <p v-else-if="proposal?.status === 'applied'" role="status">已确认，档案已更新。</p>
    <p v-else-if="proposal?.status === 'dismissed'" role="status">本次建议未写入档案。</p>
    <template v-else-if="generation.status === 'failed'"><p role="status">档案建议生成失败，评分报告仍已保存。{{ generation.error }}</p><button class="btn btn-sm" type="button" :disabled="busy" @click="retry">重试档案建议</button></template>
    <p v-else role="status">{{ ['queued', 'running'].includes(generation.status) ? '正在整理档案建议…' : '本场暂无档案建议。' }}</p>
    <button v-if="error && !proposal && generation.status !== 'failed'" class="btn btn-sm" type="button" :disabled="busy" @click="attempts = 0; error = ''; load()">重新检查</button>
  </section>
</template>

<style scoped>
.memory { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border); } h4 { margin: 0 0 8px; } .muted,small { color: var(--muted); font-size: 12px; line-height: 1.6; } .memory-item { padding: 16px 0; border-top: 1px solid var(--border); } .accept { display: flex; gap: 12px; align-items: flex-start; line-height: 1.6; cursor: pointer; } .accept input { width: 20px; height: 20px; flex-shrink: 0; accent-color: var(--blue); } small { display: block; margin: 8px 0 8px 32px; } details { margin-left: 32px; } summary { cursor: pointer; min-height: 32px; font-size: 12px; } textarea { width: 100%; min-height: 80px; } blockquote { margin-left: 0; padding-left: 12px; border-left: 2px solid var(--blue); white-space: pre-wrap; } .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; } .actions .btn { min-height: 44px; }
</style>
