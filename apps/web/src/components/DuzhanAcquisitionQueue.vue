<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { acquisitionQueue, type AcquisitionQueue } from '@/api/duzhanAgents'

const data = ref<AcquisitionQueue | null>(null)
const busy = ref(false)
const error = ref('')
const offset = ref(0)
const replyOffset = ref(0)
let timer: ReturnType<typeof setInterval> | undefined
let disposed = false
const time = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '未记录'
const stages: Record<string, string> = { in_progress: '核验中', meeting: '已约会议', proposal: '已提案', blocked: '遇到阻碍', assigned: '已分配', accepted: '已接收', researching: '核验中', contacted: '已联系', replied: '已回复', qualified: '已确认意向', negotiating: '洽谈中', won: '已成交', lost: '已流失', completed: '已完成', pending: '待处理', new: '新线索' }
const routes: Record<string, string> = { local_list: '本地名单库', historical_reactivation: '历史老客激活', consumer_to_dealer: '消费者转代理', benchmark_channel: '高端品牌渠道', partner_site: '全球代理招募网站', paid_ads: '全球广告投放', country_manager_bd: '国家经理与 BD' }
async function load(sourceOffset = offset.value, pendingOffset = replyOffset.value) {
  if (busy.value) return
  busy.value = true
  try {
    const result = await acquisitionQueue(sourceOffset, pendingOffset)
    if (disposed) return
    data.value = result; offset.value = sourceOffset; replyOffset.value = pendingOffset; error.value = ''
  } catch (err) {
    if (!disposed) error.value = err instanceof Error ? err.message : '获客数据读取失败'
  } finally { busy.value = false }
}
function refreshVisible() { if (!document.hidden) void load() }
onMounted(() => { void load(); timer = setInterval(refreshVisible, 60000); document.addEventListener('visibilitychange', refreshVisible) })
onBeforeUnmount(() => { disposed = true; clearInterval(timer); document.removeEventListener('visibilitychange', refreshVisible) })
</script>

<template>
  <section class="acquisition" aria-labelledby="acquisition-heading" :aria-busy="busy">
    <header><div><h2 id="acquisition-heading">获客线索跟进</h2><p>按线索任务统计；群内回复自动回写。接单不等于已经联系客户。</p></div><button class="btn" :disabled="busy" @click="load()">{{ busy ? '读取中…' : '刷新' }}</button></header>
    <p v-if="error" role="alert" class="queue-error">{{ error }}{{ data ? '；下方为上次成功读取的数据。' : '；数据暂不可用。' }}</p>
    <template v-if="data?.source_tasks">
      <p class="queue-time">数据时间 {{ time(data.source_tasks.as_of) }}（北京时间）</p>
      <div class="queue-stats"><span>线索任务 <b>{{ data.source_tasks.total }}</b></span><span>未接收 <b>{{ data.source_tasks.totals.unaccepted }}</b></span><span>无进展记录 <b>{{ data.source_tasks.totals.no_progress }}</b></span><span>逾期 <b>{{ data.source_tasks.totals.overdue }}</b></span><span>缺截止时间 <b>{{ data.source_tasks.totals.missing_due }}</b></span></div>
      <p class="queue-owners"><span v-for="owner in data.source_tasks.by_owner" :key="owner.owner_user_id">{{ owner.owner_name || '负责人 ' + owner.owner_user_id }}：{{ owner.records }} 条，逾期 {{ owner.overdue }} 条</span></p>
      <div class="queue-scroll" tabindex="0" aria-label="线索跟进表，可横向滚动"><table><thead><tr><th>线索 / 来源</th><th>负责人 / 接单</th><th>线索阶段 / 客户阶段</th><th>下一步 / 截止时间</th><th>跟进情况</th></tr></thead><tbody>
        <tr v-for="item in data.source_tasks.items" :key="item.task_id" :class="{ overdue: item.overdue }">
          <td><strong>#{{ item.task_id }} {{ item.display_name || '未命名线索' }}</strong><small>{{ routes[item.route] || item.route }} · {{ item.source_system }}</small><small v-if="item.stored_outreach_hold" class="queue-error">暂停触达，先核验</small></td>
          <td>{{ item.owner_name || '负责人 ' + item.owner_user_id }}<small>{{ item.accepted_at ? '已接收 ' + time(item.accepted_at) : '尚未接收' }}</small></td>
          <td>{{ stages[item.stage] || item.stage }}<small>{{ item.customer_stage ? '客户：' + (stages[item.customer_stage] || item.customer_stage) : item.customer_stage_status === 'unlinked' ? '尚未关联公司' : '客户阶段未记录' }}</small></td>
          <td>{{ item.next_action || '下一步未记录' }}<small>{{ time(item.next_due_at) }}</small><strong v-if="item.overdue" class="queue-error">已逾期</strong></td>
          <td>{{ item.last_progress_at ? time(item.last_progress_at) : '尚无进展记录' }}<small v-if="item.pending_reply">有待核对的群回复</small><small v-if="item.reply_processing">群回复处理中</small></td>
        </tr>
      </tbody></table></div>
      <p v-if="!data.source_tasks.total">当前授权范围没有线索任务。</p>
      <nav aria-label="线索分页"><button class="btn" :disabled="busy || offset === 0" @click="load(Math.max(0, offset - 100))">上一页</button><span>第 {{ Math.floor(offset / 100) + 1 }} 页 · 共 {{ data.source_tasks.total }} 条</span><button class="btn" :disabled="busy || !data.source_tasks.has_more" @click="load(offset + 100)">下一页</button></nav>
    </template>
    <p v-else-if="data">上游暂未提供线索任务数据。</p>
    <section v-if="data?.owner_pending_replies?.total" class="pending-replies"><h3>待补线索编号的群回复（{{ data.owner_pending_replies.total }} 条消息）</h3><p>这些回复尚未归入具体线索，不计作客户进展。</p><ul><li v-for="reply in data.owner_pending_replies.items" :key="reply.id">{{ reply.owner_name || '负责人 ' + reply.owner_user_id }} · {{ time(reply.occurred_at) }} · {{ reply.status === 'received' ? '处理中' : '请在原群引用派单，并补充唯一线索编号' }}</li></ul><nav aria-label="群回复分页"><button class="btn" :disabled="busy || replyOffset === 0" @click="load(offset, Math.max(0, replyOffset - 100))">上一页</button><button class="btn" :disabled="busy || !data.owner_pending_replies.has_more" @click="load(offset, replyOffset + 100)">下一页</button></nav></section>
  </section>
</template>

<style scoped>
.acquisition{margin:1.25rem 0;padding:1.25rem;background:var(--surface,#fff);border:1px solid var(--border,#deded8);border-radius:16px}.acquisition header,.acquisition nav,.queue-stats,.queue-owners{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}.acquisition h2{margin:0}.acquisition p{color:var(--muted,#626660)}.queue-stats{justify-content:flex-start}.queue-stats span{padding:.7rem 1rem;background:#f3f5f1;border-radius:8px}.queue-stats b{margin-left:.4rem}.queue-owners{justify-content:flex-start}.queue-scroll{overflow-x:auto}.acquisition table{width:100%;border-collapse:collapse;text-align:left;min-width:780px}.acquisition th,.acquisition td{padding:.8rem;border-bottom:1px solid #e3e6df;vertical-align:top}.acquisition th{font-size:.85rem;color:#545c54}.acquisition small{display:block;margin-top:.35rem;color:#626660}.acquisition nav{justify-content:flex-end;margin-top:1rem}.queue-error{color:#a32929!important}.overdue{background:#fff6f2}.pending-replies{border-top:1px solid #deded8;margin-top:1rem}.queue-time{font-size:.85rem}
</style>
