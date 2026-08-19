<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet, apiPost, HttpError } from '@/api/client'

interface AuthConfig {
  auth_mode: 'local' | 'vps' | 'hybrid'
  vps_login_url?: string
}

const route = useRoute()
const router = useRouter()

const config = ref<AuthConfig | null>(null)
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')
const mustChange = ref(false)
const oldPassword = ref('')
const newPassword = ref('')

const nextPath = typeof route.query.next === 'string' ? route.query.next : '/'

onMounted(async () => {
  try {
    config.value = await apiGet<AuthConfig>('/api/auth/config')
  } catch {
    error.value = '无法连接工作台服务，请稍后重试或联系管理员。'
  }
})

async function doLogin() {
  error.value = ''
  busy.value = true
  try {
    const result = await apiPost<{
      must_change_password?: boolean
      user?: { display_name?: string }
    }>('/api/auth/login', { username: username.value.trim(), password: password.value })
    if (result.must_change_password) {
      mustChange.value = true
      oldPassword.value = password.value
      return
    }
    router.replace(nextPath)
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '登录失败，请稍后重试'
  } finally {
    busy.value = false
  }
}

async function doChangePassword() {
  error.value = ''
  busy.value = true
  try {
    await apiPost('/api/auth/change-password', {
      old_password: oldPassword.value,
      new_password: newPassword.value,
    })
    router.replace(nextPath)
  } catch (err) {
    error.value = err instanceof HttpError ? err.detail : '修改密码失败，请稍后重试'
  } finally {
    busy.value = false
  }
}

function goVps() {
  if (config.value?.vps_login_url) {
    location.href = config.value.vps_login_url
  }
}
</script>

<template>
  <main class="login-wrap">
    <section class="card login-card">
      <h1>PDCA 工作台</h1>
      <p class="sub">经销商 PDCA 数据中台 · 请登录后继续</p>

      <div v-if="error" class="alert">{{ error }}</div>

      <form v-if="!mustChange" @submit.prevent="doLogin">
        <label class="field">
          <span>用户名</span>
          <input
            v-model="username"
            class="input"
            name="username"
            autocomplete="username"
            required
            :disabled="busy"
          />
        </label>
        <label class="field">
          <span>密码</span>
          <input
            v-model="password"
            class="input"
            type="password"
            name="password"
            autocomplete="current-password"
            required
            :disabled="busy"
          />
        </label>
        <button class="btn btn-primary btn-block" type="submit" :disabled="busy">
          {{ busy ? '登录中…' : '登录' }}
        </button>
      </form>

      <form v-else @submit.prevent="doChangePassword">
        <p class="notice">首次登录或密码已过期，请设置新密码（至少 12 位）。</p>
        <label class="field">
          <span>旧密码</span>
          <input
            v-model="oldPassword"
            class="input"
            type="password"
            name="old_password"
            autocomplete="current-password"
            required
            :disabled="busy"
          />
        </label>
        <label class="field">
          <span>新密码</span>
          <input
            v-model="newPassword"
            class="input"
            type="password"
            name="new_password"
            autocomplete="new-password"
            minlength="12"
            required
            :disabled="busy"
          />
        </label>
        <button class="btn btn-primary btn-block" type="submit" :disabled="busy">
          {{ busy ? '提交中…' : '设置新密码并进入' }}
        </button>
      </form>

      <div v-if="config && config.auth_mode !== 'local'" class="vps-row">
        <span class="divider">或</span>
        <button class="btn btn-block" type="button" @click="goVps">使用 VPS / Odoo 账号登录</button>
      </div>

      <p v-if="!config && !error" class="hint">正在读取认证配置…</p>
    </section>
  </main>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 420px;
  padding: 36px 32px;
}

h1 {
  margin: 0 0 6px;
  font-size: 26px;
  text-align: center;
}

.sub {
  margin: 0 0 26px;
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}

.field {
  display: grid;
  gap: 7px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--muted);
}

.btn-block {
  width: 100%;
  margin-top: 6px;
}

.alert {
  background: rgba(244, 63, 94, 0.1);
  border: 1px solid rgba(244, 63, 94, 0.3);
  color: var(--red);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 13px;
  margin-bottom: 16px;
}

.notice {
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.25);
  color: var(--amber);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 13px;
}

.vps-row {
  margin-top: 20px;
}

.divider {
  display: block;
  text-align: center;
  color: var(--faint);
  font-size: 12px;
  margin-bottom: 10px;
}

.hint {
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}
</style>
