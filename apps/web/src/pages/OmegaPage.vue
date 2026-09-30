<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppNav from '@/components/AppNav.vue'
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
type CaseRow = { id: string; title: string; owner_id: number; revision: number; current_version: number; draft_confirmed: boolean; draft: CaseDraft }
type Segment = { id: string; speaker: string; text: string; seq: number }
type SessionRow = { id: string; case_id: string; owner_id: number; assignment_id?: string | null; status: string; mode: string; created_at?: string; goal_timing?: string; case_version?: number; case_version_id?: string; case_snapshot?: CaseDraft; segments?: Segment[]; latest_report_id?: string; pending_job_id?: string }
type Job = { id: string; status: string; result_id: string; error: string; kind: string }
type Quote = { segment_id: string; speaker: string; text: string; start: number; end: number }
type Fact = { description?: string; reason?: string; quotes: Quote[] }
type Report = { id: string; content: { outcome?: { status: string; reason: string; quotes: Quote[] }; dimensions?: Array<{ key: string; score: number | null; reason: string; quotes: Quote[] }>; score?: { earned: number; available: number; total: number | null }; commitments?: Fact[]; concession_costs?: Fact[]; hard_limit_findings?: Fact[]; next_practice?: string }; reviews: Array<{ content: { comment: string; next_practice: string } }> }
type DimensionResult = { score: number; maximum: number; percent: number; report_id: string } | null
type Assignment = { id: string; case_id: string; assignee_id: number; source_report_id: string | null; target_dimension: string; pass_percent: number; instructions: string; due_at: string | null; baseline: DimensionResult; attempts: Array<{ session_id: string; status: string; result: DimensionResult; passed: boolean }>; status: 'pending' | 'in_progress' | 'passed' }

const defaultWeights: Record<string, number> = { outcome: 25, information: 12, value: 12,
  concessions: 12, objections: 10, listening: 8, compliance: 10, relationship: 6, closure: 5 }
const dimensionNames: Record<string, string> = { outcome: '结果', information: '信息获取', value: '价值表达',
  concessions: '让步', objections: '异议处理', listening: '倾听', compliance: '底线合规', relationship: '关系', closure: '收尾' }

const router = useRouter()
const demoMode = import.meta.env.MODE === 'omega-demo'
const me = ref<{ id: number; role: string } | null>(null)
const cases = ref<CaseRow[]>([])
const sessions = ref<SessionRow[]>([])
const assignments = ref<Assignment[]>([])
const sidebarTab = ref<'cases' | 'assignments' | 'sessions'>('cases')
const mobileNavOpen = ref(false)
const showAllSessions = ref(false)
const members = ref<Array<{ id: number; name: string }>>([])
const chosenAssignment = ref<Assignment | null>(null)
const assignUserId = ref<number | null>(null)
const assignDimension = ref('objections')
const assignPassPercent = ref(70)
const assignInstructions = ref('')
const assignDueDate = ref('')
const chosenCase = ref<CaseRow | null>(null)
const chosenSession = ref<SessionRow | null>(null)
const report = ref<Report | null>(null)
const activeJob = ref<Job | null>(null)
const textInput = ref('')
const reviewText = ref('')
const nextPractice = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const loading = ref(true)
const editing = ref(false)
const recording = ref(false)
const asrBusy = ref(false)
const realtimeReady = ref(false)
const textReady = ref(false)
const voiceConnecting = ref(false)
const voiceConnected = ref(false)
const voiceInterrupted = ref(false)
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
const meetingPreview = ref<Array<{ speaker: string; text: string }>>([])
const draft = ref<CaseDraft>(blankDraft())
const caseBriefInput = ref('')
const analysisBusy = ref(false)
const analysisReady = ref(false)
const reviewOpen = ref(false)
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
    buyer_name: '', buyer_role: '', buyer_company: '', buyer_emotion: '', buyer_objections: [],
    score_weights: { ...defaultWeights },
    goal: { outcome_type: 'payment_commitment', success_condition: '', ideal: '', minimum: '',
      hard_limits: [''], amount_minor: null, currency: 'USD', due_date: null } }
}
function detail(err: unknown): string { return err instanceof HttpError ? err.detail : err instanceof Error ? err.message : '请求失败，请重试' }
function key(): string { return crypto.randomUUID() }
function canWrite(ownerId: number): boolean { return me.value?.id === ownerId || ['manager', 'admin'].includes(me.value?.role || '') }
function caseName(id: string): string { return cases.value.find((row) => row.id === id)?.title || '谈判任务' }
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
  cases.value = caseRows
  sessions.value = sessionRows
  assignments.value = assignmentRows
  if (chosenCase.value) chosenCase.value = caseRows.find((row) => row.id === chosenCase.value?.id) || null
  if (chosenAssignment.value) chosenAssignment.value = assignmentRows.find((row) => row.id === chosenAssignment.value?.id) || null
}
async function openSession(id: string) {
  const token = ++openToken
  if (pollTimer) clearTimeout(pollTimer)
  activeJob.value = null
  report.value = null
  chosenAssignment.value = null
  const game = await apiGet<SessionRow>(`/api/omega/sessions/${id}`)
  if (token !== openToken) return
  mobileNavOpen.value = false
  chosenSession.value = game
  sidebarTab.value = 'sessions'
  if (game.latest_report_id) {
    const loadedReport = await apiGet<Report>(`/api/omega/reports/${game.latest_report_id}`)
    if (token !== openToken) return
    report.value = loadedReport
  }
  if (game.pending_job_id) {
    const job = await apiGet<Job>(`/api/omega/jobs/${game.pending_job_id}`)
    if (token !== openToken) return
    activeJob.value = job
    schedulePoll()
  }
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
  await run(async () => {
    const body = { ...draft.value,
      buyer_objections: draft.value.buyer_objections.map((s) => s.trim()).filter(Boolean),
      goal: { ...draft.value.goal,
      hard_limits: draft.value.goal.hard_limits.map((s) => s.trim()).filter(Boolean),
      amount_minor: draft.value.goal.outcome_type === 'payment_commitment' ? toMinor(amountMajor.value, draft.value.goal.currency) : null,
      currency: draft.value.goal.outcome_type === 'payment_commitment' ? draft.value.goal.currency : null,
      due_date: draft.value.goal.outcome_type === 'payment_commitment' ? draft.value.goal.due_date : null } }
    const saved = chosenCase.value && editing.value
      ? await apiPatch<CaseRow>(`/api/omega/cases/${chosenCase.value.id}`, { ...body, revision: chosenCase.value.revision })
      : await apiPost<CaseRow>('/api/omega/cases', body)
    await loadLists()
    chosenCase.value = saved
    editing.value = false
    notice.value = '草稿已保存，请核对后确认目标版本。'
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
    draft.value = {
      ...blankDraft(),
      title: found.title || '', public_brief: found.public_brief || '',
      seller_private: found.seller_private || '', counterparty_brief: found.counterparty_brief || '',
      buyer_name: found.buyer_name || '', buyer_role: found.buyer_role || '',
      buyer_company: found.buyer_company || '', buyer_emotion: found.buyer_emotion || '',
      buyer_objections: found.buyer_objections || [],
      goal: {
        ...blankDraft().goal,
        outcome_type: goal.outcome_type || 'other',
        success_condition: goal.success_condition || '', ideal: goal.ideal || '',
        minimum: goal.minimum || '', hard_limits: goal.hard_limits?.length ? goal.hard_limits : [''],
        amount_minor: null, currency: goal.currency || null, due_date: goal.due_date || null,
      },
    }
    amountMajor.value = goal.amount_major || ''
    analysisReady.value = true
    reviewOpen.value = false
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
  })
}
async function importMeeting() {
  if (!chosenCase.value) return
  await run(async () => {
    const game = await apiPost<SessionRow>('/api/omega/real-imports', {
      case_id: chosenCase.value!.id, meeting_id: meetingId.value.trim(), speaker_map: speakerMap.value,
    })
    await loadLists()
    await openSession(game.id)
    notice.value = game.goal_timing === 'pre' ? '会议已导入；目标在会前确认。' : '会议已导入；目标未能证明在会前确认，成果达成度将标为未验证。'
  })
}
async function sendTurn() {
  if (!chosenSession.value || !textReady.value || voiceConnecting.value || voiceConnected.value || !textInput.value.trim()) return
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
async function finishSession() {
  if (!chosenSession.value) return
  const sessionId = chosenSession.value.id
  stopCapture(true)
  stopVoice()
  window.speechSynthesis?.cancel()
  await run(async () => {
    const ended = await apiPost<SessionRow>(`/api/omega/sessions/${sessionId}/finish`, { request_key: key() })
    if (chosenSession.value?.id !== sessionId) return
    chosenSession.value = ended
    activeJob.value = null
    await loadLists()
    notice.value = '演练已结束，逐字稿已冻结。'
  })
}
async function makeReport() {
  if (!chosenSession.value || !textReady.value) return
  await run(async () => {
    activeJob.value = await apiPost<Job>(`/api/omega/sessions/${chosenSession.value!.id}/reports`, { request_key: key() })
    schedulePoll()
  })
}
async function pollJob() {
  if (!activeJob.value) return
  const jobId = activeJob.value.id
  const sessionId = chosenSession.value?.id
  try {
    const job = await apiGet<Job>(`/api/omega/jobs/${jobId}`)
    if (activeJob.value?.id !== jobId || chosenSession.value?.id !== sessionId) return
    activeJob.value = job
    if (job.status === 'succeeded') {
      if (job.result_id) {
        const result = await apiGet<Report>(`/api/omega/reports/${job.result_id}`)
        if (chosenSession.value?.id !== sessionId) return
        report.value = result
      }
      await refreshSession()
      if (job.result_id) await loadLists()
    } else if (job.status === 'failed' || job.status === 'cancelled') {
      error.value = job.error || '任务已取消，请重试'
    } else schedulePoll()
  } catch (err) { error.value = detail(err) }
}
function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = setTimeout(pollJob, 1200)
}
async function reviewReport() {
  if (!report.value) return
  await run(async () => {
    await apiPost(`/api/omega/reports/${report.value!.id}/reviews`, { comment: reviewText.value, next_practice: nextPractice.value })
    report.value = await apiGet<Report>(`/api/omega/reports/${report.value!.id}`)
    reviewText.value = ''
    nextPractice.value = ''
  })
}
function editCase(row: CaseRow) {
  sidebarTab.value = 'cases'
  openToken++
  chosenCase.value = row
  draft.value = structuredClone(row.draft)
  draft.value.score_weights ||= { ...defaultWeights }
  draft.value.buyer_objections ||= []
  amountMajor.value = row.draft.goal.amount_minor === null ? ''
    : (row.draft.goal.amount_minor / 10 ** minorDigits(row.draft.goal.currency)).toFixed(minorDigits(row.draft.goal.currency))
  editing.value = true
  chosenSession.value = null
  chosenAssignment.value = null
  report.value = null
}
function showCase(row: CaseRow) {
  sidebarTab.value = 'cases'
  mobileNavOpen.value = false
  openToken++
  if (pollTimer) clearTimeout(pollTimer)
  chosenCase.value = row
  chosenSession.value = null
  chosenAssignment.value = null
  activeJob.value = null
  report.value = null
  editing.value = false
}
function newCase() {
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
}
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
function stopVoice() {
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
}
async function hangupVoice() {
  const socket = voiceSocket
  const sessionId = chosenSession.value?.id
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
  if (!chosenSession.value || !realtimeReady.value || voiceConnecting.value || voiceConnected.value || voiceClosing.value) return
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
    error.value = '浏览器不支持实时语音，请使用文字或短句录音'
    return
  }
  stopCapture(true)
  const token = ++voiceToken
  const sessionId = chosenSession.value.id
  voiceConnecting.value = true
  voiceInterrupted.value = false
  error.value = ''
  try {
    voiceOutput = new AudioContext()
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
      if (event.data instanceof ArrayBuffer) { playVoiceAudio(event.data); return }
      try {
        const message = JSON.parse(event.data) as { type: string; message?: string; speaker?: string; text?: string }
        if (message.type === 'error') { if (!voiceClosing.value) { error.value = message.message || '实时语音连接失败'; voiceInterrupted.value = true; stopVoice() } return }
        if (message.type === 'closed') {
          if (!voiceClosing.value) voiceInterrupted.value = true
          stopVoice()
          return
        }
        if (message.type === 'interrupt') { stopVoicePlayback(); return }
        if (message.type === 'caption') { voiceCaption.value = `${message.speaker === 'sales' ? '你' : '对手'}：${message.text || ''}`; return }
        if (message.type === 'segment') { await refreshSession(); return }
        if (message.type !== 'ready') return
        voiceInput = new AudioContext({ sampleRate: 16000 })
        await voiceInput.audioWorklet.addModule(new URL(`${import.meta.env.BASE_URL}omega-capture-worklet.js`, location.origin).toString())
        if (token !== voiceToken || voiceSocket !== socket) return
        const source = voiceInput.createMediaStreamSource(captured)
        const worklet = new AudioWorkletNode(voiceInput, 'omega-capture')
        const silent = voiceInput.createGain()
        silent.gain.value = 0
        source.connect(worklet).connect(silent).connect(voiceInput.destination)
        voiceWorklet = worklet
        worklet.port.onmessage = (packet: MessageEvent<ArrayBuffer>) => {
          if (socket.readyState !== WebSocket.OPEN || token !== voiceToken) return
          if (socket.bufferedAmount > 256 * 1024) {
            error.value = '网络拥堵，实时语音已停止，请重试'
            stopVoice()
            return
          }
          socket.send(packet.data)
        }
        voiceConnecting.value = false
        voiceConnected.value = true
      } catch (err) { if (token === voiceToken) { error.value = detail(err); stopVoice() } }
    }
    socket.onerror = () => { if (token === voiceToken && !voiceClosing.value) error.value = '实时语音网络连接失败' }
    socket.onclose = () => {
      if (voiceSocket !== socket || token !== voiceToken) return
      if (!voiceClosing.value) voiceInterrupted.value = true
      stopVoice()
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
watch(() => chosenSession.value?.id, () => {
  stopCapture(true)
  stopVoice()
  voiceInterrupted.value = false
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
watch(caseBriefInput, () => { analysisReady.value = false; reviewOpen.value = false })
onMounted(async () => {
  try {
    const status = await apiGet<{ ready: boolean; actor_id: number; role: string; realtime_configured: boolean; model_configured: boolean; worker_online: boolean }>('/api/omega/status')
    if (!status.ready) { error.value = '谈判陪练尚未就绪，请检查功能开关、模型配置和 worker，或配置百炼实时语音'; return }
    realtimeReady.value = status.realtime_configured
    textReady.value = status.model_configured && status.worker_online
    me.value = { id: status.actor_id, role: status.role }
    if (['manager', 'admin'].includes(status.role)) members.value = await apiGet('/api/omega/team-members')
    await loadLists()
    if (cases.value.length) showCase(cases.value[0]!)
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) router.replace({ path: '/login', query: { next: '/omega' } })
    else error.value = detail(err)
  } finally { loading.value = false }
})
onBeforeUnmount(() => {
  openToken++
  if (pollTimer) clearTimeout(pollTimer)
  stopCapture(true)
  stopVoice()
  window.speechSynthesis?.cancel()
})
</script>

<template>
  <AppNav />
  <main class="page omega">
    <header class="page-head omega-head">
      <div><p class="omega-kicker">训练工作台</p><h1>谈判陪练</h1><p class="sub">带着明确目标练习，逐轮复盘有据可查。</p></div>
      <div class="omega-head-meta"><span class="pill pill-muted">组内可见</span><span :class="['pill', realtimeReady ? 'pill-green' : 'pill-muted']">{{ realtimeReady ? '实时语音可用' : '实时语音未配置' }}</span></div>
    </header>
    <p v-if="demoMode" class="omega-notice" role="status"><strong>交互原型 · 模拟数据</strong>　AI 分析、文字回复、语音识别和复盘内容均为预设；麦克风音频不会上传。刷新页面会重置演示数据。</p>
    <p v-if="error" class="omega-alert" role="alert">{{ error }}</p>
    <p v-if="notice" class="omega-notice" role="status">{{ notice }}</p>
    <p v-if="loading">正在读取演练…</p>
    <div v-else class="omega-grid">
      <aside class="card omega-side" :class="{ 'is-collapsed': !mobileNavOpen }" aria-label="演练导航">
        <div class="omega-side-head"><div><p class="omega-kicker">你的工作区</p><h2>训练项目</h2></div><div class="omega-side-actions"><button class="btn btn-sm btn-ghost omega-side-toggle" type="button" :aria-expanded="mobileNavOpen" aria-controls="omega-side-tabs omega-side-body" @click="mobileNavOpen = !mobileNavOpen">{{ mobileNavOpen ? '收起列表' : '展开列表' }}</button><button class="btn btn-sm btn-primary" type="button" @click="newCase">新建任务</button></div></div>
        <div id="omega-side-tabs" class="omega-side-tabs" role="group" aria-label="列表类型">
          <button type="button" :class="{ active: sidebarTab === 'cases' }" :aria-pressed="sidebarTab === 'cases'" @click="sidebarTab = 'cases'">任务 <span>{{ cases.length }}</span></button>
          <button type="button" :class="{ active: sidebarTab === 'assignments' }" :aria-pressed="sidebarTab === 'assignments'" @click="sidebarTab = 'assignments'">指派 <span>{{ assignments.length }}</span></button>
          <button type="button" :class="{ active: sidebarTab === 'sessions' }" :aria-pressed="sidebarTab === 'sessions'" @click="sidebarTab = 'sessions'">记录 <span>{{ sessions.length }}</span></button>
        </div>
        <div id="omega-side-body" class="omega-side-body">
          <template v-if="sidebarTab === 'cases'">
            <p class="omega-list-title">谈判任务</p>
            <ul v-if="cases.length" class="omega-list"><li v-for="row in cases" :key="row.id">
              <button type="button" class="omega-link" :class="{ selected: chosenCase?.id === row.id }" :aria-current="chosenCase?.id === row.id ? 'true' : undefined" @click="showCase(row)"><strong>{{ row.title }}</strong><small>{{ row.draft_confirmed ? `目标版本 ${row.current_version}` : '待确认目标' }}</small></button>
            </li></ul>
            <p v-else class="omega-side-empty">还没有任务。先新建一个谈判目标。</p>
          </template>
          <template v-else-if="sidebarTab === 'assignments'">
            <p class="omega-list-title">待练与复练</p>
            <ul v-if="assignments.length" class="omega-list"><li v-for="row in assignments" :key="row.id">
              <button type="button" class="omega-link" :class="{ selected: chosenAssignment?.id === row.id }" :aria-current="chosenAssignment?.id === row.id ? 'true' : undefined" @click="showAssignment(row)"><strong>{{ caseName(row.case_id) }}</strong><small>{{ dimensionNames[row.target_dimension] }} · {{ row.status === 'passed' ? '已达标' : row.status === 'in_progress' ? '练习中' : '待练' }} · {{ row.attempts.length }} 次</small></button>
            </li></ul>
            <p v-else class="omega-side-empty">暂无指派练习。</p>
          </template>
          <template v-else>
            <p class="omega-list-title">最近演练</p>
            <ul v-if="sessions.length" class="omega-list"><li v-for="(row, index) in (showAllSessions ? sessions : sessions.slice(0, 5))" :key="row.id">
              <button type="button" class="omega-link" :class="{ selected: chosenSession?.id === row.id }" :aria-current="chosenSession?.id === row.id ? 'true' : undefined" @click="openSession(row.id).catch((err) => error = detail(err))"><strong>{{ caseName(row.case_id) }}</strong><small>记录 {{ index + 1 }} · {{ row.status === 'active' ? '进行中' : '已结束' }}<span v-if="row.created_at"> · {{ new Date(row.created_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }}</span></small></button>
            </li></ul>
            <button v-if="sessions.length > 5" class="omega-more" type="button" @click="showAllSessions = !showAllSessions">{{ showAllSessions ? '收起记录' : `查看全部 ${sessions.length} 条` }}</button>
            <p v-else class="omega-side-empty">还没有演练记录。</p>
          </template>
        </div>
      </aside>
      <section class="omega-main">
        <div v-if="editing" class="card pad omega-intake">
          <template v-if="!chosenCase">
            <p class="omega-kicker">新建谈判任务</p><h2>用自己的话描述这场谈判</h2>
            <p class="sub">说清楚对方是谁、要谈什么、你想达成什么，以及不能接受什么。信息不全也可以先分析。</p>
            <label for="omega-case-brief">谈判描述</label>
            <textarea id="omega-case-brief" v-model="caseBriefInput" rows="7" minlength="1" maxlength="6000" placeholder="例如：我要和经销商谈一笔到期货款。对方希望延期，我想确认书面付款时间表；最低接受先付一半，未经批准不能降价。"></textarea>
            <div class="omega-intake-actions"><span>描述会发送给已配置的 AI 模型，只生成草稿，不会自动保存。</span><button class="btn btn-primary" type="button" :disabled="analysisBusy || !caseBriefInput.trim()" @click="analyzeCaseDraft">{{ analysisBusy ? '分析中…' : analysisReady ? '重新分析' : 'AI 分析' }}</button></div>
          </template>
          <template v-else><h2>编辑任务草稿</h2><p class="sub">修改后需重新确认目标版本，既有演练仍使用原版本。</p></template>
          <section v-if="!chosenCase && analysisReady" class="omega-analysis" aria-label="AI 生成的任务草稿">
            <div class="omega-analysis-head"><div><p class="omega-kicker">AI 已整理</p><h3>核对任务草稿</h3></div><span class="pill pill-amber">尚未保存</span></div>
            <dl class="omega-analysis-summary"><div><dt>任务</dt><dd>{{ draft.title || '待补充' }}</dd></div><div><dt>双方背景</dt><dd>{{ draft.public_brief || '待补充' }}</dd></div><div><dt>对手立场</dt><dd>{{ draft.counterparty_brief || '待补充' }}</dd></div><div><dt>成功条件</dt><dd>{{ draft.goal.success_condition || '待补充' }}</dd></div><div v-if="draft.goal.outcome_type === 'payment_commitment'"><dt>目标金额 / 日期</dt><dd>{{ amountMajor || '待补充金额' }} {{ draft.goal.currency || '待补充币种' }} · {{ draft.goal.due_date || '待补充日期' }}</dd></div><div><dt>销售内部信息</dt><dd>{{ draft.seller_private || '未提供' }}</dd></div><div><dt>最低可接受结果</dt><dd>{{ draft.goal.minimum || '待补充' }}</dd></div><div><dt>硬底线</dt><dd>{{ draft.goal.hard_limits.filter(Boolean).join('；') || '待补充' }}</dd></div></dl>
            <p v-if="missingDraftFields.length" class="omega-missing" role="status">还需补充：{{ missingDraftFields.join('、') }}。可在上方补充后重新分析，或展开草稿修改。</p>
            <p v-else class="omega-review-note">请重点核对金额、日期、私有信息和底线；保存后还需确认目标版本。</p>
            <div class="omega-actions"><button class="btn btn-primary" type="button" :disabled="busy || !!missingDraftFields.length" @click="saveCase">保存草稿</button><button class="btn btn-ghost" type="button" :aria-expanded="reviewOpen" @click="reviewOpen = !reviewOpen">{{ reviewOpen ? '收起字段' : '核对并修改全部字段' }}</button></div>
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
            <div class="span-2 omega-actions"><button class="btn" type="submit" :disabled="busy || (!chosenCase && !!missingDraftFields.length)">保存草稿</button><button class="btn btn-ghost" type="button" @click="editing = false">取消</button></div>
          </form>
          </div>
        </div>
        <div v-else-if="chosenAssignment" class="card pad">
          <h2>{{ caseName(chosenAssignment.case_id) }} · {{ dimensionNames[chosenAssignment.target_dimension] }}</h2>
          <p>达标条件：该项评分达到 {{ chosenAssignment.pass_percent }}% 且有销售原话证据。</p>
          <p v-if="chosenAssignment.instructions">练习要求：{{ chosenAssignment.instructions }}</p>
          <p v-if="chosenAssignment.due_at">截止：{{ new Date(chosenAssignment.due_at).toLocaleString() }}</p>
          <p v-if="chosenAssignment.baseline">来源报告该项：{{ chosenAssignment.baseline.score }}/{{ chosenAssignment.baseline.maximum }}（{{ chosenAssignment.baseline.percent }}%）</p>
          <p v-else-if="chosenAssignment.source_report_id">来源报告该项证据不足，暂无基线分数。</p>
          <ul><li v-for="(attempt, index) in chosenAssignment.attempts" :key="attempt.session_id">
            <button type="button" class="omega-link" @click="openSession(attempt.session_id).catch((err) => error = detail(err))">第 {{ index + 1 }} 次：{{ attempt.result ? `${attempt.result.score}/${attempt.result.maximum}（${attempt.result.percent}%）` : '尚无可核验评分' }} · {{ attempt.passed ? '达标' : '待重练' }}</button>
          </li></ul>
          <button v-if="me?.id === chosenAssignment.assignee_id" class="btn" type="button" :disabled="busy" @click="startAssignment(chosenAssignment)">开始本次练习</button>
        </div>
        <div v-else-if="chosenSession" class="omega-workspace">
          <header class="card omega-session-summary">
            <div class="omega-session-heading"><div><p class="omega-kicker">{{ chosenSession.mode === 'real_review' ? (demoMode ? '模拟会议复盘样本' : '真实会议复盘') : '模拟对手演练' }} <span v-if="chosenSession.mode === 'real_review'">· {{ chosenSession.goal_timing === 'pre' ? '会前目标' : '目标时点未获会前确认' }}</span></p><h2>{{ caseName(chosenSession.case_id) }}</h2></div><span :class="['pill', chosenSession.status === 'active' ? 'pill-green' : 'pill-muted']">{{ chosenSession.status === 'active' ? '演练中' : '已结束' }}</span></div>
            <div v-if="chosenSession.case_snapshot" class="omega-goal"><span>本场目标 · 版本 {{ chosenSession.case_version }}</span><p>{{ chosenSession.case_snapshot.goal.success_condition }}</p></div>
            <p v-if="chosenSession.assignment_id" class="omega-session-note">关联指派：{{ dimensionNames[assignments.find((item) => item.id === chosenSession?.assignment_id)?.target_dimension || ''] || '定向练习' }}</p>
          </header>
          <section class="card omega-conversation" aria-labelledby="omega-conversation-title">
            <div class="omega-conversation-head"><div><p class="omega-kicker">对话实录</p><h3 id="omega-conversation-title">逐字稿</h3></div><span class="omega-turn-count">{{ (chosenSession.segments || []).length }} 条发言</span></div>
            <ol v-if="chosenSession.segments?.length" class="omega-transcript"><li v-for="part in chosenSession.segments" :key="part.id" :class="part.speaker === 'sales' ? 'is-sales' : 'is-counterparty'"><span class="omega-speaker">{{ part.speaker === 'sales' ? '销售' : '对手' }}</span><p>{{ part.text }}</p></li></ol>
            <div v-else class="omega-transcript-empty"><strong>准备好了就开始对话</strong><p>你的发言和对手回复会按顺序显示在这里。</p></div>
            <p v-if="voiceCaption" class="omega-live-caption" role="status">{{ voiceCaption }}</p>
            <div v-if="activeJob && ['queued', 'running'].includes(activeJob.status)" class="omega-responding" role="status">{{ activeJob.kind === 'turn' ? '对手正在回应…' : '报告生成中…' }}</div>
            <div v-if="!voiceConnected && chosenSession.segments?.length" class="omega-transcript-tools"><button class="btn btn-sm btn-ghost" type="button" @click="speakLastReply">播放最新回复</button></div>
          </section>
          <form v-if="chosenSession.status === 'active' && canWrite(chosenSession.owner_id)" class="card omega-practice-controls" @submit.prevent="sendTurn">
            <div v-if="realtimeReady" class="omega-voice-panel" :class="{ 'is-live': voiceConnected }">
              <div><p class="omega-kicker">实时语音</p><strong>{{ voiceConnected ? '正在对话' : voiceConnecting ? '正在连接' : '像通话一样练习' }}</strong><p role="status">{{ voiceClosing ? '正在结束实时对话…' : voiceConnecting ? '正在连接语音…' : voiceConnected ? '边说边听，可随时打断对手' : '连接后开始说话，双方原话自动保存' }}</p></div>
              <button v-if="!voiceConnected && !voiceConnecting && !voiceClosing" class="btn btn-primary omega-voice-button" type="button" :disabled="busy || !!activeJob && ['queued', 'running'].includes(activeJob.status)" @click="startVoice">{{ voiceInterrupted ? '继续实时对话' : '开始实时对话' }}</button>
              <button v-else class="btn omega-voice-button" type="button" :disabled="voiceClosing" @click="exitVoice">{{ voiceClosing ? '挂断中…' : voiceConnecting ? '取消连接' : '挂断实时对话' }}</button>
            </div>
            <p v-if="voiceInterrupted" class="omega-alert" role="alert">语音连接中断，已保存的对话仍在。点击“继续实时对话”接着练。</p>
            <div v-if="textReady" class="omega-text-panel"><label for="omega-turn">文字发言</label><textarea id="omega-turn" v-model="textInput" rows="3" maxlength="4000" required placeholder="输入你想对客户说的话…"></textarea><p v-if="voiceOriginal" class="sub">语音原转写：{{ voiceOriginal }}</p><div class="omega-actions"><button class="btn btn-primary" type="submit" :disabled="busy || asrBusy || voiceConnecting || voiceConnected || voiceClosing || !!activeJob && ['queued', 'running'].includes(activeJob.status)">发送</button><button class="btn btn-ghost" type="button" :disabled="asrBusy || voiceConnecting || voiceConnected || voiceClosing" @click="toggleRecording">{{ recording ? '停止录音' : '语音输入' }}</button></div></div>
            <p v-if="!realtimeReady && !textReady" class="omega-unavailable">当前未配置可用的语音或文字模型。</p>
            <div class="omega-session-footer"><span>结束后逐字稿将冻结，无法继续发言。</span><button class="btn btn-ghost" type="button" :disabled="busy || voiceConnecting || voiceConnected || voiceClosing" @click="finishSession">结束并冻结逐字稿</button></div>
          </form>
          <div v-if="chosenSession.status === 'ended'" class="card omega-complete-controls"><div><p class="omega-kicker">下一步</p><strong>查看本场复盘</strong><p v-if="!textReady">复盘报告需要配置文字模型和 worker。</p><p v-else>报告会引用本场逐字稿中的原话。</p></div><button v-if="canWrite(chosenSession.owner_id)" class="btn btn-primary" type="button" :disabled="!textReady || busy" @click="makeReport">生成复盘报告</button></div>
          <section v-if="report" class="card pad omega-report"><h3>复盘报告</h3>
            <p>成果：{{ report.content.outcome?.status || '未验证' }} · {{ report.content.outcome?.reason }}</p>
            <blockquote v-for="quote in report.content.outcome?.quotes || []" :key="quote.segment_id + quote.start">“{{ quote.text }}”</blockquote>
            <h4>承诺、让步与底线</h4>
            <div v-for="(items, title) in { '承诺': report.content.commitments || [], '让步代价': report.content.concession_costs || [], '底线': report.content.hard_limit_findings || [] }" :key="title">
              <strong>{{ title }}</strong><p v-if="!items.length">没有可核验的原话</p>
              <div v-for="(item, index) in items" :key="index"><p>{{ item.description || item.reason }}</p><blockquote v-for="quote in item.quotes" :key="quote.segment_id + quote.start">“{{ quote.text }}”</blockquote></div>
            </div>
            <p>评分覆盖 {{ report.content.score?.available ?? 0 }}/100；{{ report.content.score?.total === null ? '证据不足，暂无总分' : `总分 ${report.content.score?.total}` }}</p>
            <ul><li v-for="dim in report.content.dimensions || []" :key="dim.key"><strong>{{ dimensionNames[dim.key] || dim.key }}：</strong>{{ dim.score === null ? '证据不足' : dim.score }} / {{ dim.reason }}<blockquote v-for="quote in dim.quotes || []" :key="quote.segment_id + quote.start">“{{ quote.text }}”</blockquote></li></ul>
            <p v-if="report.content.next_practice"><strong>下次练习：</strong>{{ report.content.next_practice }}</p>
            <h4>主管点评</h4><p v-for="(item, index) in report.reviews" :key="index">{{ item.content.comment }} <small>{{ item.content.next_practice }}</small></p>
            <form v-if="['manager', 'admin'].includes(me?.role || '')" @submit.prevent="reviewReport"><label>点评<textarea v-model.trim="reviewText" minlength="5" required></textarea></label><label>下次练习<input v-model.trim="nextPractice"></label><button class="btn" type="submit" :disabled="busy">追加点评</button></form>
            <form v-if="['manager', 'admin'].includes(me?.role || '')" class="omega-import" @submit.prevent="createAssignment(report.id)">
              <h4>从本场证据指派练习</h4>
              <label>销售<select v-model.number="assignUserId" required><option :value="null" disabled>请选择</option><option v-for="member in members" :key="member.id" :value="member.id">{{ member.name }}</option></select></label>
              <label>目标技能<select v-model="assignDimension"><option v-for="(name, scoreKey) in dimensionNames" :key="scoreKey" :value="scoreKey">{{ name }}</option></select></label>
              <label>达标百分比<input v-model.number="assignPassPercent" type="number" min="1" max="100" required></label>
              <label>截止日期<input v-model="assignDueDate" type="date"></label>
              <label>练习要求<textarea v-model.trim="assignInstructions" maxlength="1000"></textarea></label>
              <button class="btn" type="submit" :disabled="busy">指派针对性练习</button>
            </form>
          </section>
        </div>
        <div v-else-if="chosenCase" class="card pad omega-case-detail">
          <p class="omega-kicker">谈判任务 · {{ chosenCase.draft_confirmed ? `目标版本 ${chosenCase.current_version}` : '待确认目标' }}</p>
          <h2>{{ chosenCase.title }}</h2>
          <div class="omega-case-brief"><span>双方背景</span><p>{{ chosenCase.draft.public_brief }}</p></div>
          <div class="omega-goal"><span>成功判定条件</span><p>{{ chosenCase.draft.goal.success_condition }}</p></div>
          <p v-if="!chosenCase.draft_confirmed" role="status">当前草稿尚未确认，确认后才可开始新演练或导入会议。</p>
          <div class="omega-actions"><button v-if="chosenCase.draft_confirmed" class="btn btn-primary" type="button" :disabled="busy" @click="startSession">开始新演练</button><button v-if="canWrite(chosenCase.owner_id) && !chosenCase.draft_confirmed" class="btn btn-primary" type="button" :disabled="busy" @click="confirmCase">确认目标版本</button><button v-if="canWrite(chosenCase.owner_id)" class="btn btn-ghost" type="button" @click="editCase(chosenCase)">编辑草稿</button></div>
          <details v-if="chosenCase.draft_confirmed && ['manager', 'admin'].includes(me?.role || '')" class="omega-import"><summary>指派练习</summary>
          <form @submit.prevent="createAssignment()">
            <label>销售<select v-model.number="assignUserId" required><option :value="null" disabled>请选择</option><option v-for="member in members" :key="member.id" :value="member.id">{{ member.name }}</option></select></label>
            <label>目标技能<select v-model="assignDimension"><option v-for="(name, scoreKey) in dimensionNames" :key="scoreKey" :value="scoreKey">{{ name }}</option></select></label>
            <label>达标百分比<input v-model.number="assignPassPercent" type="number" min="1" max="100" required></label>
            <label>截止日期<input v-model="assignDueDate" type="date"></label>
            <label>练习要求<textarea v-model.trim="assignInstructions" maxlength="1000"></textarea></label>
            <button class="btn" type="submit" :disabled="busy">指派销售</button>
          </form>
          </details>
          <details v-if="chosenCase.draft_confirmed" class="omega-import"><summary>导入真实会议复盘</summary>
            <p class="sub">仅导入你有 Vemory 来源权限且具备分说话人逐字稿的会议。</p>
            <label>Vemory 会议 ID<input v-model.trim="meetingId" maxlength="120"></label>
            <button class="btn btn-ghost" type="button" :disabled="busy" @click="previewMeeting">读取逐字稿</button>
            <div v-if="meetingSpeakers.length">
              <label v-for="speaker in meetingSpeakers" :key="speaker">{{ speaker }} 的身份
                <select v-model="speakerMap[speaker]"><option disabled value="">请选择</option><option value="sales">销售</option><option value="counterparty">对手</option></select>
              </label>
              <details><summary>核对来源逐字稿（{{ meetingPreview.length }} 条）</summary><p v-for="(part, index) in meetingPreview" :key="index">{{ part.speaker }}：{{ part.text }}</p></details>
              <button class="btn" type="button" :disabled="busy || meetingSpeakers.some((speaker) => !speakerMap[speaker])" @click="importMeeting">确认映射并导入</button>
            </div>
          </details>
        </div>
        <div v-else class="card pad omega-welcome"><p class="omega-kicker">开始训练</p><h2>先定目标，再练对话</h2><p>写清客户背景、成功条件和不能触碰的底线。确认目标版本后，就能开始实时演练。</p><button class="btn btn-primary" type="button" @click="newCase">新建谈判任务</button></div>
      </section>
    </div>
  </main>
  <dialog ref="voiceDialog" class="omega-call" aria-label="实时语音对话" @cancel.prevent="exitVoice">
    <div class="omega-call-shell">
      <div class="omega-call-top"><span>谈判陪练 · 实时对话</span><span>{{ chosenSession ? caseName(chosenSession.case_id) : '' }}</span></div>
      <div class="omega-call-center">
        <div class="omega-call-orb" :class="{ 'is-speaking': voiceSpeaking, 'is-connecting': voiceConnecting }" aria-hidden="true"></div>
        <h2 aria-live="polite">{{ voiceClosing ? '正在结束' : voiceConnecting ? '正在连接' : voiceSpeaking ? '对手正在说话' : '正在听' }}</h2>
        <p>{{ voiceConnecting ? '正在连接语音，请稍候' : voiceSpeaking ? '可以随时开口打断' : '直接说话，对手会实时回应' }}</p>
        <p v-if="voiceCaption" class="omega-call-caption">{{ voiceCaption }}</p>
      </div>
      <div class="omega-call-bottom">
        <label for="omega-call-volume">对手音量 <span>{{ Math.round(voiceVolume * 100) }}%</span></label>
        <input id="omega-call-volume" v-model.number="voiceVolume" type="range" min="1" max="2.5" step="0.1" aria-label="对手音量">
        <button class="btn omega-call-hangup" type="button" :disabled="voiceClosing" @click="exitVoice">{{ voiceClosing ? '结束中…' : voiceConnecting ? '取消连接' : '结束通话' }}</button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.omega { max-width: 1380px; }
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
.omega-main > .card.pad { padding: 24px; }
.omega-main h2 { margin: 0 0 12px; font-size: 20px; }
.omega-intake h2 { font-size: 24px; }
.omega-intake > .sub { max-width: 670px; margin-bottom: 24px; line-height: 1.6; }
.omega-intake > label { font-size: 13px; font-weight: 600; }
.omega-intake > textarea { min-height: 190px; padding: 16px; background: var(--card-2); line-height: 1.7; }
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
.omega-transcript-empty { display: grid; align-content: center; justify-items: center; flex: 1; padding: 56px 16px; text-align: center; }
.omega-transcript-empty strong { font-size: 15px; }
.omega-transcript-empty p { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
.omega-live-caption, .omega-responding { margin: 0 0 10px; padding: 10px 12px; border-radius: 8px; background: var(--blue-soft); color: var(--text); font-size: 13px; }
.omega-transcript-tools { display: flex; justify-content: flex-end; border-top: 1px solid var(--border); padding-top: 8px; }
.omega-practice-controls { padding: 16px 20px 12px; }
.omega-voice-panel, .omega-complete-controls { display: flex; justify-content: space-between; align-items: center; gap: 20px; }
.omega-voice-panel { padding: 6px 4px 18px; }
.omega-voice-panel strong, .omega-complete-controls strong { font-size: 17px; }
.omega-voice-panel p:not(.omega-kicker), .omega-complete-controls p:not(.omega-kicker) { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.omega-voice-panel.is-live .omega-kicker { color: var(--green); }
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
.omega-notice { color: var(--blue); background: var(--blue-soft); }
.omega-report { margin-top: 2px; }
.omega-report blockquote { margin: 4px 0 12px; padding-left: 10px; border-left: 2px solid var(--blue); color: var(--muted); }
.omega-import { margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--border); }
.omega-import > summary { cursor: pointer; font-size: 15px; font-weight: 600; }
.omega-import > form, .omega-import > p { margin-top: 16px; }
.omega-scorecard { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0 12px; border: 1px solid var(--border); border-radius: 8px; }
.omega-scorecard legend { padding: 0 8px; }
.omega-call { inset: 0; width: 100%; max-width: none; height: 100dvh; max-height: none; margin: 0; padding: 0; border: 0; background: var(--bg); color: var(--text); }
.omega-call::backdrop { background: var(--bg); }
.omega-call-shell { display: flex; flex-direction: column; min-height: 100%; padding: max(24px, env(safe-area-inset-top)) 24px max(24px, env(safe-area-inset-bottom)); }
.omega-call-top { display: flex; justify-content: space-between; gap: 16px; color: var(--muted); font-size: 13px; }
.omega-call-top span:last-child { overflow: hidden; max-width: 48%; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.omega-call-center { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; min-height: 0; text-align: center; }
.omega-call-orb { position: relative; width: clamp(152px, 42vw, 210px); aspect-ratio: 1; border-radius: 50%; background: radial-gradient(circle at 38% 30%, #9ed9ff 0, #488ed1 38%, #1a426f 72%, #122541 100%); box-shadow: 0 0 0 1px rgba(158, 217, 255, .22), 0 0 70px rgba(78, 158, 245, .25); animation: omega-breathe 3.4s ease-in-out infinite; }
.omega-call-orb::before { position: absolute; inset: -20px; border: 1px solid rgba(78, 158, 245, .18); border-radius: 50%; content: ''; }
.omega-call-orb.is-speaking { animation-duration: 1.35s; }
.omega-call-orb.is-connecting { opacity: .55; }
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
}
@media (max-width: 640px) {
  .omega-side-toggle { display: inline-flex; }
  .omega-side.is-collapsed .omega-side-tabs, .omega-side.is-collapsed .omega-side-body { display: none; }
  .omega-workspace { display: flex; flex-direction: column; }
  .omega-practice-controls, .omega-complete-controls { order: 0; }
  .omega-session-summary { order: 1; }
  .omega-conversation { order: 2; }
  .omega-report { order: 3; }
  .omega-head h1 { font-size: 25px; }
  .omega-head-meta { width: 100%; }
  .omega-main > .card.pad, .omega-session-summary, .omega-conversation, .omega-practice-controls, .omega-complete-controls { padding: 16px; }
  .omega-session-heading h2 { font-size: 20px; }
  .omega-voice-panel, .omega-complete-controls { align-items: stretch; flex-direction: column; }
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
