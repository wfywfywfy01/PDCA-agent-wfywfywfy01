export type Usage = 'training' | 'rehearsal' | 'real_review'
export type Participant = {
  id: string; name: string; role: string; is_primary: boolean; concerns: string[];
  known_facts: string[]; decision_authority: string; voice_id?: string
}
export type TemplateDraft = {
  title: string; kind?: string; usage?: Usage; meeting_type?: string; stage_summary?: string;
  simulation?: boolean; public_brief: string; seller_private: string; counterparty_brief: string;
  buyer_name?: string; buyer_role?: string; buyer_company?: string; buyer_emotion?: string;
  buyer_objections?: string[]; dealer_id?: string; opportunity_id?: string | null;
  participants?: Participant[]; score_weights?: Record<string, number>;
  goal: { outcome_type: string; success_condition: string; ideal: string; minimum: string;
    hard_limits: string[]; amount_minor: number | null; currency: string | null; due_date: string | null }
}
export type TemplateRow = { id: string; title: string; current_version: number; owner_id: number; case_version_id?: string; available_usages?: Usage[]; draft: TemplateDraft }
export type TemplateStart = { case_id: string; case_version_id: string; session_id: string | null; next_action: 'practice' | 'import_meeting' }
export const usageNames: Record<Usage, string> = { training: '新人培训', rehearsal: '会前演练', real_review: '会后复盘' }
export const meetingNames: Record<string, string> = { introduction: '首次触达', discovery: '需求沟通', proposal: '方案介绍', negotiation: '条件博弈', order: '推进拿单' }
