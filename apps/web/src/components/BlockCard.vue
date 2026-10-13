<script setup lang="ts">
import { computed } from 'vue'
import { blockSummary, fieldVisible, type Block, type BlockFieldSpec, type BlockTypeSpec } from '@/api/duzhanBlocks'

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

const summary = computed(() => blockSummary(props.block))
const fields = computed(() => props.spec.fields.filter((field) =>
  fieldVisible(field, props.block) && !(props.block.type === 'group' && field.key === 'label'),
))
const options = computed(() => props.groupOptions || [])

function controlId(field: BlockFieldSpec): string {
  return 'block-' + props.index + '-' + field.key
}

function displayLabel(field: BlockFieldSpec): string {
  if (props.block.type === 'group' && field.key === 'channel_id') return '目标群'
  if (props.block.type === 'condition' && field.key === 'value') return '发送时机'
  return field.label
}

function rawText(field: BlockFieldSpec): string {
  const value = props.block[field.key]
  if (Array.isArray(value)) return value.join(', ')
  return value === undefined || value === null ? '' : String(value)
}

function slotChecked(field: BlockFieldSpec, option: string): boolean {
  const value = props.block[field.key]
  return Array.isArray(value) && value.includes(option)
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

function onSlot(field: BlockFieldSpec, option: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const current = Array.isArray(props.block[field.key]) ? [...(props.block[field.key] as string[])] : []
  const next = checked ? [...current, option] : current.filter((item) => item !== option)
  emit('change', field.key, next.sort())
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
        <button class="icon-btn" type="button" :disabled="disabled || !canMoveUp" :aria-label="'上移' + spec.label" @click="emit('move', -1)">↑</button>
        <button class="icon-btn" type="button" :disabled="disabled || !canMoveDown" :aria-label="'下移' + spec.label" @click="emit('move', 1)">↓</button>
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
            <option value="">选择督战官已加入的群聊</option>
            <option v-for="option in options" :key="option.id" :value="option.id">{{ option.label }}</option>
            <option v-if="rawText(field) && !options.some((option) => option.id === rawText(field))" :value="rawText(field)">当前群（未在列表中）</option>
          </select>
          <details class="manual-id"><summary>手动填写群 ID</summary>
            <input type="text" :value="rawText(field)" :disabled="disabled" aria-label="手动输入群 ID" placeholder="粘贴群 ID" @input="onText(field, $event)" />
          </details>
        </template>

        <select v-else-if="field.kind === 'select'" :id="controlId(field)" :value="rawText(field)" :disabled="disabled" @change="onSelect(field, $event)">
          <option v-if="field.required" value="" disabled>请选择{{ displayLabel(field) }}</option>
          <option v-for="option in field.options || []" :key="option" :value="option">{{ optionLabel(field, option) }}</option>
        </select>

        <select v-else-if="block.type === 'condition' && field.key === 'value'" :id="controlId(field)" :value="String(block.value !== false)" :disabled="disabled" @change="emit('change', field.key, ($event.target as HTMLSelectElement).value === 'true')">
          <option value="true">满足条件时发送</option><option value="false" :disabled="block.key === 'has_data'">不满足条件时发送</option>
        </select>

        <label v-else-if="field.kind === 'bool'" class="check">
          <input :id="controlId(field)" type="checkbox" :checked="block[field.key] === true" :disabled="disabled || block.key === 'has_data'" @change="emit('change', field.key, ($event.target as HTMLInputElement).checked)" />
          <span>{{ block[field.key] === true ? '是' : '否' }}</span>
        </label>

        <fieldset v-else-if="field.kind === 'slots'" class="slots" :aria-label="field.label">
          <label v-for="option in field.options || []" :key="option">
            <input type="checkbox" :checked="slotChecked(field, option)" :disabled="disabled" @change="onSlot(field, option, $event)" />
            <span>{{ option }}</span>
          </label>
        </fieldset>

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
.check, .slots, .slots label { display: flex; align-items: center; gap: 8px; }
.slots { flex-wrap: wrap; margin: 0; padding: 0; border: 0; }
.check, .slots label { color: var(--text); cursor: pointer; }
.slots label { padding: 6px 9px; border: 1px solid var(--border); border-radius: 6px; }
.manual-id { margin-top: 8px; color: var(--muted); font-size: 11px; }
.manual-id summary { cursor: pointer; }
.manual-id input { margin-top: 8px; }
</style>
