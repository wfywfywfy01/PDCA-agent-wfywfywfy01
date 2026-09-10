<script setup lang="ts">
interface Preview {
  username: string
  role: string
  is_active: boolean
  scope: { mode: string; team_key: string; store_ids: string[]; dealer_names: string[]; owner_keys: string[] }
  modules: Record<string, string>
  warnings: string[]
}

defineProps<{ preview: Preview | null; loading: boolean }>()

const MODULE_LABELS: Record<string, string> = {
  workbench: '今日工作台', customers: '客户管理', logistics: '物流中心',
  meetings: '会议中心', tasks: '任务中心', walkin: '客流五件套', admin: '系统管理',
}
const ACCESS_LABELS: Record<string, string> = { all: '全部', scoped: '按绑定范围', 'read-only': '仅查看', none: '不可访问' }
const SCOPE_LABELS: Record<string, string> = { all: '全公司', team: '所属团队', self: '本人绑定范围', none: '无业务数据' }
</script>

<template>
  <aside class="card preview" aria-live="polite" :aria-busy="loading">
    <h2>实际生效权限</h2>
    <p v-if="loading" class="muted">正在从权限引擎核验…</p>
    <template v-else-if="preview">
      <div v-if="preview.warnings.length" class="warnings" role="alert">
        <strong>配置告警</strong>
        <ul><li v-for="warning in preview.warnings" :key="warning">{{ warning }}</li></ul>
      </div>
      <dl class="facts">
        <div><dt>数据范围</dt><dd>{{ SCOPE_LABELS[preview.scope.mode] || preview.scope.mode }}</dd></div>
        <div><dt>团队</dt><dd>{{ preview.scope.team_key || '未绑定' }}</dd></div>
        <div><dt>有效门店</dt><dd>{{ preview.scope.mode === 'all' ? '全部有效门店' : `${preview.scope.store_ids.length} 家` }}</dd></div>
      </dl>
      <div v-if="preview.scope.dealer_names.length" class="chips" aria-label="有效门店">
        <span v-for="name in preview.scope.dealer_names" :key="name">{{ name }}</span>
      </div>
      <h3>模块权限</h3>
      <ul class="modules">
        <li v-for="(access, key) in preview.modules" :key="key">
          <span>{{ MODULE_LABELS[key] || key }}</span>
          <span :class="['access', `access-${access}`]">{{ ACCESS_LABELS[access] || access }}</span>
        </li>
      </ul>
    </template>
    <p v-else class="muted">选择账号后显示权限引擎的真实计算结果。</p>
  </aside>
</template>

<style scoped>
.preview { padding: 20px; align-self: start; position: sticky; top: 78px; }
h2, h3 { margin: 0 0 14px; font-size: 16px; }
h3 { margin-top: 22px; color: var(--muted); font-size: 13px; }
.muted { color: var(--muted); font-size: 14px; }
.warnings { padding: 12px 14px; border: 1px solid rgba(245, 158, 11, .35); border-radius: var(--radius); background: rgba(245, 158, 11, .08); color: #fbbf24; font-size: 13px; }
.warnings ul { margin: 7px 0 0; padding-left: 18px; }
.facts { display: grid; gap: 10px; margin: 18px 0; }
.facts div, .modules li { display: flex; justify-content: space-between; gap: 16px; }
dt { color: var(--muted); } dd { margin: 0; text-align: right; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips span { padding: 4px 8px; background: var(--blue-soft); color: var(--blue); border-radius: 6px; font-size: 12px; }
.modules { list-style: none; margin: 0; padding: 0; display: grid; gap: 1px; background: var(--border); }
.modules li { padding: 9px 0; background: var(--card); font-size: 13px; }
.access { font-weight: 600; }.access-all, .access-scoped { color: var(--green); }.access-read-only { color: var(--amber); }.access-none { color: var(--faint); }
@media (max-width: 900px) { .preview { position: static; } }
</style>
