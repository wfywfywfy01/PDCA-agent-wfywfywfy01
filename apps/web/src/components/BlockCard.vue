<script setup lang="ts">
import { computed, ref } from 'vue'
import { addTimeSlot, blockSummary, fieldVisible, timeStage, type Block, type BlockFieldSpec, type BlockTypeSpec } from '@/api/duzhanBlocks'

export interface GroupOption { id: string; label: string }
const props = defineProps<{
  block: Block
  spec: BlockTypeSpec
  index: number
  total: number
  groupOptions?: GroupOption[]
  disabled?: boolean
  locked?: boolean
  plain?: boolean
  canMoveUp?: boolean
  canMoveDown?: boolean
}>()
const emit = defineEmits<{
  (event: 'change', key: string, value: unknown): void
  (event: 'move', offset: number): void
  (event: 'remove'): void
}>()

const summary = computed(() => blockSummary(props.block, props.spec))
const fields = computed(() => props.spec.fields.filter((field) =>
  fieldVisible(field, props.block) && !(props.block.type === 'group' && field.key === 'label'),
))
const options = computed(() => props.groupOptions || [])
const newSlot = ref('')
const slotError = ref('')

function controlId(field: BlockFieldSpec): string {
  return 'block-' + props.index + '-' + field.key
}

function displayLabel(field: BlockFieldSpec): string {
  if (props.block.type === 'group' && field.key === 'channel_id') return '目标群'
  if (props.block.type === 'condition' && field.key === 'value') return '何时提醒'
  return field.label
}

function rawText(field: BlockFieldSpec): string {
  const value = props.block[field.key]
  if (Array.isArray(value)) return value.join(', ')
  return value === undefined || value === null ? '' : String(value)
}

function timeSlots(field: BlockFieldSpec): string[] {
  const value = props.block[field.key]
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function onText(field: BlockFieldSpec, event: Event) {
  const value = (event.target as HTMLInputElement | HTMLTextAreaElement).value
  if (field.kind === 'names') {
    emit('change', field.key, value.split(',').map((item) => item.trim()).filter(Boolean))
  } else {
    if (props.block.type === 'group' && field.key === 'channel_id' && value !== props.block.channel_id) {
      emit('change', 'label', '')
    }
    emit('change', field.key, value)
  }
}

function onSelect(field: BlockFieldSpec, event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('change', field.key, value)
  if (props.block.type === 'condition' && field.key === 'key' && value === 'has_data') {
    emit('change', 'value', true)
  }
}

function onGroupSelect(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const selected = options.value.find((option) => option.id === id)
  emit('change', 'channel_id', id)
  emit('change', 'label', selected?.label || '')
}

function addSlot(field: BlockFieldSpec) {
  const current = props.block[field.key]
  const slots = timeSlots(field)
  const stage = timeStage(newSlot.value)
  const conflict = slots.find((slot) => slot !== newSlot.value && timeStage(slot) === stage)
  if (conflict) {
    slotError.value = `${stage}已有 ${conflict}，请先删除后再添加。`
    return
  }
  const next = addTimeSlot(current, newSlot.value)
  if (next.length === slots.length) {
    slotError.value = slots.includes(newSlot.value) ? '这个时间已经添加。' : '请输入有效的 24 小时时间。'
    return
  }
  emit('change', field.key, next)
  newSlot.value = ''
  slotError.value = ''
}

function removeSlot(field: BlockFieldSpec, slot: string) {
  const current = Array.isArray(props.block[field.key]) ? props.block[field.key] as string[] : []
  emit('change', field.key, current.filter((item) => item !== slot))
  slotError.value = ''
}

function optionLabel(field: BlockFieldSpec, option: string): string {
  return (field.option_labels && field.option_labels[option]) || option
}
</script>

<template>
  <article class="block-card" :class="{ plain }">
    <header v-if="!plain" class="card-head">
      <span class="order" aria-hidden="true">{{ index + 1 }}</span>
      <div class="titles">
        <h3>{{ spec.label }}</h3>
        <p>{{ summary }}</p>
      </div>
      <div v-if="!locked" class="ops">
        <button v-if="canMoveUp" class="icon-btn" type="button" :disabled="disabled" :aria-label="'上移' + spec.label" @click="emit('move', -1)">↑</button>
        <button v-if="canMoveDown" class="icon-btn" type="button" :disabled="disabled" :aria-label="'下移' + spec.label" @click="emit('move', 1)">↓</button>
        <button class="icon-btn remove" type="button" :disabled="disabled" :aria-label="'删除' + spec.label" @click="emit('remove')">×</button>
      </div>
    </header>
    <p v-if="spec.hint && !plain" class="card-hint">{{ spec.hint }}</p>
    <div class="fields">
      <div v-for="field in fields" :key="field.key" class="field">
        <span v-if="field.kind === 'slots'" class="field-label">
          {{ displayLabel(field) }}<em v-if="field.required">必填</em>
        </span>
        <label v-else :for="controlId(field)" class="field-label">
          {{ displayLabel(field) }}<em v-if="field.required">必填</em>
        </label>

        <template v-if="block.type === 'group' && field.key === 'channel_id' && options.length">
          <select :id="controlId(field)" :value="rawText(field)" :disabled="disabled" @change="onGroupSelect">
            <option value="">选择已接入闭环检查的群聊</option>
            <option v-for="option in options" :key="option.id" :value="option.id">{{ option.label }}</option>
            <option v-if="rawText(field) && !options.some((option) => option.id === rawText(field))" :value="rawText(field)">当前群（未在列表中）</option>
          </select>
          <details class="manual-id"><summary>已有接入群未显示？填写群 ID</summary>
            <input type="text" :value="rawText(field)" :disabled="disabled" aria-label="手动输入群 ID" placeholder="粘贴群 ID" @input="onText(field, $event)" />
          </details>
        </template>

        <select v-else-if="field.kind === 'select'" :id="controlId(field)" :value="rawText(field)" :disabled="disabled" @change="onSelect(field, $event)">
          <option v-if="field.required" value="" disabled>请选择{{ displayLabel(field) }}</option>
          <option v-for="option in field.options || []" :key="option" :value="option">{{ optionLabel(field, option) }}</option>
        </select>

        <select v-else-if="block.type === 'condition' && field.key === 'value'" :id="controlId(field)" :value="String(block.value !== false)" :disabled="disabled" @change="emit('change', field.key, ($event.target as HTMLSelectElement).value === 'true')">
          <option value="true">条件成立时提醒</option><option value="false" :disabled="block.key === 'has_data'">条件不成立时提醒</option>
        </select>

        <label v-else-if="field.kind === 'bool'" class="check">
          <input :id="controlId(field)" type="checkbox" :checked="block[field.key] === true" :disabled="disabled || block.key === 'has_data'" @change="emit('change', field.key, ($event.target as HTMLInputElement).checked)" />
          <span>{{ block[field.key] === true ? '是' : '否' }}</span>
        </label>

        <div v-else-if="field.kind === 'slots'" class="slot-editor" role="group" :aria-label="field.label">
          <div v-if="timeSlots(field).length" class="slots">
            <span v-for="slot in timeSlots(field)" :key="slot" class="slot-chip">
              {{ slot }} <small>{{ timeStage(slot) }}</small>
              <button type="button" :disabled="disabled" :aria-label="'删除发送时间 ' + slot" @click="removeSlot(field, slot)">×</button>
            </span>
          </div>
          <p v-else class="slot-empty">尚未添加发送时间</p>
          <div class="slot-add">
            <input v-model="newSlot" type="time" step="60" :disabled="disabled" aria-label="新发送时间" @keydown.enter.prevent="addSlot(field)" />
            <button class="slot-add-btn" type="button" :disabled="disabled || !newSlot" @click="addSlot(field)">添加时间</button>
          </div>
          <p v-if="slotError" class="slot-error" role="alert">{{ slotError }}</p>
        </div>

        <textarea v-else-if="field.kind === 'textarea'" :id="controlId(field)" rows="3" :value="rawText(field)" :disabled="disabled" @input="onText(field, $event)"></textarea>
        <input v-else :id="controlId(field)" :type="field.kind === 'date' ? 'date' : 'text'" :value="rawText(field)" :disabled="disabled" @input="onText(field, $event)" />
      </div>
    </div>
  </article>
</template>

<style scoped>
.block-card { border: 1px solid var(--border-strong); border-radius: var(--radius-lg); background: var(--card); overflow: hidden; }
.block-card.plain { border: 0; border-radius: 0; background: transparent; }
.plain .fields { padding: 0; }
.card-head { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--border); }
.order { width: 24px; height: 24px; flex: none; display: grid; place-items: center; border-radius: 6px; background: var(--blue-soft); color: var(--blue); font-size: 12px; font-weight: 700; }
.titles { flex: 1; min-width: 0; }
.titles h3 { margin: 0; font-size: 14px; }
.titles p { margin: 2px 0 0; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops { display: flex; gap: 4px; }
.icon-btn { min-width: 30px; min-height: 30px; border: 1px solid var(--border); border-radius: 6px; background: var(--card-2); color: var(--text); cursor: pointer; }
.icon-btn:hover:not(:disabled) { border-color: var(--blue); }
.icon-btn:disabled { opacity: .45; cursor: not-allowed; }
.remove:hover:not(:disabled) { color: var(--red); border-color: var(--red); }
.card-hint { margin: 0; padding: 9px 14px 0; color: var(--muted); font-size: 12px; }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; padding: 14px; }
.field { min-width: 0; display: grid; align-content: start; gap: 6px; font-size: 12px; }
.field-label { color: var(--muted); }
.field em { margin-left: 6px; color: var(--amber); font-style: normal; font-size: 11px; }
.field input[type='text'], .field input[type='date'], .field select, .field textarea { width: 100%; min-width: 0; padding: 9px 10px; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--surface-2); color: var(--text); font-size: 13px; font-family: inherit; }
.field textarea { resize: vertical; }
.check, .slots, .slot-add { display: flex; align-items: center; gap: 8px; }
.slots { flex-wrap: wrap; }
.check { color: var(--text); cursor: pointer; }
.slot-editor { display: grid; gap: 10px; }
.slot-chip { display: inline-flex; align-items: center; gap: 5px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; color: var(--text); }
.slot-chip small { color: var(--muted); font-size: 11px; }
.slot-chip button { border: 0; background: transparent; color: var(--muted); cursor: pointer; font: inherit; line-height: 1; }
.slot-chip button:hover:not(:disabled) { color: var(--red); }
.slot-add input { width: 132px; padding: 8px 9px; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--surface-2); color: var(--text); font: inherit; }
.slot-add-btn { min-height: 35px; padding: 0 12px; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--card-2); color: var(--text); cursor: pointer; }
.slot-add-btn:disabled, .slot-chip button:disabled { opacity: .45; cursor: not-allowed; }
.slot-empty { margin: 0; color: var(--muted); font-size: 12px; }
.slot-error { margin: 0; color: var(--red); font-size: 12px; }
.manual-id { margin-top: 8px; color: var(--muted); font-size: 11px; }
.manual-id summary { cursor: pointer; }
.manual-id input { margin-top: 8px; }
</style>
