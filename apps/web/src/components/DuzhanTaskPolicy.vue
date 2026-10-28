<script setup lang="ts">
import { computed, reactive, useId, watch } from 'vue'
import type { Block } from '@/api/duzhanBlocks'
import type { GroupMember } from '@/api/duzhanWorkspace'

const props = defineProps<{ block: Block; members: GroupMember[]; disabled?: boolean }>()
type MemberField = 'publisher_user_ids' | 'excluded_user_ids'
const emit = defineEmits<{ (event: 'change', key: MemberField, value: number[]): void }>()
const prefix = useId()
const search = reactive<Record<MemberField, string>>({ publisher_user_ids: '', excluded_user_ids: '' })
const sections = [
  { key: 'publisher_user_ids', title: '谁来布置任务', hint: '只跟进这些成员发布的任务。至少选一位。', empty: '尚未选择发布人', search: '搜索任务发布人' },
  { key: 'excluded_user_ids', title: '哪些人不催办', hint: '排除人员不参与任务催办，群内原始消息仍保留。', empty: '不额外排除成员', search: '搜索要排除的成员' },
] as const
const members = computed(() => {
  const seen = new Set<number>()
  return props.members.filter((member) => {
    if (!Number.isInteger(member.user_id) || member.user_id <= 0 || seen.has(member.user_id)) return false
    seen.add(member.user_id)
    return true
  }).sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
})

watch(() => props.members, () => {
  search.publisher_user_ids = ''
  search.excluded_user_ids = ''
})

function selected(key: MemberField): number[] {
  const value = props.block[key]
  return Array.isArray(value) ? [...new Set(value.filter((id): id is number => typeof id === 'number' && Number.isInteger(id) && id > 0))] : []
}

function filtered(key: MemberField): GroupMember[] {
  const query = search[key].trim().toLocaleLowerCase()
  return members.value.filter((member) => member.name.toLocaleLowerCase().includes(query))
}

function toggle(key: MemberField, id: number) {
  if (props.disabled) return
  const ids = selected(key)
  emit('change', key, ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id])
}

function memberName(id: number): string {
  return members.value.find((member) => member.user_id === id)?.name || `名单外成员（账号 ${id}）`
}

function roleLabel(role?: string): string {
  return role === 'owner' ? '群主' : ['admin', 'administrator'].includes(role || '') ? '管理员' : ''
}
</script>

<template>
  <div class="task-policy">
    <fieldset v-for="section in sections" :key="section.key" :disabled="disabled" :aria-describedby="prefix + '-' + section.key + '-hint'">
      <legend>{{ section.title }} <span class="count">{{ selected(section.key).length }} 人</span></legend>
      <p :id="prefix + '-' + section.key + '-hint'" class="hint">{{ section.hint }}</p>
      <div class="selections" :aria-label="'已选' + section.title">
        <button v-for="id in selected(section.key)" :key="id" type="button" class="member-chip" :class="{ unavailable: !members.some((member) => member.user_id === id) }" :aria-label="'移除' + memberName(id)" @click="toggle(section.key, id)">
          {{ memberName(id) }} <span aria-hidden="true">×</span>
        </button>
        <span v-if="!selected(section.key).length" class="selection-empty">{{ section.empty }}</span>
      </div>
      <label class="search-label" :for="prefix + '-' + section.key">{{ section.search }}</label>
      <input :id="prefix + '-' + section.key" v-model="search[section.key]" type="search" autocomplete="off" :placeholder="section.search" />
      <div v-if="members.length" class="member-list" role="group" :aria-label="section.title">
        <label v-for="member in filtered(section.key)" :key="member.user_id" class="member-row" :class="{ selected: selected(section.key).includes(member.user_id) }">
          <input type="checkbox" :checked="selected(section.key).includes(member.user_id)" @change="toggle(section.key, member.user_id)" />
          <span class="member-name">{{ member.name }}</span>
          <span v-if="roleLabel(member.role)" class="member-role">{{ roleLabel(member.role) }}</span>
        </label>
        <p v-if="!filtered(section.key).length" class="empty" role="status">没有匹配的成员，换个姓名试试。</p>
      </div>
      <p v-else class="empty" role="status">选择可用群聊后，这里会显示真实群成员。</p>
    </fieldset>
  </div>
</template>

<style scoped>
.task-policy { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--sp-6); }
fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }
legend { display: flex; align-items: center; gap: var(--sp-2); padding: 0; font-size: 14px; font-weight: 600; color: var(--text-1); }
.count { color: var(--text-3); font-size: 12px; font-weight: 400; }
.hint { margin: var(--sp-2) 0 var(--sp-3); color: var(--text-2); font-size: 12px; line-height: 1.6; }
.selections { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); min-height: 36px; margin-bottom: var(--sp-3); }
.member-chip { display: inline-flex; align-items: center; gap: var(--sp-2); max-width: 100%; min-height: 32px; padding: var(--sp-1) var(--sp-2); border: 1px solid var(--line-strong); border-radius: var(--radius-sm); background: var(--surface-active); color: var(--text-1); font: inherit; font-size: 12px; text-align: left; overflow-wrap: anywhere; cursor: pointer; }
.member-chip span { flex: none; font-size: 16px; color: var(--text-2); }
.member-chip.unavailable { color: var(--warn); background: var(--surface-2); }
.member-chip:hover:not(:disabled) { border-color: var(--info); }
.selection-empty { color: var(--text-3); font-size: 12px; }
.search-label { display: block; margin-bottom: var(--sp-2); color: var(--text-2); font-size: 12px; }
input[type='search'] { width: 100%; min-width: 0; min-height: 40px; padding: var(--sp-2) var(--sp-3); border: 1px solid var(--line-strong); border-radius: var(--radius-md); background: var(--surface-2); color: var(--text-1); font: inherit; font-size: 13px; }
input::placeholder { color: var(--text-3); }
.member-list { max-height: 208px; margin-top: var(--sp-2); overflow-y: auto; scrollbar-gutter: stable; }
.member-row { display: flex; align-items: center; gap: var(--sp-2); min-height: 40px; padding: var(--sp-2); border-radius: var(--radius-sm); cursor: pointer; }
.member-row:hover { background: var(--surface-hover); }
.member-row.selected { background: var(--surface-active); }
.member-row input { width: 16px; height: 16px; margin: 0; flex: none; accent-color: var(--info); }
.member-name { min-width: 0; overflow-wrap: anywhere; color: var(--text-1); font-size: 13px; }
.member-role { flex: none; margin-left: auto; color: var(--text-3); font-size: 11px; }
.empty { margin: var(--sp-3) 0 0; color: var(--text-3); font-size: 12px; line-height: 1.6; }
button:focus-visible, input:focus-visible { outline: 2px solid var(--info); outline-offset: 2px; }
fieldset:disabled { opacity: .65; }
fieldset:disabled .member-row, button:disabled { cursor: not-allowed; }
@media (max-width: 720px) { .task-policy { grid-template-columns: minmax(0, 1fr); } }
</style>
