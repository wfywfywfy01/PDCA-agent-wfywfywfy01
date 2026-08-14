/**
 * PDCA 工作台公共顶栏。
 * 使用原生 DOM API，避免生产 CSP 为运行时模板编译器开放 unsafe-eval。
 */

const ROLE_LABELS = {
  admin: '管理员',
  manager: '主管',
  sales: '销售',
  viewer: '只读',
  dealer: '经销商',
};

const PERIOD_LABELS = {
  day: '日',
  week: '周',
  month: '月',
  quarter: '季',
};

function localToday() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function appendTextElement(parent, tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

function divider() {
  const line = document.createElement('hr');
  line.style.cssText = 'border:none;border-top:1px solid #e2e8f0;margin:10px 0';
  return line;
}

export async function mountPdcaShell(mountId) {
  const root = document.getElementById(mountId);
  if (!root || root.dataset.mounted === 'true') return;

  let user;
  try {
    const response = await fetch('/api/auth/me', { credentials: 'include' });
    if (!response.ok) return;
    user = await response.json();
  } catch (_) {
    return;
  }

  root.dataset.mounted = 'true';
  const query = new URLSearchParams(location.search);
  const date = query.get('date') || localToday();
  const storedPeriod = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('pdca_period') : '';
  const period = query.get('period') || storedPeriod || 'month';
  if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('pdca_period', period);

  function href(path) {
    const params = new URLSearchParams({ date, period });
    return path + '?' + params.toString();
  }

  function setPeriod(nextPeriod) {
    if (nextPeriod === period) return;
    if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('pdca_period', nextPeriod);
    const params = new URLSearchParams(location.search);
    params.set('period', nextPeriod);
    params.set('date', date);
    location.search = params.toString();
  }

  async function logout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
    } finally {
      location.href = '/login';
    }
  }

  const nav = document.createElement('nav');
  nav.className = 'pdca-shell-bar';
  nav.setAttribute('aria-label', 'PDCA 工作台导航');

  const periodGroup = document.createElement('span');
  periodGroup.className = 'pdca-period-group';
  periodGroup.setAttribute('aria-label', '统计周期');
  Object.entries(PERIOD_LABELS).forEach(function ([key, label]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'pdca-period-btn' + (period === key ? ' active' : '');
    button.textContent = label;
    button.setAttribute('aria-pressed', period === key ? 'true' : 'false');
    button.addEventListener('click', function () { setPeriod(key); });
    periodGroup.appendChild(button);
  });
  nav.appendChild(periodGroup);

  const separator = document.createElement('span');
  separator.className = 'pdca-shell-sep';
  separator.setAttribute('aria-hidden', 'true');
  nav.appendChild(separator);

  const home = document.createElement('a');
  home.href = href('/');
  home.textContent = '经营首页';
  const currentPath = location.pathname.replace(/\/$/, '') || '/';
  if (currentPath === '/') home.className = 'pdca-nav-active';
  nav.appendChild(home);

  const userWrap = document.createElement('span');
  userWrap.className = 'pdca-shell-user';
  userWrap.style.position = 'relative';

  const profileToggle = document.createElement('button');
  profileToggle.type = 'button';
  profileToggle.className = 'pdca-shell-user-toggle';
  profileToggle.setAttribute('aria-haspopup', 'dialog');
  profileToggle.setAttribute('aria-expanded', 'false');
  profileToggle.setAttribute('aria-label', '打开用户菜单');
  appendTextElement(profileToggle, 'span', '', user.display_name || user.username);
  appendTextElement(profileToggle, 'span', 'pdca-shell-role', ROLE_LABELS[user.role] || user.role);
  appendTextElement(profileToggle, 'span', 'pdca-shell-arrow', '▾');
  userWrap.appendChild(profileToggle);

  const dropdown = document.createElement('div');
  dropdown.className = 'pdca-profile-dropdown';
  dropdown.hidden = true;
  dropdown.setAttribute('role', 'dialog');
  dropdown.setAttribute('aria-label', '用户资料与密码设置');
  dropdown.addEventListener('click', function (event) { event.stopPropagation(); });

  appendTextElement(dropdown, 'div', 'pdca-profile-header', user.display_name || user.username);
  appendTextElement(dropdown, 'div', 'pdca-profile-sub', user.username + ' · ' + (ROLE_LABELS[user.role] || user.role));
  dropdown.appendChild(divider());
  appendTextElement(dropdown, 'div', 'pdca-profile-section-title', '修改密码');

  const oldPassword = document.createElement('input');
  oldPassword.type = 'password';
  oldPassword.className = 'pdca-profile-input';
  oldPassword.placeholder = '原密码';
  oldPassword.autocomplete = 'current-password';
  oldPassword.setAttribute('aria-label', '原密码');
  dropdown.appendChild(oldPassword);

  const newPassword = document.createElement('input');
  newPassword.type = 'password';
  newPassword.className = 'pdca-profile-input';
  newPassword.placeholder = '新密码（至少 12 位）';
  newPassword.autocomplete = 'new-password';
  newPassword.setAttribute('aria-label', '新密码');
  dropdown.appendChild(newPassword);

  const confirmPassword = document.createElement('input');
  confirmPassword.type = 'password';
  confirmPassword.className = 'pdca-profile-input';
  confirmPassword.placeholder = '确认新密码';
  confirmPassword.autocomplete = 'new-password';
  confirmPassword.setAttribute('aria-label', '确认新密码');
  dropdown.appendChild(confirmPassword);

  const errorMessage = appendTextElement(dropdown, 'div', 'pdca-profile-message pdca-profile-error', '');
  errorMessage.hidden = true;
  const successMessage = appendTextElement(dropdown, 'div', 'pdca-profile-message pdca-profile-success', '');
  successMessage.hidden = true;

  function showMessage(element, message) {
    errorMessage.hidden = true;
    successMessage.hidden = true;
    element.textContent = message;
    element.hidden = false;
  }

  const changeButton = appendTextElement(dropdown, 'button', 'pdca-profile-btn', '确认修改');
  changeButton.type = 'button';
  changeButton.addEventListener('click', async function () {
    if (newPassword.value !== confirmPassword.value) {
      showMessage(errorMessage, '两次输入的新密码不一致');
      return;
    }
    if (newPassword.value.length < 12) {
      showMessage(errorMessage, '新密码至少 12 位');
      return;
    }
    changeButton.disabled = true;
    try {
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ old_password: oldPassword.value, new_password: newPassword.value }),
      });
      const payload = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        showMessage(errorMessage, payload.detail || '修改失败');
        return;
      }
      showMessage(successMessage, '密码已修改，即将重新登录…');
      setTimeout(logout, 1500);
    } catch (_) {
      showMessage(errorMessage, '请求失败，请重试');
    } finally {
      changeButton.disabled = false;
    }
  });

  dropdown.appendChild(divider());
  const logoutLink = document.createElement('a');
  logoutLink.href = '/login';
  logoutLink.className = 'pdca-profile-logout';
  logoutLink.textContent = '退出登录';
  logoutLink.addEventListener('click', function (event) {
    event.preventDefault();
    logout();
  });
  dropdown.appendChild(logoutLink);
  userWrap.appendChild(dropdown);

  function setProfileOpen(open) {
    dropdown.hidden = !open;
    profileToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  profileToggle.addEventListener('click', function (event) {
    event.stopPropagation();
    setProfileOpen(dropdown.hidden);
  });
  document.addEventListener('click', function () { setProfileOpen(false); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      setProfileOpen(false);
      profileToggle.focus();
    }
  });

  nav.appendChild(userWrap);
  root.replaceChildren(nav);
}

if (typeof document !== 'undefined') {
  if (!document.getElementById('pdca-shell-period-style')) {
    const style = document.createElement('style');
    style.id = 'pdca-shell-period-style';
    style.textContent = `
      .pdca-period-group { display:inline-flex;align-items:center;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);border-radius:7px;padding:2px;gap:1px;flex-shrink:0 }
      .pdca-period-btn { background:transparent;border:none;color:rgba(255,255,255,.55);font-size:12px;font-weight:700;padding:3px 9px;min-width:32px;min-height:32px;border-radius:5px;cursor:pointer;line-height:1.4;transition:background .15s,color .15s;font-family:inherit }
      .pdca-period-btn:hover { color:rgba(255,255,255,.85) }
      .pdca-period-btn.active { background:rgba(255,255,255,.18);color:#fff }
      .pdca-shell-sep { width:1px;height:18px;background:rgba(255,255,255,.15);margin:0 2px;flex-shrink:0 }
      .pdca-nav-active { background:rgba(255,255,255,.15)!important;color:#fff!important;border-radius:5px }
      .pdca-shell-user-toggle { all:unset;display:flex;align-items:center;gap:6px;cursor:pointer }
      .pdca-shell-user-toggle:focus-visible { outline:2px solid #4e9ef5;outline-offset:4px;border-radius:4px }
      .pdca-shell-arrow { font-size:10px;margin-left:2px }
      .pdca-profile-section-title { font-size:13px;font-weight:600;color:#cbd5e1;margin-bottom:8px }
      .pdca-profile-message { font-size:12px;margin-bottom:6px }
      .pdca-profile-error { color:#f87171 }
      .pdca-profile-success { color:#4ade80 }
      .pdca-profile-logout { color:#f87171!important;font-size:13px;text-decoration:none;padding:0!important }
      [hidden] { display:none!important }
    `;
    document.head.appendChild(style);
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('pdca-shell-root')) mountPdcaShell('pdca-shell-root');
  });
}
