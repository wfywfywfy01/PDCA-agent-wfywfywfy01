import assert from 'node:assert/strict'
import test from 'node:test'
import { permissionPayload } from '../src/api/permissions.ts'

test('visual role binding sends only fields relevant to the selected role', () => {
  assert.deepEqual(permissionPayload({
    display_name: ' April ', role: 'sales', is_active: true,
    owner_key: 'april-owner', team_key: 'overseas', sales_name: 'April',
    dealer_id: 'stale-store',
  }), {
    display_name: 'April', role: 'sales', is_active: true,
    owner_key: 'april-owner', team_key: 'overseas', sales_name: 'April',
    dealer_id: '', data_scope: 'self',
  })

  assert.deepEqual(permissionPayload({
    display_name: 'Dealer', role: 'dealer', is_active: true,
    dealer_id: 'store-a', owner_key: 'stale-owner', team_key: 'stale-team', sales_name: 'stale',
  }), {
    display_name: 'Dealer', role: 'dealer', is_active: true,
    dealer_id: 'store-a', owner_key: '', team_key: '', sales_name: '', data_scope: 'self',
  })
})
