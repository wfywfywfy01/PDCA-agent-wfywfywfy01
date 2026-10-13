<script setup lang="ts">
import { computed } from 'vue'
import type { Block, BlockTypeSpec } from '@/api/duzhanBlocks'

const props = defineProps<{ specs: BlockTypeSpec[]; blocks: Block[]; disabled?: boolean }>()
const emit = defineEmits<{ (event: 'add', spec: BlockTypeSpec): void }>()
const types = new Set(['group', 'times', 'condition', 'rule'])
const visible = computed(() => props.specs.filter((spec) => types.has(spec.type)))

function unavailable(spec: BlockTypeSpec): boolean {
  return Boolean(props.disabled || (spec.multiple === false && props.blocks.some((block) => block.type === spec.type)))
}
</script>

<template>
  <section class="palette" aria-labelledby="palette-title">
    <div class="palette-head">
      <h3 id="palette-title">添加积木</h3>
      <p>选择模块，插入当前群的规则卡片</p>
    </div>
    <div class="choices">
      <button
        v-for="spec in visible"
        :key="spec.type"
        class="choice"
        type="button"
        :disabled="unavailable(spec)"
        :aria-label="'添加' + spec.label"
        @click="emit('add', spec)"
      >
        <span class="plus" aria-hidden="true">＋</span>
        <span><strong>{{ spec.label }}</strong><small>{{ spec.hint }}</small></span>
        <span v-if="spec.multiple === false && blocks.some((block) => block.type === spec.type)" class="added">已添加</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.palette { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--card); padding: 16px; }
.palette-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.palette h3 { margin: 0; font-size: 15px; }
.palette p { margin: 0; color: var(--muted); font-size: 12px; }
.choices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.choice { min-height: 64px; display: flex; align-items: center; gap: 10px; text-align: left; padding: 9px 11px; border: 1px solid var(--border-strong); border-radius: var(--radius-md); color: var(--text); background: var(--card-2); cursor: pointer; }
.choice:hover:not(:disabled) { border-color: var(--blue); }
.choice:disabled { opacity: .55; cursor: not-allowed; }
.choice strong { display: block; font-size: 13px; }
.choice small { display: block; margin-top: 2px; color: var(--muted); font-size: 11px; line-height: 1.4; }
.plus { color: var(--blue); font-size: 20px; line-height: 1; }
.added { margin-left: auto; flex: none; color: var(--muted); font-size: 11px; }
@media (max-width: 620px) { .choices { grid-template-columns: 1fr; } }
</style>
