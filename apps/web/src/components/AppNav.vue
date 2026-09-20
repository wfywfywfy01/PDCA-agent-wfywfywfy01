<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'

interface Me {
  username: string
  display_name: string
  role: string
  must_change_password?: boolean
}

interface NavItem {
  to: string
  label: string
  roles?: string[]
}

const router = useRouter()
const me = ref<Me | null>(null)
const logoutBusy = ref(false)
const logoutError = ref('')
const panelOpen = ref(false)
const identityError = ref('')
const identityBusy = ref(false)

const ROLE_LABELS: Record<string, string> = {
  admin: '系统管理员',
  manager: '海外中台主管',
  sales: '经销商销售',
  dealer: '经销商门店',
  viewer: '只读访客',
}

// 全部入口都在导航里可见（换行而不是横向滚动），避免入口被截断找不到。
const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '今日工作台' },
  { to: '/dashboard', label: '数据看板' },
  { to: '/tasks', label: '任务中心' },
  { to: '/logistics', label: '物流中心' },
  { to: '/meetings', label: '会议中心' },
  { to: '/knowledge', label: '资料库' },
  { to: '/signalseller', label: '获客指挥' },
  { to: '/walkin', label: '客流五件套' },
  { to: '/onboarding', label: '新人培训' },
  { to: '/admin/agents', label: 'Agent 管理', roles: ['manager', 'admin'] },
  { to: '/admin/sync', label: '数据同步', roles: ['manager', 'admin'] },
  { to: '/admin/permissions', label: '权限管理', roles: ['admin'] },
]

const navItems = computed(() =>
  NAV_ITEMS.filter((item) => !item.roles || (me.value && item.roles.includes(me.value.role))),
)

const roleLabel = computed(() => (me.value ? ROLE_LABELS[me.value.role] || me.value.role : ''))
const whoLabel = computed(() => (me.value ? me.value.display_name || me.value.username : ''))

function closePanel() {
  panelOpen.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closePanel()
}

watch(() => router.currentRoute.value.fullPath, closePanel)

async function loadIdentity() {
  identityBusy.value = true
  identityError.value = ''
  try {
    me.value = await apiGet<Me>('/api/auth/me')
    if (me.value.must_change_password) {
      router.replace({ path: '/login', query: { change_password: '1', next: router.currentRoute.value.fullPath } })
    }
  } catch (err) {
    me.value = null
    if (err instanceof HttpError && err.status === 401) {
      identityError.value = ''
      return
    }
    // 身份接口失败通常意味着后端或数据库异常；此时页面上的权限相关入口会消失，
    // 必须显式告知用户，而不是静默降级。
    if (err instanceof HttpError) {
      identityError.value = err.status >= 500
        ? '后端服务异常（HTTP ' + err.status + '），常见原因是数据库不可用'
        : '身份接口返回 HTTP ' + err.status + '（' + err.detail + '）'
    } else {
      identityError.value = '无法连接后端服务'
    }
  } finally {
    identityBusy.value = false
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await loadIdentity()
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

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
  <header class="nav">
    <div class="nav-inner">
      <router-link class="brand" to="/">
        <span class="brand-mark" aria-hidden="true">V</span>
        <span class="brand-text">PDCA 工作台</span>
      </router-link>

      <nav class="links" aria-label="工作台导航">
        <router-link v-for="item in navItems" :key="item.to" :to="item.to">{{ item.label }}</router-link>
      </nav>

      <div class="user">
        <span v-if="me" class="who">
          <span class="who-name">{{ whoLabel }}</span>
          <span class="role-badge">{{ roleLabel }}</span>
        </span>
        <button class="btn btn-sm logout" type="button" :disabled="logoutBusy" @click="logout">
          {{ logoutBusy ? '退出中…' : '退出' }}
        </button>
        <button
          class="burger"
          type="button"
          :aria-expanded="panelOpen"
          aria-controls="nav-panel"
          :aria-label="panelOpen ? '收起导航' : '展开导航'"
          @click="panelOpen = !panelOpen"
        >
          <span aria-hidden="true">{{ panelOpen ? '×' : '☰' }}</span>
        </button>
      </div>
    </div>

    <nav v-if="panelOpen" id="nav-panel" class="panel" aria-label="工作台导航（展开）">
      <router-link v-for="item in navItems" :key="item.to" :to="item.to" @click="closePanel">{{ item.label }}</router-link>
      <span v-if="me" class="panel-user">{{ whoLabel }} · {{ roleLabel }}</span>
    </nav>

    <div v-if="identityError" class="identity-warning" role="alert">
      <span>
        无法读取当前登录身份：{{ identityError }}。数据接口可能同时不可用，页面上的管理入口会暂时隐藏。
      </span>
      <button class="btn btn-sm" type="button" :disabled="identityBusy" @click="loadIdentity">
        {{ identityBusy ? '重试中…' : '重试' }}
      </button>
    </div>

    <p v-if="logoutError" class="logout-error" role="alert">{{ logoutError }}</p>
  </header>
</template>

<style scoped>
.nav {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(11, 13, 19, 0.94);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(6px);
}

.nav-inner {
  max-width: 1240px;
  margin: 0 auto;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand { display: inline-flex; align-items: center; gap: 9px; flex: 0 0 auto; color: var(--text); font-weight: 700; font-size: 14px; }
.brand-mark {
  display: grid; place-items: center; width: 24px; height: 24px; border-radius: 7px;
  background: var(--blue-soft); color: var(--blue); font-size: 13px; font-weight: 700;
}

/* 换行而不是横向滚动：任何窗口宽度下入口都不会被截断 */
.links { flex: 1 1 auto; min-width: 0; display: flex; flex-wrap: wrap; gap: 4px 2px; }
.links a {
  padding: 6px 12px; border-radius: 999px; color: var(--muted); font-size: 13px; white-space: nowrap;
  transition: background-color 0.15s, color 0.15s;
}
.links a:hover { color: var(--text); background: rgba(255, 255, 255, 0.04); }
.links a.router-link-active { background: var(--blue-soft); color: var(--blue); font-weight: 600; }

.user { flex: 0 0 auto; display: flex; align-items: center; gap: 10px; }
.who { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
.who-name { max-width: 12ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.role-badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border-strong); color: var(--text); white-space: nowrap; }
.logout { padding: 6px 12px; }

.burger {
  display: none; width: 34px; height: 34px; align-items: center; justify-content: center;
  border-radius: 9px; border: 1px solid var(--border-strong); background: var(--card-2);
  color: var(--text); font-size: 15px; cursor: pointer;
}

.panel {
  display: grid; gap: 2px; padding: 8px 20px 14px;
  border-top: 1px solid var(--border); background: var(--card);
}
.panel a { padding: 10px 12px; border-radius: 9px; color: var(--muted); font-size: 14px; }
.panel a.router-link-active { background: var(--blue-soft); color: var(--blue); font-weight: 600; }
.panel-user { padding: 10px 12px; color: var(--faint); font-size: 12px; }

.logout-error { margin: 0; padding: 6px 20px 10px; color: var(--red); font-size: 13px; }

.identity-warning {
  display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap;
  margin: 0; padding: 9px 20px; font-size: 13px;
  color: var(--amber); background: rgba(245, 158, 11, 0.1);
  border-top: 1px solid rgba(245, 158, 11, 0.28);
}

@media (max-width: 900px) {
  .links { display: none; }
  .burger { display: inline-flex; }
  .nav-inner { padding: 10px 14px; }
}
@media (max-width: 640px) {
  .who { display: none; }
  .brand-text { display: none; }
}
</style>
