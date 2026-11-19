import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from app import dealer_whatsapp_daily as daily
from app.dealer_whatsapp_daily import product_of, select_samples, validate_score


class DailyTests(unittest.TestCase):
    def test_existing_message_prevents_collection_and_send(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'PDCA_DEALER_DAILY_DIR': directory}), \
                patch.object(daily, 'history', return_value=[{'idempotency_key': 'dealer-whatsapp-script-daily:2026-11-19'}]), \
                patch.object(daily, 'collect') as collect, patch.object(daily, 'cli') as cli:
            self.assertEqual(daily.run(send=True, day='2026-11-19')['status'], 'already_sent')
            collect.assert_not_called()
            cli.assert_not_called()

    def test_no_marker_disables_job(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'PDCA_DEALER_DAILY_DIR': directory}), \
                patch.object(daily, 'run') as run:
            daily.scheduled_job()
            run.assert_not_called()

    def test_pagination_requires_explicit_terminal_page(self):
        first = {'rows': [{'id': 'a'}], 'pagination': {'has_more': True, 'next_page': 2}}
        last = {'rows': [{'id': 'b'}], 'pagination': {'has_more': False}}
        with patch.object(daily, 'mcp', side_effect=[first, last]) as mcp:
            self.assertEqual(len(daily.pages({}, [])), 2)
            self.assertEqual(mcp.call_args.args[1]['filters']['page'], 2)
        with patch.object(daily, 'mcp', return_value={'rows': [], 'pagination': {}}):
            with self.assertRaises(RuntimeError):
                daily.pages({}, [])

    def test_delivery_requires_history_and_keeps_same_key(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(daily, 'cli', return_value={'message': {'id': 'm'}}) as cli, \
                patch.object(daily, 'history', return_value=[]):
            p = Path(directory) / 'day.txt'
            p.write_text('正文', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                daily.deliver('2026-11-19', 'same-key', '正文', p, p.with_suffix('.json'), {})
            self.assertIn('same-key', cli.call_args.args)
            self.assertIn(daily.CHANNEL, cli.call_args.args)

    def test_product_boundary(self):
        dual = 'Agent Watch and Signature S Agent'
        self.assertEqual(product_of(dual, 'Agent Watch'), 'Agent Watch')
        self.assertEqual(product_of(dual, 'Signature Agent'), 'Signature Agent')
        self.assertIsNone(product_of('Signature is classic. Our agent will call.'))
        self.assertIsNone(product_of('Agent Q and mechanical watch'))
        self.assertEqual(product_of('new Signature S Agent'), 'Signature Agent')
        self.assertEqual(product_of('third AI generation watch'), 'Agent Watch')

    def test_selection_excludes_ai_recall_and_duplicates(self):
        base = dict(account_id='a', direction='outbound', reply_source='human',
                    message_kind='text', content='Agent Watch', time='2026-11-18 10:00:00')
        rows = [dict(base, id='1'), dict(base, id='2'),
                dict(base, id='3', reply_source='ai'), dict(base, id='4', is_recalled=True)]
        self.assertEqual(len(select_samples(rows)['a']), 1)

    def test_scores_require_verbatim_evidence(self):
        sample = {'id': '1', 'content': 'Agent Watch for your store'}
        good = {'parts': [{'score': 10, 'message_id': '1', 'quote': 'your store', 'reason': '渠道'}]*4,
                'advice': '补演示时间'}
        self.assertEqual(validate_score(good, [sample]), 40)
        good['parts'][0] = dict(good['parts'][0], quote='invented')
        with self.assertRaises(ValueError):
            validate_score(good, [sample])


if __name__ == '__main__':
    unittest.main()
