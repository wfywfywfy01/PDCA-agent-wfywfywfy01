/**
 * Agent 管理后台 API：IM 机器人与 PDCA 智能体。
 * 后端契约见 pdca-workbench/app/agent_admin/router.py。
 */
import { apiGet, apiPatch, apiPost } from '@/api/client'

export interface ImBot {
  id: string
  app_id: string
  name: string
  description: string
  avatar_display_url: string | null
  avatar_signed_url?: string | null
  webhook_url: string
  agent_enabled: boolean
  agent_provider: string
  agent_model: string
  is_public: boolean
  owned_by_me: boolean
  active: boolean
  last_used_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface BotChannel {
  bot_app_id?: string
  app_id?: string
  bot_key?: string
  channel_id: string
  channel_name?: string
  channel_type?: string
  joined_at?: string
  [key: string]: unknown
}

export interface PdcaAgent {
  key: string
  name: string
  role: string
  outputs: string[]
  status: 'active' | 'planned'
  model_task: string
  hermes_profile_linked: boolean
}

export interface HermesProfile {
  name: string
  path: string
  soul_exists: boolean
  env_exists: boolean
}

export interface ModelRoutingRow {
  task: string
  label: string
  provider: string
  model: string
  configured: boolean
  default_note: string
}

export interface PdcaAgentsPayload {
  agents: PdcaAgent[]
  hermes_profiles_root: string | null
  hermes_profiles: HermesProfile[]
  model_routing: ModelRoutingRow[]
  fetched_at: string
}

export interface BotsPayload {
  items: ImBot[]
  fetched_at: string
}

export interface ChannelsPayload {
  items: BotChannel[]
  fetched_at: string
}

export interface BotCreatePayload {
  name: string
  bot_key?: string
  description?: string
  webhook_url?: string
  public?: boolean
}

export interface BotCreateResult {
  ok: boolean
  result: unknown
}

export interface BotVisibilityResult {
  ok: boolean
  public: boolean
  result: unknown
}

export function fetchBots(): Promise<BotsPayload> {
  return apiGet('/api/agent-admin/bots')
}

export function fetchBotChannels(): Promise<ChannelsPayload> {
  return apiGet('/api/agent-admin/bot-channels')
}

export function createBot(payload: BotCreatePayload): Promise<BotCreateResult> {
  return apiPost('/api/agent-admin/bots', payload)
}

export function setBotVisibility(appId: string, isPublic: boolean): Promise<BotVisibilityResult> {
  return apiPatch('/api/agent-admin/bots/' + encodeURIComponent(appId) + '/visibility', { public: isPublic })
}

export function fetchPdcaAgents(): Promise<PdcaAgentsPayload> {
  return apiGet('/api/agent-admin/pdca-agents')
}
