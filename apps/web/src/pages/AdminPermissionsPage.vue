<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiGet, apiPatch, HttpError } from '@/api/client'
import { permissionPayload, type PermissionForm, type UserRole } from '@/api/permissions'
import AppNav from '@/components/AppNav.vue'
import PermissionPreview from '@/components/admin/PermissionPreview.vue'

interface UserRow extends PermissionForm { username: string; data_scope: string; must_change_password: boolean }
interface Store { store_id: string; name: string; sales_owner: string; team_key: string }
interface Preview { username: string; role: string; is_active: boolean; scope: { mode: string; team_key: string; store_ids: string[]; dealer_names: string[]; owner_keys: string[] }; modules: Record<string, string>; warnings: string[] }

const users = ref<UserRow[]>([]), stores = ref<Store[]>([])
const selected = ref<UserRow | null>(null), preview = ref<Preview | null>(null)
const me = ref(''), search = ref(''), error = ref(''), notice = ref('')
const loading = ref(true), previewLoading = ref(false), saving = ref(false)
const form = ref<PermissionForm>({ display_name: '', role: 'viewer', is_active: true, dealer_id: '', owner_key: '', team_key: '', sales_name: '' })
const ROLE_LABELS: Record<UserRole, string> = { viewer: '只读访客', dealer: '经销商门店', sales: '内部销售', manager: '团队主管', admin: '系统管理员' }
const SCOPE_LABELS: Record<string, string> = { none: '无业务数据', self: '本人绑定范围', team: '所属团队', all: '全公司' }
const visibleUsers = computed(() => { const q = search.value.trim().toLowerCase(); return q ? users.value.filter(u => `${u.username} ${u.display_name}`.toLowerCase().includes(q)) : users.value })
const owners = computed(() => [...new Set(stores.value.map(s => s.sales_owner).filter(Boolean))].sort())
const teams = computed(() => [...new Set(stores.value.map(s => s.team_key).filter(Boolean))].sort())
let previewRequest = 0

function needsSetup(user: UserRow) { return (user.role === 'sales' && !user.owner_key) || (user.role === 'manager' && !user.team_key) || (user.role === 'dealer' && !user.dealer_id) }
async function choose(user: UserRow, resetMessage = true) {
  const request = ++previewRequest
  selected.value = user
  if (resetMessage) { notice.value = ''; error.value = '' }
  form.value = { display_name: user.display_name, role: user.role, is_active: user.is_active, dealer_id: user.dealer_id, owner_key: user.owner_key, team_key: user.team_key, sales_name: user.sales_name }
  previewLoading.value = true
  try {
    const result = await apiGet<Preview>(`/api/admin/users/${encodeURIComponent(user.username)}/effective-permissions`)
    if (request === previewRequest) preview.value = result
  } catch (err) {
    if (request === previewRequest) { error.value = err instanceof HttpError ? err.detail : '权限预览加载失败'; preview.value = null }
  } finally { if (request === previewRequest) previewLoading.value = false }
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const identity = await apiGet<{ username: string; role: string }>('/api/auth/me')
    me.value = identity.username
    if (identity.role !== 'admin') { error.value = '当前账号不是系统管理员'; return }
    ;[users.value, stores.value] = await Promise.all([
      apiGet<UserRow[]>('/api/admin/users'), apiGet<Store[]>('/api/admin/stores?include_inactive=true'),
    ])
    if (users.value[0]) await choose(users.value[0])
  } catch (err) { error.value = err instanceof HttpError ? err.detail : '权限数据加载失败' }
  finally { loading.value = false }
}
async function save() {
  if (!selected.value || saving.value) return
  const username = selected.value.username
  const risky = form.value.role === 'admin' || !form.value.is_active
  if (risky && !window.confirm(`确认变更 ${selected.value.username} 的高权限或账号状态？`)) return
  saving.value = true; error.value = ''; notice.value = ''
  try {
    await apiPatch(`/api/admin/users/${encodeURIComponent(username)}`, permissionPayload(form.value))
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '保存失败'; saving.value = false; return
  }
  notice.value = '权限已保存并重新计算'
  try {
    ;[users.value, stores.value] = await Promise.all([
      apiGet<UserRow[]>('/api/admin/users'), apiGet<Store[]>('/api/admin/stores?include_inactive=true'),
    ])
    const updated = users.value.find(u => u.username === username); if (updated) await choose(updated, false)
  } catch { error.value = '权限已保存，但页面刷新失败；请手动刷新核对' }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <AppNav />
  <main class="page">
    <header class="head"><div><h1>权限控制台</h1><p>账号绑定、数据隔离与实际权限核验。</p></div><a class="btn" href="/admin-panel/">完整运营后台</a></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message ok" role="status">{{ notice }}</p>
    <div v-if="loading" class="card state" aria-busy="true">正在加载账号与门店…</div>
    <div v-else-if="users.length" class="layout">
      <section class="workspace">
        <div class="card list-card">
          <label class="search">搜索账号<input v-model="search" class="input" type="search" placeholder="姓名或账号" /></label>
          <div class="table-wrap"><table><thead><tr><th>账号</th><th>角色</th><th>数据范围</th><th>状态</th></tr></thead><tbody>
            <tr v-for="user in visibleUsers" :key="user.username" :class="{ active: selected?.username === user.username }">
              <td><button type="button" :aria-pressed="selected?.username === user.username" @click="choose(user)"><strong>{{ user.display_name || user.username }}</strong><small>{{ user.username }}</small></button></td>
              <td>{{ ROLE_LABELS[user.role] }}</td><td>{{ SCOPE_LABELS[user.data_scope] || user.data_scope }}<span v-if="needsSetup(user)" class="warn">需配置</span></td>
              <td>{{ user.is_active ? '启用' : '停用' }}<span v-if="user.must_change_password" class="muted"> · 待改密</span></td>
            </tr></tbody></table></div>
        </div>
        <form v-if="selected" class="card editor" @submit.prevent="save">
          <div class="section-title"><div><h2>编辑 {{ selected.username }}</h2><p>角色决定数据范围；绑定项决定能看到哪些业务数据。</p></div><button class="btn btn-primary" :disabled="saving" type="submit">{{ saving ? '保存中…' : '保存权限' }}</button></div>
          <div class="fields"><label>显示名称<input v-model="form.display_name" class="input" /></label><label>角色<select v-model="form.role" class="input" :disabled="selected.username === me"><option v-for="(label, role) in ROLE_LABELS" :key="role" :value="role">{{ label }}</option></select></label>
            <label v-if="form.role === 'sales'">负责人<select v-model="form.owner_key" class="input" required><option value="">请选择</option><option v-for="owner in owners" :key="owner">{{ owner }}</option></select></label>
            <label v-if="form.role === 'sales' || form.role === 'manager'">团队<select v-model="form.team_key" class="input" :required="form.role === 'manager'"><option value="">请选择</option><option v-for="team in teams" :key="team">{{ team }}</option></select></label>
            <label v-if="form.role === 'sales'">来源数据名称<input v-model="form.sales_name" class="input" placeholder="物流/客户数据中的销售名称" /></label>
            <label v-if="form.role === 'dealer'">绑定门店<select v-model="form.dealer_id" class="input" required><option value="">请选择</option><option v-for="store in stores" :key="store.store_id" :value="store.store_id">{{ store.name }}（{{ store.store_id }}）</option></select></label>
          </div>
          <label class="switch"><input v-model="form.is_active" type="checkbox" :disabled="selected.username === me" /> 允许登录</label>
          <p v-if="selected.username === me" class="muted">为防止锁死后台，当前登录账号不能在此修改自身角色或停用。</p>
        </form>
      </section>
      <PermissionPreview :preview="preview" :loading="previewLoading" />
    </div>
    <div v-else-if="!error" class="card state">暂无账号。</div>
  </main>
</template>

<style scoped>
.page { max-width: 1180px; margin: 0 auto; padding: 24px 20px 60px; }.head,.section-title { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }.head { margin-bottom:18px; }.head h1,.editor h2 { margin:0 0 5px; }.head h1 { font-size:24px; }.head p,.editor p { margin:0; color:var(--muted); font-size:13px; }
.layout { display:grid; grid-template-columns:minmax(0, 2fr) minmax(280px, 1fr); gap:16px; }.workspace { display:grid; gap:16px; }.list-card,.editor { padding:18px; }.search { display:grid; grid-template-columns:auto minmax(180px, 280px); align-items:center; gap:12px; color:var(--muted); font-size:13px; margin-bottom:12px; }.table-wrap { overflow-x:auto; }table { width:100%; border-collapse:collapse; font-size:13px; }th,td { padding:10px; border-bottom:1px solid var(--border); text-align:left; }th { color:var(--muted); }tr.active { background:var(--blue-soft); }td button { all:unset; cursor:pointer; color:var(--text); display:grid; width:100%; }td button:focus-visible { outline:2px solid var(--blue); }small,.muted { color:var(--muted); }.warn { margin-left:7px; color:var(--amber); font-weight:600; }
.fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:18px 0; }.fields label { display:grid; gap:7px; color:var(--muted); font-size:13px; }.switch { display:block; font-size:14px; }.message { padding:10px 14px; border-radius:var(--radius); }.error { color:var(--red); background:rgba(244,63,94,.1); }.ok { color:var(--green); background:rgba(16,185,129,.1); }.state { padding:40px; text-align:center; color:var(--muted); }
@media(max-width:900px){.layout{grid-template-columns:1fr}}@media(max-width:600px){.page{padding:16px 12px 40px}.fields{grid-template-columns:1fr}.head,.section-title{align-items:stretch;flex-direction:column}.section-title .btn{width:100%}.search{grid-template-columns:1fr}}
</style>
