<script setup lang="ts">
import { ref } from 'vue'
import { apiRequest, HttpError } from '@/api/client'
import type { MeetingMaterial } from './omega-types'

const props = defineProps<{ modelValue: MeetingMaterial[]; hint?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: MeetingMaterial[]]; busy: [value: boolean] }>()
const busy = ref(false)
const error = ref('')

function update(index: number, changes: Partial<MeetingMaterial>) {
  emit('update:modelValue', props.modelValue.map((item, at) => at === index ? { ...item, ...changes } : item))
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length || busy.value) return
  error.value = ''
  if (props.modelValue.length + files.length > 3) { error.value = '每场最多 3 份资料'; return }
  busy.value = true
  emit('busy', true)
  try {
    const added: MeetingMaterial[] = []
    for (const file of files) {
      if (file.size > 5 * 1024 * 1024) throw new Error(`${file.name} 超过 5 MB`)
      const body = new FormData()
      body.append('file', file)
      const response = await apiRequest('/api/omega/materials/extract', { method: 'POST', body })
      const extracted = await response.json() as Pick<MeetingMaterial, 'name' | 'text' | 'truncated'>
      added.push({ ...extracted, purpose: 'reference', visibility: 'shared' })
    }
    emit('update:modelValue', [...props.modelValue, ...added])
  } catch (err) { error.value = err instanceof HttpError ? err.detail : err instanceof Error ? err.message : '资料读取失败' }
  finally { busy.value = false; emit('busy', false) }
}
</script>

<template>
  <section class="materials" aria-label="本次会议资料">
    <h3>本次会议资料 <small>可选</small></h3>
    <p>{{ hint || '上传本次会议要用的资料、培训内容或命题。' }}资料只随本场练习保存，不进入团队预设或长期档案；组内有权限的人可查看。</p>
    <label class="file-choice">添加文件<input type="file" multiple accept=".txt,.md,.csv,.pdf,.docx,.pptx,.xlsx" :disabled="disabled || busy || modelValue.length >= 3" @change="upload"></label>
    <small>TXT、MD、CSV、PDF、DOCX、PPTX、XLSX；每份不超过 5 MB，最多 3 份。仅提取文字，长文取前 1800 字。</small>
    <p v-if="busy" role="status">正在读取资料…</p><p v-if="error" role="alert" class="error">{{ error }}</p>
    <div v-for="(item, index) in modelValue" :key="index" class="material">
      <div class="material-head"><strong>{{ item.name }}</strong><button type="button" :disabled="disabled" @click="emit('update:modelValue', modelValue.filter((_, at) => at !== index))">移除</button></div>
      <div class="options"><label>用途<select :value="item.purpose" :disabled="disabled" @change="update(index, { purpose: ($event.target as HTMLSelectElement).value as MeetingMaterial['purpose'] })"><option value="reference">会议资料</option><option value="content">培训内容</option><option value="topic">会议命题</option></select></label><label>给谁看<select :value="item.visibility" :disabled="disabled" @change="update(index, { visibility: ($event.target as HTMLSelectElement).value as MeetingMaterial['visibility'] })"><option value="shared">模拟对手与教练</option><option value="coach">仅复盘教练</option></select></label></div>
      <label>提取文字，可在开练前修改<textarea :value="item.text" :disabled="disabled" rows="3" maxlength="1800" @input="update(index, { text: ($event.target as HTMLTextAreaElement).value })"></textarea></label>
      <small v-if="item.truncated">原文件更长，本次仅使用上方文字。请确认关键段落已包含。</small>
    </div>
  </section>
</template>

<style scoped>
.materials { margin: 16px 0; padding: 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--card-2); }
h3 { margin: 0 0 6px; font-size: 16px; } h3 small { font-size: 12px; font-weight: 400; }
p,small { color: var(--muted); line-height: 1.5; font-size: 12px; } p { margin: 6px 0 10px; }
.file-choice { display: inline-flex; align-items: center; min-height: 44px; padding: 0 14px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }
.file-choice input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.file-choice:focus-within { outline: 2px solid var(--blue); outline-offset: 2px; }
.material { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
.material-head { display: flex; justify-content: space-between; gap: 8px; } .material-head strong { overflow-wrap: anywhere; }
.material-head button { border: 0; background: transparent; color: var(--blue); min-height: 44px; cursor: pointer; }
.options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
label:not(.file-choice) { display: grid; gap: 4px; margin-top: 8px; font-size: 12px; }
select,textarea { width: 100%; min-height: 44px; } textarea { resize: vertical; }
.error { color: var(--red); } @media(max-width:600px) { .options { grid-template-columns: 1fr; } }
</style>
