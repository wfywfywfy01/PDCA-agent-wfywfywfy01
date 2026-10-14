import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import test from 'node:test'

const html = readFileSync(new URL('../../../pdca-workbench/frontend/admin_panel.html', import.meta.url), 'utf8')
const source = html.split('function initExport(){')[1].split('// ── 待办催办 ──')[0]

test('admin sales export selects one snapshot and keeps history separate', async () => {
  const elements = Object.fromEntries([
    'exportFiveKitMonth', 'exportSalesMonth', 'exportSalesBatch',
    'dlFiveKit', 'dlSales', 'dlSalesHistory', 'salesBatchHint',
  ].map(id => [id, {
    value: '', href: '', textContent: '', attributes: {},
    addEventListener() {},
    setAttribute(name, value) { this.attributes[name] = value },
  }]))
  let empty = false
  const context = {
    API: '',
    document: {
      getElementById: id => elements[id],
      addEventListener() {},
    },
    fetch: async url => {
      const month = new URL(url, 'https://pdca.test').searchParams.get('month')
      return {
        ok: true,
        json: async () => empty
          ? { snapshot_date: null, total_wan: null }
          : { snapshot_date: `${month}-15`, total_wan: 10.5, amount_state: 'available' },
      }
    },
  }
  runInNewContext(`function initExport(){${source}`, context)
  context.initExport()
  await new Promise(resolve => setImmediate(resolve))
  const month = elements.exportSalesMonth.value
  assert.match(elements.dlSales.href, new RegExp(`month=${month}&batch_date=${month}-15`))
  assert.equal(elements.dlSalesHistory.href, `/api/export/dealer-sales?month=${month}`)

  elements.exportSalesMonth.value = '2026-09'
  context.loadSalesBatch()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(elements.exportSalesBatch.value, '2026-09-15')
  elements.exportSalesBatch.value = '2026-09-20'
  context.updateExportLinks()
  assert.match(elements.dlSales.href, /batch_date=2026-09-20$/)

  empty = true
  context.loadSalesBatch()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(elements.dlSales.href, '#')
  assert.equal(elements.dlSales.attributes['aria-disabled'], 'true')
})
