/**
 * PDCA 工作台公共顶栏（Vue 3 CDN）
 * 支持日 / 周 / 月 / 季度 全局切换，通过 URL ?period=X&date=Y 传递给所有页面。
 */
import { createApp, ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';

export function mountPdcaShell(mountId) {
  createApp({
    setup() {
      const user        = ref(null);
      const showProfile = ref(false);
      const pwForm      = ref({ old: '', newPw: '', confirm: '', msg: '', err: '' });

      // ── 时间参数（从 URL 读取，sessionStorage 兜底）──
      const _qs      = new URLSearchParams(location.search);
      const date     = ref(_qs.get('date')   || '');
      const period   = ref(
        _qs.get('period') ||
        (typeof sessionStorage !== 'undefined' && sessionStorage.getItem('pdca_period')) ||
        'month'
      );

      onMounted(async () => {
        try {
          const res = await fetch('/api/auth/me', { credentials: 'include' });
          if (res.ok) user.value = await res.json();
        } catch (_) {}
        // 确保 sessionStorage 与 URL 同步
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.setItem('pdca_period', period.value);
        }
      });

      /** 生成带 date + period 参数的导航 URL */
      function href(path) {
        const p = new URLSearchParams();
        if (date.value) p.set('date', date.value);
        p.set('period', period.value);
        return path + '?' + p.toString();
      }

      /** 切换期间：写 sessionStorage，刷新当前页以触发数据更新 */
      function setPeriod(p) {
        if (period.value === p) return;
        period.value = p;
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.setItem('pdca_period', p);
        }
        const params = new URLSearchParams(location.search);
        params.set('period', p);
        location.search = params.toString(); // 触发页面重载
      }

      async function logout() {
        await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
        location.href = '/login';
      }

      async function changePassword() {
        pwForm.value.msg = '';
        pwForm.value.err = '';
        if (pwForm.value.newPw !== pwForm.value.confirm) {
          pwForm.value.err = '两次输入的新密码不一致'; return;
        }
        if (pwForm.value.newPw.length < 8) {
          pwForm.value.err = '新密码至少 8 位'; return;
        }
        try {
          const res = await fetch('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ old_password: pwForm.value.old, new_password: pwForm.value.newPw }),
          });
          const data = await res.json();
          if (!res.ok) { pwForm.value.err = data.detail || '修改失败'; return; }
          pwForm.value.msg = '密码已修改，即将重新登录…';
          setTimeout(() => logout(), 1500);
        } catch (_) {
          pwForm.value.err = '请求失败，请重试';
        }
      }

      const ROLE_LABELS  = { admin: '管理员', manager: '主管', sales: '销售', viewer: '只读', dealer: '经销商' };
      const PERIOD_LABELS = { day: '日', week: '周', month: '月', quarter: '季' };

      return { user, href, logout, showProfile, pwForm, changePassword,
               ROLE_LABELS, PERIOD_LABELS, period, setPeriod };
    },

    template: `
      <nav class="pdca-shell-bar" v-if="user">

        <!-- 期间切换器 -->
        <span class="pdca-period-group">
          <button v-for="(label, key) in PERIOD_LABELS" :key="key"
            :class="['pdca-period-btn', { active: period === key }]"
            @click="setPeriod(key)">{{ label }}</button>
        </span>

        <span class="pdca-shell-sep"></span>

        <!-- 导航链接 -->
        <a :href="href('/admin-panel/')" v-if="user.role==='admin'" style="background:rgba(124,58,237,0.08);color:#7c3aed;border-radius:6px;padding:0 8px">管理后台</a>

        <!-- 用户菜单 -->
        <span class="pdca-shell-user" style="cursor:pointer;position:relative" @click="showProfile=!showProfile">
          {{ user.display_name || user.username }}
          <span class="pdca-shell-role">{{ ROLE_LABELS[user.role] || user.role }}</span>
          <span style="font-size:10px;margin-left:2px">▾</span>
          <div v-if="showProfile" @click.stop class="pdca-profile-dropdown">
            <div class="pdca-profile-header">{{ user.display_name || user.username }}</div>
            <div class="pdca-profile-sub">{{ user.username }} · {{ ROLE_LABELS[user.role] || user.role }}</div>
            <hr style="border:none;border-top:1px solid #e2e8f0;margin:10px 0"/>
            <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px">修改密码</div>
            <input v-model="pwForm.old"    type="password" placeholder="原密码"        class="pdca-profile-input" />
            <input v-model="pwForm.newPw"  type="password" placeholder="新密码（至少 8 位）" class="pdca-profile-input" />
            <input v-model="pwForm.confirm" type="password" placeholder="确认新密码"    class="pdca-profile-input" />
            <div v-if="pwForm.err" style="color:#dc2626;font-size:12px;margin-bottom:6px">{{ pwForm.err }}</div>
            <div v-if="pwForm.msg" style="color:#16a34a;font-size:12px;margin-bottom:6px">{{ pwForm.msg }}</div>
            <button class="pdca-profile-btn" @click="changePassword">确认修改</button>
            <hr style="border:none;border-top:1px solid #e2e8f0;margin:10px 0"/>
            <a href="#" @click.prevent="logout" style="color:#dc2626;font-size:13px;text-decoration:none">退出登录</a>
          </div>
        </span>
      </nav>
    `
  }).mount('#' + mountId);
}

// ── 全局样式（注入一次）──────────────────────────────────────────────────────
if (typeof document !== 'undefined') {
  if (!document.getElementById('pdca-shell-period-style')) {
    const style = document.createElement('style');
    style.id = 'pdca-shell-period-style';
    style.textContent = `
      .pdca-period-group {
        display: inline-flex;
        align-items: center;
        background: rgba(255,255,255,.08);
        border: 1px solid rgba(255,255,255,.14);
        border-radius: 7px;
        padding: 2px;
        gap: 1px;
        flex-shrink: 0;
      }
      .pdca-period-btn {
        background: transparent;
        border: none;
        color: rgba(255,255,255,.55);
        font-size: 12px;
        font-weight: 700;
        padding: 3px 9px;
        border-radius: 5px;
        cursor: pointer;
        line-height: 1.4;
        transition: background .15s, color .15s;
        font-family: inherit;
      }
      .pdca-period-btn:hover { color: rgba(255,255,255,.85); }
      .pdca-period-btn.active {
        background: rgba(255,255,255,.18);
        color: #fff;
      }
      .pdca-shell-sep {
        width: 1px;
        height: 18px;
        background: rgba(255,255,255,.15);
        margin: 0 2px;
        flex-shrink: 0;
      }
    `;
    document.head.appendChild(style);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var el = document.getElementById('pdca-shell-root');
    if (el) mountPdcaShell('pdca-shell-root');
  });
}
