import assert from 'node:assert/strict'
import test from 'node:test'
import { cloneTemplate, genericStarterBlocks, groupSummary, modeOf, stages, updateStageSlot } from '../src/api/duzhanWorkspace.ts'
import { timeStage } from '../src/api/duzhanBlocks.ts'

test('通用模板没有群或人员绑定；每次创建都是独立草稿', () => {
  const first = genericStarterBlocks()
  const second = genericStarterBlocks()
  assert.equal(modeOf(first), 'group_tasks')
  assert.deepEqual(first, [
    { type: 'group', channel_id: '', label: '' },
    { type: 'times', slots: ['10:00', '20:00'] },
    { type: 'task_policy', publisher_user_ids: [], excluded_user_ids: [] },
  ])
  first[1].slots.push('15:00')
  first[2].excluded_user_ids.push(123)
  assert.deepEqual(second[1].slots, ['10:00', '20:00'])
  assert.deepEqual(second[2].excluded_user_ids, [])
})

test('复制规则清除群与人员范围，保留时间及条件，且不修改来源', () => {
  const source = [
    { type: 'group', channel_id: 'previous-group', label: '原群' },
    { type: 'times', slots: ['09:30', '20:30'] },
    { type: 'people', names: ['原成员'] },
    { type: 'task_policy', publisher_user_ids: [12], excluded_user_ids: [34] },
    { type: 'recipient', kind: 'user', id: '56' },
    { type: 'condition', key: 'workday', value: true },
    { type: 'style', lang: 'zh', title: '原群标题', footer: '请提供提交证据' },
  ]
  const original = structuredClone(source)
  const copy = cloneTemplate(source)
  assert.deepEqual(copy.find((item) => item.type === 'group'), { type: 'group', channel_id: '', label: '' })
  assert.deepEqual(copy.find((item) => item.type === 'people').names, [])
  assert.deepEqual(copy.find((item) => item.type === 'task_policy'), {
    type: 'task_policy', publisher_user_ids: [], excluded_user_ids: [],
  })
  assert.equal(copy.some((item) => item.type === 'recipient'), false)
  assert.equal(copy.find((item) => item.type === 'style').title, '')
  assert.equal(copy.find((item) => item.type === 'style').footer, '请提供提交证据')
  assert.deepEqual(copy.find((item) => item.type === 'condition'), { type: 'condition', key: 'workday', value: true })
  copy.find((item) => item.type === 'times').slots.push('14:00')
  assert.deepEqual(source, original)
})

test('摘要区分任务与业务模式，缺失或坏时段不会冒充已配置', () => {
  assert.equal(modeOf([{ type: 'group' }]), 'business')
  assert.equal(groupSummary(genericStarterBlocks()), '任务闭环 · 10:00 / 20:00')
  assert.equal(groupSummary([{ type: 'times', slots: ['25:00', 15, ''] }]), '业务督战 · 未设提醒时间')
  assert.equal(groupSummary([{ type: 'times', slots: ['20:00', '09:30', '20:00'] }]), '业务督战 · 09:30 / 20:00')
})

test('编辑阶段只修改该阶段，禁用后可恢复，原始卡片不变', () => {
  const original = genericStarterBlocks()
  const changed = updateStageSlot(original, '早追', '09:30')
  assert.deepEqual(changed.find((item) => item.type === 'times').slots, ['09:30', '20:00'])
  assert.deepEqual(original.find((item) => item.type === 'times').slots, ['10:00', '20:00'])
  const noon = updateStageSlot(changed, '中追', '15:00')
  assert.deepEqual(noon.find((item) => item.type === 'times').slots, ['09:30', '15:00', '20:00'])
  const disabled = updateStageSlot(noon, '晚追', null)
  assert.deepEqual(disabled.find((item) => item.type === 'times').slots, ['09:30', '15:00'])
  assert.deepEqual(updateStageSlot([], '早追', '10:00'), [{ type: 'times', slots: ['10:00'] }])
})

test('阶段边界与现有运行规则一致，错阶段和非法时间明确拒绝', () => {
  for (const stage of stages) {
    assert.equal(timeStage(stage.min), stage.key)
    assert.equal(timeStage(stage.max), stage.key)
    assert.equal(timeStage(stage.defaultTime), stage.key)
  }
  assert.throws(() => updateStageSlot(genericStarterBlocks(), '早追', '20:00'), /早间/)
  assert.throws(() => updateStageSlot(genericStarterBlocks(), '晚追', '17:29'), /晚间/)
  assert.throws(() => updateStageSlot(genericStarterBlocks(), '早追', '9:30'), /24 小时/)
  assert.throws(() => updateStageSlot(genericStarterBlocks(), '早追', '24:00'), /24 小时/)
  assert.throws(() => updateStageSlot(genericStarterBlocks(), '未知', null), /阶段/)
})
