export type Usage = 'training' | 'rehearsal' | 'real_review'
export type Participant = {
  id: string; name: string; role: string; is_primary: boolean; concerns: string[];
  known_facts: string[]; decision_authority: string; voice_id?: string
}
export type MeetingMaterial = { name: string; purpose: 'reference' | 'content' | 'topic';
  visibility: 'shared' | 'coach'; text: string; truncated: boolean }
export type TemplateDraft = {
  title: string; kind?: string; usage?: Usage; meeting_type?: string; stage_summary?: string;
  meeting_topic?: string; meeting_materials?: MeetingMaterial[];
  simulation?: boolean; public_brief: string; seller_private: string; counterparty_brief: string;
  buyer_name?: string; buyer_role?: string; buyer_company?: string; buyer_emotion?: string;
  buyer_objections?: string[]; dealer_id?: string; opportunity_id?: string | null;
  participants?: Participant[]; score_weights?: Record<string, number>;
  goal: { outcome_type: string; success_condition: string; ideal: string; minimum: string;
    hard_limits: string[]; amount_minor: number | null; currency: string | null; due_date: string | null }
}
export type TemplateRow = { id: string; title: string; current_version: number; owner_id: number; case_version_id?: string; available_usages?: Usage[];
  card_group?: string; material_hint?: string; suggested_topics?: string[]; draft: TemplateDraft }
export type TemplateStart = { case_id: string; case_version_id: string | null; session_id: string | null; next_action: 'practice' | 'import_meeting' | 'review_case' }
export const usageNames: Record<Usage, string> = { training: '模拟练习', rehearsal: '会前演练', real_review: '会后复盘' }
export const meetingNames: Record<string, string> = {
  introduction: '破冰了解', discovery: '需求沟通', proposal: '方案推进', negotiation: '条件博弈', order: '试单推进',
  enablement: '合作培训', retail_training: '终销培训', marketing_support: '营销支持', product_launch: '新品培训',
  store_weekly: '店铺周会', store_monthly: '店铺月会', custom: '临时会议', store_opening: '开店准备',
  reorder: '补货复购', aftersales: '售后协调',
}
