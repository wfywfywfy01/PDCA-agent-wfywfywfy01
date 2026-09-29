/** Throwaway Omega prototype: browser memory only, no production API calls. */
type Row = Record<string, any>

const draft = {
  title: '海外经销商回款谈判',
  public_brief: '经销商确认收到上一批货，双方正在讨论尾款和下一批订单。',
  seller_private: '先争取书面付款承诺；不承诺额外折扣。',
  counterparty_brief: '经销商希望先确认下一批货的交付安排，再支付尾款。',
  buyer_name: 'Alex', buyer_role: '采购负责人', buyer_company: '示例经销商',
  buyer_emotion: '谨慎，担心交付延迟', buyer_objections: ['交付时间不确定', '现金流紧张'],
  score_weights: { outcome: 25, information: 12, value: 12, concessions: 12,
    objections: 10, listening: 8, compliance: 10, relationship: 6, closure: 5 },
  dealer_id: '',
  goal: {
    outcome_type: 'payment_commitment', success_condition: '确认尾款金额和付款日期，并取得书面承诺',
    ideal: '本周五付清尾款', minimum: '确认两期付款时间表', hard_limits: ['不承诺额外折扣'],
    amount_minor: 1000000, currency: 'USD', due_date: '2026-10-09',
  },
}

function clone<T>(value: T): T { return structuredClone(value) }
function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

export function installOmegaDemo() {
  const cases: Row[] = [{ id: 'demo-case', title: draft.title, owner_id: 1, revision: 1,
    current_version: 1, draft_confirmed: true, draft: clone(draft) }]
  const sessions: Row[] = [{ id: 'demo-real', case_id: 'demo-case', owner_id: 1,
    status: 'ended', mode: 'real_review', goal_timing: 'pre',
    case_version: 1, case_snapshot: clone(draft), assignment_id: null,
    segments: [{ id: 'demo-real-sales', seq: 1, speaker: 'sales', text: '请确认付款日期。' },
      { id: 'demo-real-buyer', seq: 2, speaker: 'counterparty', text: '交付时间不确定，我还不能承诺付款。' }],
    latest_report_id: 'demo-real-report' }]
  const jobs = new Map<string, Row>()
  const reports = new Map<string, Row>([['demo-real-report', { id: 'demo-real-report',
    session_id: 'demo-real', content: { outcome: { status: 'unverified', reason: '示例逐字稿没有书面付款承诺。', quotes: [] },
      commitments: [], concession_costs: [], hard_limit_findings: [],
      dimensions: [{ key: 'objections', score: 4, reason: '销售只要求日期，未回应交付顾虑。',
        quotes: [{ segment_id: 'demo-real-sales', speaker: 'sales', start: 0, end: 8, text: '请确认付款日期。' }] }],
      score_weights: draft.score_weights, score: { earned: 4, available: 10, total: null },
      next_practice: '先复述交付顾虑，再确认付款日期。' }, reviews: [] }]])
  const assignments: Row[] = [{ id: 'demo-assignment', case_id: 'demo-case', assignee_id: 1,
    source_report_id: 'demo-real-report', target_dimension: 'objections', pass_percent: 70,
    instructions: '先复述交付顾虑，再锁定付款时间。', due_at: null,
    baseline: { score: 4, maximum: 10, percent: 40, report_id: 'demo-real-report' },
    attempts: [], status: 'pending' }]
  const nextId = () => crypto.randomUUID()
  const addSegment = (game: Row, speaker: string, text: string) => {
    game.segments.push({ id: nextId(), speaker, text, seq: game.segments.length + 1 })
  }
  const reply = (text: string) => /付款|回款|pay|payment/i.test(text)
    ? '我可以在本周五安排首笔付款。请先发来金额和交付时间表，我们书面确认。'
    : '我需要确认交付和付款安排。你能提出一个具体日期吗？'

  const realFetch = window.fetch.bind(window)
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href)
    if (!url.pathname.startsWith('/api/')) return realFetch(input, init)
    const path = url.pathname
    const method = init?.method || 'GET'
    const body = init?.body && typeof init.body === 'string' ? JSON.parse(init.body) as Row : {}
    if (path === '/api/auth/me') return json({ id: 1, username: 'demo-manager', display_name: '演示主管', role: 'manager' })
    if (path === '/api/auth/logout') return json({ ok: true })
    if (path === '/api/omega/status') return json({ enabled: true, ready: true, actor_id: 1, role: 'manager',
      model_configured: true, worker_online: true, realtime_configured: true })
    if (path === '/api/omega/team-members') return json([{ id: 1, name: '演示主管' }])
    if (path === '/api/omega/case-draft/analyze') return json({ draft: {
      ...clone(draft), title: '演示：经销商回款谈判',
      goal: { ...clone(draft.goal), amount_major: '10000' },
    } })
    if (path === '/api/omega/assignments') {
      if (method === 'GET') return json(assignments)
      const scenario = cases.find((item) => item.id === body.case_id)
      const sourceReport = reports.get(body.source_report_id)
      const dimension = sourceReport?.content.dimensions.find((item: Row) => item.key === body.target_dimension)
      const maximum = scenario?.draft.score_weights[body.target_dimension] || 10
      const baseline = dimension?.score == null ? null : { score: dimension.score, maximum,
        percent: Math.round(dimension.score * 100 / maximum), report_id: sourceReport!.id }
      const row = { id: nextId(), ...body, baseline, attempts: [], status: 'pending' }
      assignments.unshift(row)
      return json(row, 201)
    }
    const assignmentMatch = /^\/api\/omega\/assignments\/([^/]+)$/.exec(path)
    if (assignmentMatch) {
      const row = assignments.find((item) => item.id === assignmentMatch[1])
      return row ? json(row) : json({ detail: '指派不存在' }, 404)
    }
    if (path === '/api/omega/cases') {
      if (method === 'GET') return json(cases)
      const row = { id: nextId(), title: body.title, owner_id: 1, revision: 1,
        current_version: 0, draft_confirmed: false, draft: body }
      cases.push(row)
      return json(row, 201)
    }
    const caseMatch = /^\/api\/omega\/cases\/([^/]+)(?:\/(confirm))?$/.exec(path)
    if (caseMatch) {
      const row = cases.find((item) => item.id === caseMatch[1])
      if (!row) return json({ detail: '演示任务不存在' }, 404)
      if (caseMatch[2] === 'confirm') {
        row.current_version += 1
        row.draft_confirmed = true
        return json({ id: nextId(), version: row.current_version })
      }
      if (method === 'PATCH') {
        row.title = body.title
        row.draft = body
        row.revision += 1
        row.draft_confirmed = false
        return json(row)
      }
    }
    if (path === '/api/omega/sessions') {
      if (method === 'GET') return json(sessions)
      const scenario = cases.find((item) => item.id === body.case_id)
      if (!scenario?.draft_confirmed) return json({ detail: '先确认目标版本' }, 409)
      const assignment = body.assignment_id ? assignments.find((item) => item.id === body.assignment_id) : null
      if (body.assignment_id && (!assignment || assignment.case_id !== scenario.id)) return json({ detail: '指派不存在' }, 404)
      const game = { id: nextId(), case_id: scenario.id, owner_id: 1, status: 'active', mode: 'rehearsal',
        case_version: scenario.current_version, case_snapshot: clone(scenario.draft), segments: [] as Row[],
        latest_report_id: '', assignment_id: assignment?.id || null }
      sessions.unshift(game)
      if (assignment) { assignment.attempts.push({ session_id: game.id, status: 'active', result: null, passed: false }); assignment.status = 'in_progress' }
      return json(game, 201)
    }
    const sessionMatch = /^\/api\/omega\/sessions\/([^/]+)(?:\/(turns|finish|reports))?$/.exec(path)
    if (sessionMatch) {
      const game = sessions.find((item) => item.id === sessionMatch[1])
      if (!game) return json({ detail: '演示会话不存在' }, 404)
      if (!sessionMatch[2]) return json(game)
      if (sessionMatch[2] === 'turns') {
        if (game.status !== 'active') return json({ detail: '演练已结束' }, 409)
        addSegment(game, 'sales', String(body.text))
        addSegment(game, 'counterparty', reply(String(body.text)))
        const job = { id: nextId(), kind: 'turn', status: 'succeeded', result_id: '', error: '' }
        jobs.set(job.id, job)
        return json(job, 202)
      }
      if (sessionMatch[2] === 'finish') {
        game.status = 'ended'
        const assignment = assignments.find((item) => item.id === game.assignment_id)
        const attempt = assignment?.attempts.find((item: Row) => item.session_id === game.id)
        if (attempt) attempt.status = 'ended'
        return json(game)
      }
      const reportId = nextId()
      const report = { id: reportId, content: {
        outcome: { status: 'unverified', reason: '演示报告：需由真人核对付款凭证和书面承诺。', quotes: [] },
        commitments: [], concession_costs: [], hard_limit_findings: [],
        dimensions: game.segments.length ? [{ key: 'objections', score: 8,
          reason: '演示评分：练习回应了付款异议，请由主管复核。', quotes: [{ segment_id: game.segments[0].id,
            speaker: 'sales', start: 0, end: game.segments[0].text.length, text: game.segments[0].text }] }] : [],
        score_weights: game.case_snapshot.score_weights,
        score: { earned: 8, available: 10, total: null }, next_practice: '明确金额、日期和书面确认方式。',
      }, reviews: [] as Row[] }
      reports.set(reportId, report)
      game.latest_report_id = reportId
      const assignment = assignments.find((item) => item.id === game.assignment_id)
      const attempt = assignment?.attempts.find((item: Row) => item.session_id === game.id)
      if (attempt && assignment) { attempt.result = { score: 8, maximum: 10, percent: 80, report_id: reportId }; attempt.passed = 80 >= assignment.pass_percent; assignment.status = attempt.passed ? 'passed' : 'in_progress' }
      const job = { id: nextId(), kind: 'report', status: 'succeeded', result_id: reportId, error: '' }
      jobs.set(job.id, job)
      return json(job, 202)
    }
    const jobMatch = /^\/api\/omega\/jobs\/([^/]+)$/.exec(path)
    if (jobMatch) return jobs.has(jobMatch[1]) ? json(jobs.get(jobMatch[1])) : json({ detail: '任务不存在' }, 404)
    const reportMatch = /^\/api\/omega\/reports\/([^/]+)(?:\/(reviews))?$/.exec(path)
    if (reportMatch) {
      const report = reports.get(reportMatch[1])
      if (!report) return json({ detail: '报告不存在' }, 404)
      if (reportMatch[2] === 'reviews') {
        report.reviews.push({ id: nextId(), content: body })
        return json({ id: nextId() }, 201)
      }
      return json(report)
    }
    if (path === '/api/omega/transcribe') return json({ text: '请确认本周五付款日期。', needs_manual_review: true })
    return json({ detail: '交互原型未连接此服务' }, 404)
  }

  class DemoSocket {
    static readonly OPEN = 1
    readonly url: string
    readyState = 0
    binaryType: BinaryType = 'blob'
    bufferedAmount = 0
    onmessage: ((event: MessageEvent) => void) | null = null
    onclose: (() => void) | null = null
    onerror: (() => void) | null = null
    private activeFrames = 0
    private silentFrames = 0
    private responded = false

    constructor(url: string | URL) {
      this.url = String(url)
      setTimeout(() => {
        if (this.readyState !== 0) return
        this.readyState = 1
        this.emit({ type: 'ready' })
      }, 120)
    }

    private emit(value: unknown) {
      if (this.readyState === 1) this.onmessage?.(new MessageEvent('message', {
        data: value instanceof ArrayBuffer ? value : JSON.stringify(value),
      }))
    }

    send(data: string | ArrayBufferLike | Blob | ArrayBufferView) {
      if (data === 'stop' || this.responded || !(data instanceof ArrayBuffer)) return
      const samples = new Int16Array(data)
      let level = 0
      for (let index = 0; index < samples.length; index += 8) level += Math.abs(samples[index])
      const speaking = level / Math.ceil(samples.length / 8) > 260
      if (speaking) { this.activeFrames++; this.silentFrames = 0 }
      else if (this.activeFrames) this.silentFrames++
      if (this.activeFrames < 30 || (this.silentFrames < 15 && this.activeFrames < 90)) return
      this.responded = true
      const game = sessions.find((item) => this.url.includes(`/sessions/${item.id}/`))
      if (!game || game.status !== 'active') return
      const salesText = '演示转写：请确认尾款付款日期。'
      const answer = reply(salesText)
      addSegment(game, 'sales', salesText)
      this.emit({ type: 'caption', speaker: 'sales', text: salesText })
      this.emit({ type: 'segment' })
      setTimeout(() => {
        if (this.readyState !== 1) return
        addSegment(game, 'counterparty', answer)
        this.emit({ type: 'caption', speaker: 'counterparty', text: answer })
        for (let part = 0; part < 4; part++) {
          const tone = new Float32Array(2400)
          for (let i = 0; i < tone.length; i++) tone[i] = Math.sin(2 * Math.PI * 660 * (i + part * 2400) / 24000) * 0.04
          this.emit(tone.buffer)
        }
        this.emit({ type: 'segment' })
      }, 350)
    }

    close() {
      if (this.readyState === 3) return
      this.readyState = 3
      queueMicrotask(() => this.onclose?.())
    }
  }

  window.WebSocket = DemoSocket as unknown as typeof WebSocket
}
