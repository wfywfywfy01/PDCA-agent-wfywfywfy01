// Run: node scripts/duzhan-ui-acceptance.mjs [--playwright-module=/path/to/playwright/index.js]
// Requires existing web dependencies, Playwright and its Chromium browser. Installs nothing.
// --screenshots-only refreshes screenshots without repeating save/enable acceptance.
// Synthetic UI fixtures only. All API requests are fulfilled locally; no production access.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '../../..')
const output = resolve(root, '.artifacts/ui-qa')
await mkdir(output, { recursive: true })
const screenshotsOnly = process.argv.includes('--screenshots-only')
const web = resolve(root, 'apps/web')
const require = createRequire(import.meta.url)
const moduleArgument = process.argv.find(item => item.startsWith('--playwright-module='))
const { chromium } = require(moduleArgument ? moduleArgument.slice('--playwright-module='.length) : 'playwright')
const { createServer } = await import(new URL('../node_modules/vite/dist/node/index.js', import.meta.url))
const groupId = '00000000-0000-4000-8000-000000000001'
const taskId = '00000000-0000-4000-8000-000000000002'
const newId = '00000000-0000-4000-8000-000000000003'
const botId = 'fixture-bot-no-credentials'
const memberRows = [
  { user_id: 101, name: '示例发布人', role: 'admin' },
  { user_id: 102, name: '示例成员甲', role: 'member' },
  { user_id: 103, name: '示例成员乙', role: 'member' },
  { user_id: 104, name: '示例成员丙', role: 'member' },
]
const schema = { blocks: [
  { type: 'group', label: '群聊', multiple: false, fields: [{ key: 'channel_id', label: '群', kind: 'uuid', required: true }] },
  { type: 'times', label: '时间', multiple: false, fields: [{ key: 'slots', label: '时间', kind: 'slots', default: ['10:00', '15:00', '20:00'] }] },
  { type: 'task_policy', label: '任务规则', multiple: false, fields: [] },
  { type: 'condition', label: '提醒条件', fields: [
    { key: 'key', label: '条件', kind: 'select', options: ['workday', 'holiday', 'has_data'], option_labels: { workday: '工作日', holiday: '节假日', has_data: '数据完整' }, required: true },
    { key: 'value', label: '满足', kind: 'bool', default: true },
  ] },
  { type: 'rule', label: '提醒重点', fields: [{ key: 'mode', label: '方式', kind: 'select', options: ['text','ai'], default: 'text' }, { key: 'text', label: '文案', kind: 'textarea' }] },
  { type: 'style', label: '旧版样式', multiple: false, fields: [{ key: 'lang', label: '语言', kind: 'select', options:['zh','en'] }] },
] }
let agents = [
  { id: 1, name: '示例部门督战官', enabled: true, timezone: 'Asia/Shanghai', note: '', errors: [], renderer: 'duzhan.render_brief', updated_at: '2026-10-28T00:00:00+00:00', blocks: { blocks: [
    { type: 'group', channel_id: groupId, label: '示例经销商一部' }, { type: 'times', slots: ['10:00','15:00','20:00'] },
    { type: 'people', names: ['示例成员甲','示例成员乙','示例成员丙'] }, { type: 'style', lang: 'zh', title: '示例经销商一部' },
  ] } },
  { id: 2, name: '示例项目督战官', enabled: false, timezone: 'Asia/Shanghai', note: '', errors: [], renderer: 'group_tasks', updated_at: '2026-10-28T00:00:00+00:00', blocks: { blocks: [
    { type: 'group', channel_id: taskId, label: '示例项目协作群' }, { type: 'times', slots: ['10:00','20:00'] },
    { type: 'task_policy', publisher_user_ids: [101], excluded_user_ids: [104] },
  ] } },
]
let metric = { channel_id: groupId, month: '2026-10', goal: 'amount', sales_target_wan: 200, mto_daily_count: 4, mto_min_wan: 30, version: 1, source: 'saved', updated_at: '2026-10-28T00:00:00+00:00' }
const errors = [], warnings = [], requests = [], unhandled = [], overflows = [], checks = []
const server = await createServer({ root: web, server: { host: '127.0.0.1', port: 5188, strictPort: true }, mode: 'development', logLevel: 'warn' })
let browser, page
try {
  await server.listen()
  console.log(JSON.stringify({ started: true, pid: process.pid, port: 5188, mode: 'headless synthetic local UI test' }))
  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai' })
  await context.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.hostname !== '127.0.0.1') return route.abort()
    return route.continue()
  })
  page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text())
    if (message.type() === 'warning') warnings.push(message.text())
  })
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    if (!path.startsWith('/api/')) return route.continue()
    const body = request.postDataJSON()
    requests.push({ path, method, body })
    let result
    if (path === '/api/auth/me') result = { username: 'ui-test', display_name: '界面验收', role: 'admin' }
    else if (path === '/api/omega/status') result = { ready: false }
    else if (path === '/api/duzhan-agents/block-schema') result = schema
    else if (path === '/api/duzhan-agents/runtime-status') result = { source: 'db', enabled: true, ctob_enabled: false, bot_app_id: botId, supported_channel_ids: [groupId], department_rosters: { [groupId]: ['示例成员甲','示例成员乙','示例成员丙'] }, department_task_only_rosters: { [groupId]: ['示例成员丙'] }, schedule_updates_require_restart: true, group_tasks_enabled: true, group_tasks_schedule_live: true }
    else if (path === '/api/duzhan-agents/ai-status') result = { day:'2026-10-28',calls:0,cached:0,limit:60 }
    else if (path === '/api/agent-admin/bot-channels') result = { items: [{ app_id: botId, channel_type: 'group', channel_id: groupId, channel_name: '示例经销商一部' }] }
    else if (path === '/api/duzhan-agents/group-options') result = { configured: true, bot_app_id: botId, items: [
      { channel_id: groupId, label: '示例经销商一部', bot_joined: true, available: false, reason: '已由业务督战管理', members: memberRows },
      { channel_id: taskId, label: '示例项目协作群', bot_joined: true, available: true, members: memberRows },
      { channel_id: newId, label: '示例专项交付群', bot_joined: true, available: true, members: memberRows },
    ] }
    else if (path === '/api/duzhan-agents/monthly-metrics') {
      if (method === 'PUT') metric = { ...body, version: body.version + 1, source: 'saved' }
      result = { metrics: { ...metric, month: url.searchParams.get('month') || metric.month }, saved_months: ['2026-10'] }
    }
    else if (path === '/api/duzhan-agents' && method === 'GET') result = { items: agents }
    else if (path === '/api/duzhan-agents' && method === 'POST') {
      const saved = { ...body, id: 3, enabled: false, errors: [], renderer: 'group_tasks', updated_at: '2026-10-28T01:00:00+00:00', blocks: {blocks:body.blocks} }
      agents.push(saved); result = saved
    }
    else if (/\/api\/duzhan-agents\/\d+$/.test(path) && method === 'PUT') {
      const id = Number(path.split('/').at(-1)); const index = agents.findIndex(item => item.id === id)
      agents[index] = { ...agents[index], ...body, blocks: {blocks:body.blocks} }; result = agents[index]
    }
    else if (path.endsWith('/preview')) {
      const id = Number(path.split('/').at(-2)), agent = agents.find(item => item.id === id)
      result = { mode: 'render', ok: true, group: agent.blocks.blocks.find(item => item.type === 'group').label, day: body.day, slot: body.slot || '20:00', source: 'task_ledger', body: '【晚间任务核对】\n示例成员甲：已找到提交记录，待验收。\n示例成员乙：请补充本次任务的实际提交证据。', send_allowed: true, send_reason: '配置条件满足', note: '合成 UI 测试数据，未取真实群消息。' }
    }
    else if (path.endsWith('/toggle')) {
      const id = Number(path.split('/').at(-2)), agent = agents.find(item => item.id === id)
      agent.enabled = body.enabled; result = agent
    }
    else { unhandled.push({path,method}); return route.fulfill({status:500,json:{detail:'未配置的测试接口'}}) }
    return route.fulfill({ status: 200, json: result })
  })
  await page.goto('http://127.0.0.1:5188/admin/duzhan-agents', { waitUntil: 'networkidle' })
  await page.getByRole('heading',{name:'示例经销商一部',exact:true}).waitFor()
  assert.equal(await page.getByText('仅追待办',{exact:true}).count(),1)
  if (!screenshotsOnly) {
    await page.getByRole('button',{name:'2 规则与时间'}).click()
    await page.getByLabel('本月业绩目标（万元）',{exact:true}).fill('350')
    await page.locator('.group-row').filter({hasText:'示例项目协作群'}).click()
    await page.getByText('当前配置有未保存的改动。',{exact:true}).waitFor()
    await page.getByRole('button',{name:'继续编辑',exact:true}).click()
    assert.equal(await page.getByLabel('本月业绩目标（万元）',{exact:true}).inputValue(),'350')
    await page.getByRole('button',{name:'保存本月指标',exact:true}).click()
    await page.getByText('本月指标已保存，下一次检查生效。',{exact:true}).waitFor()
    assert.equal(requests.filter(item=>item.path.endsWith('/monthly-metrics')&&item.method==='PUT').length,1)
    checks.push('department metrics persisted and unsaved-switch protected')
  }
  await page.getByRole('button',{name:'＋ 新建督战',exact:true}).click()
  await page.getByRole('heading',{name:'让一个群开始有序跟进',exact:true}).waitFor()
  const select = page.locator('.group-form select')
  await select.selectOption(newId)
  assert.equal(await page.getByLabel('配置名称',{exact:true}).inputValue(),'示例专项交付群督战官')
  assert.notEqual(await select.locator(`option[value="${groupId}"]`).getAttribute('disabled'),null)
  await page.locator('.task-policy fieldset').nth(0).getByRole('checkbox',{name:/示例发布人/}).check()
  await page.locator('.task-policy fieldset').nth(1).getByRole('checkbox',{name:'示例成员丙',exact:true}).check()
  await page.getByLabel('搜索任务发布人',{exact:true}).fill('未匹配')
  await page.getByText('没有匹配的成员，换个姓名试试。',{exact:true}).waitFor()
  await page.getByLabel('搜索任务发布人',{exact:true}).fill('')
  checks.push('new group, selected publisher and exclusion, search empty state')
  for (const width of [1920,1440,390,320]) {
    await page.setViewportSize({width,height:1000})
    await page.getByRole('heading', { level: 1 }).click()
    await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' }))
    await page.screenshot({path:resolve(output,`group-${width}.png`),fullPage:false,animations:'disabled'})
    await page.screenshot({path:resolve(output,`group-${width}-full.png`),fullPage:true,animations:'disabled'})
    const dimensions = await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth}))
    overflows.push({screen:'group',...dimensions})
  }
  await page.setViewportSize({width:1440,height:1000})
  await page.getByRole('button',{name:'下一步：规则与时间 →',exact:true}).click()
  await page.getByLabel('早间提醒时间',{exact:true}).fill('09:30')
  await page.getByLabel('早间提醒时间',{exact:true}).press('Tab')
  await page.getByRole('checkbox',{name:/午间轻提醒/}).check()
  await page.getByLabel('午间轻提醒时间',{exact:true}).fill('14:30')
  await page.getByLabel('午间轻提醒时间',{exact:true}).press('Tab')
  for (const width of [1920,1440,390,320]) {
    await page.setViewportSize({width,height:1000})
    await page.getByRole('heading', { level: 1 }).click()
    await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' }))
    await page.screenshot({path:resolve(output,`schedule-${width}.png`),fullPage:false,animations:'disabled'})
    await page.screenshot({path:resolve(output,`schedule-${width}-full.png`),fullPage:true,animations:'disabled'})
    const dimensions = await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth}))
    overflows.push({screen:'schedule',...dimensions})
  }
  await page.setViewportSize({width:1440,height:1000})
  if (!screenshotsOnly) {
    await page.getByRole('button',{name:'保存并预览 →',exact:true}).click()
    await page.locator('.message-preview').waitFor()
    const created = requests.find(item=>item.path==='/api/duzhan-agents'&&item.method==='POST')
    assert.ok(created)
    assert.notEqual(created.body.enabled,true)
    assert.deepEqual(created.body.blocks.find(item=>item.type==='times').slots,['09:30','14:30','20:00'])
    assert.deepEqual(created.body.blocks.find(item=>item.type==='task_policy'),{type:'task_policy',publisher_user_ids:[101],excluded_user_ids:[104]})
    assert.equal(requests.filter(item=>item.path.endsWith('/toggle')).length,0)
    checks.push('save+preview posts correct independent policy and time slots without enabling')
    await page.getByRole('button',{name:'启用督战',exact:true}).click()
    await page.getByText('督战已启用',{exact:true}).waitFor()
    assert.equal(requests.filter(item=>item.path.endsWith('/toggle')).length,1)
    assert.equal(requests.find(item=>item.path.endsWith('/toggle')).body.enabled,true)
    checks.push('explicit enable is separate from save and preview')
    await page.getByRole('button',{name:'1 群与人员'}).click()
    await page.getByLabel('配置名称',{exact:true}).fill('尚未保存的测试名称')
    await page.locator('.group-row').filter({hasText:'示例项目协作群'}).click()
    await page.getByRole('button',{name:'放弃改动并切换',exact:true}).click()
    await page.getByRole('heading',{name:'示例项目协作群',exact:true}).waitFor()
    assert.equal(await page.getByLabel('配置名称',{exact:true}).inputValue(),'示例项目督战官')
    checks.push('discard-and-switch retains saved target configuration')
    await page.getByRole('button',{name:'复用规则到新群',exact:true}).click()
    assert.equal(await page.locator('.group-form select').inputValue(),'')
    assert.equal(await page.locator('.task-policy input[type="checkbox"]:checked').count(),0)
    checks.push('copy template clears old group and member identities')
    await page.getByRole('button',{name:'3 预览与启用'}).click()
    await page.getByRole('button',{name:'保存并预览',exact:true}).click()
    await page.waitForTimeout(200)
    assert.equal(await page.locator('.steps button[aria-current="step"]').innerText(),'1\n群与人员')
    checks.push('incomplete draft returns to required group fields')
  }
  await writeFile(resolve(output,screenshotsOnly ? 'screenshots-results.json' : 'results.json'),JSON.stringify({synthetic:true,checks,errors,warnings,unhandled,overflows,requests},null,2))
  console.log(JSON.stringify({checks,errors,warnings,unhandled,overflows}))
  assert.equal(unhandled.length,0)
  assert.ok(overflows.every(item=>item.scroll<=item.width && item.body<=item.width),'horizontal overflow')
  assert.equal(errors.length,0,'browser console errors')
  assert.equal(warnings.length,0,'browser warnings')
} catch(error) {
  if (page) await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{})
  await writeFile(resolve(output,'failure.json'),JSON.stringify({message:error.message,stack:error.stack,checks,errors,warnings,unhandled,overflows,requests},null,2))
  console.error(error)
  process.exitCode=1
} finally {
  if(browser) await browser.close()
  await server.close()
  console.log(JSON.stringify({stopped:true,pid:process.pid,port:5188}))
}
