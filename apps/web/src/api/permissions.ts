export type UserRole = 'viewer' | 'dealer' | 'sales' | 'manager' | 'admin'

export interface PermissionForm {
  display_name: string
  role: UserRole
  is_active: boolean
  dealer_id: string
  owner_key: string
  team_key: string
  sales_name: string
}

const ROLE_SCOPE: Record<UserRole, string> = {
  viewer: 'none', dealer: 'self', sales: 'self', manager: 'team', admin: 'all',
}

export function permissionPayload(form: PermissionForm) {
  return {
    display_name: form.display_name.trim(),
    role: form.role,
    is_active: form.is_active,
    dealer_id: form.role === 'dealer' ? form.dealer_id : '',
    owner_key: form.role === 'sales' ? form.owner_key : '',
    team_key: ['sales', 'manager'].includes(form.role) ? form.team_key : '',
    sales_name: form.role === 'sales' ? form.sales_name.trim() : '',
    data_scope: ROLE_SCOPE[form.role],
  }
}
