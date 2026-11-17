/**
 * 督战官子 Agent 配置 API。
 * 后端契约见 pdca-workbench/app/duzhan_admin/router.py。
 */
import { apiGet, apiPost, apiPut, apiRequest } from '@/api/client'
import type { GroupOptionsResponse } from '@/api/duzhanWorkspace'
import type { Block, BlockTypeSpec, BlocksPayload } from '@/api/duzhanBlocks'

export type { Block, BlockTypeSpec, BlockFieldSpec, BlocksPayload } from '@/api/duzhanBlocks'
export {
  addBlock, agentPayload, blockPositions, blockSummary, configChanged, defaultBlock, fieldVisible,
  fromJson, moveBlock, nameForSelectedGroup, removeBlock, toJson, updateBlockField,
  starterBlocks,
} from '@/api/duzhanBlocks'

export interface DuzhanAgentItem {
  id: number
  name: string
  enabled: boolean
  timezone: string
  note: string
  blocks: BlocksPayload
  errors: string[]
  renderer: string
  updated_at: string
}

export interface DuzhanRuntimeStatus {
  group_tasks_enabled?: boolean
  group_tasks_schedule_live?: boolean
  source: 'code' | 'db'
  enabled: boolean
  ctob_enabled: boolean
  bot_app_id: string
  supported_channel_ids: string[]
  department_rosters?: Record<string, string[]>
  department_task_only_rosters?: Record<string, string[]>
  schedule_updates_require_restart: boolean
}

export interface PreviewResult {
  agent: { id: number | null; name: string; enabled: boolean }
  day: string | null
  hour: number | null
  slot?: string | null
  errors: string[]
  spec: Record<string, unknown>
  summary: string[]
  note: string
}

export interface AgentInput {
  name: string
  timezone: string
  note: string
  enabled?: boolean
  blocks: Block[]
}

export function listAgents(): Promise<{ items: DuzhanAgentItem[] }> {
  return apiGet('/api/duzhan-agents')
}

export function blockSchema(): Promise<{ blocks: BlockTypeSpec[] }> {
  return apiGet('/api/duzhan-agents/block-schema')
}

export function runtimeStatus(): Promise<DuzhanRuntimeStatus> {
  return apiGet('/api/duzhan-agents/runtime-status')
}

export function createAgent(input: AgentInput): Promise<DuzhanAgentItem> {
  return apiPost('/api/duzhan-agents', input)
}

export function updateAgent(id: number, input: AgentInput): Promise<DuzhanAgentItem> {
  return apiPut('/api/duzhan-agents/' + id, input)
}

export interface MonthlyMetrics {
  channel_id: string
  month: string
  goal: 'amount' | 'break_zero'
  sales_target_wan: number | null
  mto_daily_count: number
  mto_min_wan: number
  version: number
  source: 'saved' | 'bundled' | 'unset'
  updated_at: string | null
}

interface MonthlyMetricsResult { metrics: MonthlyMetrics; saved_months: string[] }

export function getMonthlyMetrics(channelId: string, month: string): Promise<MonthlyMetricsResult> {
  return apiGet('/api/duzhan-agents/monthly-metrics?' + new URLSearchParams({ channel_id: channelId, month }))
}

export function putMonthlyMetrics(input: MonthlyMetrics): Promise<MonthlyMetricsResult> {
  return apiPut('/api/duzhan-agents/monthly-metrics', input)
}

export function toggleAgent(id: number, enabled: boolean): Promise<DuzhanAgentItem> {
  return apiPost('/api/duzhan-agents/' + id + '/toggle', { enabled })
}

/** 内容试跑：用已有快照台账和当前卡片重新渲染，不发送。 */
export interface RenderPreviewResult {
  mode: 'render'
  ok: boolean
  error?: string
  agent?: { id: number | null; name: string; enabled: boolean }
  day?: string | null
  hour?: number | null
  slot?: string | null
  timezone?: string
  channel_id?: string
  group?: string
  renderer?: string
  source?: 'snapshot' | 'snapshot_ledger' | 'empty_ledger'
  send_allowed?: boolean
  send_reason?: string
  message_count?: number
  chars?: number
  body?: string
  note?: string
}

export type PreviewMode = 'structure' | 'render'

export function previewAgent(
  id: number,
  day?: string,
  slot?: string,
  mode: PreviewMode = 'structure',
): Promise<PreviewResult | RenderPreviewResult> {
  return apiPost('/api/duzhan-agents/' + id + '/preview', { day, slot, mode })
}

export interface AiStatus {
  day: string
  calls: number
  cached: number
  limit: number
}

/** AI 规则今天的用量（调用次数 / 缓存条数 / 上限）。 */
export function aiStatus(): Promise<AiStatus> {
  return apiGet('/api/duzhan-agents/ai-status')
}

export function seedFromCode(): Promise<{ created: DuzhanAgentItem[]; skipped: string[] }> {
  return apiPost('/api/duzhan-agents/seed-from-code', {})
}

export async function deleteAgent(id: number): Promise<{ deleted: number }> {
  const response = await apiRequest('/api/duzhan-agents/' + id, { method: 'DELETE', credentials: 'include' })
  return (await response.json()) as { deleted: number }
}

/** 固定督战机器人可读取的 VPS 群与成员。 */
export function groupOptions(): Promise<GroupOptionsResponse> {
  return apiGet('/api/duzhan-agents/group-options')
}

interface AcquisitionOwner { owner_user_id: number; owner_name: string | null }
interface AcquisitionCounts { records: number; unaccepted: number; no_progress: number; overdue: number; missing_due: number }
export interface AcquisitionQueue {
  source_tasks?: {
    as_of: string; total: number; has_more: boolean; totals: AcquisitionCounts
    by_owner: (AcquisitionOwner & AcquisitionCounts)[]
    items: (AcquisitionOwner & {
      task_id: number; display_name: string | null; route: string; source_system: string; stage: string
      customer_stage: string | null; customer_stage_status: string; accepted_at: string | null
      last_progress_at: string | null; next_action?: string | null; next_due_at: string | null
      overdue: boolean | null; pending_reply: boolean; reply_processing: boolean; stored_outreach_hold: boolean
    })[]
  }
  owner_pending_replies?: { total: number; has_more: boolean; items: (AcquisitionOwner & { id: number; occurred_at: string | null; status: string })[] }
}
export function acquisitionQueue(sourceOffset = 0, replyOffset = 0): Promise<AcquisitionQueue> {
  return apiGet('/api/duzhan-agents/acquisition-queue?' + new URLSearchParams({ source_offset: String(sourceOffset), reply_offset: String(replyOffset) }))
}
