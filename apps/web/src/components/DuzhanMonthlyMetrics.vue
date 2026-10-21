<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getMonthlyMetrics, putMonthlyMetrics, type MonthlyMetrics } from '@/api/duzhanAgents'

const props = defineProps<{ channelId: string; initialMonth: string; disabled: boolean; metricMembers: number }>()
const emit = defineEmits<{ dirty: [value: boolean]; saved: [] }>()
const month = ref(props.initialMonth)
const data = ref<MonthlyMetrics | null>(null)
const baseline = ref('')
const savedMonths = ref<string[]>([])
const pendingMonth = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const message = ref('')
const form = ref<HTMLFormElement | null>(null)
let request = 0
const dirty = computed(() => data.value !== null && JSON.stringify(data.value) !== baseline.value)
watch(dirty, (value) => emit('dirty', value), { immediate: true })
onBeforeUnmount(() => { request++ })

function describe(err: unknown): string {
  const detail = (err as { detail?: unknown })?.detail
  return typeof detail === 'string' ? detail : err instanceof Error ? err.message : String(err)
}

async function load(nextMonth: string) {
  const token = ++request
  month.value = nextMonth
  loading.value = true
  error.value = ''
  message.value = ''
  data.value = null
  try {
    const result = await getMonthlyMetrics(props.channelId, nextMonth)
    if (token !== request) return
    data.value = result.metrics
    baseline.value = JSON.stringify(result.metrics)
    savedMonths.value = result.saved_months
  } catch (err) {
    if (token === request) error.value = describe(err)
  } finally {
    if (token === request) loading.value = false
  }
}

function chooseMonth(event: Event) {
  const input = event.target as HTMLInputElement
  const next = input.value
  input.value = month.value
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(next) || next === month.value) return
  if (dirty.value) pendingMonth.value = next
  else void load(next)
}

async function save(): Promise<boolean> {
  if (!dirty.value && data.value?.source === 'saved') return true
  if (saving.value || !data.value || !form.value?.reportValidity()) return false
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await putMonthlyMetrics({ ...data.value,
      sales_target_wan: data.value.goal === 'break_zero' ? null : data.value.sales_target_wan })
    data.value = result.metrics
    baseline.value = JSON.stringify(result.metrics)
    savedMonths.value = result.saved_months
    message.value = '本月指标已保存，下一次检查生效。'
    emit('saved')
    return true
  } catch (err) {
    error.value = describe(err)
    return false
  } finally {
    saving.value = false
  }
}

function discardMonth() {
  const next = pendingMonth.value
  pendingMonth.value = ''
  void load(next)
}

watch(() => props.channelId, () => { void load(month.value) }, { immediate: true })
defineExpose({ save })
</script>

<template>
  <section class="monthly" aria-labelledby="monthly-title" :aria-busy="loading || saving">
    <header><div><h3 id="monthly-title">本月考核指标</h3><p>只修改当前群、当前月份。其他月份保留。</p></div>
      <label>生效月份<input :value="month" type="month" min="1000-01" max="9999-12" :disabled="disabled || loading || saving" @change="chooseMonth" /></label>
    </header>
    <p v-if="savedMonths.length" class="hint">已保存月份：{{ savedMonths.join('、') }}</p>
    <div v-if="pendingMonth" class="notice" role="status">本月有未保存的指标。
      <button class="btn btn-sm" type="button" @click="discardMonth">放弃改动，切到 {{ pendingMonth }}</button>
      <button class="btn btn-sm" type="button" @click="pendingMonth = ''">继续编辑</button>
    </div>
    <p v-if="loading" role="status">正在读取本月指标…</p>
    <form v-else-if="data" ref="form" @submit.prevent="save">
      <p class="hint">{{ data.source === 'saved' ? '使用已保存的本月指标。' : data.source === 'bundled' ? '当前沿用原配置，修改后保存即可。' : '本月业绩目标待填写；MTO 默认每人每天 4 款、单款 30 万元。' }}</p>
      <fieldset :disabled="disabled || saving"><legend class="sr-only">本月指标</legend>
        <label>业绩目标方式<select v-model="data.goal"><option value="amount">填写金额</option><option value="break_zero">破零</option></select></label>
        <label v-if="data.goal === 'amount'">本月业绩目标（万元）<input v-model.number="data.sales_target_wan" type="number" min="0.01" max="1000000000" step="0.01" required placeholder="例如 800，表示 800 万元" /></label>
        <label>MTO 每人每天（款）<input v-model.number="data.mto_daily_count" type="number" min="1" max="100" step="1" required /></label>
        <label>MTO 单款最低金额（万元）<input v-model.number="data.mto_min_wan" type="number" min="0.01" max="1000000" step="0.01" required /></label>
      </fieldset>
      <p class="hint">人民币万元。MTO 专项考核 {{ metricMembers }} 人，每日合计 {{ Number(data.mto_daily_count) * metricMembers }} 款；“仅追待办”成员不承担此配额。</p>
      <div class="footer"><button class="btn" type="submit" :disabled="disabled || saving || (!dirty && data.source === 'saved')">{{ saving ? '正在保存…' : '保存本月指标' }}</button><span v-if="dirty">指标未保存</span></div>
    </form>
    <p v-if="error" class="error" role="alert">{{ error }} <button v-if="!dirty" class="btn btn-sm" type="button" :disabled="disabled || loading" @click="load(month)">重新载入</button></p>
    <p v-if="error && dirty" class="hint">输入已保留。若提示已被其他页面修改，请先记下本次修改，再放弃并重新载入。</p>
    <button v-if="error && dirty" class="btn btn-sm" type="button" :disabled="disabled || saving" @click="pendingMonth = month">放弃本次指标改动并重新载入</button>
    <p v-if="message" class="success" role="status">{{ message }}</p>
  </section>
</template>

<style scoped>
.monthly { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; background: var(--surface-2); }
header { display: flex; justify-content: space-between; align-items: start; flex-wrap: wrap; gap: 12px; }
h3 { margin: 0 0 4px; font-size: 15px; }
p { margin: 8px 0; font-size: 12px; line-height: 1.6; color: var(--muted); }
label { display: grid; gap: 6px; font-size: 12px; color: var(--text); min-width: 0; }
input, select { min-width: 0; width: 100%; box-sizing: border-box; color: var(--text); background: var(--card); border: 1px solid var(--border-strong); border-radius: var(--radius-md); padding: 9px; font: inherit; }
input:focus-visible, select:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
fieldset { border: 0; padding: 0; margin: 14px 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.footer { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 12px; font-size: 12px; color: var(--amber); }
.notice { margin: 12px 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--amber); font-size: 12px; }
.error { color: var(--red); } .success { color: var(--green); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
@media (max-width: 480px) { fieldset { grid-template-columns: 1fr; } }
</style>
