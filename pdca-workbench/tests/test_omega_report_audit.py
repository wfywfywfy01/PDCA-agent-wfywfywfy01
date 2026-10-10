"""Unverified report facts cannot reach publication or memory preparation."""
import json
import hashlib
import unittest
from datetime import timedelta
from unittest.mock import patch

from sqlmodel import Session, select

from app.auth.models import User
from app.omega.context import audit_messages, coach_messages
from app.omega.jobs import _default_generate, run_once
from app.omega.models import OmegaJob, OmegaReport, OmegaSegment, OmegaSession, utcnow
from app.omega.reports import WEIGHTS, validate_report, validate_report_audit
from app.omega import reports as report_tools
from tests import test_omega_flow as flow_tests


def audit_fixture_report():
    return {'outcome': {'status': 'unverified', 'reason': None},
            'dimensions': [{'key': key, 'score': None, 'reason': '证据不足'} for key in WEIGHTS],
            'commitments': [], 'concession_costs': [], 'hard_limit_findings': []}


def audit_fixture_checks():
    ids = ['outcome.reason'] + [f'dimensions[{index}].reason' for index in range(9)]
    return {'checks': [{'claim_id': claim_id, 'consistent': True, 'issues': []} for claim_id in ids]}


def audit_reply(messages, *, rejected=None, code='unsupported_fact'):
    claims = json.loads(messages[-1]['content'])['claims']
    return json.dumps({'checks': [{'claim_id': claim['claim_id'], 'consistent': claim['claim_id'] != rejected,
                                  'issues': [code] if claim['claim_id'] == rejected else []} for claim in claims]})


class ReportAuditValidationTests(unittest.TestCase):
    def test_coach_prompt_separates_parallel_answered_facts_and_unanswered_numbers(self):
        system = coach_messages({}, [], WEIGHTS)[0]['content']
        for clause in ('并列事项须逐项核对', '已答的定性顾虑', '周期、资金等数字必须分写',
                       '否定覆盖全部并列事项', '未进一步追问', '回答细节不足',
                       '次数、连续性和语气强度必须逐条由原话支持', '不能重复计数',
                       '不得仅凭提问或列举选项写成坚持、要求或同意',
                       '询问文件形式不自动等于坚持某选项'):
            with self.subTest(clause=clause):
                self.assertIn(clause, system)

    def test_audit_prompt_keeps_parallel_negation_scope_and_qualified_gaps_distinct(self):
        system = audit_messages([], audit_fixture_report())[0]['content']
        for clause in ('并列事项须逐项核对', '否定覆盖全部并列事项',
                       '不能擅自缩成只有数字未答', '判answered_fact_omitted',
                       '未进一步追问', '回答细节不足', '不得因已有定性回答而自动拒绝',
                       '仅返回 checks 一个字段', '禁止 type', '每个 claim_id 恰好核验一次',
                       '不能遗漏、重复或添加 claim_id', 'text=null 或空字符串表示没有文字断言',
                       '同一条件在 outcome.reason', '即使 status=partial',
                       '不得声称已符合最低目标', '提问或单方计划不能当作对方确认',
                       '判 condition_unconfirmed', '不能只凭 partial 拒绝',
                       '不混淆理想目标与最低目标',
                       '次数、连续性和语气强度必须逐条由原话支持', '不能重复计数',
                       '不得仅凭提问或列举选项写成坚持、要求或同意',
                       '询问文件形式不自动等于坚持某选项',
                       '次数或语气强度超出原话支持时，判 unsupported_fact',
                       '准确保留提问或条件的概括不得因此拒绝'):
            with self.subTest(clause=clause):
                self.assertIn(clause, system)

    def test_duplicate_json_keys_cannot_override_a_rejection(self):
        with self.assertRaisesRegex(ValueError, '复盘事实核验无效'):
            validate_report_audit('{"checks":[],"checks":[]}', audit_fixture_report())
        raw = json.dumps(audit_fixture_checks()).replace('"consistent": true', '"consistent": false,"consistent": true', 1)
        with self.assertRaisesRegex(ValueError, '复盘事实核验无效'):
            validate_report_audit(raw, audit_fixture_report())

    def test_exact_bool_enum_list_and_consistency_are_required(self):
        report = audit_fixture_report()
        invalid = [None, '', 'not JSON', 'null', '[]', 'true', '0', '{}',
                   '{"consistent":true,"issues":[]}', '{"checks":null}', '{"checks":{}}',
                   json.dumps({**audit_fixture_checks(), 'consistent': True}),
                   json.dumps({**audit_fixture_checks(), 'score': 100})]
        mutations = [{'consistent': 1}, {'consistent': 'true'}, {'issues': None}, {'issues': {}},
                     {'consistent': False, 'issues': []}, {'issues': ['speaker_mismatch']},
                     {'consistent': False, 'issues': ['unknown_code']},
                     {'consistent': False, 'issues': [{}]},
                     {'consistent': False, 'issues': ['chronology', 'chronology']},
                     {'consistent': False, 'issues': ['chronology', 'speaker_mismatch', 'condition_unconfirmed',
                                                    'answered_fact_omitted', 'unsupported_fact', 'chronology']},
                     {'score': 100}, {'text': 'replacement'}, {'claim_id': None}, {'claim_id': []}]
        for mutation in mutations:
            payload = audit_fixture_checks()
            payload['checks'][0].update(mutation)
            invalid.append(json.dumps(payload))
        for missing in ('claim_id', 'consistent', 'issues'):
            payload = audit_fixture_checks()
            del payload['checks'][0][missing]
            invalid.append(json.dumps(payload))
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, '复盘事实核验无效'):
                validate_report_audit(raw, report)
        self.assertIsNone(validate_report_audit(json.dumps(audit_fixture_checks()), report))
        for code in ('speaker_mismatch', 'chronology', 'condition_unconfirmed',
                     'answered_fact_omitted', 'unsupported_fact'):
            payload = audit_fixture_checks()
            payload['checks'][-1].update(consistent=False, issues=[code])
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, '复盘事实核验未通过'):
                validate_report_audit(json.dumps(payload), report)

    def test_exact_coverage_rejects_missing_duplicate_unknown_and_empty_claims(self):
        valid = audit_fixture_checks()
        invalid = [{'checks': []}, {'checks': valid['checks'][:-1]},
                   {'checks': valid['checks'] + [valid['checks'][0]]},
                   {'checks': [valid['checks'][0]] * 10},
                   {'checks': valid['checks'][:-1] + [{'claim_id': 'unknown.reason', 'consistent': True, 'issues': []}]},
                   {'checks': valid['checks'] + [{'claim_id': 'unknown.reason', 'consistent': True, 'issues': []}]}]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, '复盘事实核验无效'):
                validate_report_audit(json.dumps(payload), audit_fixture_report())
        self.assertIsNone(validate_report_audit(json.dumps({'checks': list(reversed(valid['checks']))}), audit_fixture_report()))

    def test_claims_preserve_full_text_all_slots_facts_and_input_hash(self):
        report = audit_fixture_report()
        report['dimensions'][7]['reason'] = ' 三次坚持同一条件；最后却只问文件形式。' * 80
        report['dimensions'][1]['reason'] = None
        del report['dimensions'][2]['reason']
        report['dimensions'][3]['reason'] = ''
        for name in ('commitments', 'concession_costs', 'hard_limit_findings'):
            report[name] = [{'description': ' 同样的原话。 '}, {'description': ' 同样的原话。 '}]
        before = hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        claims = report_tools.report_audit_claims(report)
        expected = [{'claim_id': 'outcome.reason', 'text': None}] + [
            {'claim_id': f'dimensions[{index}].reason', 'text': dim.get('reason')} for index, dim in enumerate(report['dimensions'])] + [
            {'claim_id': f'{name}[{index}].description', 'text': ' 同样的原话。 '}
            for name in ('commitments', 'concession_costs', 'hard_limit_findings') for index in range(2)]
        self.assertEqual(claims, expected)
        self.assertEqual(len(claims), 16)
        checks = {'checks': [{'claim_id': claim['claim_id'], 'consistent': True, 'issues': []} for claim in expected]}
        self.assertIsNone(validate_report_audit(json.dumps(checks), report))
        self.assertEqual(hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True).encode()).hexdigest(), before)

    def test_missing_null_empty_and_nonstring_required_reasons_are_invalid(self):
        for location in ('scored', 'achieved', 'partial', 'not_achieved', 'commitments', 'concession_costs', 'hard_limit_findings'):
            for value in (None, '', '  ', [], {}, 0, False):
                with self.subTest(location=location, value=value):
                    report = audit_fixture_report()
                    if location == 'scored':
                        report['dimensions'][0].update(score=0, reason=value)
                    elif location in ('achieved', 'partial', 'not_achieved'):
                        report['outcome'].update(status=location, reason=value)
                    else:
                        report[location] = [{'description': value}]
                    with self.assertRaisesRegex(ValueError, '复盘事实核验无效'):
                        report_tools.report_audit_claims(report)
            report = audit_fixture_report()
            if location == 'scored':
                report['dimensions'][0].update(score=0)
                del report['dimensions'][0]['reason']
            elif location in ('achieved', 'partial', 'not_achieved'):
                report['outcome'] = {'status': location}
            else:
                report[location] = [{}]
            with self.subTest(location=location, missing=True), self.assertRaisesRegex(ValueError, '复盘事实核验无效'):
                report_tools.report_audit_claims(report)

    def test_unscored_nonstring_and_malformed_report_shapes_cannot_drop_slots(self):
        invalid = [None, {}, {'outcome': None}, {**audit_fixture_report(), 'dimensions': []},
                   {**audit_fixture_report(), 'commitments': None}]
        for value in ([], {}, 0, False):
            for target in ('outcome', 'dimension'):
                report = audit_fixture_report()
                if target == 'outcome':
                    report['outcome']['reason'] = value
                else:
                    report['dimensions'][0]['reason'] = value
                invalid.append(report)
        for report in invalid:
            with self.subTest(report=report), self.assertRaisesRegex(ValueError, '复盘事实核验无效'):
                report_tools.report_audit_claims(report)

    def test_claim_prompt_keeps_full_public_transcript_report_and_no_private_data(self):
        report = audit_fixture_report()
        report.update(score={'earned': 0}, next_practice='PRIVATE_ADVICE', summary={'next_step': 'PRIVATE_SUMMARY'},
                      seller_private='PRIVATE_LIMIT', memory_context={'secret': 'PRIVATE_MEMORY'})
        parts = [{'id': 'one', 'speaker': 'sales', 'speaker_id': 'sales', 'text': '这是完整原话。' * 90},
                 {'id': 'two', 'speaker': 'counterparty', 'speaker_id': 'buyer', 'text': '您给正式协议还是内部审批单？'}]
        before = json.dumps([report, parts], ensure_ascii=False, sort_keys=True)
        messages = audit_messages(parts, report)
        payload = json.loads(messages[-1]['content'])
        self.assertEqual(set(payload), {'transcript', 'report', 'claims'})
        self.assertEqual(payload['claims'], report_tools.report_audit_claims(report))
        self.assertEqual(payload['report']['dimensions'], report['dimensions'])
        self.assertEqual(payload['report']['score'], report['score'])
        self.assertEqual(payload['transcript'], [dict(seq=index, **part) for index, part in enumerate(parts, 1)])
        self.assertNotIn('PRIVATE_', json.dumps(messages))
        self.assertEqual(json.dumps([report, parts], ensure_ascii=False, sort_keys=True), before)

    def test_deepseek_report_stages_use_kind_specific_thinking_json_and_stage_timeout(self):
        with patch.dict('os.environ', {'PDCA_SUPERVISOR_PROVIDER': 'https://api.deepseek.com',
                'PDCA_SUPERVISOR_MODEL': 'deepseek-flash', 'PDCA_SUPERVISOR_API_KEY': 'test-only'}), \
                patch('app.omega.jobs.httpx.post') as post:
            post.return_value.json.return_value = {'choices': [{'finish_reason': 'stop',
                'message': {'content': '{"consistent":true,"issues":[]}',
                            'reasoning_content': 'private reasoning must not become report text'}}]}
            for kind, limit, effort, timeout in [('report', 16384, 'high', 90),
                                                 ('report_audit', 32768, 'high', 150),
                                                 ('practice', 4096, 'high', 30)]:
                with self.subTest(kind=kind):
                    self.assertEqual(_default_generate(kind, [{'role': 'user', 'content': 'JSON'}], limit),
                                     '{"consistent":true,"issues":[]}')
                    payload = post.call_args.kwargs['json']
                    self.assertEqual(payload['response_format'], {'type': 'json_object'})
                    self.assertEqual(payload['thinking'], {'type': 'enabled'})
                    self.assertEqual((payload['reasoning_effort'], post.call_args.kwargs['timeout']),
                                     (effort, timeout))
                    self.assertEqual(payload['max_tokens'], limit)
                    self.assertNotIn('temperature', payload)

    def test_other_deepseek_kinds_keep_disabled_thinking_and_existing_budget(self):
        with patch.dict('os.environ', {'PDCA_SUPERVISOR_PROVIDER': 'https://api.deepseek.com',
                'PDCA_SUPERVISOR_MODEL': 'deepseek-flash', 'PDCA_SUPERVISOR_API_KEY': 'test-only'}), \
                patch('app.omega.jobs.httpx.post') as post:
            post.return_value.json.return_value = {'choices': [{'finish_reason': 'stop',
                'message': {'content': 'unchanged'}}]}
            for kind in ('turn', 'draft', 'memory', 'coaching'):
                with self.subTest(kind=kind):
                    self.assertEqual(_default_generate(kind, [], 777), 'unchanged')
                    payload = post.call_args.kwargs['json']
                    self.assertEqual(payload['thinking'], {'type': 'disabled'})
                    self.assertNotIn('reasoning_effort', payload)
                    self.assertEqual(payload['max_tokens'], 777)
                    self.assertEqual('response_format' in payload, kind == 'memory')
                    self.assertEqual(post.call_args.kwargs['timeout'], 90 if kind == 'memory' else 20)

    def test_non_deepseek_calls_keep_existing_provider_parameters_and_timeout(self):
        for provider, model in [('https://models.example.test', 'other-model'),
                                ('https://api.deepseek.com.evil.test', 'deepseek-flash'),
                                ('https://api.deepseek.com', 'other-model')]:
            with patch.dict('os.environ', {'PDCA_SUPERVISOR_PROVIDER': provider,
                    'PDCA_SUPERVISOR_MODEL': model, 'PDCA_SUPERVISOR_API_KEY': 'test-only'}), \
                    patch('app.omega.jobs.httpx.post') as post:
                post.return_value.json.return_value = {'choices': [{'finish_reason': 'stop',
                    'message': {'content': 'unchanged'}}]}
                for kind in ('report', 'report_audit', 'practice'):
                    with self.subTest(provider=provider, model=model, kind=kind):
                        self.assertEqual(_default_generate(kind, [], 777), 'unchanged')
                        payload = post.call_args.kwargs['json']
                        for key in ('thinking', 'reasoning_effort', 'response_format'):
                            self.assertNotIn(key, payload)
                        self.assertEqual(payload['temperature'], 0.3 if kind == 'report' else 0.8)
                        self.assertEqual(payload['max_tokens'], 777)
                        self.assertEqual(post.call_args.kwargs['timeout'], 90 if kind == 'report' else 20)

    def test_truncated_or_empty_audit_is_an_invalid_result_for_retry(self):
        with patch.dict('os.environ', {'PDCA_SUPERVISOR_PROVIDER': 'https://api.deepseek.com',
                'PDCA_SUPERVISOR_MODEL': 'deepseek-flash', 'PDCA_SUPERVISOR_API_KEY': 'test-only'}), \
                patch('app.omega.jobs.httpx.post') as post:
            for finish, content in (('length', '{"consistent":'), ('stop', '')):
                with self.subTest(finish=finish):
                    post.return_value.json.return_value = {'choices': [{'finish_reason': finish,
                        'message': {'content': content}}]}
                    with self.assertRaisesRegex(ValueError, '复盘事实核验无效'):
                        _default_generate('report_audit', [], 1000)


class ReportAuditTests(unittest.TestCase):
    def setUp(self):
        self.flow = flow_tests.OmegaFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.tearDown)
        self.client, self.engine = self.flow.client, self.flow.engine
        case = self.client.post('/api/omega/cases', json=self.flow.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        self.game = self.client.post('/api/omega/sessions', json={'case_id': case['id']}).json()
        text = '未经批准我不能降价。您是否确认周五由财务回复？'
        self.client.post(f"/api/omega/sessions/{self.game['id']}/turns", json={
            'request_key': 'audit-sales', 'text': text}).raise_for_status()
        run_once(self.engine, generate=lambda *_: '我得先看正式条款，未获批准前不会确认。')
        self.parts = self.client.get(f"/api/omega/sessions/{self.game['id']}").json()['segments']
        quote = {'segment_id': self.parts[0]['id'], 'speaker': 'sales', 'speaker_id': 'sales',
                 'start': 0, 'end': len(text), 'text': text}
        self.raw = {'outcome': {'status': 'unverified', 'reason': '对方尚未确认', 'quotes': []},
                    'dimensions': [{'key': key, 'score': 10 if key == 'compliance' else None,
                                    'reason': '明确守住底线' if key == 'compliance' else '证据不足',
                                    'quotes': [quote] if key == 'compliance' else []} for key in WEIGHTS],
                    'commitments': [], 'concession_costs': [], 'hard_limit_findings': [],
                    'next_practice': '这个旧建议不能未经核验发布。'}
        ended = self.client.post(f"/api/omega/sessions/{self.game['id']}/finish", json={
            'request_key': 'audit-finish'}).json()
        self.job_id = ended['pending_job_id']

    def job(self):
        return self.client.get('/api/omega/jobs/' + self.job_id).json()

    def assert_unpublished(self):
        game = self.client.get(f"/api/omega/sessions/{self.game['id']}").json()
        self.assertFalse(game.get('latest_report_id'))
        with Session(self.engine) as db:
            self.assertEqual(db.exec(select(OmegaReport)).all(), [])
            self.assertEqual(db.exec(select(OmegaJob).where(OmegaJob.kind == 'memory')).all(), [])

    def run_report_with_clock(self, final_elapsed):
        start = utcnow() + timedelta(seconds=1)
        clock = {'now': start}
        calls, leases = [], []
        def generate(kind, messages, _limit):
            calls.append(kind)
            with Session(self.engine) as db:
                lease = db.get(OmegaJob, self.job_id).lease_until
                if lease.tzinfo is None:
                    lease = lease.replace(tzinfo=start.tzinfo)
                leases.append(lease)
            if kind == 'report':
                clock['now'] = start + timedelta(seconds=90)
                return json.dumps(self.raw)
            if kind == 'report_audit':
                clock['now'] = start + timedelta(seconds=180)
                return audit_reply(messages)
            clock['now'] = start + timedelta(seconds=final_elapsed)
            return json.dumps({'next_practice': 'Confirm the permitted public terms.'})
        with patch('app.omega.jobs.utcnow', side_effect=lambda: clock['now']):
            self.assertTrue(run_once(self.engine, generate=generate))
        self.assertEqual(calls, ['report', 'report_audit', 'practice'])
        self.assertEqual(leases, [start + timedelta(seconds=300)] * 3)

    def test_report_lease_covers_250_seconds_without_renewing_or_bypassing_guards(self):
        self.run_report_with_clock(250)
        self.assertEqual(self.job()['status'], 'succeeded')
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaReport)).all()), 1)

    def test_report_cannot_publish_at_exact_300_second_lease_boundary(self):
        self.run_report_with_clock(300)
        self.assertEqual(self.job()['status'], 'running')
        self.assert_unpublished()

    def test_turn_and_memory_claims_keep_180_second_lease(self):
        for kind in ('turn', 'memory'):
            with self.subTest(kind=kind):
                start = utcnow() + timedelta(seconds=1)
                with Session(self.engine) as db:
                    job = db.get(OmegaJob, self.job_id)
                    job.kind, job.status, job.lease_token = kind, 'queued', ''
                    game = db.get(OmegaSession, self.game['id'])
                    game.status = 'active' if kind == 'turn' else 'ended'
                    db.commit()
                calls, leases = [], []
                def generate(actual_kind, *_):
                    calls.append(actual_kind)
                    with Session(self.engine) as db:
                        lease = db.get(OmegaJob, self.job_id).lease_until
                        if lease.tzinfo is None:
                            lease = lease.replace(tzinfo=start.tzinfo)
                        leases.append(lease)
                    raise ValueError('test-only stop after lease inspection')
                with patch('app.omega.jobs.utcnow', return_value=start), \
                        patch('app.omega.memory.prepare_memory_job', return_value=[]):
                    self.assertTrue(run_once(self.engine, generate=generate))
                self.assertEqual(calls, [kind])
                self.assertEqual(leases, [start + timedelta(seconds=180)])
                self.assertEqual(self.job()['status'], 'failed')

    def test_inconsistent_audit_retries_without_practice_publication_or_memory(self):
        calls = []

        def generate(kind, messages, _limit):
            calls.append(kind)
            if kind == 'report':
                return json.dumps(self.raw)
            if kind == 'report_audit':
                return audit_reply(messages, rejected='outcome.reason', code='condition_unconfirmed')
            return json.dumps({'next_practice': '先核实正式条款是否可出具。'})

        self.assertTrue(run_once(self.engine, generate=generate))
        self.assertEqual(calls, ['report', 'report_audit'])
        self.assertEqual(self.job()['status'], 'queued')
        self.assert_unpublished()
        self.assertTrue(run_once(self.engine, generate=generate))
        self.assertEqual(calls, ['report', 'report_audit'] * 2)
        self.assertEqual(self.job()['status'], 'failed')
        self.assertEqual(self.job()['error'], '复盘事实核验未通过')
        self.assert_unpublished()

    def test_invalid_audit_retries_but_never_publishes(self):
        calls = []
        def generate(kind, *_):
            calls.append(kind)
            return json.dumps(self.raw) if kind == 'report' else '{"consistent":"true","issues":[]}'
        for expected in ('queued', 'failed'):
            self.assertTrue(run_once(self.engine, generate=generate))
            self.assertEqual(self.job()['status'], expected)
            self.assert_unpublished()
        self.assertEqual(calls, ['report', 'report_audit'] * 2)

    def test_missing_check_retries_without_practice_publication_or_memory(self):
        calls = []
        def generate(kind, messages, _limit):
            calls.append(kind)
            if kind == 'report':
                return json.dumps(self.raw)
            payload = json.loads(audit_reply(messages))
            payload['checks'].pop()
            return json.dumps(payload)
        for expected in ('queued', 'failed'):
            run_once(self.engine, generate=generate)
            self.assertEqual(self.job()['status'], expected)
            self.assert_unpublished()
        self.assertEqual(calls, ['report', 'report_audit'] * 2)
        self.assertEqual(self.job()['error'], '复盘事实核验无效')

    def test_false_check_for_null_scored_reason_blocks_publication(self):
        self.raw['dimensions'][7]['reason'] = '客户连续三次坚持先给盖章兜底条款。'
        calls = []
        def generate(kind, messages, _limit):
            calls.append(kind)
            if kind == 'report':
                return json.dumps(self.raw)
            payload = json.loads(messages[-1]['content'])
            self.assertEqual(payload['claims'][8], {'claim_id': 'dimensions[7].reason',
                                                    'text': self.raw['dimensions'][7]['reason']})
            self.assertIsNone(payload['report']['dimensions'][7]['score'])
            return audit_reply(messages, rejected='dimensions[7].reason')
        run_once(self.engine, generate=generate)
        self.assertEqual(calls, ['report', 'report_audit'])
        self.assertEqual(self.job()['status'], 'queued')
        self.assert_unpublished()

    def test_invalid_scored_reason_blocks_audit_and_retries_without_publication(self):
        self.raw['dimensions'][6]['reason'] = None
        calls = []
        def generate(kind, *_):
            calls.append(kind)
            return json.dumps(self.raw)
        for expected in ('queued', 'failed'):
            run_once(self.engine, generate=generate)
            self.assertEqual(self.job()['status'], expected)
            self.assert_unpublished()
        self.assertEqual(calls, ['report', 'report'])
        self.assertEqual(self.job()['error'], '复盘事实核验无效')

    def test_successful_audit_keeps_scores_facts_quotes_and_uses_public_sequence_only(self):
        calls = []
        original_hash = hashlib.sha256(json.dumps(self.raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        def generate(kind, messages, limit):
            calls.append(kind)
            if kind == 'report':
                self.assertEqual(limit, 16384)
                return json.dumps(self.raw)
            if kind == 'report_audit':
                self.assertEqual(limit, 32768)
                payload = json.loads(messages[-1]['content'])
                self.assertEqual(set(payload), {'transcript', 'report', 'claims'})
                self.assertEqual([p['seq'] for p in payload['transcript']], [1, 2])
                self.assertEqual([p['speaker'] for p in payload['transcript']], ['sales', 'counterparty'])
                self.assertEqual([p['text'] for p in payload['transcript']], [p['text'] for p in self.parts])
                self.assertEqual(payload['report']['dimensions'], self.raw['dimensions'])
                self.assertNotIn('next_practice', payload['report'])
                self.assertNotIn('summary', payload['report'])
                self.assertNotIn('PRIVATE_BOTTOM_LINE', json.dumps(messages))
                self.assertEqual(len(payload['claims']), 10)
                self.assertEqual(payload['claims'][7], {'claim_id': 'dimensions[6].reason', 'text': '明确守住底线'})
                return audit_reply(messages)
            self.assertEqual(kind, 'practice')
            self.assertEqual(limit, 4096)
            return json.dumps({'next_practice': '先内部核实可公开的条款与替代路径。'})
        self.assertTrue(run_once(self.engine, generate=generate))
        self.assertEqual(calls, ['report', 'report_audit', 'practice'])
        job = self.job()
        self.assertEqual(job['status'], 'succeeded', job)
        published = self.client.get('/api/omega/reports/' + job['result_id']).json()['content']
        self.assertEqual(published['dimensions'], self.raw['dimensions'])
        self.assertEqual(published['outcome'], self.raw['outcome'])
        self.assertEqual(published['score'], {'earned': 10, 'available': 10, 'coverage_percent': 10, 'total': None})
        for key in ('commitments', 'concession_costs', 'hard_limit_findings'):
            self.assertEqual(published[key], [])
        self.assertEqual(published['next_practice'], '先内部核实可公开的条款与替代路径。')
        self.assertEqual(hashlib.sha256(json.dumps(self.raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest(), original_hash)

    def test_rejected_attempt_is_regenerated_and_reaudited_before_publication(self):
        calls, attempts = [], 0
        def generate(kind, messages, _limit):
            nonlocal attempts
            calls.append(kind)
            if kind == 'report':
                attempts += 1
                fresh = dict(self.raw, outcome={**self.raw['outcome'], 'reason': '新报告确认尚未批准' if attempts == 2 else '旧报告'})
                return json.dumps(fresh)
            if kind == 'report_audit':
                return audit_reply(messages, rejected='outcome.reason' if attempts == 1 else None)
            return json.dumps({'next_practice': '先核实能够公开的正式条款。'})
        run_once(self.engine, generate=generate)
        self.assertEqual(self.job()['status'], 'queued')
        self.assert_unpublished()
        run_once(self.engine, generate=generate)
        job = self.job()
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(calls, ['report', 'report_audit', 'report', 'report_audit', 'practice'])
        report = self.client.get('/api/omega/reports/' + job['result_id']).json()['content']
        self.assertEqual(report['outcome']['reason'], '新报告确认尚未批准')

    def test_audit_is_mandatory_without_a_scored_practice_focus(self):
        for dimension in self.raw['dimensions']:
            dimension.update(score=None, reason='证据不足', quotes=[])
        calls = []
        def generate(kind, messages, _limit):
            calls.append(kind)
            return json.dumps(self.raw) if kind == 'report' else audit_reply(messages)
        run_once(self.engine, generate=generate)
        self.assertEqual(calls, ['report', 'report_audit'])
        self.assertEqual(self.job()['status'], 'succeeded')

    def test_disabled_owner_during_report_blocks_the_audit(self):
        calls = []
        def generate(kind, messages, _limit):
            calls.append(kind)
            if kind == 'report':
                with Session(self.engine) as db:
                    db.get(User, 1).is_active = False
                    db.commit()
                return json.dumps(self.raw)
            return audit_reply(messages) if kind == 'report_audit' else '{"next_practice":"核实条款。"}'
        run_once(self.engine, generate=generate)
        self.assertEqual(calls, ['report'])
        self.assertEqual(self.job()['status'], 'failed')
        self.assert_unpublished()

    def assert_boundary_stops(self, stage, change):
        calls = []
        def generate(kind, messages, _limit):
            calls.append(kind)
            if kind == stage:
                with Session(self.engine) as db:
                    if change == 'permission':
                        db.get(User, 1).team_key = 'revoked-team'
                    elif change == 'disabled':
                        db.get(User, 1).is_active = False
                    elif change == 'revision':
                        db.get(OmegaSession, self.game['id']).revision += 1
                    elif change == 'hash':
                        game = db.get(OmegaSession, self.game['id'])
                        game.context_snapshot_json = json.dumps({**json.loads(game.context_snapshot_json), 'stage_summary': 'changed'})
                    elif change == 'transcript':
                        db.get(OmegaSegment, self.parts[0]['id']).text += ' 未经许可的改写'
                    elif change == 'lease':
                        job = db.get(OmegaJob, self.job_id)
                        job.status, job.lease_token = 'cancelled', ''
                    elif change == 'expired':
                        db.get(OmegaJob, self.job_id).lease_until = utcnow() - timedelta(seconds=1)
                    else:
                        self.fail('unknown test mutation')
                    db.commit()
            if kind == 'report':
                return json.dumps(self.raw)
            if kind == 'report_audit':
                return audit_reply(messages)
            return '{"next_practice":"先核实正式条款。"}'
        run_once(self.engine, generate=generate)
        expected = ['report'] if stage == 'report' else ['report', 'report_audit']
        if stage == 'practice':
            expected.append('practice')
        self.assertEqual(calls, expected)
        self.assert_unpublished()
        if change == 'lease':
            self.assertEqual(self.job()['status'], 'cancelled')
        elif change != 'expired':
            self.assertEqual(self.job()['status'], 'failed')

    def test_permission_revoked_during_report_blocks_audit(self):
        self.assert_boundary_stops('report', 'permission')

    def test_permission_revoked_during_audit_blocks_practice(self):
        self.assert_boundary_stops('report_audit', 'permission')

    def test_revision_changed_during_report_blocks_audit(self):
        self.assert_boundary_stops('report', 'revision')

    def test_revision_changed_during_audit_blocks_practice(self):
        self.assert_boundary_stops('report_audit', 'revision')

    def test_changed_frozen_input_during_audit_blocks_practice(self):
        self.assert_boundary_stops('report_audit', 'hash')

    def test_changed_transcript_without_revision_during_audit_blocks_practice(self):
        self.assert_boundary_stops('report_audit', 'transcript')

    def test_cancelled_lease_during_report_blocks_audit(self):
        self.assert_boundary_stops('report', 'lease')

    def test_expired_lease_during_audit_blocks_practice(self):
        self.assert_boundary_stops('report_audit', 'expired')

    def test_disabled_owner_during_practice_blocks_publication(self):
        self.assert_boundary_stops('practice', 'disabled')

    def test_disabled_owner_during_audit_blocks_practice(self):
        self.assert_boundary_stops('report_audit', 'disabled')

    def test_changed_transcript_without_revision_during_practice_blocks_publication(self):
        self.assert_boundary_stops('practice', 'transcript')


if __name__ == '__main__':
    unittest.main()
