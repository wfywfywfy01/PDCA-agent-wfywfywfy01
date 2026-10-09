<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{ items: { to: string; label: string; icon?: string }[] }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const router = useRouter()
const query = ref('')
const active = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

const results = computed(() => {
  const q = query.value.trim().toLowerCase()
  const list = q ? props.items.filter((item) => item.label.toLowerCase().includes(q)) : props.items
  return list.slice(0, 12)
})

function move(delta: number) {
  const count = results.value.length
  if (!count) return
  active.value = (active.value + delta + count) % count
}

function choose(index: number) {
  const item = results.value[index]
  if (!item) return
  emit('close')
  router.push(item.to)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') { event.preventDefault(); move(1) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); move(-1) }
  else if (event.key === 'Enter') { event.preventDefault(); choose(active.value) }
  else if (event.key === 'Escape') { event.preventDefault(); emit('close') }
}

onMounted(async () => {
  await nextTick()
  inputRef.value?.focus()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="palette-backdrop" @click.self="emit('close')">
    <div class="palette" role="dialog" aria-modal="true" aria-label="命令面板">
      <input
        ref="inputRef"
        v-model="query"
        type="search"
        placeholder="跳转到页面…（↑↓ 选择，Enter 打开，Esc 关闭）"
        aria-label="搜索页面"
        @input="active = 0"
      />
      <ul v-if="results.length">
        <li v-for="(item, index) in results" :key="item.to">
          <button
            type="button"
            :class="{ active: index === active }"
            @mouseenter="active = index"
            @click="choose(index)"
          >
            <span>{{ item.label }}</span>
            <span class="hint">{{ item.to }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="palette-empty">没有匹配的页面</p>
    </div>
  </div>
</template>
