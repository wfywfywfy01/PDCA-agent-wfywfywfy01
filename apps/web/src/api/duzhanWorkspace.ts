import type { Block } from './duzhanBlocks'

export interface GroupMember {
  user_id: number
  name: string
  role?: string
}

export interface GroupOption {
  channel_id: string
  label: string
  members: GroupMember[]
  bot_joined: boolean
  available?: boolean
  reason?: string
}

export interface GroupOptionsResponse {
  error?: string
  items: GroupOption[]
  bot_app_id: string
  configured: boolean
}

export const stages = [
  { key: '早追', label: '早间提醒', defaultTime: '10:00', min: '00:00', max: '12:29' },
  { key: '中追', label: '午间轻提醒', defaultTime: '15:00', min: '12:30', max: '17:29' },
  { key: '晚追', label: '晚间核对', defaultTime: '20:00', min: '17:30', max: '23:59' },
] as const

const validTime = (value: unknown): value is string => typeof value === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value)

export function genericStarterBlocks(): Block[] {
  return [
    { type: 'group', channel_id: '', label: '' },
    { type: 'times', slots: ['10:00', '20:00'] },
    { type: 'task_policy', publisher_user_ids: [], excluded_user_ids: [] },
  ]
}

export function modeOf(blocks: Block[]): 'group_tasks' | 'business' {
  return blocks.some((block) => block.type === 'task_policy') ? 'group_tasks' : 'business'
}

export function groupSummary(blocks: Block[]): string {
  const slots = blocks.find((block) => block.type === 'times')?.slots
  const times = Array.isArray(slots) ? [...new Set(slots.filter(validTime))].sort() : []
  return `${modeOf(blocks) === 'group_tasks' ? '任务闭环' : '业务督战'} · ${times.join(' / ') || '未设提醒时间'}`
}

/** 配置本身是 JSON；JSON 深拷贝也适用于 Vue 的响应式代理。 */
export function cloneTemplate(blocks: Block[]): Block[] {
  const copy = JSON.parse(JSON.stringify(blocks)) as Block[]
  return copy.filter((block) => block.type !== 'recipient').map((block) => {
    if (block.type === 'group') return { type: 'group', channel_id: '', label: '' }
    if (block.type === 'people') return { type: 'people', names: [] }
    if (block.type === 'task_policy') return { type: 'task_policy', publisher_user_ids: [], excluded_user_ids: [] }
    if (block.type === 'style') return { ...block, title: '' }
    return block
  })
}

export function updateStageSlot(blocks: Block[], stageKey: string, value: string | null): Block[] {
  const stage = stages.find((item) => item.key === stageKey)
  if (!stage) throw new Error('未知提醒阶段')
  if (value !== null && !validTime(value)) throw new Error('请输入有效的 24 小时时间，例如 09:30。')
  if (value !== null && (value < stage.min || value > stage.max)) {
    throw new Error(`${stage.label}时间须在 ${stage.min} 至 ${stage.max} 之间。`)
  }
  const copy = JSON.parse(JSON.stringify(blocks)) as Block[]
  let times = copy.find((block) => block.type === 'times')
  if (!times) {
    times = { type: 'times', slots: [] }
    copy.push(times)
  }
  const slots: unknown[] = Array.isArray(times.slots) ? times.slots : []
  const remaining = slots.filter((slot) => !validTime(slot) || slot < stage.min || slot > stage.max)
  times.slots = [...new Set(value === null ? remaining : [...remaining, value])].sort()
  return copy
}
