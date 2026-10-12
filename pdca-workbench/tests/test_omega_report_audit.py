"""Semantic publication must cover every final claim, not just quote offsets."""
import copy
import json
import unittest

from app.omega import report_audit
from app.omega.reports import WEIGHTS, validate_report


class ReportAuditTests(unittest.TestCase):
    def setUp(self):
        self.parts = [
            {'id': 'seller', 'speaker': 'sales', 'speaker_id': 'sales',
             'text': '我建议先给您书面风险方案，再确认首单。'},
            {'id': 'buyer', 'speaker': 'counterparty', 'speaker_id': 'buyer',
             'text': '没有书面兜底，我不会下单，也不会给库存数据。'},
        ]
        quote = {'segment_id': 'seller', 'speaker': 'sales', 'start': 0,
                 'end': len(self.parts[0]['text']), 'text': self.parts[0]['text']}
        self.report = validate_report(json.dumps({
            'outcome': {'status': 'not_achieved', 'reason': '客户未承诺首单', 'quotes': []},
            'dimensions': [{'key': key, 'score': 1, 'reason': '仅提出下一步', 'quotes': [quote]}
                           for key in WEIGHTS],
            'commitments': [], 'concession_costs': [], 'hard_limit_findings': [],
            'next_practice': '先问客户书面兜底必须包含哪些条件，再准备待审批方案。',
        }, ensure_ascii=False), self.parts)

    def response(self):
        return {'checks': [{'path': path, 'verdict': 'supported',
                            'reason': '销售提出建议；客户明确拒绝，未把提议当承诺。',
                            'segment_ids': ['seller', 'buyer']}
                           for path in report_audit.claims(self.report)]}

    def test_invented_approval_is_rejected_despite_exact_quote(self):
        self.report['outcome'].update(status='achieved', reason='客户已同意首单',
                                     quotes=self.report['dimensions'][0]['quotes'])
        response = self.response()
        response['checks'][0].update(verdict='unsupported', reason='客户明确拒绝下单。')
        with self.assertRaisesRegex(ValueError, '报告语义复核未通过'):
            report_audit.validate(json.dumps(response), self.report, self.parts)

    def test_missing_duplicate_unknown_or_uncertain_field_fails_closed(self):
        complete = self.response()
        for mutation in ('missing', 'duplicate', 'unknown', 'uncertain', 'unknown_source'):
            response = copy.deepcopy(complete)
            if mutation == 'missing': response['checks'].pop()
            if mutation == 'duplicate': response['checks'].append(response['checks'][0])
            if mutation == 'unknown': response['checks'][0]['path'] = 'made_up'
            if mutation == 'uncertain': response['checks'][0]['verdict'] = 'uncertain'
            if mutation == 'unknown_source': response['checks'][0]['segment_ids'] = ['invented']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                report_audit.validate(json.dumps(response), self.report, self.parts)

    def test_final_practice_and_fact_items_are_all_covered(self):
        quote = self.report['dimensions'][0]['quotes'][0]
        self.report['commitments'] = [{'text': '销售建议准备书面方案', 'quotes': [quote]}]
        paths = report_audit.claims(self.report)
        self.assertIn('next_practice', paths)
        self.assertIn('commitments.0', paths)
        audit = report_audit.validate(json.dumps(self.response()), self.report, self.parts)
        self.assertEqual(len(audit['checks']), len(paths))
        self.assertEqual(len(audit['report_sha256']), 64)
        self.assertEqual(len(audit['transcript_sha256']), 64)

    def test_auditor_sees_actual_scores_and_rubric_limits(self):
        before = report_audit.claims(self.report)['dimensions.relationship']
        changed = copy.deepcopy(self.report)
        changed['dimensions'][-2]['score'] = WEIGHTS['relationship']
        after = report_audit.claims(changed)['dimensions.relationship']
        self.assertEqual(before['score'], 1)
        self.assertEqual(before['max_score'], WEIGHTS['relationship'])
        self.assertNotEqual(before, after)

    def test_duplicate_json_members_cannot_hide_rejected_checks(self):
        good = json.dumps(self.response())
        bad = '{"checks":[{"verdict":"unsupported"}],' + good[1:]
        with self.assertRaisesRegex(ValueError, '报告语义复核未通过'):
            report_audit.validate(bad, self.report, self.parts)
        nested = good.replace('"verdict": "supported"',
                              '"verdict":"unsupported","verdict":"supported"', 1)
        with self.assertRaises(ValueError):
            report_audit.validate(nested, self.report, self.parts)

    def test_prompt_requires_speaker_attribution_and_refusal_prerequisites(self):
        messages = report_audit.messages({'goal': {'type': 'new_order'}}, self.parts, self.report)
        prompt = messages[0]['content']
        for term in ('sales', 'speaker_id', '拒绝', '前提', 'next_practice', 'unsupported'):
            self.assertIn(term, prompt)
        data = json.loads(messages[-1]['content'])
        self.assertEqual(data['transcript'], self.parts)
        self.assertEqual(data['claims']['next_practice'], self.report['next_practice'])


if __name__ == '__main__':
    unittest.main()
