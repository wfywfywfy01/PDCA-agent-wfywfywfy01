<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'
import CommandPalette from '@/components/CommandPalette.vue'

interface Me {
  username: string
  display_name: string
  role: string
  must_change_password?: boolean
}

interface NavItem {
  to: string
  label: string
  icon: string
  roles?: string[]
}

const route = useRoute()
const router = useRouter()
const me = ref<Me | null>(null)
const logoutBusy = ref(false)
const logoutError = ref('')
const identityError = ref('')
const collapsed = ref(false)
const mobileOpen = ref(false)
const paletteOpen = ref(false)

const ROLE_LABELS: Record<string, string> = {
  admin: '系统管理员',
  manager: '海外中台主管',
  sales: '经销商销售',
  dealer: '经销商门店',
  viewer: '只读访客',
}

// 分组侧边栏（对标 Ant Design Pro sider menu：分组 + 图标 + 可折叠）
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: '概览',
    items: [
      { to: '/', label: '今日工作台', icon: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z' },
      { to: '/dashboard', label: '数据看板', icon: 'M4 19V9m5 10V5m5 14v-6m5 6V8' },
    ],
  },
  {
    label: '业务',
    items: [
      { to: '/tasks', label: '任务中心', icon: 'M4 6h2m3 0h11M4 12h2m3 0h11M4 18h2m3 0h11' },
      { to: '/logistics', label: '物流中心', icon: 'M3 7h10v8H3zM13 10h4l4 3v2h-8z' },
      { to: '/meetings', label: '会议中心', icon: 'M4 5h16v11H4zM9 20h6' },
      { to: '/knowledge', label: '资料库', icon: 'M5 4h13v16H7a2 2 0 0 1-2-2zM9 8h6M9 12h6' },
      { to: '/signalseller', label: '获客指挥', icon: 'M4 20 20 4M14 4h6v6' },
      { to: '/walkin', label: '客流五件套', icon: 'M12 3v18M6 9l6-6 6 6' },
      { to: '/onboarding', label: '新人培训', icon: 'M12 4 3 8l9 4 9-4zM7 11v5c0 1.5 2.2 2.6 5 2.6s5-1.1 5-2.6v-5' },
    ],
  },
  {
    label: '管理',
    items: [
      { to: '/admin/agents', label: 'Agent 管理', icon: 'M12 3a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM4.5 20.5c0-3.6 3.4-5.5 7.5-5.5s7.5 1.9 7.5 5.5', roles: ['manager', 'admin'] },
      { to: '/admin/sync', label: '数据同步', icon: 'M4 12a8 8 0 0 1 13.6-5.6M20 12a8 8 0 0 1-13.6 5.6M17 3v4h-4M7 21v-4h4', roles: ['manager', 'admin'] },
      { to: '/admin/permissions', label: '权限管理', icon: 'M12 3l7 3v6c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6z', roles: ['admin'] },
    ],
  },
]

const visibleGroups = computed(() =>
  NAV_GROUPS.map((group) => ({
    label: group.label,
    items: group.items.filter((item) => !item.roles || (me.value && item.roles.includes(me.value.role))),
  })).filter((group) => group.items.length > 0),
)

const allItems = computed(() => NAV_GROUPS.flatMap((group) => group.items))
const roleLabel = computed(() => (me.value ? ROLE_LABELS[me.value.role] || me.value.role : ''))
const whoLabel = computed(() => (me.value ? me.value.display_name || me.value.username : '未登录'))
const currentTitle = computed(() => allItems.value.find((item) => item.to === route.path)?.label || '')

function setBodyClasses() {
  const body = document.body
  body.classList.add('shell-ready')
  body.classList.toggle('shell-collapsed', collapsed.value)
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
  try { localStorage.setItem('pdca.shell.collapsed', collapsed.value ? '1' : '0') } catch { /* ignore */ }
  setBodyClasses()
}

function onKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    paletteOpen.value = true
    return
  }
  if (event.key === 'Escape') mobileOpen.value = false
}

async function loadIdentity() {
  identityError.value = ''
  try {
    me.value = await apiGet<Me>('/api/auth/me')
    if (me.value.must_change_password) {
      router.replace({ path: '/login', query: { change_password: '1', next: route.fullPath } })
    }
  } catch (err) {
    me.value = null
    if (err instanceof HttpError && err.status === 401) return
    identityError.value = err instanceof HttpError
      ? (err.status >= 500 ? '后端服务异常（HTTP ' + err.status + '），常见原因是数据库不可用' : '身份接口返回 HTTP ' + err.status + '（' + err.detail + '）')
      : '无法连接后端服务'
  }
}

watch(() => route.fullPath, () => { mobileOpen.value = false })

onMounted(async () => {
  try { collapsed.value = localStorage.getItem('pdca.shell.collapsed') === '1' } catch { /* ignore */ }
  setBodyClasses()
  window.addEventListener('keydown', onKeydown)
  await loadIdentity()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.classList.remove('shell-ready', 'shell-collapsed')
})

async function logout() {
  if (logoutBusy.value) return
  logoutBusy.value = true
  logoutError.value = ''
  try {
    await apiPost('/api/auth/logout')
    router.replace('/login')
  } catch (err) {
    logoutError.value = err instanceof HttpError ? err.detail : '退出失败，请重试'
  } finally {
    logoutBusy.value = false
  }
}
</script>
<template>
  <aside class="shell-sidebar" :class="{ open: mobileOpen }" aria-label="主导航">
    <div class="shell-brand">
      <span class="mark" aria-hidden="true">V</span>
      <span class="label">PDCA 工作台</span>
    </div>

    <nav class="shell-nav">
      <div v-for="group in visibleGroups" :key="group.label" class="shell-group">
        <p class="shell-group-label">{{ group.label }}</p>
        <router-link v-for="item in group.items" :key="item.to" class="shell-link" :to="item.to" :title="item.label">
          <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path :d="item.icon" />
          </svg>
          <span class="label">{{ item.label }}</span>
        </router-link>
      </div>
    </nav>

    <div class="shell-foot">
      <button class="shell-link" type="button" :aria-expanded="!collapsed" @click="toggleCollapse">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
          <path :d="collapsed ? 'M9 6l6 6-6 6' : 'M15 6l-6 6 6 6'" />
        </svg>
        <span class="label">{{ collapsed ? '展开侧栏' : '收起侧栏' }}</span>
      </button>
    </div>
  </aside>

  <header class="shell-topbar">
    <button class="icon-btn menu-btn" type="button" aria-label="打开导航" @click="mobileOpen = !mobileOpen">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
        <path d="M4 7h16M4 12h16M4 17h16" />
      </svg>
    </button>

    <nav class="shell-crumbs" aria-label="面包屑">
      <span>工作台</span>
      <span aria-hidden="true">/</span>
      <strong>{{ currentTitle }}</strong>
    </nav>

    <button class="shell-search" type="button" aria-label="打开命令面板" @click="paletteOpen = true">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">
        <circle cx="11" cy="11" r="6" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <span>搜索页面…</span>
      <kbd>Ctrl K</kbd>
    </button>

    <div class="shell-right">
      <span v-if="me" class="status" :class="me.role === 'admin' ? 'info' : 'ok'">{{ roleLabel }}</span>
      <button class="shell-user" type="button" :disabled="logoutBusy" @click="logout">
        <span>{{ whoLabel }}</span>
        <span class="role">{{ logoutBusy ? '退出中…' : '退出' }}</span>
      </button>
    </div>
  </header>

  <div v-if="identityError" class="identity-warning" role="alert">
    <span>无法读取当前登录身份：{{ identityError }}。数据接口可能同时不可用，管理入口会暂时隐藏。</span>
    <button class="btn btn-sm" type="button" @click="loadIdentity">重试</button>
  </div>

  <p v-if="logoutError" class="logout-error" role="alert">{{ logoutError }}</p>

  <CommandPalette v-if="paletteOpen" :items="allItems" @close="paletteOpen = false" />
</template>

<style scoped>
.menu-btn { display: none; }
.identity-warning {
  position: fixed; top: var(--topbar-h); left: var(--sidebar-w); right: 0; z-index: 24;
  display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap;
  padding: 8px 20px; font-size: 13px; color: var(--warn);
  background: rgba(245, 158, 11, 0.1); border-bottom: 1px solid rgba(245, 158, 11, 0.25);
}
.shell-collapsed .identity-warning { left: var(--sidebar-w-collapsed); }
.logout-error { position: fixed; right: 16px; bottom: 16px; z-index: 40; margin: 0; padding: 8px 14px; border-radius: var(--radius-md); background: var(--surface-3); color: var(--danger); font-size: 13px; }

@media (max-width: 900px) {
  .menu-btn { display: inline-grid; }
  .identity-warning { left: 0; }
}
</style>

