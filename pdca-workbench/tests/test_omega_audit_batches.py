"""Audit every original slot in small groups before accepting a complete report."""
import json
import unittest

from app.omega import context
from app.omega.jobs import run_once
from app.omega.reports import report_audit_claims
from tests import test_omega_report_audit as fixtures


class AuditBatchTests(unittest.TestCase):
    def test_batches_keep_full_context_and_every_original_slot_without_truncation(self):
        report = fixtures.audit_fixture_report()
        report['next_practice'] = ''
        report['dimensions'][4]['reason'] = ' 人物与顺序必须来自原话。😀 ' * 300
        report['dimensions'][1]['reason'] = None
        for name in ('commitments', 'concession_costs', 'hard_limit_findings'):
            report[name] = [{'description': ' 相同文字仍是独立事实槽。 '} for _ in range(6)]
        segments = [{'id': 'one', 'speaker': 'sales', 'speaker_id': 'sales', 'text': '完整原话。' * 200}]
        before = json.dumps([segments, report], ensure_ascii=False, sort_keys=True)
        original = context.audit_messages(segments, report, include_practice=True)
        payload = json.loads(original[-1]['content'])
        batches = list(context.audit_message_batches(segments, report, include_practice=True))
        all_claims = []
        self.assertGreater(len(batches), 4)
        for messages in batches:
            group = json.loads(messages[-1]['content'])
            self.assertEqual(messages[:-1], original[:-1])
            self.assertGreater(len(group['claims']), 0)
            self.assertLessEqual(len(group['claims']), 4)
            all_claims.extend(group.pop('claims'))
            self.assertEqual(group, {key: value for key, value in payload.items() if key != 'claims'})
        self.assertEqual(all_claims, report_audit_claims(report, include_practice=True))
        self.assertEqual(json.dumps([segments, report], ensure_ascii=False, sort_keys=True), before)
        self.assertEqual(context.audit_messages(segments, report, include_practice=True), original)

    def fixture(self):
        fixture = fixtures.ReportAuditTests('test_invalid_audit_retries_but_never_publishes')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def test_negative_group_followed_by_invalid_group_cannot_create_partial_feedback(self):
        fixture = self.fixture()
        audits = []
        def generate(kind, messages, _limit):
            if kind == 'report':
                return json.dumps(fixture.raw)
            if kind == 'practice':
                return '{"next_practice":"先内部核实。"}'
            audits.append(json.loads(messages[-1]['content'])['claims'])
            return fixtures.audit_reply(messages, rejected='outcome.reason') if len(audits) == 1 else '{}'
        run_once(fixture.engine, generate=generate)
        self.assertEqual(len(audits), 2)
        self.assertEqual(fixture.job()['status'], 'queued')
        self.assertNotIn('_report_audit_feedback', fixture.payload())
        fixture.assert_unpublished()

    def test_all_groups_must_be_valid_before_full_original_rejection_feedback(self):
        fixture = self.fixture()
        original = ' 这份旧候选需要完整保留。😀 ' * 300
        fixture.raw['outcome']['reason'] = original
        audits = []
        def generate(kind, messages, _limit):
            if kind == 'report':
                return json.dumps(fixture.raw)
            if kind == 'practice':
                return '{"next_practice":"先内部核实。"}'
            payload = json.loads(messages[-1]['content'])
            self.assertNotIn('audit_feedback', payload)
            audits.extend(payload['claims'])
            return fixtures.audit_reply(messages, rejected='outcome.reason', code='condition_unconfirmed')
        run_once(fixture.engine, generate=generate)
        self.assertEqual(len(audits), 11)
        self.assertEqual([row['claim_id'] for row in audits],
                         ['outcome.reason'] + [f'dimensions[{index}].reason' for index in range(9)] + ['next_practice'])
        self.assertEqual(fixture.job()['status'], 'queued')
        self.assertEqual(fixture.payload()['_report_audit_feedback']['claims'],
                         [{'claim_id': 'outcome.reason', 'text': original, 'issues': ['condition_unconfirmed']}])
        fixture.assert_unpublished()
