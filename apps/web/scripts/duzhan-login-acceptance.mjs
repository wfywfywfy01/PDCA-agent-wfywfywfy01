// Run: node scripts/duzhan-login-acceptance.mjs [--playwright-module=/path/to/playwright/index.js]
// Uses existing Playwright/Chromium and web dependencies. All API responses are synthetic.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
const web = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const output = resolve(web, '../../.artifacts/login-qa')
await mkdir(output, { recursive: true })
const require = createRequire(import.meta.url)
const moduleArgument = process.argv.find(item => item.startsWith('--playwright-module='))
const { chromium } = require(moduleArgument ? moduleArgument.slice('--playwright-module='.length) : 'playwright')
const { createServer } = await import(new URL('../node_modules/vite/dist/node/index.js', import.meta.url))
const server = await createServer({ root: web, server: { host: '127.0.0.1', port: 5189, strictPort: true }, logLevel: 'warn' })
const checks = [], errors = [], expected401 = [], unhandled = []
let browser, page, unauthorized = true
try {
  await server.listen()
  console.log(JSON.stringify({ started: true, pid: process.pid, port: 5189 }))
  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
  await context.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.hostname !== '127.0.0.1') return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/auth/config') return route.fulfill({ json: { auth_mode: 'local' } })
    if (unauthorized) return route.fulfill({ status: 401, json: { detail: '登录已过期' } })
    const fixtures = {
      '/api/auth/me': { username: 'synthetic-test', display_name: '界面验收', role: 'admin' },
      '/api/omega/status': { ready: false },
      '/api/duzhan-agents': { items: [] },
      '/api/duzhan-agents/block-schema': { blocks: [] },
      '/api/duzhan-agents/runtime-status': { source: 'db', enabled: true, ctob_enabled: false, bot_app_id: 'synthetic-bot', supported_channel_ids: [], group_tasks_enabled: true, group_tasks_schedule_live: true },
      '/api/duzhan-agents/ai-status': { day: '2026-10-28', calls: 0, cached: 0, limit: 60 },
      '/api/duzhan-agents/group-options': { configured: true, bot_app_id: 'synthetic-bot', items: [] },
      '/api/agent-admin/bot-channels': { items: [] },
    }
    if (url.pathname in fixtures) return route.fulfill({ json: fixtures[url.pathname] })
    unhandled.push(url.pathname)
    return route.fulfill({ status: 500, json: { detail: '未配置的测试接口' } })
  })
  page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    if (message.type() !== 'error') return
    if (/Failed to load resource:.*401/.test(message.text())) expected401.push(message.text())
    else errors.push(message.text())
  })
  const destination = 'http://127.0.0.1:5189/admin/duzhan-agents'
  await page.goto(destination, { waitUntil: 'networkidle' })
  await page.waitForURL(url => url.pathname === '/login', { timeout: 5000 })
  assert.equal(new URL(page.url()).searchParams.get('next'), '/admin/duzhan-agents')
  await page.getByLabel('用户名', { exact: true }).waitFor()
  checks.push('初次未登录进入督战页面会跳转登录，并保留返回地址')

  unauthorized = false
  await page.goto(destination, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: '让一个群开始有序跟进', exact: true }).waitFor()
  await page.getByLabel('配置名称', { exact: true }).fill('等待保存的测试草稿')
  await page.getByRole('link', { name: '任务中心', exact: true }).click()
  await page.getByText('当前有未保存的改动，请先保存再离开。', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/admin/duzhan-agents')
  assert.equal(await page.getByLabel('配置名称', { exact: true }).inputValue(), '等待保存的测试草稿')
  checks.push('普通离开仍保护真实未保存改动')

  unauthorized = true
  await page.getByRole('button', { name: '刷新群列表', exact: true }).click()
  await page.getByRole('button', { name: '放弃改动并重新登录', exact: true }).waitFor({ timeout: 5000 })
  assert.equal(new URL(page.url()).pathname, '/admin/duzhan-agents')
  assert.equal(await page.getByLabel('配置名称', { exact: true }).inputValue(), '等待保存的测试草稿')
  checks.push('编辑中会话过期保留输入，并提供明确放弃后登录的入口')
  await page.screenshot({ path: resolve(output, 'expired-draft.png'), fullPage: true })
  await page.getByRole('button', { name: '放弃改动并重新登录', exact: true }).click()
  await page.waitForURL(url => url.pathname === '/login', { timeout: 5000 })
  assert.equal(new URL(page.url()).searchParams.get('next'), '/admin/duzhan-agents')
  await page.getByLabel('用户名', { exact: true }).waitFor()
  checks.push('仅在明确放弃后跳到登录页，保留返回地址')
  assert.equal(errors.length, 0)
  assert.equal(unhandled.length, 0)
  await writeFile(resolve(output, 'results.json'), JSON.stringify({ synthetic: true, checks, errors, expected401, unhandled }, null, 2))
  console.log(JSON.stringify({ checks, errors, expected401Count: expected401.length, unhandled }))
} catch (error) {
  if (page) await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(resolve(output, 'failure.json'), JSON.stringify({ message: error.message, checks, errors, expected401, unhandled }, null, 2))
  console.error(error)
  process.exitCode = 1
} finally {
  if (browser) await browser.close()
  await server.close()
  console.log(JSON.stringify({ stopped: true, pid: process.pid, port: 5189 }))
}
