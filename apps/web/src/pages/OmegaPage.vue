<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import AppNav from '@/components/AppNav.vue'
import OmegaSetup from '@/components/omega/OmegaSetup.vue'
import OmegaMeetingMaterials from '@/components/omega/OmegaMeetingMaterials.vue'
import OmegaMemoryReview from '@/components/omega/OmegaMemoryReview.vue'
import OmegaProfiles from '@/components/omega/OmegaProfiles.vue'
import type { MeetingMaterial, Participant, TemplateStart } from '@/components/omega/omega-types'
import { apiGet, apiPatch, apiPost, apiRequest, HttpError } from '@/api/client'

type Goal = {
  outcome_type: 'payment_commitment' | 'new_order' | 'schedule' | 'other'
  success_condition: string
  ideal: string
  minimum: string
  hard_limits: string[]
  amount_minor: number | null
  currency: string | null
  due_date: string | null
}
type CaseDraft = {
  kind?: string
  usage?: 'training' | 'rehearsal' | 'real_review'
  meeting_type?: string
  stage_summary?: string
  meeting_topic?: string
  meeting_materials?: MeetingMaterial[]
  participants?: Participant[]
  title: string
  public_brief: string
  seller_private: string
  counterparty_brief: string
  buyer_name: string
  buyer_role: string
  buyer_company: string
  buyer_emotion: string
  buyer_objections: string[]
  score_weights: Record<string, number>
  dealer_id: string
  goal: Goal
}
type ExtractedDraft = Partial<Omit<CaseDraft, 'goal' | 'score_weights' | 'dealer_id'>> & {
  goal?: Partial<Omit<Goal, 'amount_minor'>> & { amount_major?: string }
}
type CaseRow = { id: string; kind?: string; title: string; team_key?: string; owner_id: number; revision: number; current_version: number; draft_confirmed: boolean; draft: CaseDraft }
type Segment = { id: string; speaker: string; speaker_id?: string; source_speaker?: string; text: string; asr_original?: string; seq: number }
type SessionRow = { id: string; case_id: string; team_key?: string; owner_id: number; assignment_id?: string | null; status: string; mode: string; created_at?: string; goal_timing?: string; case_version?: number; case_version_id?: string; case_snapshot?: CaseDraft; segments?: Segment[]; latest_report_id?: string; pending_job_id?: string; failed_turn_job_id?: string; report_blocked?: boolean; report_blocked_message?: string; report_partial?: boolean; report_warning?: string; voice_tail_unrecoverable?: boolean }
type Job = { id: string; status: string; result_id: string; error: string; kind: string }
type Quote = { segment_id: string; speaker: string; text: string; start: number; end: number }
type Fact = { description?: string; reason?: string; quotes: Quote[] }
type Report = { id: string; content: { evidence_status?: 'incomplete'; incomplete_reason?: string; saved_segment_count?: number; saved_quotes?: Quote[]; outcome?: { status: string; reason: string; quotes: Quote[] }; dimensions?: Array<{ key: string; score: number | null; reason: string; quotes: Quote[] }>; score?: { earned: number; available: number; total: number | null }; score_weights?: Record<string, number>; commitments?: Fact[]; concession_costs?: Fact[]; hard_limit_findings?: Fact[]; next_practice?: string | Record<string, unknown>; hints_used?: Array<{ id: string }> }; reviews: Array<{ content: { comment: string; next_practice: string; outcome_verdict?: 'confirmed' | 'rejected' | null } }> }
type DimensionResult = { score: number; maximum: number; percent: number; report_id: string } | null
type Assignment = { id: string; case_id: string; team_key?: string; assignee_id: number; source_report_id: string | null; source_session_id: string | null; target_dimension: string; pass_percent: number; instructions: string; due_at: string | null; baseline: DimensionResult; baseline_quote: string | null; baseline_reason: string; attempts: Array<{ session_id: string; status: string; result: DimensionResult; passed: boolean; outcome_review?: 'confirmed' | 'rejected' | null }>; status: 'pending' | 'in_progress' | 'passed' }

const defaultWeights: Record<string, number> = { outcome: 25, information: 12, value: 12,
  concessions: 12, objections: 10, listening: 8, compliance: 10, relationship: 6, closure: 5 }
const dimensionOrder = Object.keys(defaultWeights)
const dimensionNames: Record<string, string> = { outcome: '结果', information: '信息获取', value: '价值表达',
  concessions: '让步', objections: '异议处理', listening: '倾听', compliance: '底线合规', relationship: '关系', closure: '收尾' }
const quickScenarios = [
  { title: '客户要求降价', brief: '销售与客户正在讨论一笔订单，客户提出价格顾虑。',
    stance: '客户希望获得更好的价格，尚未答应下单。', objection: '现在的价格缺少说服力。',
    goal: '弄清价格顾虑，并争取一个可核实的下一步。' },
  { title: '客户要求延期付款', brief: '销售与客户正在讨论付款安排，客户希望延期。',
    stance: '客户担心当前付款安排难以执行，尚未承诺付款日期。', objection: '目前无法按原计划付款。',
    goal: '弄清延期原因，并争取可核实的付款协商安排。' },
  { title: '客户迟迟不下单', brief: '销售与客户正在讨论订单，客户尚未决定。',
    stance: '客户对立即下单仍有顾虑，需要销售进一步说明。', objection: '现在还不能决定下单。',
    goal: '找到真正的决策卡点，并约定可核实的下一步。' },
]
const safeTrainingLimit = '未经确认，不承诺价格、付款日期或交期。'
const outcomeNames: Record<string, string> = { achieved: '达成目标', partial: '部分达成',
  not_achieved: '未达成', unverified: '证据不足' }
function reportSavedNotice(result: Report): string {
  if (result.content.evidence_status === 'incomplete') return '部分复盘已保存；语音尾稿不完整，本场不能评分或达标。'
  return result.content.score?.total == null
    ? '复盘已生成；评分证据不足，暂无总分。' : '复盘已生成，对话和评分已保存。'
}

const router = useRouter()
const demoMode = import.meta.env.MODE === 'omega-demo'
const me = ref<{ id: number; role: string } | null>(null)
const cases = ref<CaseRow[]>([])
const sessions = ref<SessionRow[]>([])
const assignments = ref<Assignment[]>([])
const sessionsHasMore = ref(false)
const assignmentsHasMore = ref(false)
const loadingMoreSessions = ref(false)
const loadingMoreAssignments = ref(false)
const sidebarTab = ref<'cases' | 'assignments' | 'sessions'>('cases')
const mobileNavOpen = ref(false)
const showAllSessions = ref(false)
const members = ref<Array<{ id: number; name: string; username?: string; team_key?: string }>>([])
const chosenAssignment = ref<Assignment | null>(null)
const assignUserId = ref<number | null>(null)
const assignDimension = ref('objections')
const assignPassPercent = ref(70)
const assignInstructions = ref('')
const assignDueDate = ref('')
const chosenCase = ref<CaseRow | null>(null)
const chosenSession = ref<SessionRow | null>(null)
const report = ref<Report | null>(null)
const focusedQuoteId = ref('')
const activeJob = ref<Job | null>(null)
const textInput = ref('')
const reviewText = ref('')
const nextPractice = ref('')
const outcomeVerdictInput = ref<'' | 'confirmed' | 'rejected'>('')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const loading = ref(true)
const editing = ref(false)
const recording = ref(false)
const asrBusy = ref(false)
const realtimeReady = ref(false)
const textReady = ref(false)
const multiVoiceReady = ref(false)
const setupOpen = ref(true)
const setupKey = ref(0)
const setupRef = ref<{ hasUnsavedChanges: () => boolean; isBusy: () => boolean } | null>(null)
const discardPrompt = ref('')
const discardButton = ref<HTMLButtonElement | null>(null)
let pendingDiscardAction: (() => void | Promise<void>) | null = null
let pendingRouteResolve: ((allow: boolean) => void) | null = null
let discardApproved = false
const profilesOpen = ref(false)
const voicePhase = ref<'live' | 'pausing' | 'coaching' | 'resuming' | 'error'>('live')
const voiceRecoveryBlocked = ref(false)
const voiceEpoch = ref(0)
let packetEpoch = 0
const currentSpeakerId = ref('')
const coachText = ref('')
const coachBusy = ref(false)
const coachError = ref('')
let coachTimer: ReturnType<typeof setTimeout> | undefined
let controlTimer: ReturnType<typeof setTimeout> | undefined
let pendingControlKey = ''
let primedVoice = false
let primedSessionId = ''
const participants = computed(() => chosenSession.value?.case_snapshot?.participants || [])
const currentSpeakerName = computed(() => participants.value.find(row => row.id === currentSpeakerId.value)?.name || '对手')
const voiceAllowed = computed(() => participants.value.length <= 1 || multiVoiceReady.value)
const voiceConnecting = ref(false)
const voiceConnected = ref(false)
const voiceInterrupted = ref(false)
const voiceEndNotice = ref('')
const voiceSessionKey = 'omega-active-voice-session'
function rememberedVoiceSession() {
  try { return sessionStorage.getItem(voiceSessionKey) } catch { return null }
}
function rememberVoiceSession(id: string | null) {
  try {
    if (id) sessionStorage.setItem(voiceSessionKey, id)
    else sessionStorage.removeItem(voiceSessionKey)
  } catch { /* Voice still works when browser storage is unavailable. */ }
}
const voiceClosing = ref(false)
const voiceSpeaking = ref(false)
const voiceCaption = ref('')
const voiceVolume = ref(2.5)
const voiceDialog = ref<HTMLDialogElement | null>(null)
const callOpen = computed(() => voiceConnecting.value || voiceConnected.value || voiceClosing.value)
const voiceOriginal = ref('')
const amountMajor = ref('')
const meetingId = ref('')
const meetingSpeakers = ref<string[]>([])
const speakerMap = ref<Record<string, 'sales' | 'counterparty'>>({})
const participantMap = ref<Record<string, string>>({})
const meetingPreview = ref<Array<{ speaker: string; text: string }>>([])
const draft = ref<CaseDraft>(blankDraft())
const caseBriefInput = ref('')
let editingBaseline = ''
const materialBusy = ref(false)
const analysisBusy = ref(false)
const analysisReady = ref(false)
const reviewOpen = ref(false)
const reportWeights = computed(() => report.value?.content.score_weights || chosenSession.value?.case_snapshot?.score_weights || defaultWeights)
const coachingPoint = computed(() => {
  const weights = reportWeights.value
  const dimensions = (report.value?.content.dimensions || []).filter((row) => row.key !== 'outcome' && row.score !== null && row.quotes?.length && weights[row.key])
  return dimensions.sort((a, b) => a.score! * weights[b.key]! - b.score! * weights[a.key]!
    || dimensionOrder.indexOf(a.key) - dimensionOrder.indexOf(b.key))[0] || null
})
const strengthPoint = computed(() => {
  const weights = reportWeights.value
  return (report.value?.content.dimensions || []).filter(row => row.key !== 'outcome' && row.score !== null && row.quotes?.length && weights[row.key])
    .sort((a, b) => b.score! * weights[a.key]! - a.score! * weights[b.key]!
      || dimensionOrder.indexOf(a.key) - dimensionOrder.indexOf(b.key))[0] || null
})
const focusPercent = computed(() => {
  const point = coachingPoint.value
  const maximum = reportWeights.value[point?.key || '']
  return point && maximum ? Math.round(point.score! * 100 / maximum) : null
})
const focusPassPercent = computed(() => Math.min(100, Math.max(70, (focusPercent.value ?? 0) + 10)))
const currentAssignment = computed(() => assignments.value.find((row) => row.id === chosenSession.value?.assignment_id) || null)
const assignableMembers = computed(() => {
  const team = chosenSession.value?.team_key || chosenCase.value?.team_key
  return team ? members.value.filter((row) => row.team_key === team) : members.value
})
function memberLabel(member: { id: number; name: string; username?: string }): string {
  return members.value.some((row) => row.id !== member.id && row.name === member.name)
    ? `${member.name}（${member.username || member.id}）` : member.name
}
const currentAttempt = computed(() => currentAssignment.value?.attempts.find((item) => item.session_id === chosenSession.value?.id) || null)
function attemptLabel(attempt: Assignment['attempts'][number] | null, dimension: string): string {
  if (dimension !== 'outcome') return attempt?.passed ? '达标' : '待重练'
  if (attempt?.outcome_review === 'rejected') return '主管未认可'
  if (!attempt?.result) return '待评分'
  if (attempt.outcome_review !== 'confirmed') return '待主管确认'
  return attempt.passed ? '达标' : '继续练习'
}
const outcomeVerdict = computed(() => report.value?.reviews
  .filter((item) => item.content.outcome_verdict === 'confirmed' || item.content.outcome_verdict === 'rejected')
  .slice(-1)[0]?.content.outcome_verdict || null)
const outcomeLabel = computed(() => {
  const status = report.value?.content.outcome?.status || 'unverified'
  const label = outcomeNames[status] || '证据不足'
  if (outcomeVerdict.value === 'confirmed') return `主管已确认：${label}`
  if (outcomeVerdict.value === 'rejected') return `主管已驳回：AI 初判${label}`
  return ['achieved', 'partial'].includes(status) ? `AI 初判：${label}（待主管确认）` : `AI 初判：${label}`
})
const matchingAssignment = computed(() => assignments.value.find((row) => row.source_report_id === report.value?.id
  && row.assignee_id === assignUserId.value && row.target_dimension === coachingPoint.value?.key) || null)
const reportNextPractice = computed(() => {
  const value = report.value?.content.next_practice
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') {
    const action = value['动作'] || value.action
    if (typeof action === 'string') return action
  }
  return ''
})
const missingDraftFields = computed(() => {
  const fields: string[] = []
  const goal = draft.value.goal
  if (draft.value.title.trim().length < 2) fields.push('任务名称')
  if (draft.value.public_brief.trim().length < 5) fields.push('双方背景')
  if (draft.value.counterparty_brief.trim().length < 5) fields.push('对手立场')
  if (goal.success_condition.trim().length < 5) fields.push('成功条件')
  if (goal.ideal.trim().length < 2) fields.push('理想结果')
  if (goal.minimum.trim().length < 2) fields.push('最低可接受结果')
  if (!goal.hard_limits.some((value) => value.trim())) fields.push('硬底线')
  if (goal.outcome_type === 'payment_commitment') {
    if (!amountMajor.value.trim()) fields.push('目标金额')
    if (!goal.currency) fields.push('币种')
    if (!goal.due_date) fields.push('最迟日期')
  }
  return fields
})
let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollFailureJobId = ''
let pollFailures = 0
let pollError = ''
let quoteTimer: ReturnType<typeof setTimeout> | undefined
let recorder: MediaRecorder | undefined
let stream: MediaStream | undefined
let audioContext: AudioContext | undefined
const closingAudioContexts = new WeakSet<AudioContext>()
let recordingTimeout: ReturnType<typeof setTimeout> | undefined
let recordingToken = 0
let openToken = 0
let voiceToken = 0
let voiceSocket: WebSocket | undefined
let voiceStream: MediaStream | undefined
let voiceInput: AudioContext | undefined
let voiceOutput: AudioContext | undefined
let voiceGain: GainNode | undefined
let voiceWorklet: AudioWorkletNode | undefined
let nextVoicePlayback = 0
const voiceSources = new Set<AudioBufferSourceNode>()

function blankDraft(): CaseDraft {
  return { title: '', public_brief: '', seller_private: '', counterparty_brief: '', dealer_id: '',
    meeting_topic: '', meeting_materials: [],
    buyer_name: '', buyer_role: '', buyer_company: '', buyer_emotion: '', buyer_objections: [],
    score_weights: { ...defaultWeights },
    goal: { outcome_type: 'payment_commitment', success_condition: '', ideal: '', minimum: '',
      hard_limits: [''], amount_minor: null, currency: 'USD', due_date: null } }
}
function quickDraft(scenario: typeof quickScenarios[number]): CaseDraft {
  const base = blankDraft()
  return { ...base, title: `练习：${scenario.title}`, public_brief: scenario.brief,
    counterparty_brief: scenario.stance, buyer_objections: [scenario.objection],
    goal: { ...base.goal, outcome_type: 'other', success_condition: scenario.goal,
      ideal: scenario.goal, minimum: '明确客户顾虑和下一步。', hard_limits: [safeTrainingLimit],
      currency: null } }
}
function caseBody(): CaseDraft {
  return { ...draft.value,
    buyer_objections: draft.value.buyer_objections.map((s) => s.trim()).filter(Boolean),
    goal: { ...draft.value.goal,
      hard_limits: draft.value.goal.hard_limits.map((s) => s.trim()).filter(Boolean),
      amount_minor: draft.value.goal.outcome_type === 'payment_commitment' ? toMinor(amountMajor.value, draft.value.goal.currency) : null,
      currency: draft.value.goal.outcome_type === 'payment_commitment' ? draft.value.goal.currency : null,
      due_date: draft.value.goal.outcome_type === 'payment_commitment' ? draft.value.goal.due_date : null } }
}
function detail(err: unknown): string {
  if (err instanceof DOMException) {
    if (['NotAllowedError', 'SecurityError'].includes(err.name)) return '麦克风权限被拒绝，请在浏览器地址栏允许麦克风后重试。'
    if (err.name === 'NotFoundError') return '未找到麦克风，请连接麦克风后重试。'
    if (err.name === 'NotReadableError') return '麦克风无法使用，请检查是否被其他程序占用。'
  }
  return err instanceof HttpError ? err.detail : err instanceof Error ? err.message : '请求失败，请重试'
}
function key(): string { return crypto.randomUUID() }
function canWrite(ownerId: number): boolean { return me.value?.id === ownerId || ['manager', 'admin'].includes(me.value?.role || '') }
function caseName(id: string): string { return cases.value.find((row) => row.id === id)?.title || '谈判任务' }
function editingSnapshot() {
  return JSON.stringify({ caseBriefInput: caseBriefInput.value, draft: draft.value, amountMajor: amountMajor.value })
}
function hasUnsavedChanges() {
  return editing.value && editingSnapshot() !== editingBaseline || setupRef.value?.hasUnsavedChanges() === true
}
function setupBusy() { return setupRef.value?.isBusy() === true }
function cancelDiscard() {
  const resolve = pendingRouteResolve
  pendingRouteResolve = null
  pendingDiscardAction = null
  discardPrompt.value = ''
  resolve?.(false)
}
function requestDiscard(message: string, action: (() => void | Promise<void>) | null, resolve?: (allow: boolean) => void) {
  cancelDiscard()
  discardPrompt.value = message
  pendingDiscardAction = action
  pendingRouteResolve = resolve || null
  void nextTick(() => discardButton.value?.focus())
}
function discardAndContinue() {
  const action = pendingDiscardAction
  const resolve = pendingRouteResolve
  pendingDiscardAction = null
  pendingRouteResolve = null
  discardPrompt.value = ''
  if (resolve) { resolve(true); return }
  discardApproved = true
  try {
    if (action) void Promise.resolve(action()).catch(err => { error.value = detail(err) })
  } catch (err) { error.value = detail(err) }
  finally { discardApproved = false }
}
function confirmDiscard(action: () => void | Promise<void>, target: string) {
  if (setupBusy()) { notice.value = '正在保存本次设置，请等待完成。'; return false }
  if (discardApproved || !hasUnsavedChanges()) return true
  requestDiscard(`本次会议设置尚未保存。${target}会丢失填写的内容和资料。`, action)
  return false
}
function warnBeforeUnload(event: BeforeUnloadEvent) {
  if (!hasUnsavedChanges() && !setupBusy()) return
  event.preventDefault()
  event.returnValue = ''
}
onBeforeRouteLeave(() => {
  if (setupBusy()) { notice.value = '正在保存本次设置，请等待完成。'; return false }
  if (!hasUnsavedChanges()) return true
  return new Promise<boolean>(resolve => requestDiscard('本次会议设置尚未保存。离开会议陪练会丢失填写的内容和资料。', null, resolve))
})
function toggleProfiles() {
  if (setupBusy()) { notice.value = '正在保存本次设置，请等待完成。'; return }
  profilesOpen.value = !profilesOpen.value
}
function quoteNumber(quote: Quote): number { return (chosenSession.value?.segments || []).findIndex((part) => part.id === quote.segment_id) + 1 }
function showQuote(quote: Quote) {
  const target = document.getElementById(`omega-segment-${quote.segment_id}`)
  if (!target) return
  focusedQuoteId.value = quote.segment_id
  target.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' })
  target.focus({ preventScroll: true })
  if (quoteTimer) clearTimeout(quoteTimer)
  quoteTimer = setTimeout(() => { focusedQuoteId.value = '' }, 3000)
}
function minorDigits(currency: string | null): number {
  try {
    return new Intl.NumberFormat('en', { style: 'currency', currency: currency || 'USD' })
      .resolvedOptions().maximumFractionDigits ?? 2
  } catch { return 2 }
}
function toMinor(amount: string, currency: string | null): number {
  try { new Intl.NumberFormat('en', { style: 'currency', currency: currency || 'USD' }) }
  catch { throw new Error('币种代码无效') }
  const digits = minorDigits(currency)
  const match = /^(\d+)(?:\.(\d+))?$/.exec(amount.trim())
  if (!match || (match[2] || '').length > digits) throw new Error(`金额格式无效：${currency || '币种'}最多 ${digits} 位小数`)
  const value = Number(match[1]) * 10 ** digits + Number((match[2] || '').padEnd(digits, '0'))
  if (!Number.isSafeInteger(value)) throw new Error('金额过大')
  return value
}

async function loadLists() {
  const [caseRows, sessionRows, assignmentRows] = await Promise.all([
    apiGet<CaseRow[]>('/api/omega/cases'), apiGet<SessionRow[]>('/api/omega/sessions'),
    apiGet<Assignment[]>('/api/omega/assignments'),
  ])
  cases.value = caseRows.filter(row => row.kind !== 'template')
  sessions.value = sessionRows
  assignments.value = assignmentRows
  sessionsHasMore.value = sessionRows.length === 100
  assignmentsHasMore.value = assignmentRows.length === 100
  if (chosenCase.value) chosenCase.value = caseRows.find((row) => row.id === chosenCase.value?.id) || null
  if (chosenAssignment.value) chosenAssignment.value = assignmentRows.find((row) => row.id === chosenAssignment.value?.id) || null
}
async function loadMoreSessions() {
  if (loadingMoreSessions.value || !sessionsHasMore.value || !sessions.value.length) return
  const cursor = sessions.value[sessions.value.length - 1].id
  loadingMoreSessions.value = true
  try {
    const rows = await apiGet<SessionRow[]>(`/api/omega/sessions?before=${encodeURIComponent(cursor)}`)
    if (sessions.value[sessions.value.length - 1]?.id !== cursor) return
    sessions.value.push(...rows)
    sessionsHasMore.value = rows.length === 100
  } catch (err) { error.value = detail(err) }
  finally { loadingMoreSessions.value = false }
}
async function loadMoreAssignments() {
  if (loadingMoreAssignments.value || !assignmentsHasMore.value || !assignments.value.length) return
  const cursor = assignments.value[assignments.value.length - 1].id
  loadingMoreAssignments.value = true
  try {
    const rows = await apiGet<Assignment[]>(`/api/omega/assignments?before=${encodeURIComponent(cursor)}`)
    if (assignments.value[assignments.value.length - 1]?.id !== cursor) return
    assignments.value.push(...rows)
    assignmentsHasMore.value = rows.length === 100
  } catch (err) { error.value = detail(err) }
  finally { loadingMoreAssignments.value = false }
}
async function openSession(id: string, discardConfirmed = false) {
  if (!discardConfirmed && !confirmDiscard(() => openSession(id), '切换演练记录')) return
  const discardedSetup = setupRef.value?.hasUnsavedChanges() === true
  profilesOpen.value = false
  const token = ++openToken
  if (pollTimer) clearTimeout(pollTimer)
  activeJob.value = null
  report.value = null
  chosenAssignment.value = null
  const game = await apiGet<SessionRow>(`/api/omega/sessions/${id}`)
  if (token !== openToken) return
  if (discardedSetup) setupKey.value++
  mobileNavOpen.value = false
  editing.value = false
  chosenSession.value = game
  setupOpen.value = false
  sidebarTab.value = 'sessions'
  await nextTick()
  if (token !== openToken) return
  window.scrollTo(0, 0)
  assignUserId.value = ['manager', 'admin'].includes(me.value?.role || '')
    && members.value.some((row) => row.id === game.owner_id && (!game.team_key || row.team_key === game.team_key))
    ? game.owner_id : null
  if (game.latest_report_id) {
    const loadedReport = await apiGet<Report>(`/api/omega/reports/${game.latest_report_id}`)
    if (token !== openToken) return
    report.value = loadedReport
  }
  const recoverableJobId = game.pending_job_id || game.failed_turn_job_id
  if (recoverableJobId) {
    const job = await apiGet<Job>(`/api/omega/jobs/${recoverableJobId}`)
    if (token !== openToken) return
    activeJob.value = job
    if (['queued', 'running'].includes(job.status)) schedulePoll()
  }
}
function prepareTemplateVoice() {
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) return
  try {
    voiceOutput ||= new AudioContext()
    voiceInput ||= new AudioContext({ sampleRate: 16000 })
    primedVoice = true
    // Unlock both contexts during the user's tap, before creating the session.
    void voiceOutput.resume().catch(() => {})
    void voiceInput.resume().catch(() => {})
  } catch { cancelTemplateVoice() }
}
function cancelTemplateVoice() {
  primedVoice = false
  primedSessionId = ''
  if (!voiceConnected.value && !voiceConnecting.value) stopVoice(true)
}
async function startedTemplate(result: TemplateStart, autoVoice = false) {
  if (autoVoice && primedVoice) primedSessionId = result.session_id || ''
  await run(async () => {
    await loadLists()
    setupOpen.value = false
    setupKey.value++
    cancelDiscard()
    if (result.session_id) await openSession(result.session_id, true)
    else {
      const row = cases.value.find(item => item.id === result.case_id)
      if (!row) throw new Error('场景已建立，请刷新任务列表后继续导入会议')
      showCase(row)
      notice.value = '场景已备好，请导入要复盘的真实会议。'
    }
  })
  if (autoVoice && result.session_id && chosenSession.value?.id === result.session_id) await startVoice()
  else cancelTemplateVoice()
}
async function savedTemplate(caseId: string) {
  await run(async () => {
    await loadLists()
    const row = cases.value.find(item => item.id === caseId)
      || await apiGet<CaseRow>(`/api/omega/cases/${caseId}`)
    cancelDiscard()
    showCase(row)
    setupKey.value++
    notice.value = '本次设置已保存到任务列表。确认目标后可继续开练。'
  })
}
async function refreshSession() {
  const id = chosenSession.value?.id
  if (id) {
    const game = await apiGet<SessionRow>(`/api/omega/sessions/${id}`)
    if (chosenSession.value?.id === id) chosenSession.value = game
  }
}
async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action() } catch (err) { error.value = detail(err) } finally { busy.value = false }
}
async function saveCase() {
  if (materialBusy.value) return
  await run(async () => {
    const body = caseBody()
    const saved = chosenCase.value && editing.value
      ? await apiPatch<CaseRow>(`/api/omega/cases/${chosenCase.value.id}`, { ...body, revision: chosenCase.value.revision })
      : await apiPost<CaseRow>('/api/omega/cases', body)
    await loadLists()
    chosenCase.value = saved
    editing.value = false
    cancelDiscard()
    notice.value = '草稿已保存，请核对后确认目标版本。'
  })
}
async function saveAndStart() {
  if (missingDraftFields.value.length || materialBusy.value) return
  await run(async () => {
    const saved = await apiPost<CaseRow>('/api/omega/cases', caseBody())
    chosenCase.value = saved
    editing.value = false
    cancelDiscard()
    await loadLists()
    await apiPost(`/api/omega/cases/${saved.id}/confirm`)
    const game = await apiPost<SessionRow>('/api/omega/sessions', { case_id: saved.id })
    await loadLists()
    await openSession(game.id, true)
  })
}
async function startQuickPractice(scenario: typeof quickScenarios[number]) {
  if (!confirmDiscard(() => startQuickPractice(scenario), '开始新练习')) return
  await run(async () => {
    const template = quickDraft(scenario)
    let saved = cases.value.find((row) => row.owner_id === me.value?.id && row.title === template.title
      && row.draft.public_brief === template.public_brief && row.draft.goal.success_condition === template.goal.success_condition
      && row.draft_confirmed)
    if (!saved) {
      saved = await apiPost<CaseRow>('/api/omega/cases', template)
      await apiPost(`/api/omega/cases/${saved.id}/confirm`)
    }
    const game = await apiPost<SessionRow>('/api/omega/sessions', { case_id: saved.id })
    await loadLists()
    editing.value = false
    await openSession(game.id, true)
  })
}
async function analyzeCaseDraft() {
  if (analysisBusy.value || !caseBriefInput.value.trim()) return
  const description = caseBriefInput.value.trim()
  analysisBusy.value = true
  analysisReady.value = false
  reviewOpen.value = false
  error.value = ''
  notice.value = ''
  try {
    const result = await apiPost<{ draft: ExtractedDraft }>('/api/omega/case-draft/analyze',
      { text: description })
    if (caseBriefInput.value.trim() !== description) return
    const found = result.draft
    const goal = found.goal || {}
    const completePayment = goal.outcome_type === 'payment_commitment' && goal.amount_major && goal.currency && goal.due_date
    const practiceGoal = goal.success_condition || '澄清客户顾虑，并约定可核实的下一步。'
    draft.value = {
      ...blankDraft(),
      meeting_topic: draft.value.meeting_topic, meeting_materials: draft.value.meeting_materials,
      title: found.title || '客户谈判练习', public_brief: found.public_brief || '双方正在商谈交易，具体背景待澄清。',
      seller_private: found.seller_private || '', counterparty_brief: found.counterparty_brief || '客户顾虑需要在对话中澄清。',
      buyer_name: found.buyer_name || '', buyer_role: found.buyer_role || '',
      buyer_company: found.buyer_company || '', buyer_emotion: found.buyer_emotion || '',
      buyer_objections: found.buyer_objections || [],
      goal: {
        ...blankDraft().goal,
        outcome_type: completePayment ? 'payment_commitment' : goal.outcome_type === 'payment_commitment' ? 'other' : goal.outcome_type || 'other',
        success_condition: practiceGoal, ideal: goal.ideal || practiceGoal,
        minimum: goal.minimum || '明确客户顾虑和下一步。', hard_limits: goal.hard_limits?.length ? goal.hard_limits : [safeTrainingLimit],
        amount_minor: null, currency: completePayment ? goal.currency || null : null, due_date: completePayment ? goal.due_date || null : null,
      },
    }
    amountMajor.value = completePayment ? goal.amount_major || '' : ''
    analysisReady.value = true
    reviewOpen.value = false
    if (goal.outcome_type === 'payment_commitment' && !completePayment) notice.value = '金额或日期未明确，本场先练推进下一步；需要回款判定可在更多设定中补齐。'
  } catch (err) { error.value = detail(err) } finally { analysisBusy.value = false }
}
async function confirmCase() {
  if (!chosenCase.value) return
  await run(async () => {
    await apiPost(`/api/omega/cases/${chosenCase.value!.id}/confirm`)
    await loadLists()
    notice.value = '目标版本已确认，可以开始演练。'
  })
}
async function startSession() {
  if (!chosenCase.value) return
  await run(async () => {
    const row = await apiPost<SessionRow>('/api/omega/sessions', { case_id: chosenCase.value!.id })
    await loadLists()
    await openSession(row.id)
  })
}
async function repeatPractice() {
  if (!chosenSession.value) return
  const { case_id, assignment_id } = chosenSession.value
  await run(async () => {
    let targetId = assignment_id
    if (!targetId && report.value && coachingPoint.value && me.value) {
      const assignment = await apiPost<Assignment>('/api/omega/assignments', {
        case_id, assignee_id: me.value.id, source_report_id: report.value.id,
        target_dimension: coachingPoint.value.key, pass_percent: focusPassPercent.value,
        instructions: reportNextPractice.value || `重点练习${dimensionNames[coachingPoint.value.key] || coachingPoint.value.key}`,
      })
      targetId = assignment.id
    }
    const game = await apiPost<SessionRow>('/api/omega/sessions', { case_id, ...(targetId ? { assignment_id: targetId } : {}) })
    await loadLists()
    await openSession(game.id)
  })
}
async function assignFromReport() {
  if (!chosenSession.value || !report.value || !coachingPoint.value || !assignUserId.value || matchingAssignment.value) return
  await run(async () => {
    await apiPost('/api/omega/assignments', {
      case_id: chosenSession.value!.case_id, assignee_id: assignUserId.value,
      source_report_id: report.value!.id, target_dimension: coachingPoint.value!.key,
      pass_percent: focusPassPercent.value,
      instructions: reportNextPractice.value || `重点练习${dimensionNames[coachingPoint.value!.key] || coachingPoint.value!.key}`,
    })
    await loadLists()
    notice.value = '练习已指派，销售可在待练列表开始。'
  })
}
async function startAssignment(row: Assignment) {
  await run(async () => {
    const game = await apiPost<SessionRow>('/api/omega/sessions',
      { case_id: row.case_id, assignment_id: row.id })
    await loadLists()
    await openSession(game.id)
  })
}
async function createAssignment(sourceReportId: string | null = null) {
  const caseId = chosenSession.value?.case_id || chosenCase.value?.id
  if (!caseId || !assignUserId.value) return
  await run(async () => {
    await apiPost('/api/omega/assignments', {
      case_id: caseId, assignee_id: assignUserId.value,
      source_report_id: sourceReportId, target_dimension: assignDimension.value,
      pass_percent: assignPassPercent.value, instructions: assignInstructions.value,
      due_at: assignDueDate.value ? new Date(`${assignDueDate.value}T23:59:59`).toISOString() : null,
    })
    await loadLists()
    assignInstructions.value = ''
    notice.value = '练习已指派，销售可在待练列表开始。'
  })
}
function showAssignment(row: Assignment) {
  if (!confirmDiscard(() => showAssignment(row), '切换指派练习')) return
  if (setupRef.value?.hasUnsavedChanges()) setupKey.value++
  profilesOpen.value = false
  setupOpen.value = false
  sidebarTab.value = 'assignments'
  mobileNavOpen.value = false
  chosenAssignment.value = row
  chosenCase.value = null
  chosenSession.value = null
  report.value = null
  editing.value = false
}
async function previewMeeting() {
  if (!meetingId.value.trim()) return
  await run(async () => {
    const response = await apiGet<{ meeting: Record<string, unknown> }>(
      `/api/meeting-center/vemory/detail?meeting_id=${encodeURIComponent(meetingId.value.trim())}`)
    const meeting = response.meeting
    const raw = meeting.transcript_segments || meeting.transcript
    const parts = Array.isArray(raw) ? raw : raw && typeof raw === 'object'
      ? (raw as { utterances?: unknown; segments?: unknown }).utterances || (raw as { segments?: unknown }).segments : null
    if (!Array.isArray(parts) || !parts.length) throw new Error('会议没有可分说话人的逐字稿')
    meetingPreview.value = parts.map((item) => {
      const row = item as Record<string, unknown>
      return { speaker: String(row.speaker || row.speaker_name || ''), text: String(row.text || row.content || '') }
    })
    if (meetingPreview.value.some((part) => !part.speaker || !part.text)) throw new Error('逐字稿包含无法确认的说话人或空白内容')
    meetingSpeakers.value = [...new Set(meetingPreview.value.map((part) => part.speaker).filter(Boolean))]
    speakerMap.value = {}
    participantMap.value = {}
  })
}
async function importMeeting() {
  if (!chosenCase.value) return
  await run(async () => {
    const game = await apiPost<SessionRow>('/api/omega/real-imports', {
      case_id: chosenCase.value!.id, meeting_id: meetingId.value.trim(), speaker_map: speakerMap.value,
      ...(chosenCase.value!.draft.participants?.length ? { participant_map: Object.fromEntries(meetingSpeakers.value.map(name => [name, speakerMap.value[name] === 'sales' ? 'sales' : participantMap.value[name]])) } : {}),
    })
    await loadLists()
    await openSession(game.id)
    notice.value = game.goal_timing === 'pre' ? '会议已导入；目标在会前确认。' : '会议已导入；目标未能证明在会前确认，成果达成度将标为未验证。'
  })
}
async function sendTurn() {
  if (!chosenSession.value || chosenSession.value.status !== 'active' || chosenSession.value.voice_tail_unrecoverable
      || !textReady.value || voiceConnecting.value || voiceConnected.value || !textInput.value.trim()
      || activeJob.value?.kind === 'turn' && activeJob.value.status === 'failed') return
  const sessionId = chosenSession.value.id
  await run(async () => {
    const job = await apiPost<Job>(`/api/omega/sessions/${sessionId}/turns`,
      { request_key: key(), text: textInput.value.trim(),
        source: voiceOriginal.value ? 'voice' : 'text', asr_original: voiceOriginal.value })
    if (chosenSession.value?.id !== sessionId) return
    textInput.value = ''
    voiceOriginal.value = ''
    activeJob.value = job
    await refreshSession()
    schedulePoll()
  })
}
async function retryTurn() {
  if (!chosenSession.value || chosenSession.value.status !== 'active' || chosenSession.value.voice_tail_unrecoverable
      || activeJob.value?.kind !== 'turn' || activeJob.value.status !== 'failed') return
  const sessionId = chosenSession.value.id
  const jobId = activeJob.value.id
  await run(async () => {
    const job = await apiPost<Job>(`/api/omega/jobs/${jobId}/retry`)
    if (chosenSession.value?.id !== sessionId || activeJob.value?.id !== jobId) return
    activeJob.value = job
    schedulePoll()
  })
}
async function finishSession() {
  if (!chosenSession.value) return
  const sessionId = chosenSession.value.id
  if (rememberedVoiceSession() === sessionId) rememberVoiceSession(null)
  stopCapture(true)
  window.speechSynthesis?.cancel()
  await run(async () => {
    if (voiceSocket && voiceConnected.value) {
      await hangupVoice()
      const deadline = performance.now() + 22000
      while (voiceClosing.value && performance.now() < deadline) await new Promise(resolve => setTimeout(resolve, 100))
      if (voiceClosing.value) throw new Error('语音尾部还在保存，请稍后再结束复盘。')
      await apiPost(`/api/omega/sessions/${encodeURIComponent(sessionId)}/realtime/stop`)
    }
    stopVoice(true)
    const ended = await apiPost<SessionRow>(`/api/omega/sessions/${sessionId}/finish`, { request_key: key() })
    if (chosenSession.value?.id !== sessionId) return
    chosenSession.value = ended
    activeJob.value = null
    await loadLists()
    if (ended.latest_report_id) {
      report.value = await apiGet<Report>(`/api/omega/reports/${ended.latest_report_id}`)
      notice.value = reportSavedNotice(report.value)
    } else if (!ended.report_blocked && (ended.pending_job_id || textReady.value && ended.segments?.length)) {
      activeJob.value = ended.pending_job_id
        ? await apiGet<Job>(`/api/omega/jobs/${ended.pending_job_id}`)
        : await apiPost<Job>(`/api/omega/sessions/${sessionId}/reports`, { request_key: key() })
      schedulePoll()
      notice.value = ended.report_partial ? '已保存可确认的对话，正在打开部分复盘；本场不能评分或达标。' : '对话已保存，正在生成复盘。'
    } else notice.value = ended.report_blocked ? ended.report_blocked_message || '本场对话不完整，无法评分；请新开一场。'
      : ended.segments?.length ? '对话已保存，可稍后生成复盘。' : '演练已结束，本场没有可复盘的对话。'
  })
}
async function makeReport() {
  if (!chosenSession.value || chosenSession.value.report_blocked || (!textReady.value && !chosenSession.value.report_partial)) return
  await run(async () => {
    activeJob.value = await apiPost<Job>(`/api/omega/sessions/${chosenSession.value!.id}/reports`, { request_key: key() })
    schedulePoll()
  })
}
async function pollJob() {
  if (!activeJob.value) return
  const jobId = activeJob.value.id
  const sessionId = chosenSession.value?.id
  if (pollFailureJobId !== jobId) { pollFailureJobId = jobId; pollFailures = 0 }
  try {
    const job = await apiGet<Job>(`/api/omega/jobs/${jobId}`)
    if (activeJob.value?.id !== jobId || chosenSession.value?.id !== sessionId) return
    if (error.value === pollError) error.value = ''
    pollError = ''
    pollFailures = 0
    activeJob.value = job
    if (job.status === 'succeeded') {
      if (job.result_id) {
        const result = await apiGet<Report>(`/api/omega/reports/${job.result_id}`)
        if (chosenSession.value?.id !== sessionId) return
        report.value = result
        notice.value = reportSavedNotice(result)
      }
      await refreshSession()
      if (job.result_id) await loadLists()
    } else if (job.status === 'failed' || job.status === 'cancelled') {
      error.value = job.error || '任务已取消，请重试'
    } else schedulePoll()
  } catch (err) {
    if (activeJob.value?.id !== jobId || chosenSession.value?.id !== sessionId) return
    if (err instanceof HttpError && err.status === 401) {
      router.replace({ path: '/login', query: { next: '/omega' } })
      return
    }
    pollError = detail(err)
    error.value = pollError
    pollFailures++
    schedulePoll(Math.min(30000, 1200 * 2 ** Math.min(pollFailures, 5)))
  }
}
function schedulePoll(delay = 1200) {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = setTimeout(pollJob, delay)
}
async function reviewReport() {
  if (!report.value) return
  const reportId = report.value.id
  const comment = reviewText.value
  const practice = nextPractice.value
  const verdict = report.value.content.evidence_status === 'incomplete' ? '' : outcomeVerdictInput.value
  await run(async () => {
    await apiPost(`/api/omega/reports/${reportId}/reviews`, { comment, next_practice: practice,
      ...(verdict ? { outcome_verdict: verdict } : {}) })
    const refreshed = await apiGet<Report>(`/api/omega/reports/${reportId}`)
    if (report.value?.id === reportId) {
      report.value = refreshed
      reviewText.value = ''
      nextPractice.value = ''
      outcomeVerdictInput.value = ''
    }
    await loadLists()
  })
}
function editCase(row: CaseRow) {
  if (!confirmDiscard(() => editCase(row), '编辑其他任务')) return
  if (setupRef.value?.hasUnsavedChanges()) setupKey.value++
  profilesOpen.value = false
  setupOpen.value = false
  sidebarTab.value = 'cases'
  openToken++
  chosenCase.value = row
  draft.value = structuredClone(toRaw(row.draft))
  draft.value.score_weights ||= { ...defaultWeights }
  draft.value.buyer_objections ||= []
  amountMajor.value = row.draft.goal.amount_minor === null ? ''
    : (row.draft.goal.amount_minor / 10 ** minorDigits(row.draft.goal.currency)).toFixed(minorDigits(row.draft.goal.currency))
  editing.value = true
  editingBaseline = editingSnapshot()
  chosenSession.value = null
  chosenAssignment.value = null
  report.value = null
}
function showCase(row: CaseRow) {
  if (!confirmDiscard(() => showCase(row), '切换任务')) return
  if (setupRef.value?.hasUnsavedChanges()) setupKey.value++
  profilesOpen.value = false
  setupOpen.value = false
  sidebarTab.value = 'cases'
  mobileNavOpen.value = false
  openToken++
  if (pollTimer) clearTimeout(pollTimer)
  chosenCase.value = row
  assignUserId.value = null
  chosenSession.value = null
  chosenAssignment.value = null
  activeJob.value = null
  report.value = null
  editing.value = false
}
function newCase(resetSetup = true) {
  if (callOpen.value || !confirmDiscard(() => { newCase(resetSetup) }, '开始新练习')) return false
  cancelTemplateVoice()
  if (resetSetup) setupKey.value++
  profilesOpen.value = false
  setupOpen.value = true
  sidebarTab.value = 'cases'
  mobileNavOpen.value = false
  openToken++
  if (pollTimer) clearTimeout(pollTimer)
  chosenCase.value = null
  chosenSession.value = null
  chosenAssignment.value = null
  activeJob.value = null
  report.value = null
  editing.value = true
  draft.value = blankDraft()
  amountMajor.value = ''
  caseBriefInput.value = ''
  analysisReady.value = false
  reviewOpen.value = false
  editingBaseline = editingSnapshot()
  return true
}
function customCase() {
  if (!confirmDiscard(customCase, '创建自定义练习')) return
  if (newCase()) setupOpen.value = false
}
function cancelEditing() { if (confirmDiscard(cancelEditing, '取消编辑')) editing.value = false }
function stopCapture(discard = false) {
  if (discard) recordingToken++
  if (recordingTimeout) clearTimeout(recordingTimeout)
  if (recorder && recorder.state !== 'inactive') recorder.stop()
  stream?.getTracks().forEach((track) => track.stop())
  stream = undefined
  recorder = undefined
  if (discard && audioContext) {
    closeAudioContext(audioContext)
    audioContext = undefined
  }
  recording.value = false
}
function stopVoice(intentional = false) {
  if (!intentional && voiceConnected.value && !voiceClosing.value) {
    voiceInterrupted.value = true
    if (chosenSession.value?.id) rememberVoiceSession(chosenSession.value.id)
  }
  voiceToken++
  voiceSocket?.close()
  voiceSocket = undefined
  voiceWorklet?.disconnect()
  voiceWorklet = undefined
  voiceStream?.getTracks().forEach((track) => track.stop())
  voiceStream = undefined
  if (voiceInput) { closeAudioContext(voiceInput); voiceInput = undefined }
  stopVoicePlayback()
  if (voiceOutput) { closeAudioContext(voiceOutput); voiceOutput = undefined }
  voiceGain = undefined
  voiceConnecting.value = false
  voiceConnected.value = false
  voiceClosing.value = false
  voiceSpeaking.value = false
  voiceCaption.value = ''
  voicePhase.value = 'live'
  pendingControlKey = ''
  coachBusy.value = false
  if (coachTimer) clearTimeout(coachTimer)
  if (controlTimer) clearTimeout(controlTimer)
}
function failVoiceControl(message: string) {
  stopVoicePlayback()
  voicePhase.value = 'error'
  coachBusy.value = false
  pendingControlKey = ''
  if (coachTimer) clearTimeout(coachTimer)
  if (controlTimer) clearTimeout(controlTimer)
  if (message.includes('语音尾稿未完成')) voiceRecoveryBlocked.value = true
  coachError.value = voiceRecoveryBlocked.value
    ? '语音尾稿未完成，本场无法恢复。请结束通话，核对逐字稿后新开练。'
    : message
}
function controlVoice(action: 'pause' | 'resume') {
  const socket = voiceSocket
  if (voiceClosing.value || voiceRecoveryBlocked.value) return
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    failVoiceControl('语音连接不可用，麦克风保持暂停。请结束通话后重连。')
    return
  }
  voicePhase.value = action === 'pause' ? 'pausing' : 'resuming'
  voiceEpoch.value++
  stopVoicePlayback()
  coachError.value = ''
  pendingControlKey = key()
  if (controlTimer) clearTimeout(controlTimer)
  controlTimer = setTimeout(() => {
    if (voicePhase.value === 'pausing' || voicePhase.value === 'resuming') {
      failVoiceControl('状态确认超时，麦克风保持暂停。请重试恢复或结束通话。')
    }
  }, 55000)
  try { socket.send(JSON.stringify({ type: 'control', action, request_key: pendingControlKey, audio_epoch: voiceEpoch.value })) }
  catch (err) { failVoiceControl(`语音控制发送失败，麦克风保持暂停：${detail(err)}`) }
}
async function requestCoach() {
  const id = chosenSession.value?.id
  const token = voiceToken
  if (!id || voicePhase.value !== 'coaching' || coachBusy.value) return
  coachBusy.value = true
  coachError.value = ''
  try {
    const job = await apiPost<Job>(`/api/omega/sessions/${id}/coach-hints`, { request_key: key() })
    let checks = 0
    const check = async () => {
      if (token !== voiceToken || chosenSession.value?.id !== id || voicePhase.value !== 'coaching') return
      try {
        const current = await apiGet<Job>(`/api/omega/jobs/${job.id}`)
        if (token !== voiceToken || voicePhase.value !== 'coaching') return
        if (current.status === 'succeeded') {
          const response = await apiGet<Array<{ id: string; text: string }>>(`/api/omega/sessions/${id}/coach-hints`)
          if (token !== voiceToken || voicePhase.value !== 'coaching') return
          coachText.value = response.find(row => row.id === current.result_id)?.text || response[response.length - 1]?.text || '暂无建议，可以直接恢复演练。'
          coachBusy.value = false
        } else if (['failed', 'cancelled'].includes(current.status)) {
          coachError.value = current.error || '教练暂时无法回应，可以恢复演练。'
          coachBusy.value = false
        } else if (++checks < 120) coachTimer = setTimeout(() => void check(), 1000)
        else { coachBusy.value = false; coachError.value = '教练回应超时，可以重试或恢复演练。' }
      } catch (err) { coachBusy.value = false; coachError.value = detail(err) }
    }
    await check()
  } catch (err) { if (token === voiceToken) { coachBusy.value = false; coachError.value = detail(err) } }
}
async function resumeVoice() {
  if (voiceRecoveryBlocked.value || voiceClosing.value || !['coaching', 'error'].includes(voicePhase.value)) return
  if (coachTimer) clearTimeout(coachTimer)
  coachBusy.value = false
  try { await voiceOutput?.resume(); await voiceInput?.resume(); controlVoice('resume') }
  catch (err) { failVoiceControl(`语音恢复失败，麦克风保持暂停：${detail(err)}`) }
}
async function hangupVoice() {
  const socket = voiceSocket
  const sessionId = chosenSession.value?.id
  if (sessionId && rememberedVoiceSession() === sessionId) rememberVoiceSession(null)
  voiceInterrupted.value = false
  if (!socket || !sessionId) { stopVoice(); return }
  voiceClosing.value = true
  voiceWorklet?.disconnect()
  voiceWorklet = undefined
  voiceStream?.getTracks().forEach((track) => track.stop())
  voiceStream = undefined
  if (voiceInput) { closeAudioContext(voiceInput); voiceInput = undefined }
  stopVoicePlayback()
  if (voiceOutput) { closeAudioContext(voiceOutput); voiceOutput = undefined }
  voiceGain = undefined
  voiceConnected.value = false
  voiceSpeaking.value = false
  if (socket.readyState === WebSocket.OPEN) {
    socket.send('stop')
    setTimeout(async () => {
      if (voiceSocket !== socket) return
      try { await apiPost(`/api/omega/sessions/${encodeURIComponent(sessionId)}/realtime/stop`) }
      catch (err) { error.value = `挂断确认失败：${detail(err)}` }
      if (voiceSocket === socket) stopVoice()
    }, 20000)
    return
  }
  stopVoice()
}
function stopVoicePlayback() {
  for (const source of voiceSources) {
    try { source.stop() } catch { /* already stopped */ }
  }
  voiceSources.clear()
  voiceSpeaking.value = false
  nextVoicePlayback = voiceOutput?.currentTime || 0
}
function playVoiceAudio(bytes: ArrayBuffer) {
  const context = voiceOutput
  if (!context || bytes.byteLength % 2) return
  const view = new DataView(bytes)
  const buffer = context.createBuffer(1, bytes.byteLength / 2, 24000)
  const samples = buffer.getChannelData(0)
  for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i * 2, true) / 32768
  const source = context.createBufferSource()
  source.buffer = buffer
  source.connect(voiceGain || context.destination)
  source.onended = () => {
    voiceSources.delete(source)
    if (!voiceSources.size) voiceSpeaking.value = false
  }
  voiceSources.add(source)
  voiceSpeaking.value = true
  const at = Math.max(context.currentTime + 0.015, nextVoicePlayback)
  source.start(at)
  nextVoicePlayback = at + buffer.duration
}
function exitVoice() {
  if (voiceClosing.value) return
  if (voiceConnecting.value) stopVoice()
  else void hangupVoice()
}
async function startVoice() {
  if (!chosenSession.value || chosenSession.value.status !== 'active' || chosenSession.value.voice_tail_unrecoverable
      || !realtimeReady.value || !voiceAllowed.value || voiceConnecting.value || voiceConnected.value || voiceClosing.value) return
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
    error.value = '浏览器不支持实时语音，请使用文字或短句录音'
    return
  }
  stopCapture(true)
  primedVoice = false
  primedSessionId = ''
  const token = ++voiceToken
  const sessionId = chosenSession.value.id
  voiceConnecting.value = true
  voiceInterrupted.value = false
  voiceEndNotice.value = ''
  voicePhase.value = 'live'
  voiceRecoveryBlocked.value = false
  voiceEpoch.value = 0
  packetEpoch = 0
  coachText.value = ''
  coachError.value = ''
  currentSpeakerId.value = participants.value.find(row => row.is_primary)?.id || ''
  error.value = ''
  try {
    voiceOutput ||= new AudioContext()
    await voiceOutput.resume()
    voiceGain = voiceOutput.createGain()
    voiceGain.gain.value = voiceVolume.value
    const limiter = voiceOutput.createDynamicsCompressor()
    limiter.threshold.value = -8
    limiter.knee.value = 0
    limiter.ratio.value = 12
    voiceGain.connect(limiter).connect(voiceOutput.destination)
    const captured = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    if (token !== voiceToken || chosenSession.value?.id !== sessionId || chosenSession.value?.status !== 'active') {
      captured.getTracks().forEach((track) => track.stop())
      return
    }
    voiceStream = captured
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${location.host}/api/omega/sessions/${encodeURIComponent(sessionId)}/realtime`)
    voiceSocket = socket
    socket.binaryType = 'arraybuffer'
    socket.onmessage = async (event) => {
      if (voiceSocket !== socket || token !== voiceToken) return
      if (event.data instanceof ArrayBuffer) { if (voicePhase.value === 'live' && packetEpoch === voiceEpoch.value) playVoiceAudio(event.data); return }
      try {
        const message = JSON.parse(event.data) as { type: string; message?: string; speaker?: string; speaker_id?: string; text?: string; state?: string; audio_epoch?: number; request_key?: string }
        if (message.type === 'error') {
          error.value = message.message || '实时语音连接失败'
          if (!voiceClosing.value) {
            voiceInterrupted.value = true
            voiceClosing.value = true
            voiceWorklet?.disconnect()
            voiceWorklet = undefined
            voiceStream?.getTracks().forEach(track => track.stop())
            voiceStream = undefined
            if (voiceInput) { closeAudioContext(voiceInput); voiceInput = undefined }
            stopVoicePlayback()
            if (voiceOutput) { closeAudioContext(voiceOutput); voiceOutput = undefined }
            voiceGain = undefined
            voiceConnecting.value = false
            voiceConnected.value = false
          }
          voiceEndNotice.value = error.value
          return
        }
        if (message.type === 'ending_soon') {
          voiceEndNotice.value = message.message || '距离通话时长上限约 2 分钟，请尽快收尾并复盘'
          return
        }
        if (message.type === 'ending') {
          voiceEndNotice.value = message.message || '本次通话已达时长上限'
          if (!voiceClosing.value) void hangupVoice()
          return
        }
        if (message.type === 'closed') {
          if (!voiceClosing.value) voiceInterrupted.value = true
          stopVoice()
          void refreshSession().catch(() => {})
          return
        }
        if (message.type === 'audio') { packetEpoch = message.audio_epoch ?? 0; currentSpeakerId.value = message.speaker_id || currentSpeakerId.value; return }
        if (message.type === 'state') {
          const spontaneousError = message.state === 'error' && !message.request_key
          const currentControl = !!pendingControlKey && message.request_key === pendingControlKey
          const currentError = message.state === 'error' && currentControl
          if (typeof message.audio_epoch !== 'number' || (message.audio_epoch < voiceEpoch.value && !currentError) || (!spontaneousError && !currentControl)) return
          // An interrupt can advance the epoch before a matching failure ACK arrives.
          // Fail closed without rolling back the epoch or accepting stale success ACKs.
          voiceEpoch.value = Math.max(voiceEpoch.value, message.audio_epoch)
          packetEpoch = voiceEpoch.value
          if (message.state === 'coaching') {
            voicePhase.value = 'coaching'
            pendingControlKey = ''
            if (controlTimer) clearTimeout(controlTimer)
            void requestCoach()
          } else if (message.state === 'listening') {
            voicePhase.value = 'live'
            pendingControlKey = ''
            if (controlTimer) clearTimeout(controlTimer)
          } else if (message.state === 'error') {
            failVoiceControl(message.message || '暂停或恢复失败，麦克风保持暂停。可重试恢复或结束通话。')
          }
          return
        }
        if (message.type === 'interrupt') {
          if (typeof message.audio_epoch === 'number' && message.audio_epoch >= voiceEpoch.value) {
            voiceEpoch.value = message.audio_epoch
            packetEpoch = message.audio_epoch
          }
          stopVoicePlayback()
          return
        }
        if (message.type === 'caption') { if (voicePhase.value !== 'live') return; currentSpeakerId.value = message.speaker_id || currentSpeakerId.value; voiceCaption.value = `${message.speaker === 'sales' ? '你' : currentSpeakerName.value}：${message.text || ''}`; return }
        if (message.type === 'segment') { await refreshSession(); return }
        if (message.type !== 'ready') return
        voiceEpoch.value = message.audio_epoch ?? 0
        packetEpoch = voiceEpoch.value
        voicePhase.value = message.state === 'coaching' ? 'coaching' : 'live'
        if (['pausing', 'resuming', 'error'].includes(message.state || '')) {
          failVoiceControl(message.message || '上次暂停或恢复未完成，麦克风保持暂停。可重试恢复或结束通话。')
        }
        voiceInput ||= new AudioContext({ sampleRate: 16000 })
        await voiceInput.audioWorklet.addModule(new URL(`${import.meta.env.BASE_URL}omega-capture-worklet.js`, location.origin).toString())
        if (token !== voiceToken || voiceSocket !== socket) return
        const source = voiceInput.createMediaStreamSource(captured)
        const worklet = new AudioWorkletNode(voiceInput, 'omega-capture')
        const silent = voiceInput.createGain()
        silent.gain.value = 0
        source.connect(worklet).connect(silent).connect(voiceInput.destination)
        voiceWorklet = worklet
        worklet.port.onmessage = (packet: MessageEvent<ArrayBuffer>) => {
          if (socket.readyState !== WebSocket.OPEN || token !== voiceToken || voicePhase.value !== 'live') return
          if (socket.bufferedAmount > 256 * 1024) {
            error.value = '网络拥堵，实时语音已停止，请重试'
            stopVoice()
            return
          }
          socket.send(packet.data)
        }
        voiceConnecting.value = false
        voiceConnected.value = true
        rememberVoiceSession(sessionId)
        if (message.state === 'coaching') void requestCoach()
      } catch (err) { if (token === voiceToken) { error.value = detail(err); stopVoice() } }
    }
    socket.onerror = () => { if (token === voiceToken && !voiceClosing.value) error.value = '实时语音网络连接失败' }
    socket.onclose = () => {
      if (voiceSocket !== socket || token !== voiceToken) return
      if (!voiceClosing.value) voiceInterrupted.value = true
      stopVoice()
      void refreshSession().catch(() => {})
    }
  } catch (err) { if (token === voiceToken) { error.value = detail(err); stopVoice() } }
}
function closeAudioContext(context: AudioContext) {
  if (closingAudioContexts.has(context)) return
  closingAudioContexts.add(context)
  void context.close().catch(() => {})
}
function wavFromAudio(buffer: AudioBuffer): Blob {
  const samples = buffer.getChannelData(0)
  const bytes = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(bytes)
  const write = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i))
  }
  write(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); write(8, 'WAVE')
  write(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true)
  view.setUint16(22, 1, true); view.setUint32(24, buffer.sampleRate, true)
  view.setUint32(28, buffer.sampleRate * 2, true); view.setUint16(32, 2, true)
  view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i++) {
    const value = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true)
  }
  return new Blob([bytes], { type: 'audio/wav' })
}
async function transcribeBlob(blob: Blob, token: number, context: AudioContext) {
  asrBusy.value = true
  try {
    const input = await blob.arrayBuffer()
    const decoded = await context.decodeAudioData(input)
    const length = Math.ceil(decoded.duration * 16000)
    const offline = new OfflineAudioContext(1, length, 16000)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start()
    const rendered = await offline.startRendering()
    const response = await apiRequest('/api/omega/transcribe', {
      method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wavFromAudio(rendered),
    })
    const result = await response.json() as { text: string; needs_manual_review: boolean }
    if (token === recordingToken) {
      voiceOriginal.value = result.text
      textInput.value = result.text
      notice.value = result.needs_manual_review ? '转写需人工核对；请修改后再发送。' : '请核对转写，确认后发送。'
    }
  } catch (err) { if (token === recordingToken) error.value = detail(err) }
  finally {
    asrBusy.value = false
    closeAudioContext(context)
    if (audioContext === context) audioContext = undefined
  }
}
async function toggleRecording() {
  if (voiceConnected.value || voiceConnecting.value) return
  if (recording.value) { stopCapture(); return }
  error.value = ''
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    error.value = '浏览器不支持录音，请使用文字输入'
    return
  }
  const token = ++recordingToken
  try {
    const sessionId = chosenSession.value?.id
    const captured = await navigator.mediaDevices.getUserMedia({ audio: true })
    if (token !== recordingToken || chosenSession.value?.id !== sessionId || chosenSession.value?.status !== 'active') {
      captured.getTracks().forEach((track) => track.stop())
      return
    }
    stream = captured
    const context = new AudioContext()
    audioContext = context
    const chunks: BlobPart[] = []
    recorder = new MediaRecorder(captured)
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
    recorder.onstop = () => {
      if (token === recordingToken && chunks.length) void transcribeBlob(new Blob(chunks), token, context)
      else { closeAudioContext(context); if (audioContext === context) audioContext = undefined }
    }
    recorder.start()
    recording.value = true
    recordingTimeout = setTimeout(stopCapture, 29000)
  } catch (err) {
    if (token === recordingToken) { stopCapture(true); error.value = detail(err) }
  }
}
function speakLastReply() {
  const parts = chosenSession.value?.segments || []
  const last = [...parts].reverse().find((part) => part.speaker === 'counterparty')
  if (!last || !window.speechSynthesis) return
  window.speechSynthesis.cancel()
  const speech = new SpeechSynthesisUtterance(last.text)
  speech.lang = /[\u4e00-\u9fff]/.test(last.text) ? 'zh-CN' : 'en-US'
  window.speechSynthesis.speak(speech)
}
watch(() => chosenSession.value?.id, (id, previousId) => {
  if (previousId && previousId !== id && rememberedVoiceSession() === previousId) rememberVoiceSession(null)
  stopCapture(true)
  if (!(primedVoice && id && id === primedSessionId)) {
    primedVoice = false
    primedSessionId = ''
    stopVoice(true)
  }
  voiceInterrupted.value = chosenSession.value?.status === 'active' && rememberedVoiceSession() === chosenSession.value.id
  window.speechSynthesis?.cancel()
})
watch(callOpen, async (open) => {
  await nextTick()
  if (open && callOpen.value && !voiceDialog.value?.open) voiceDialog.value?.showModal()
  else if (!callOpen.value && voiceDialog.value?.open) voiceDialog.value.close()
})
watch(voiceVolume, (volume) => {
  if (voiceGain && voiceOutput) voiceGain.gain.setTargetAtTime(volume, voiceOutput.currentTime, 0.03)
})
watch(error, async (message) => {
  if (message) {
    await nextTick()
    document.querySelector('.omega > .omega-alert')?.scrollIntoView({ block: 'center' })
  }
})
watch(caseBriefInput, () => { analysisReady.value = false; reviewOpen.value = false })
watch(() => report.value?.id, () => { outcomeVerdictInput.value = '' })
onMounted(async () => {
  window.addEventListener('beforeunload', warnBeforeUnload)
  try {
    const status = await apiGet<{ ready: boolean; actor_id: number; role: string; realtime_configured: boolean; model_configured: boolean; worker_online: boolean; multi_voice_ready?: boolean }>('/api/omega/status')
    if (!status.ready) { error.value = '会议陪练暂不可用，请联系管理员检查语音与复盘服务。'; return }
    realtimeReady.value = status.realtime_configured
    textReady.value = status.model_configured && status.worker_online
    multiVoiceReady.value = status.multi_voice_ready === true
    me.value = { id: status.actor_id, role: status.role }
    if (['manager', 'admin'].includes(status.role)) members.value = await apiGet('/api/omega/team-members')
    await loadLists()
    const remembered = rememberedVoiceSession()
    if (remembered && sessions.value.some((row) => row.id === remembered && row.status === 'active')) await openSession(remembered)
    else {
      if (remembered) rememberVoiceSession(null)
      const nextAssignment = assignments.value.find((row) => row.assignee_id === me.value?.id && row.status !== 'passed')
      if (nextAssignment) showAssignment(nextAssignment)
      else newCase()
    }
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) router.replace({ path: '/login', query: { next: '/omega' } })
    else error.value = detail(err)
  } finally { loading.value = false }
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnBeforeUnload)
  cancelDiscard()
  openToken++
  if (pollTimer) clearTimeout(pollTimer)
  if (quoteTimer) clearTimeout(quoteTimer)
  stopCapture(true)
  stopVoice()
  primedVoice = false
  primedSessionId = ''
  window.speechSynthesis?.cancel()
})
</script>

<template>
  <AppNav />
  <main class="page omega" :class="{ 'is-setup': setupOpen && !profilesOpen }">
    <header class="page-head omega-head">
      <div><p class="omega-kicker">培训 · 会前演练 · 会后复盘</p><h1>会议陪练</h1><p class="sub">选一张场景卡，练到关键问题，带着下一步去见客户。</p></div>
      <div class="omega-head-meta"><button class="btn btn-sm btn-ghost" type="button" :disabled="callOpen || busy || setupBusy() || !me" @click="toggleProfiles">{{ profilesOpen ? '返回练习' : '查看档案' }}</button><span class="pill pill-muted">组内可见</span><span :class="['pill', realtimeReady ? 'pill-green' : 'pill-muted']">{{ realtimeReady ? '实时语音可用' : '实时语音未配置' }}</span></div>
    </header>
    <div v-if="discardPrompt" class="card omega-discard-confirm" role="region" aria-label="确认离开当前设置"><p>{{ discardPrompt }}</p><div><button ref="discardButton" class="btn btn-primary" type="button" @click="discardAndContinue">继续，丢弃未保存内容</button><button class="btn btn-ghost" type="button" @click="cancelDiscard">继续编辑</button></div></div>
    <p v-if="demoMode" class="omega-notice" role="status"><strong>交互原型 · 模拟数据</strong>　AI 分析、文字回复、语音识别和复盘内容均为预设；麦克风音频不会上传。刷新页面会重置演示数据。</p>
    <p v-if="error" class="omega-alert" role="alert">{{ error }}</p>
    <p v-if="notice" class="omega-notice" role="status">{{ notice }}</p>
    <p v-if="loading">正在读取演练…</p>
    <div v-else class="omega-grid">
      <aside class="card omega-side" :class="{ 'is-collapsed': !mobileNavOpen }" aria-label="演练导航">
        <div class="omega-side-head"><div><p class="omega-kicker">你的工作区</p><h2>{{ me?.role === 'admin' ? '团队训练' : '我的练习' }}</h2></div><div class="omega-side-actions"><button class="btn btn-sm btn-ghost omega-side-toggle" type="button" :aria-expanded="mobileNavOpen" aria-controls="omega-side-tabs omega-side-body" @click="mobileNavOpen = !mobileNavOpen">{{ mobileNavOpen ? '收起列表' : '展开列表' }}</button><button class="btn btn-sm btn-primary" type="button" :disabled="callOpen || busy" @click="newCase()">新练习</button></div></div>
        <div id="omega-side-tabs" class="omega-side-tabs" role="group" aria-label="列表类型">
          <button type="button" :class="{ active: sidebarTab === 'cases' }" :aria-pressed="sidebarTab === 'cases'" @click="sidebarTab = 'cases'">任务 <span>{{ cases.length }}</span></button>
          <button type="button" :class="{ active: sidebarTab === 'assignments' }" :aria-pressed="sidebarTab === 'assignments'" @click="sidebarTab = 'assignments'">指派 <span>{{ assignments.length }}</span></button>
          <button type="button" :class="{ active: sidebarTab === 'sessions' }" :aria-pressed="sidebarTab === 'sessions'" @click="sidebarTab = 'sessions'">记录 <span>{{ sessions.length }}</span></button>
        </div>
        <div id="omega-side-body" class="omega-side-body">
          <template v-if="sidebarTab === 'cases'">
            <p class="omega-list-title">谈判任务</p>
            <ul v-if="cases.length" class="omega-list"><li v-for="row in cases" :key="row.id">
              <button type="button" class="omega-link" :class="{ selected: chosenCase?.id === row.id }" :aria-current="chosenCase?.id === row.id ? 'true' : undefined" @click="showCase(row)"><strong>{{ row.title }}</strong><small>{{ me?.role === 'admin' && row.team_key ? `${row.team_key} · ` : '' }}{{ row.draft_confirmed ? `目标版本 ${row.current_version}` : '待确认目标' }}</small></button>
            </li></ul>
            <p v-else class="omega-side-empty">还没有任务。先新建一个谈判目标。</p>
          </template>
          <template v-else-if="sidebarTab === 'assignments'">
            <p class="omega-list-title">待练与复练</p>
            <ul v-if="assignments.length" class="omega-list"><li v-for="row in assignments" :key="row.id">
              <button type="button" class="omega-link" :class="{ selected: chosenAssignment?.id === row.id }" :aria-current="chosenAssignment?.id === row.id ? 'true' : undefined" @click="showAssignment(row)"><strong>{{ caseName(row.case_id) }}</strong><small>{{ me?.role === 'admin' && row.team_key ? `${row.team_key} · ` : '' }}{{ dimensionNames[row.target_dimension] }} · {{ row.status === 'passed' ? '已达标' : row.status === 'in_progress' ? '练习中' : '待练' }} · {{ row.attempts.length }} 次</small></button>
            </li></ul>
            <button v-if="assignmentsHasMore" class="omega-more" type="button" :disabled="loadingMoreAssignments" @click="loadMoreAssignments">{{ loadingMoreAssignments ? '加载中…' : '加载更早指派' }}</button>
            <p v-if="!assignments.length" class="omega-side-empty">暂无指派练习。</p>
          </template>
          <template v-else>
            <p class="omega-list-title">最近演练</p>
            <ul v-if="sessions.length" class="omega-list"><li v-for="(row, index) in (showAllSessions ? sessions : sessions.slice(0, 5))" :key="row.id">
              <button type="button" class="omega-link" :class="{ selected: chosenSession?.id === row.id }" :aria-current="chosenSession?.id === row.id ? 'true' : undefined" @click="openSession(row.id).catch((err) => error = detail(err))"><strong>{{ caseName(row.case_id) }}</strong><small>{{ me?.role === 'admin' && row.team_key ? `${row.team_key} · ` : '' }}记录 {{ index + 1 }} · {{ row.status === 'active' ? '进行中' : '已结束' }}<span v-if="row.created_at"> · {{ new Date(row.created_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }}</span></small></button>
            </li></ul>
            <button v-if="sessions.length > 5" class="omega-more" type="button" @click="showAllSessions = !showAllSessions">{{ showAllSessions ? '收起记录' : `查看${sessionsHasMore ? '最近' : '全部'} ${sessions.length} 条` }}</button>
            <button v-if="showAllSessions && sessionsHasMore" class="omega-more" type="button" :disabled="loadingMoreSessions" @click="loadMoreSessions">{{ loadingMoreSessions ? '加载中…' : '加载更早记录' }}</button>
            <p v-if="!sessions.length" class="omega-side-empty">还没有演练记录。</p>
          </template>
        </div>
      </aside>
      <section class="omega-main">
        <div v-if="!setupOpen && !profilesOpen" class="omega-return"><button class="btn btn-sm" type="button" :disabled="callOpen || busy" @click="editing ? cancelEditing() : newCase(false)">{{ editing ? '取消编辑' : '← 返回场景卡' }}</button></div>
        <OmegaSetup :key="setupKey" ref="setupRef" v-show="setupOpen && !profilesOpen" :manager="['manager', 'admin'].includes(me?.role || '')" :multi-voice-ready="multiVoiceReady" :realtime-ready="realtimeReady" @prepare-voice="prepareTemplateVoice" @cancel-voice-preparation="cancelTemplateVoice" @started="startedTemplate" @saved="savedTemplate" @custom="customCase" />
        <OmegaProfiles v-if="profilesOpen && me" :sales-id="me.id" @open-session="openSession($event).catch((err) => error = detail(err))" />
        <div v-else-if="!setupOpen && editing" class="card pad omega-intake">
          <template v-if="!chosenCase">
            <p class="omega-kicker">开始一场练习</p><h2>今天想练哪个客户卡点？</h2>
            <p class="sub">直接选一个常见场景，或用一句话描述手头客户。AI 会整理目标，你核对后就能开练。</p>
            <div class="omega-quick-grid" aria-label="常见谈判场景">
              <button v-for="scenario in quickScenarios" :key="scenario.title" class="omega-quick-card" type="button" :disabled="busy" @click="startQuickPractice(scenario)"><strong>{{ scenario.title }}</strong><span>模拟场景 · 直接开练</span></button>
            </div>
            <label for="omega-case-brief">带入手头客户</label>
            <textarea id="omega-case-brief" v-model="caseBriefInput" rows="4" minlength="1" maxlength="6000" placeholder="例如：客户觉得价格高，要求再降 10%。我想先弄清他跟谁比较，再争取本周确认订单。"></textarea>
            <label for="omega-custom-topic">本次会议命题（可选）</label><input id="omega-custom-topic" v-model.trim="draft.meeting_topic" maxlength="500" placeholder="例如：给代理销售主管做新品培训">
            <OmegaMeetingMaterials :model-value="draft.meeting_materials || []" @update:model-value="draft.meeting_materials = $event" @busy="materialBusy = $event" />
            <div class="omega-intake-actions"><span>输入和资料尚未保存。先整理练习，再保存草稿；AI 不会猜缺少的金额、日期。</span><button class="btn btn-primary" type="button" :disabled="analysisBusy || !caseBriefInput.trim()" @click="analyzeCaseDraft">{{ analysisBusy ? '分析中…' : analysisReady ? '重新分析' : '整理练习' }}</button></div>
          </template>
          <template v-else><h2>编辑任务草稿</h2><p class="sub">修改后需重新确认目标版本，既有演练仍使用原版本。</p></template>
          <section v-if="!chosenCase && analysisReady" class="omega-analysis" aria-label="AI 生成的任务草稿">
            <div class="omega-analysis-head"><div><p class="omega-kicker">开练前看一眼</p><h3>{{ draft.title }}</h3></div><span class="pill pill-amber">尚未保存</span></div>
            <dl class="omega-analysis-summary"><div><dt>对手会知道</dt><dd>{{ draft.public_brief }} {{ draft.counterparty_brief }} {{ draft.buyer_objections.join('；') }}</dd></div><div><dt>本场目标</dt><dd>{{ draft.goal.success_condition }}</dd></div><div><dt>不能承诺</dt><dd>{{ draft.goal.hard_limits.filter(Boolean).join('；') }}</dd></div><div v-if="draft.goal.outcome_type === 'payment_commitment'"><dt>金额与日期</dt><dd>{{ amountMajor }} {{ draft.goal.currency }} · {{ draft.goal.due_date }}</dd></div><div v-if="draft.seller_private"><dt>仅销售可见</dt><dd>{{ draft.seller_private }}</dd></div></dl>
            <p v-if="missingDraftFields.length" class="omega-missing" role="status">还需补充：{{ missingDraftFields.join('、') }}。请展开更多设定修改。</p>
            <p v-else class="omega-review-note">确认目标和底线无误后开始；这一步会保存并确认本场目标。</p>
            <div class="omega-actions"><button class="btn btn-primary" type="button" :disabled="busy || materialBusy || !!missingDraftFields.length" @click="saveAndStart">确认并开练</button><button class="btn" type="button" :disabled="busy || materialBusy || !!missingDraftFields.length" @click="saveCase">保存草稿，稍后再练</button><button class="btn btn-ghost" type="button" :aria-expanded="reviewOpen" @click="reviewOpen = !reviewOpen">{{ reviewOpen ? '收起更多设定' : '修改内容或更多设定' }}</button></div>
          </section>
          <div v-show="chosenCase || reviewOpen" class="omega-review-fields">
          <form class="form-grid omega-form" @submit.prevent="saveCase">
            <label class="span-2">任务名称<input v-model.trim="draft.title" required minlength="2" maxlength="200"></label>
            <label class="span-2">双方已知背景<textarea v-model.trim="draft.public_brief" required minlength="5" rows="3"></textarea></label>
            <label class="span-2">销售私有信息与底线<textarea v-model.trim="draft.seller_private" rows="3"></textarea></label>
            <label class="span-2">对手已知立场<textarea v-model.trim="draft.counterparty_brief" required minlength="5" rows="3"></textarea></label>
            <label>买方姓名<input v-model.trim="draft.buyer_name" maxlength="100"></label>
            <label>买方职位<input v-model.trim="draft.buyer_role" maxlength="100"></label>
            <label>买方公司<input v-model.trim="draft.buyer_company" maxlength="120"></label>
            <label>当前情绪/态度<input v-model.trim="draft.buyer_emotion" maxlength="120"></label>
            <label class="span-2">典型异议（每行一条）<textarea :value="draft.buyer_objections.join('\n')" rows="3" @input="draft.buyer_objections = ($event.target as HTMLTextAreaElement).value.split('\n')"></textarea></label>
            <label class="span-2">资料库客户 ID（可选，需具备授权）<input v-model.trim="draft.dealer_id"></label>
            <fieldset class="span-2 omega-scorecard"><legend>场景评分卡 · 九项权重合计 100</legend>
              <label v-for="(name, scoreKey) in dimensionNames" :key="scoreKey">{{ name }}<input v-model.number="draft.score_weights[scoreKey]" type="number" min="1" max="100" required></label>
            </fieldset>
            <label>目标类型<select v-model="draft.goal.outcome_type"><option value="payment_commitment">回款承诺</option><option value="new_order">新订单</option><option value="schedule">明确时间表</option><option value="other">其他</option></select></label>
            <label>成功判定条件<input v-model.trim="draft.goal.success_condition" required minlength="5"></label>
            <label>理想结果<input v-model.trim="draft.goal.ideal" required minlength="2"></label>
            <label>最低可接受结果<input v-model.trim="draft.goal.minimum" required minlength="2"></label>
            <label class="span-2">硬底线（每行一条）<textarea :value="draft.goal.hard_limits.join('\n')" rows="3" @input="draft.goal.hard_limits = ($event.target as HTMLTextAreaElement).value.split('\n')"></textarea></label>
            <template v-if="draft.goal.outcome_type === 'payment_commitment'">
              <label>目标金额（按所选币种填写）<input v-model.trim="amountMajor" type="text" inputmode="decimal" placeholder="例如 10000.00" required></label>
              <label>币种<input v-model.trim="draft.goal.currency" maxlength="3" pattern="[A-Z]{3}" required></label>
              <label>最迟日期<input v-model="draft.goal.due_date" type="date" required></label>
            </template>
            <div class="span-2 omega-actions"><button class="btn" type="submit" :disabled="busy || materialBusy || (!chosenCase && !!missingDraftFields.length)">保存草稿</button><button class="btn btn-ghost" type="button" @click="cancelEditing">取消</button></div>
          </form>
          </div>
        </div>
        <div v-else-if="!setupOpen && chosenAssignment" class="card pad">
          <h2>{{ caseName(chosenAssignment.case_id) }} · {{ dimensionNames[chosenAssignment.target_dimension] }}</h2>
          <p>达标条件：该项评分达到 {{ chosenAssignment.pass_percent }}% 且有销售原话证据{{ chosenAssignment.target_dimension === 'outcome' ? '，并由主管确认结果判断' : '' }}。</p>
          <p v-if="chosenAssignment.instructions">练习要求：{{ chosenAssignment.instructions }}</p>
          <p v-if="chosenAssignment.due_at">截止：{{ new Date(chosenAssignment.due_at).toLocaleString() }}</p>
          <p v-if="chosenAssignment.baseline">来源报告该项：{{ chosenAssignment.baseline.score }}/{{ chosenAssignment.baseline.maximum }}（{{ chosenAssignment.baseline.percent }}%）</p>
          <p v-else-if="chosenAssignment.source_report_id">来源报告该项证据不足，暂无基线分数。</p>
          <blockquote v-if="chosenAssignment.baseline_quote" class="omega-assignment-quote">上轮原话：“{{ chosenAssignment.baseline_quote }}”</blockquote>
          <p v-if="chosenAssignment.baseline_reason">上轮评语：{{ chosenAssignment.baseline_reason }}</p>
          <button v-if="chosenAssignment.source_session_id" class="btn btn-sm btn-ghost" type="button" @click="openSession(chosenAssignment.source_session_id).catch((err) => error = detail(err))">查看上轮完整复盘</button>
          <ul><li v-for="(attempt, index) in chosenAssignment.attempts" :key="attempt.session_id">
            <button type="button" class="omega-link" @click="openSession(attempt.session_id).catch((err) => error = detail(err))">第 {{ index + 1 }} 次：{{ attempt.result ? `${attempt.result.score}/${attempt.result.maximum}（${attempt.result.percent}%）` : '尚无可核验评分' }} · {{ attemptLabel(attempt, chosenAssignment.target_dimension) }}</button>
          </li></ul>
          <button v-if="me?.id === chosenAssignment.assignee_id" class="btn" type="button" :disabled="busy" @click="startAssignment(chosenAssignment)">开始本次练习</button>
        </div>
        <div v-else-if="!setupOpen && chosenSession" class="omega-workspace">
          <header class="card omega-session-summary">
            <div class="omega-session-heading"><div><p class="omega-kicker">{{ chosenSession.mode === 'real_review' ? (demoMode ? '模拟会议复盘样本' : '真实会议复盘') : '模拟对手演练' }} <span v-if="chosenSession.mode === 'real_review'">· {{ chosenSession.goal_timing === 'pre' ? '会前目标' : '目标时点未获会前确认' }}</span></p><h2>{{ caseName(chosenSession.case_id) }}</h2></div><span :class="['pill', chosenSession.status === 'active' ? 'pill-green' : 'pill-muted']">{{ chosenSession.status === 'active' ? '演练中' : '已结束' }}</span></div>
            <div v-if="chosenSession.case_snapshot" class="omega-goal"><span>本场目标 · 版本 {{ chosenSession.case_version }}</span><p>{{ chosenSession.case_snapshot.goal.success_condition }}</p></div>
          <p v-if="chosenSession.case_snapshot?.meeting_topic" class="sub">本次命题：{{ chosenSession.case_snapshot.meeting_topic }}</p>
          <p v-if="chosenSession.case_snapshot?.meeting_materials?.length" class="sub">本场资料：{{ chosenSession.case_snapshot.meeting_materials.map(item => item.name).join('、') }}</p>
          <div v-if="currentAssignment" class="omega-session-note"><strong>本轮只练：{{ dimensionNames[currentAssignment.target_dimension] || currentAssignment.target_dimension }}</strong><p>{{ currentAssignment.instructions || '先处理客户的主要卡点，再争取具体下一步。' }} · 达到 {{ currentAssignment.pass_percent }}% {{ currentAssignment.target_dimension === 'outcome' ? '且主管确认结果后达标' : '算达标' }}</p></div>
          </header>
          <section class="card omega-conversation" aria-labelledby="omega-conversation-title">
            <div class="omega-conversation-head"><div><p class="omega-kicker">对话实录</p><h3 id="omega-conversation-title">逐字稿</h3></div><span class="omega-turn-count">{{ (chosenSession.segments || []).length }} 条发言</span></div>
            <ol v-if="chosenSession.segments?.length" class="omega-transcript"><li v-for="part in chosenSession.segments" :id="`omega-segment-${part.id}`" :key="part.id" tabindex="-1" :class="[part.speaker === 'sales' ? 'is-sales' : 'is-counterparty', { 'is-quoted': focusedQuoteId === part.id }]"><span class="omega-speaker">{{ part.speaker === 'sales' ? (part.source_speaker || '销售') : participants.find(person => person.id === part.speaker_id)?.name || part.source_speaker || '对手／身份未细分' }}</span><p>{{ part.text }}</p><details v-if="part.asr_original && part.asr_original !== part.text" class="omega-asr-original"><summary>查看原始识别</summary><p>{{ part.asr_original }}</p></details></li></ol>
            <div v-else class="omega-transcript-empty"><strong>准备好了就开始对话</strong><p>你的发言和对手回复会按顺序显示在这里。</p></div>
            <p v-if="voiceCaption" class="omega-live-caption" role="status">{{ voiceCaption }}</p>
            <div v-if="activeJob && ['queued', 'running'].includes(activeJob.status)" class="omega-responding" role="status">{{ activeJob.kind === 'turn' ? '对手正在回应…' : '报告生成中…' }}</div>
            <div v-if="!voiceConnected && chosenSession.segments?.length" class="omega-transcript-tools"><button class="btn btn-sm btn-ghost" type="button" @click="speakLastReply">播放最新回复</button></div>
          </section>
          <form v-if="chosenSession.status === 'active' && chosenSession.owner_id === me?.id" class="card omega-practice-controls" @submit.prevent="sendTurn">
            <div v-if="chosenSession.voice_tail_unrecoverable" class="omega-tail-recovery" role="alert">
              <div><strong>本场语音尾稿未确认</strong><p v-if="chosenSession.segments?.length">逐字稿可能缺失，不能继续发言或评分。上方可核对已保存的原话。</p><p v-else>没有可复盘的原话，结束后不会生成报告。</p></div>
              <button class="btn btn-primary omega-voice-button" type="button" :disabled="busy || callOpen" @click="finishSession">{{ chosenSession.segments?.length ? '结束并查看部分复盘' : '结束本场' }}</button>
            </div>
            <template v-else>
            <div v-if="realtimeReady" class="omega-voice-panel" :class="{ 'is-live': voiceConnected }">
              <div><p class="omega-kicker">{{ participants.length > 1 ? '可打断的多角色演练' : '实时语音' }}</p><strong>{{ voiceConnected ? '正在对话' : voiceConnecting ? '正在连接' : '像通话一样练习' }}</strong><p role="status">{{ voiceClosing ? '正在结束实时对话…' : voiceConnecting ? '正在连接语音…' : voiceConnected ? '边说边听，可随时打断对手' : participants.length > 1 ? '每次一位对手发言，角色切换可能稍有等待' : '连接后开始说话，双方原话自动保存' }}</p></div>
              <div class="omega-voice-actions"><button v-if="!voiceConnected && !voiceConnecting && !voiceClosing" class="btn btn-primary omega-voice-button" type="button" :disabled="!voiceAllowed || busy || activeJob?.kind === 'turn' && activeJob?.status === 'failed' || !!activeJob && ['queued', 'running'].includes(activeJob.status)" @click="startVoice">{{ voiceInterrupted ? '继续实时对话' : '开始实时对话' }}</button>
                <button v-else class="btn omega-voice-button" type="button" :disabled="voiceClosing" @click="exitVoice">{{ voiceClosing ? '挂断中…' : voiceConnecting ? '取消连接' : '挂断实时对话' }}</button>
                <button v-if="!callOpen" class="btn btn-ghost omega-voice-button" type="button" :disabled="busy" @click="finishSession">{{ activeJob?.kind === 'turn' && activeJob.status !== 'succeeded' ? '结束本场（不评分）' : '结束并复盘' }}</button></div>
            </div>
            <p v-if="voiceEndNotice && !callOpen" class="omega-alert" role="status">{{ voiceEndNotice }} 已确认的原话仍可查看。</p>
            <div v-if="activeJob?.kind === 'turn' && activeJob.status === 'failed'" class="omega-alert" role="alert">销售发言已保存，对手回复失败。<button class="btn btn-sm" type="button" :disabled="busy" @click="retryTurn">重试对手回复</button></div>
            <p v-if="voiceInterrupted" class="omega-alert" role="alert">语音连接中断，已保存的对话仍在。点击“继续实时对话”接着练。</p>
            <p v-if="!voiceAllowed" class="sub" role="status">多人语音尚未通过当前服务的能力验证。可用文字演练，或改为一位主谈。</p>
            <div v-if="textReady" class="omega-text-panel"><label for="omega-turn">文字发言</label><textarea id="omega-turn" v-model="textInput" rows="3" maxlength="4000" required placeholder="输入你想对客户说的话…"></textarea><p v-if="voiceOriginal" class="sub">语音原转写：{{ voiceOriginal }}</p><div class="omega-actions"><button class="btn btn-primary" type="submit" :disabled="busy || asrBusy || voiceConnecting || voiceConnected || voiceClosing || activeJob?.kind === 'turn' && activeJob?.status === 'failed' || !!activeJob && ['queued', 'running'].includes(activeJob.status)">发送</button><button class="btn btn-ghost" type="button" :disabled="asrBusy || voiceConnecting || voiceConnected || voiceClosing" @click="toggleRecording">{{ recording ? '停止录音' : '语音输入' }}</button></div></div>
            <p v-if="!realtimeReady && !textReady" class="omega-unavailable">当前未配置可用的语音或文字模型。</p>
            <div v-if="!realtimeReady" class="omega-session-footer"><span>结束后自动生成有原话证据的复盘。</span><button class="btn btn-ghost" type="button" :disabled="busy" @click="finishSession">{{ activeJob?.kind === 'turn' && activeJob.status !== 'succeeded' ? '结束本场（不评分）' : '结束并复盘' }}</button></div>
            </template>
          </form>
          <div v-if="chosenSession.status === 'ended' && !report" class="card omega-complete-controls"><div><p class="omega-kicker">本场已结束</p><strong>{{ chosenSession.report_blocked ? '本场无法评分' : activeJob && ['queued', 'running'].includes(activeJob.status) ? '复盘生成中…' : chosenSession.report_partial ? '可生成部分复盘' : '查看本场复盘' }}</strong><p v-if="chosenSession.report_blocked">{{ chosenSession.report_blocked_message || '本场对话不完整，无法评分。' }}已保存的原话仍可查看。</p><p v-else-if="chosenSession.report_partial">{{ chosenSession.report_warning || '语音尾稿未确认' }}。逐字稿可能缺失，部分复盘不能评分或达标。</p><p v-else-if="!textReady">复盘服务暂不可用。</p><p v-else>报告会引用本场对话原话。</p></div><button v-if="!chosenSession.report_blocked && canWrite(chosenSession.owner_id) && !(activeJob && ['queued', 'running'].includes(activeJob.status))" class="btn btn-primary" type="button" :disabled="(!textReady && !chosenSession.report_partial) || busy || !chosenSession.segments?.length" @click="makeReport">{{ activeJob?.status === 'failed' ? '重试复盘' : chosenSession.report_partial ? '生成部分复盘' : '生成复盘' }}</button></div>
          <section v-if="report" class="card pad omega-report"><h3>复盘报告</h3>
            <div v-if="report.content.evidence_status === 'incomplete'" class="omega-partial-report">
              <div role="alert"><strong>部分复盘，证据不完整，不能评分/达标</strong>
                <p>{{ report.content.incomplete_reason || chosenSession.report_warning || '语音尾稿未完成' }}。逐字稿可能缺失，不能确认谈判成果。已保存的发言可在上方逐字稿核对。</p></div>
              <h4>已保存原话</h4>
              <blockquote v-for="quote in report.content.saved_quotes || []" :key="quote.segment_id + quote.start"><button type="button" class="omega-quote-link" @click="showQuote(quote)">“{{ quote.text }}” <small>查看第 {{ quoteNumber(quote) }} 条原话</small></button></blockquote>
              <p v-if="!report.content.saved_quotes?.length">本场没有可引用的原话，请查看上方逐字稿。</p>
              <button v-if="canWrite(chosenSession.owner_id)" class="btn btn-primary" type="button" :disabled="busy" @click="repeatPractice">再练一轮</button>
              <h4>主管点评</h4><p v-for="(item, index) in report.reviews" :key="index">{{ item.content.comment }} <small>{{ item.content.next_practice }}</small></p>
              <form v-if="['manager', 'admin'].includes(me?.role || '')" @submit.prevent="reviewReport"><label>点评<textarea v-model.trim="reviewText" minlength="5" required></textarea></label><label>下次练习<input v-model.trim="nextPractice"></label><button class="btn" type="submit" :disabled="busy">追加点评</button></form>
            </div>
            <template v-else>
            <p v-if="report.content.hints_used?.length" class="sub">本场使用了 {{ report.content.hints_used.length }} 次教练建议。评分仍依据本场原话。</p>
            <div class="omega-score-summary">
              <strong v-if="report.content.score?.total != null">{{ report.content.score.total }} 分</strong>
              <strong v-else-if="report.content.score?.available">已评分项 {{ report.content.score.earned }} / {{ report.content.score.available }} 分</strong>
              <strong v-else>证据不足</strong>
              <span v-if="report.content.score?.total != null">本场综合评分 · 满分 100</span>
              <span v-else-if="report.content.score?.available">仅已观察维度，覆盖 {{ report.content.score.available }}/100；暂无综合总分</span>
              <span v-else>无可评分项，暂无综合总分</span>
            </div>
            <p class="sub">AI 评分用于训练建议。主管需核对原话与结论，再用于正式评价。</p>
            <p class="omega-report-result"><strong>{{ outcomeLabel }}</strong>　{{ report.content.outcome?.reason }}</p>
            <div v-if="strengthPoint" class="omega-report-strength"><span>做得好 · {{ dimensionNames[strengthPoint.key] || strengthPoint.key }}</span><p>{{ strengthPoint.reason }}</p><blockquote v-if="strengthPoint.quotes[0]"><button type="button" class="omega-quote-link" @click="showQuote(strengthPoint.quotes[0])">“{{ strengthPoint.quotes[0].text }}” <small>查看第 {{ quoteNumber(strengthPoint.quotes[0]) }} 条原话</small></button></blockquote></div>
            <div class="omega-report-focus"><span>{{ coachingPoint ? `最需要练：${dimensionNames[coachingPoint.key] || coachingPoint.key}` : '下次只改这一点' }}</span><p>{{ coachingPoint?.reason || reportNextPractice || '本场证据不足，先完成一轮有来有回的对话。' }}</p><blockquote v-if="coachingPoint?.quotes[0]"><button type="button" class="omega-quote-link" @click="showQuote(coachingPoint.quotes[0])">“{{ coachingPoint.quotes[0].text }}” <small>查看第 {{ quoteNumber(coachingPoint.quotes[0]) }} 条原话</small></button></blockquote><p v-if="coachingPoint && reportNextPractice" class="omega-report-next"><strong>下次尝试：</strong>{{ reportNextPractice }}</p></div>
            <p v-if="currentAssignment?.baseline" class="omega-session-note">{{ dimensionNames[currentAssignment.target_dimension] }}：上次 {{ currentAssignment.baseline.percent }}% · 本轮 {{ currentAttempt?.result ? `${currentAttempt.result.percent}%` : '待评分' }} · {{ currentAssignment.target_dimension === 'outcome' ? attemptLabel(currentAttempt, 'outcome') : currentAttempt?.passed ? '已达标' : '继续练习' }}</p>
            <button v-if="canWrite(chosenSession.owner_id)" class="btn btn-primary" type="button" :disabled="busy" @click="repeatPractice">{{ currentAssignment ? '继续练本项' : coachingPoint ? '按这个卡点再练' : '再练一轮' }}</button>
            <OmegaMemoryReview v-if="chosenSession?.owner_id === me?.id" :report-id="report.id" />
            <form v-if="['manager', 'admin'].includes(me?.role || '') && coachingPoint" class="omega-import" @submit.prevent="assignFromReport">
              <h4>让销售练这个卡点</h4><p>推荐练 {{ dimensionNames[coachingPoint.key] || coachingPoint.key }}；当前 {{ focusPercent }}%，目标 {{ focusPassPercent }}%。{{ reportNextPractice }}</p>
              <label>销售<select v-model.number="assignUserId" required><option :value="null" disabled>请选择</option><option v-for="member in assignableMembers" :key="member.id" :value="member.id">{{ memberLabel(member) }}</option></select></label>
              <p v-if="matchingAssignment" role="status">已指派 · {{ matchingAssignment.status === 'passed' ? '已达标' : matchingAssignment.status === 'in_progress' ? '练习中' : '待练' }} · {{ matchingAssignment.attempts.length }} 次练习</p>
              <button v-if="matchingAssignment" class="btn" type="button" @click="showAssignment(matchingAssignment)">查看指派进展</button>
              <button v-else class="btn" type="submit" :disabled="busy">指派这项练习</button>
            </form>
            <details class="omega-report-details"><summary>查看原话证据和完整评分</summary>
              <blockquote v-for="quote in report.content.outcome?.quotes || []" :key="quote.segment_id + quote.start"><button type="button" class="omega-quote-link" @click="showQuote(quote)">“{{ quote.text }}” <small>查看第 {{ quoteNumber(quote) }} 条原话</small></button></blockquote>
              <h4>承诺、让步与底线</h4>
              <div v-for="(items, title) in { '承诺': report.content.commitments || [], '让步代价': report.content.concession_costs || [], '底线': report.content.hard_limit_findings || [] }" :key="title">
                <strong>{{ title }}</strong><p v-if="!items.length">没有可核验的原话</p>
                <div v-for="(item, index) in items" :key="index"><p>{{ item.description || item.reason }}</p><blockquote v-for="quote in item.quotes" :key="quote.segment_id + quote.start"><button type="button" class="omega-quote-link" @click="showQuote(quote)">“{{ quote.text }}” <small>查看第 {{ quoteNumber(quote) }} 条原话</small></button></blockquote></div>
              </div>
              <p>评分覆盖 {{ report.content.score?.available ?? 0 }}/100；{{ report.content.score?.total === null ? '证据不足，暂无总分' : `总分 ${report.content.score?.total}` }}</p>
              <ul><li v-for="dim in report.content.dimensions || []" :key="dim.key"><strong>{{ dimensionNames[dim.key] || dim.key }}：</strong>{{ reportWeights[dim.key] === 0 ? '不适用' : dim.score === null ? '证据不足' : dim.score }} / {{ dim.reason }}<blockquote v-for="quote in dim.quotes || []" :key="quote.segment_id + quote.start"><button type="button" class="omega-quote-link" @click="showQuote(quote)">“{{ quote.text }}” <small>查看第 {{ quoteNumber(quote) }} 条原话</small></button></blockquote></li></ul>
            </details>
            <h4>主管点评</h4><p v-for="(item, index) in report.reviews" :key="index">{{ item.content.comment }} <small>{{ item.content.next_practice }}</small><strong v-if="item.content.outcome_verdict"> · {{ item.content.outcome_verdict === 'confirmed' ? '已确认目标判断' : '已驳回目标判断' }}</strong></p>
            <form v-if="['manager', 'admin'].includes(me?.role || '')" @submit.prevent="reviewReport">
              <fieldset class="omega-outcome-review"><legend>目标判断 · 核对原话</legend>
                <p>{{ outcomeLabel }}。{{ report.content.outcome?.reason }}</p>
                <blockquote v-for="quote in report.content.outcome?.quotes || []" :key="quote.segment_id + quote.start"><button type="button" class="omega-quote-link" @click="showQuote(quote)">“{{ quote.text }}” <small>查看第 {{ quoteNumber(quote) }} 条原话</small></button></blockquote>
                <p v-if="!report.content.outcome?.quotes?.length">AI 未提供结果原话；请核对逐字稿后再判断。</p>
                <label>本次点评对目标判断的处理<select v-model="outcomeVerdictInput"><option value="">仅点评，不确认目标</option><option v-if="['achieved', 'partial'].includes(report.content.outcome?.status || '')" value="confirmed">确认 AI 的目标判断</option><option value="rejected">驳回 AI 的目标判断</option></select></label>
              </fieldset>
              <label>点评<textarea v-model.trim="reviewText" minlength="5" required></textarea></label><label>下次练习<input v-model.trim="nextPractice"></label><button class="btn" type="submit" :disabled="busy">追加点评</button>
            </form>
            <details v-if="['manager', 'admin'].includes(me?.role || '')" class="omega-import"><summary>手动设置指派</summary>
            <form @submit.prevent="createAssignment(report.id)">
              <label>销售<select v-model.number="assignUserId" required><option :value="null" disabled>请选择</option><option v-for="member in assignableMembers" :key="member.id" :value="member.id">{{ memberLabel(member) }}</option></select></label>
              <label>目标技能<select v-model="assignDimension"><option v-for="(name, scoreKey) in dimensionNames" :key="scoreKey" :value="scoreKey">{{ name }}</option></select></label>
              <label>达标百分比<input v-model.number="assignPassPercent" type="number" min="1" max="100" required></label>
              <label>截止日期<input v-model="assignDueDate" type="date"></label>
              <label>练习要求<textarea v-model.trim="assignInstructions" maxlength="1000"></textarea></label>
              <button class="btn" type="submit" :disabled="busy">指派针对性练习</button>
            </form>
            </details>
            </template>
          </section>
        </div>
        <div v-else-if="!setupOpen && chosenCase" class="card pad omega-case-detail">
          <p class="omega-kicker">谈判任务 · {{ chosenCase.draft_confirmed ? `目标版本 ${chosenCase.current_version}` : '待确认目标' }}</p>
          <h2>{{ chosenCase.title }}</h2>
          <div class="omega-case-brief"><span>双方背景</span><p>{{ chosenCase.draft.public_brief }}</p></div>
          <div class="omega-goal"><span>成功判定条件</span><p>{{ chosenCase.draft.goal.success_condition }}</p></div>
          <p v-if="chosenCase.draft.meeting_topic" class="sub">本次命题：{{ chosenCase.draft.meeting_topic }}</p>
          <p v-if="chosenCase.draft.meeting_materials?.length" class="sub">本次资料：{{ chosenCase.draft.meeting_materials.map(item => item.name).join('、') }}</p>
          <p v-if="!chosenCase.draft_confirmed" role="status">当前草稿尚未确认，确认后才可开始新演练或导入会议。</p>
          <div class="omega-actions"><button v-if="chosenCase.draft_confirmed" class="btn btn-primary" type="button" :disabled="busy" @click="startSession">开始新演练</button><button v-if="canWrite(chosenCase.owner_id) && !chosenCase.draft_confirmed" class="btn btn-primary" type="button" :disabled="busy" @click="confirmCase">确认目标版本</button><button v-if="canWrite(chosenCase.owner_id)" class="btn btn-ghost" type="button" @click="editCase(chosenCase)">编辑草稿</button></div>
          <details v-if="chosenCase.draft_confirmed && ['manager', 'admin'].includes(me?.role || '')" class="omega-import"><summary>指派练习</summary>
          <form @submit.prevent="createAssignment()">
            <label>销售<select v-model.number="assignUserId" required><option :value="null" disabled>请选择</option><option v-for="member in assignableMembers" :key="member.id" :value="member.id">{{ memberLabel(member) }}</option></select></label>
            <label>目标技能<select v-model="assignDimension"><option v-for="(name, scoreKey) in dimensionNames" :key="scoreKey" :value="scoreKey">{{ name }}</option></select></label>
            <label>达标百分比<input v-model.number="assignPassPercent" type="number" min="1" max="100" required></label>
            <label>截止日期<input v-model="assignDueDate" type="date"></label>
            <label>练习要求<textarea v-model.trim="assignInstructions" maxlength="1000"></textarea></label>
            <button class="btn" type="submit" :disabled="busy">指派销售</button>
          </form>
          </details>
          <details v-if="chosenCase.draft_confirmed" :open="chosenCase.draft.usage === 'real_review'" class="omega-import"><summary>导入真实会议复盘</summary>
            <p class="sub">仅导入你有 Vemory 来源权限且具备分说话人逐字稿的会议。</p>
            <label>Vemory 会议 ID<input v-model.trim="meetingId" maxlength="120"></label>
            <button class="btn btn-ghost" type="button" :disabled="busy" @click="previewMeeting">读取逐字稿</button>
            <div v-if="meetingSpeakers.length">
              <label v-for="speaker in meetingSpeakers" :key="speaker">{{ speaker }} 的身份
                <select v-model="speakerMap[speaker]"><option disabled value="">请选择</option><option value="sales">销售</option><option value="counterparty">对手</option></select>
                <select v-if="speakerMap[speaker] === 'counterparty' && chosenCase.draft.participants?.length" v-model="participantMap[speaker]" :aria-label="`${speaker}对应的参会人`"><option value="" disabled>选择对应参会人</option><option v-for="person in chosenCase.draft.participants" :key="person.id" :value="person.id">{{ person.name }} · {{ person.role }}</option></select>
              </label>
              <details><summary>核对来源逐字稿（{{ meetingPreview.length }} 条）</summary><p v-for="(part, index) in meetingPreview" :key="index">{{ part.speaker }}：{{ part.text }}</p></details>
              <button class="btn" type="button" :disabled="busy || meetingSpeakers.some((speaker) => !speakerMap[speaker] || speakerMap[speaker] === 'counterparty' && !!chosenCase?.draft.participants?.length && !participantMap[speaker])" @click="importMeeting">确认映射并导入</button>
            </div>
          </details>
        </div>
        <div v-else-if="!setupOpen" class="card pad omega-welcome"><p class="omega-kicker">开始训练</p><h2>选个客户卡点，马上开练</h2><p>可以用常见场景，也可以写下手头客户的情况。</p><button class="btn btn-primary" type="button" @click="newCase()">开始练习</button></div>
      </section>
    </div>
  </main>
  <dialog ref="voiceDialog" class="omega-call" aria-label="实时语音对话" @cancel.prevent="exitVoice">
    <div class="omega-call-shell">
      <div class="omega-call-top"><span>会议陪练 · 实时对话</span><span>{{ chosenSession ? caseName(chosenSession.case_id) : '' }}</span></div>
      <div class="omega-call-center">
        <div class="omega-call-orb" :class="{ 'is-speaking': voiceSpeaking, 'is-connecting': voiceConnecting, 'is-paused': voicePhase !== 'live' }" aria-hidden="true"></div>
        <h2 aria-live="polite">{{ voiceClosing ? '正在结束' : voiceConnecting ? '正在连接' : voicePhase === 'error' ? '演练已暂停' : voicePhase === 'coaching' ? '教练时间' : voicePhase === 'pausing' ? '正在暂停' : voicePhase === 'resuming' ? '正在恢复' : voiceSpeaking ? `${currentSpeakerName}正在说话` : '正在听' }}</h2>
        <p>{{ voiceClosing ? voiceEndNotice || '正在保存语音尾稿…' : voicePhase === 'error' ? '麦克风已暂停，请查看错误提示' : ['pausing', 'resuming'].includes(voicePhase) ? '正在保存上一句语音并确认状态，可能需要约 50 秒，请保持页面。' : voicePhase === 'coaching' ? '麦克风已暂停，教练提示只对你可见' : voiceConnecting ? '正在连接语音，请稍候' : voiceSpeaking ? '可以随时开口打断' : '直接说话，对手会实时回应' }}</p>
        <p v-if="voiceEndNotice && !voiceClosing" class="omega-call-warning" role="status">{{ voiceEndNotice }}</p>
        <div v-if="participants.length > 1" class="omega-participants" aria-label="对手参会人"><span v-for="person in participants" :key="person.id" :class="{ active: voiceSpeaking && currentSpeakerId === person.id }">{{ person.name }} · {{ person.role }}</span></div>
        <div v-if="voicePhase === 'coaching'" class="omega-private-coach" role="status"><p>{{ coachBusy ? '教练正在看本场对话…' : coachText || '可向教练求助，也可直接继续演练。' }}</p><button v-if="!coachBusy" class="btn btn-sm btn-ghost" type="button" @click="requestCoach">再给一条建议</button></div>
        <p v-if="coachError" class="omega-call-error" role="alert">{{ coachError }}</p>
        <p v-if="voiceCaption && voicePhase === 'live'" class="omega-call-caption">{{ voiceCaption }}</p>
      </div>
      <div class="omega-call-bottom">
        <button v-if="voiceConnected && voicePhase === 'live'" class="btn omega-coach-button" type="button" :disabled="voiceClosing" @click="controlVoice('pause')">暂停，问问教练</button>
        <button v-else-if="voiceConnected" class="btn btn-primary omega-coach-button" type="button" :disabled="voiceClosing || voiceRecoveryBlocked || !['coaching', 'error'].includes(voicePhase)" @click="resumeVoice">{{ voiceRecoveryBlocked ? '本场无法恢复' : voicePhase === 'resuming' ? '正在恢复…' : voicePhase === 'error' ? '重试恢复' : '继续演练' }}</button>
        <label for="omega-call-volume">对手音量 <span>{{ Math.round(voiceVolume * 100) }}%</span></label>
        <input id="omega-call-volume" v-model.number="voiceVolume" type="range" min="1" max="2.5" step="0.1" aria-label="对手音量">
        <button class="btn omega-call-hangup" type="button" :disabled="voiceClosing" @click="exitVoice">{{ voiceClosing ? '结束中…' : voiceConnecting ? '取消连接' : '结束通话' }}</button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.omega { max-width: 1380px; }
.omega-discard-confirm { margin-bottom: 16px; padding: 14px; border-color: var(--blue); background: var(--blue-soft); }
.omega-discard-confirm p { margin: 0 0 10px; line-height: 1.5; }
.omega-discard-confirm > div { display: flex; flex-wrap: wrap; gap: 8px; }
.omega-discard-confirm .btn { min-height: 44px; }
.omega-head { align-items: center; margin-bottom: 22px; }
.omega-head h1 { font-size: 30px; letter-spacing: -.03em; }
.omega-kicker { margin: 0 0 6px; color: var(--blue); font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.omega-head-meta { display: flex; gap: 8px; align-items: center; }
.omega-grid { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 20px; align-items: start; }
.omega-side { position: sticky; top: 92px; overflow: hidden; }
.omega-side-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 18px 16px 16px; }
.omega-side-head h2 { margin: 0; font-size: 17px; }
.omega-side-head .btn { white-space: nowrap; }
.omega-side-actions { display: flex; align-items: center; gap: 6px; }
.omega-side-toggle { display: none; }
.omega-side-tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; margin: 0 12px; padding: 4px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); }
.omega-side-tabs button { min-height: 36px; padding: 6px 4px; border: 0; border-radius: 7px; background: transparent; color: var(--muted); cursor: pointer; font-size: 12px; }
.omega-side-tabs button.active { background: var(--card-2); color: var(--text); font-weight: 700; }
.omega-side-tabs span { color: var(--muted); font-variant-numeric: tabular-nums; }
.omega-side-body { max-height: min(68vh, 680px); min-height: 160px; overflow-y: auto; padding: 16px 12px; }
.omega-list-title { margin: 0 4px 8px; color: var(--muted); font-size: 12px; }
.omega-list { list-style: none; margin: 0; padding: 0; }
.omega-list li + li { margin-top: 4px; }
.omega-link { display: block; width: 100%; padding: 11px 12px; border: 1px solid transparent; border-radius: 9px; background: none; color: var(--text); text-align: left; cursor: pointer; }
.omega-link:hover { background: var(--card-2); }
.omega-link.selected { background: var(--blue-soft); border-color: rgba(78, 158, 245, .22); }
.omega-link strong { display: -webkit-box; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical; font-size: 13px; line-height: 1.4; font-weight: 600; overflow-wrap: anywhere; }
.omega-link small { display: block; margin-top: 5px; color: var(--muted); font-size: 11px; }
.omega-side-empty { margin: 18px 8px; color: var(--muted); font-size: 13px; line-height: 1.6; }
.omega-more { display: block; width: 100%; min-height: 36px; margin-top: 8px; border: 0; background: transparent; color: var(--blue); font-size: 12px; cursor: pointer; }
.omega-main { min-width: 0; }
.omega-return { margin-bottom: 12px; }
.omega-return .btn { min-height: 44px; border: 1px solid var(--blue); background: var(--blue-soft); color: var(--text); padding: 0 14px; }
.omega-main > .card.pad { padding: 24px; }
.omega-main h2 { margin: 0 0 12px; font-size: 20px; }
.omega-intake h2 { font-size: 24px; }
.omega-intake > .sub { max-width: 670px; margin-bottom: 24px; line-height: 1.6; }
.omega-intake > label { font-size: 13px; font-weight: 600; }
.omega-intake > textarea { min-height: 112px; padding: 16px; background: var(--card-2); line-height: 1.7; }
.omega-quick-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0 0 24px; }
.omega-quick-card { display: flex; min-height: 104px; flex-direction: column; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--card-2); color: var(--text); text-align: left; cursor: pointer; }
.omega-quick-card:hover, .omega-quick-card:focus-visible { border-color: var(--blue); background: var(--blue-soft); }
.omega-quick-card:disabled { opacity: .5; cursor: wait; }
.omega-quick-card strong { font-size: 15px; }
.omega-quick-card span { color: var(--muted); font-size: 12px; }
.omega-intake-actions { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-top: 16px; }
.omega-intake-actions span { color: var(--muted); font-size: 12px; line-height: 1.5; }
.omega-intake-actions .btn { min-width: 128px; }
.omega-analysis { margin-top: 28px; padding-top: 24px; border-top: 1px solid var(--border); }
.omega-analysis-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.omega-analysis-head h3 { margin: 0; font-size: 18px; }
.omega-analysis-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }
.omega-analysis-summary div { padding: 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--card-2); }
.omega-analysis-summary dt { margin-bottom: 6px; color: var(--muted); font-size: 11px; }
.omega-analysis-summary dd { margin: 0; line-height: 1.55; overflow-wrap: anywhere; }
.omega-missing { padding: 10px 12px; border-radius: 8px; color: var(--amber); background: rgba(245, 158, 11, .1); font-size: 13px; line-height: 1.6; }
.omega-review-note { color: var(--muted); font-size: 12px; }
.omega-review-fields { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }
.omega-welcome { display: flex; flex-direction: column; align-items: flex-start; justify-content: center; min-height: 330px; }
.omega-welcome > p:not(.omega-kicker) { max-width: 520px; color: var(--muted); line-height: 1.7; }
.omega-welcome .btn { margin-top: 12px; }
.omega-case-brief { margin-top: 22px; }
.omega-case-brief span { color: var(--muted); font-size: 12px; }
.omega-case-brief p { margin: 8px 0 0; line-height: 1.65; white-space: pre-wrap; }
.omega-case-detail > .omega-actions { margin-top: 22px; }
.omega-workspace { display: grid; gap: 14px; }
.omega-session-summary { padding: 22px 24px; }
.omega-session-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.omega-session-heading h2 { margin: 0; font-size: 23px; line-height: 1.3; }
.omega-session-heading .pill { flex: none; }
.omega-goal { margin-top: 20px; padding: 14px 16px; border-left: 3px solid var(--blue); border-radius: 0 8px 8px 0; background: var(--blue-soft); }
.omega-goal span { color: var(--muted); font-size: 11px; }
.omega-goal p { margin: 5px 0 0; font-size: 15px; line-height: 1.55; }
.omega-session-note { margin: 12px 0 0; color: var(--muted); font-size: 12px; }
.omega-conversation { display: flex; flex-direction: column; min-height: 330px; padding: 20px 24px 12px; }
.omega-conversation-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding-bottom: 14px; border-bottom: 1px solid var(--border); }
.omega-conversation-head h3 { margin: 0; font-size: 17px; }
.omega-turn-count { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.omega-transcript { display: flex; flex-direction: column; flex: 1; gap: 18px; max-height: 52vh; margin: 0; padding: 22px 4px; overflow-y: auto; list-style: none; }
.omega-transcript li { max-width: min(76%, 650px); }
.omega-transcript li.is-sales { align-self: flex-end; }
.omega-speaker { display: block; margin: 0 0 6px 2px; color: var(--muted); font-size: 11px; }
.omega-transcript li.is-sales .omega-speaker { text-align: right; margin-right: 2px; }
.omega-transcript li p { margin: 0; padding: 12px 15px; border: 1px solid var(--border); border-radius: 4px 12px 12px; background: var(--card-2); line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.omega-transcript li.is-sales p { border-color: rgba(78, 158, 245, .24); border-radius: 12px 4px 12px 12px; background: var(--blue-soft); }
.omega-transcript li.is-quoted p { outline: 3px solid var(--blue); outline-offset: 3px; }
.omega-asr-original { margin-top: 4px; color: var(--muted); font-size: 12px; }
.omega-asr-original summary { line-height: 44px; cursor: pointer; }
.omega-transcript-empty { display: grid; align-content: center; justify-items: center; flex: 1; padding: 56px 16px; text-align: center; }
.omega-transcript-empty strong { font-size: 15px; }
.omega-transcript-empty p { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
.omega-live-caption, .omega-responding { margin: 0 0 10px; padding: 10px 12px; border-radius: 8px; background: var(--blue-soft); color: var(--text); font-size: 13px; }
.omega-transcript-tools { display: flex; justify-content: flex-end; border-top: 1px solid var(--border); padding-top: 8px; }
.omega-practice-controls { padding: 16px 20px 12px; }
.omega-tail-recovery { display: flex; justify-content: space-between; align-items: center; gap: 20px; padding: 12px 4px; }
.omega-tail-recovery strong { color: var(--red); font-size: 17px; }
.omega-tail-recovery p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.omega-voice-panel, .omega-complete-controls { display: flex; justify-content: space-between; align-items: center; gap: 20px; }
.omega-voice-panel { padding: 6px 4px 18px; }
.omega-voice-panel strong, .omega-complete-controls strong { font-size: 17px; }
.omega-voice-panel p:not(.omega-kicker), .omega-complete-controls p:not(.omega-kicker) { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.omega-voice-panel.is-live .omega-kicker { color: var(--green); }
.omega-voice-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.omega-voice-button { min-width: 174px; min-height: 44px; flex: none; }
.omega-text-panel { padding: 18px 4px; border-top: 1px solid var(--border); }
.omega-text-panel label { margin-top: 0; font-size: 13px; font-weight: 600; }
.omega-session-footer { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 4px 0; border-top: 1px solid var(--border); }
.omega-session-footer span { color: var(--muted); font-size: 12px; }
.omega-unavailable { color: var(--amber); font-size: 13px; }
.omega-complete-controls { padding: 18px 24px; }
.omega-complete-controls .btn { flex: none; }
.omega-form { margin-top: 20px; }
.omega input, .omega textarea, .omega select { width: 100%; padding: 10px 12px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--bg); color: var(--text); font: inherit; }
.omega textarea { resize: vertical; }
.omega label { display: grid; gap: 6px; margin: 8px 0; }
.omega-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.omega-alert, .omega-notice { padding: 12px 14px; border-radius: 8px; }
.omega-alert { color: var(--red); background: rgba(239, 68, 68, .12); }
.omega-call-center > p.omega-call-warning { margin-top: 12px; color: var(--amber); font-weight: 600; }
.omega-notice { color: var(--blue); background: var(--blue-soft); }
.omega-report { margin-top: 2px; }
.omega-partial-report { padding: 16px; border: 1px solid var(--red); border-radius: 10px; background: rgba(239, 68, 68, .08); }
.omega-partial-report [role="alert"] strong { color: var(--red); }
.omega-partial-report p { line-height: 1.6; }
.omega-report-result { line-height: 1.6; }
.omega-outcome-review { margin: 16px 0; padding: 12px 16px; border: 1px solid var(--border); border-radius: 8px; }
.omega-outcome-review legend { padding: 0 6px; font-weight: 600; }
.omega-report-focus { margin: 20px 0; padding: 18px; border-radius: 10px; background: var(--blue-soft); }
.omega-report-focus span { color: var(--blue); font-size: 12px; font-weight: 700; }
.omega-report-focus p { margin: 8px 0 0; font-size: 17px; line-height: 1.6; }
.omega-report-details { margin-top: 20px; border-top: 1px solid var(--border); padding-top: 16px; }
.omega-report-details > summary { cursor: pointer; font-weight: 600; }
.omega-report blockquote { margin: 4px 0 12px; padding-left: 10px; border-left: 2px solid var(--blue); color: var(--muted); }
.omega-quote-link { max-width: 100%; padding: 2px 0; border: 0; background: transparent; color: inherit; text-align: left; line-height: 1.6; overflow-wrap: anywhere; cursor: pointer; }
.omega-quote-link small { display: block; color: var(--blue); font-size: 11px; }
.omega-quote-link:focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; }
.omega-assignment-quote { margin: 16px 0; padding: 12px 14px; border-left: 3px solid var(--blue); background: var(--blue-soft); line-height: 1.6; overflow-wrap: anywhere; }
.omega-import { margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--border); }
.omega-import > summary { cursor: pointer; font-size: 15px; font-weight: 600; }
.omega-import > form, .omega-import > p { margin-top: 16px; }
.omega-scorecard { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0 12px; border: 1px solid var(--border); border-radius: 8px; }
.omega-scorecard legend { padding: 0 8px; }
.omega-call { inset: 0; width: 100%; max-width: none; height: 100dvh; max-height: none; margin: 0; padding: 0; border: 0; background: var(--bg); color: var(--text); }
.omega-call::backdrop { background: var(--bg); }
.omega-call-shell { display: flex; flex-direction: column; height: 100%; box-sizing: border-box; overflow: hidden; padding: max(24px, env(safe-area-inset-top)) 24px max(24px, env(safe-area-inset-bottom)); }
.omega-call-top { display: flex; justify-content: space-between; gap: 16px; color: var(--muted); font-size: 13px; }
.omega-call-top span:last-child { overflow: hidden; max-width: 48%; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.omega-call-center { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; min-height: 0; text-align: center; }
.omega-call-orb { position: relative; width: clamp(152px, 42vw, 210px); aspect-ratio: 1; border-radius: 50%; background: radial-gradient(circle at 38% 30%, #9ed9ff 0, #488ed1 38%, #1a426f 72%, #122541 100%); box-shadow: 0 0 0 1px rgba(158, 217, 255, .22), 0 0 70px rgba(78, 158, 245, .25); animation: omega-breathe 3.4s ease-in-out infinite; }
.omega-call-orb::before { position: absolute; inset: -20px; border: 1px solid rgba(78, 158, 245, .18); border-radius: 50%; content: ''; }
.omega-call-orb.is-speaking { animation-duration: 1.35s; }
.omega-call-orb.is-connecting { opacity: .55; }
.omega-call-orb.is-paused { width: 80px; opacity: .5; animation-play-state: paused; }
.omega-coach-button { width: 100%; min-height: 48px; margin-bottom: 12px; }
.omega-private-coach { max-height: 26dvh; overflow-y: auto; width: min(100%,520px); text-align: left; padding: 16px; margin-top: 20px; background: var(--card-2); border: 1px solid var(--border); border-radius: 8px; line-height: 1.7; }
.omega-private-coach p { margin: 0; white-space: pre-wrap; }
.omega-call-error { color: var(--red) !important; max-width: 500px; }
.omega-participants { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; justify-content: center; }
.omega-participants span { padding: 6px 10px; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; }
.omega-participants span.active { border-color: var(--blue); }
.omega-score-summary { display: grid; gap: 8px; margin: 20px 0; }
.omega-score-summary strong { font-size: 32px; }
.omega-score-summary span,.omega-report-strength > span { color: var(--muted); font-size: 12px; }
.omega-report-strength { padding: 16px; margin-bottom: 16px; border-left: 3px solid var(--green); background: var(--card-2); }
.omega-call-center h2 { margin: 42px 0 8px; font-size: 26px; font-weight: 600; }
.omega-call-center > p { margin: 0; color: var(--muted); font-size: 14px; }
.omega-call-caption { display: -webkit-box; overflow: hidden; max-width: 520px; margin-top: 28px !important; -webkit-box-orient: vertical; -webkit-line-clamp: 3; line-height: 1.6; }
.omega-call-bottom { width: min(100%, 420px); margin: 0 auto; }
.omega-call-bottom label { display: flex; justify-content: space-between; color: var(--muted); font-size: 13px; }
.omega-call-bottom input { width: 100%; min-height: 44px; margin: 4px 0 16px; accent-color: var(--blue); }
.omega-call-hangup { width: 100%; min-height: 52px; border-color: rgba(244, 63, 94, .36); color: #ff7188; }
@keyframes omega-breathe { 50% { transform: scale(1.09); box-shadow: 0 0 0 12px rgba(78, 158, 245, .07), 0 0 95px rgba(78, 158, 245, .4); } }
@media (prefers-reduced-motion: reduce) { .omega-call-orb { animation: none; } }
@media (max-height: 560px) {
  .omega-call-shell { padding: 12px 20px; }
  .omega-call-orb { width: 96px; }
  .omega-call-orb::before { inset: -10px; }
  .omega-call-center h2 { margin: 12px 0 4px; font-size: 21px; }
  .omega-call-caption { display: none; }
  .omega-call-bottom input { min-height: 28px; margin-bottom: 8px; }
  .omega-call-hangup { min-height: 44px; }
}
@media (max-width: 900px) {
  .omega-grid { grid-template-columns: 1fr; }
  .omega-side { position: static; }
  .omega-side-body { max-height: 190px; min-height: 0; }
  .omega-quick-grid { grid-template-columns: 1fr; }
  .omega-quick-card { min-height: 64px; flex-direction: row; align-items: center; }
}
@media (max-width: 640px) {
  .omega.is-setup .omega-head > div:first-child { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .omega.is-setup .omega-head { margin-bottom: 12px; }
  .omega-side-toggle { display: inline-flex; }
  .omega-side.is-collapsed .omega-side-tabs, .omega-side.is-collapsed .omega-side-body { display: none; }
  .omega-workspace { display: flex; flex-direction: column; }
  .omega-practice-controls, .omega-complete-controls { order: 0; }
  .omega-session-summary { order: 1; }
  .omega-conversation { order: 2; }
  .omega-report { order: 0; }
  .omega-head h1 { font-size: 25px; }
  .omega-head-meta { width: 100%; }
  .omega-main > .card.pad, .omega-session-summary, .omega-conversation, .omega-practice-controls, .omega-complete-controls { padding: 16px; }
  .omega-session-heading h2 { font-size: 20px; }
  .omega-voice-panel, .omega-complete-controls { align-items: stretch; flex-direction: column; }
  .omega-tail-recovery { align-items: stretch; flex-direction: column; }
  .omega-voice-actions { flex-direction: column; }
  .omega-voice-button, .omega-complete-controls .btn { width: 100%; }
  .omega-session-footer { align-items: stretch; flex-direction: column; }
  .omega-transcript li { max-width: 92%; }
  .omega-transcript { max-height: none; overflow: visible; }
  .omega-intake-actions { align-items: stretch; flex-direction: column; }
  .omega-intake-actions .btn { width: 100%; }
  .omega-analysis-summary { grid-template-columns: 1fr; }
  .omega-form, .omega-scorecard { grid-template-columns: 1fr; }
  .omega-form .span-2 { grid-column: auto; }
}
</style>
