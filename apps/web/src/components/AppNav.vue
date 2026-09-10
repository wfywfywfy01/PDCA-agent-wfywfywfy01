<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'

interface Me {
  username: string
  display_name: string
  role: string
  must_change_password?: boolean
}

const router = useRouter()
const me = ref<Me | null>(null)
const logoutBusy = ref(false)
const logoutError = ref('')

const ROLE_LABELS: Record<string, string> = {
  admin: '系统管理员',
  manager: '海外中台主管',
  sales: '经销商销售',
  dealer: '经销商门店',
  viewer: '只读访客',
}

onMounted(async () => {
  try {
    me.value = await apiGet<Me>('/api/auth/me')
    if (me.value.must_change_password) {
      router.replace({ path: '/login', query: { change_password: '1', next: router.currentRoute.value.fullPath } })
    }
  } catch {
    me.value = null
  }
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
  <header class="nav">
    <div class="nav-inner">
      <router-link class="brand" to="/">PDCA 工作台</router-link>
      <nav class="links" aria-label="工作台导航">
        <router-link to="/">今日工作台</router-link>
        <router-link to="/dashboard">数据看板</router-link>
        <router-link to="/logistics">物流中心</router-link>
        <router-link to="/meetings">会议中心</router-link>
        <router-link to="/knowledge">资料库</router-link>
        <router-link to="/signalseller">获客指挥</router-link>
        <router-link to="/walkin">客流五件套</router-link>
        <router-link to="/tasks">任务中心</router-link>
        <router-link to="/onboarding">新人培训</router-link>
        <router-link v-if="me && (me.role === 'manager' || me.role === 'admin')" to="/admin/sync">
          数据同步
        </router-link>
        <router-link v-if="me?.role === 'admin'" to="/admin/permissions">权限管理</router-link>
      </nav>
      <div class="user">
        <span v-if="me" class="who">
          {{ me.display_name || me.username }}
          <span class="role-badge">{{ ROLE_LABELS[me.role] || me.role }}</span>
        </span>
        <button class="btn btn-logout" type="button" :disabled="logoutBusy" @click="logout">{{ logoutBusy ? '退出中…' : '退出' }}</button>
      </div>
    </div>
    <p v-if="logoutError" class="logout-error" role="alert">{{ logoutError }}</p>
  </header>
</template>

<style scoped>
.nav {
  background: rgba(11, 13, 19, 0.92);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
  backdrop-filter: blur(6px);
}

.nav-inner {
  max-width: 1180px;
  margin: 0 auto;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  gap: 20px;
}

.brand {
  flex: 0 0 auto;
  font-weight: 700;
  color: var(--text);
  font-size: 15px;
}

.links {
  min-width: 0;
  display: flex;
  gap: 4px;
  flex: 1;
  overflow-x: auto;
  scrollbar-width: none;
}

.links a {
  flex: 0 0 auto;
}

.links a {
  padding: 7px 14px;
  border-radius: 999px;
  color: var(--muted);
  font-size: 13px;
  transition: all 0.15s;
}

.links a.router-link-active {
  background: var(--blue-soft);
  color: var(--blue);
  font-weight: 600;
}

.user {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

.who {
  font-size: 13px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 8px;
}

.role-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-strong);
  color: var(--text);
}

.btn-logout {
  padding: 6px 12px;
  font-size: 12px;
}

.logout-error { margin: 0; padding: 4px 20px 10px; color: var(--red); font-size: 13px; }

@media (max-width: 640px) {
  .who {
    display: none;
  }
  .nav-inner {
    flex-wrap: wrap;
    gap: 10px;
    padding: 10px 12px;
  }
  .links { order: 3; flex-basis: 100%; }
  .user { margin-left: auto; }
}
</style>
