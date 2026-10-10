"""Focused advice must use the actual failed attempt without rewriting evidence."""
import copy
import json
import unittest

from sqlmodel import Session, select

from app.omega.jobs import run_once
from app.auth.models import User
from app.omega.models import OmegaJob, OmegaReport, OmegaSession
from app.omega.reports import WEIGHTS, validate_report
from tests import test_omega_flow as flow_tests


class OmegaPracticeTests(unittest.TestCase):
    def setUp(self):
        self.flow = flow_tests.OmegaFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.tearDown)
        self.client, self.engine = self.flow.client, self.flow.engine
        case = self.client.post('/api/omega/cases', json=self.flow.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        self.game = self.client.post('/api/omega/sessions', json={'case_id': case['id']}).json()
        self.utterance = '您能接受的库存周转周期和首批资金上限分别是多少？'
        self.reply = '先给出滞销兜底的书面条件，否则我现在不能提供这些数据。'
        self.client.post(f"/api/omega/sessions/{self.game['id']}/turns", json={
            'request_key': 'practice-first-attempt', 'text': self.utterance}).raise_for_status()
        run_once(self.engine, generate=lambda *_: self.reply)
        self.parts = self.client.get(f"/api/omega/sessions/{self.game['id']}").json()['segments']
        quote = {'segment_id': self.parts[0]['id'], 'speaker': 'sales',
                 'start': 0, 'end': len(self.utterance), 'text': self.utterance,
                 'speaker_id': self.parts[0]['speaker_id']}
        self.raw = {'outcome': {'status': 'unverified', 'reason': '未获得批准', 'quotes': []},
                    'dimensions': [{'key': key, 'score': None, 'reason': '证据不足', 'quotes': []}
                                   for key in reversed(WEIGHTS)],
                    'commitments': [], 'concession_costs': [], 'hard_limit_findings': [],
                    'next_practice': '先问库存周转周期和首批资金上限，再带回审批。'}
        for dimension in self.raw['dimensions']:
            if dimension['key'] in {'value', 'concessions'}:
                dimension.update(score=4, reason='未把风险投入和支持条件形成可核对的交换', quotes=[quote])
        ended = self.client.post(f"/api/omega/sessions/{self.game['id']}/finish", json={
            'request_key': 'practice-finish'}).json()
        self.job_id = ended['pending_job_id']

    def report_rows(self):
        with Session(self.engine) as db:
            return db.exec(select(OmegaReport)).all()

    def test_advice_uses_refused_attempt_and_final_tie_breaker_without_rescoring(self):
        calls = []
        action = '先核对对方为何不愿给数据；准备投入和滞销风险的待填评估表，约定兜底条件获批后再共同核算。'

        def generate(kind, messages, limit):
            calls.append(kind)
            if kind == 'report':
                self.assertEqual([p['seq'] for p in json.loads(messages[-1]['content'])['transcript']], [1, 2])
                return json.dumps(self.raw, ensure_ascii=False)
            self.assertEqual(kind, 'practice')
            payload = json.loads(messages[-1]['content'])
            self.assertEqual(payload['target_dimension']['key'], 'value')
            self.assertEqual([p['text'] for p in payload['transcript']], [self.utterance, self.reply])
            self.assertEqual([p['seq'] for p in payload['transcript']], [1, 2])
            self.assertLessEqual(limit, 1000)
            return json.dumps({'next_practice': action}, ensure_ascii=False)

        self.assertTrue(run_once(self.engine, generate=generate))
        job = self.client.get('/api/omega/jobs/' + self.job_id).json()
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(calls, ['report', 'practice'])
        published = self.client.get('/api/omega/reports/' + job['result_id']).json()
        self.assertEqual(self.report_rows()[0].prompt_version, 'coach-v3')
        report = published['content']
        self.assertEqual(report['next_practice'], action)
        self.assertEqual(report['summary']['next_step'], action)
        expected = validate_report(json.dumps(copy.deepcopy(self.raw)), self.parts)
        for key in ('outcome', 'dimensions', 'score', 'commitments', 'concession_costs', 'hard_limit_findings'):
            self.assertEqual(report[key], expected[key], key)

    def test_invalid_advice_is_retried_once_without_publishing_stale_recommendation(self):
        def generate(kind, *_):
            return json.dumps(self.raw) if kind == 'report' else json.dumps({'next_practice': ''})
        run_once(self.engine, generate=generate)
        self.assertEqual(self.client.get('/api/omega/jobs/' + self.job_id).json()['status'], 'queued')
        self.assertEqual(self.report_rows(), [])
        run_once(self.engine, generate=generate)
        job = self.client.get('/api/omega/jobs/' + self.job_id).json()
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(self.report_rows(), [])

    def test_advice_cannot_return_replacement_scores_or_facts(self):
        def generate(kind, *_):
            return json.dumps(self.raw) if kind == 'report' else json.dumps({
                'next_practice': '确认订单。', 'score': {'total': 100}})
        run_once(self.engine, generate=generate)
        self.assertEqual(self.report_rows(), [])
        self.assertEqual(self.client.get('/api/omega/jobs/' + self.job_id).json()['status'], 'queued')

    def test_insufficient_evidence_does_not_invent_a_scored_focus(self):
        for dimension in self.raw['dimensions']:
            dimension.update(score=None, reason='证据不足', quotes=[])
        calls = []
        run_once(self.engine, generate=lambda kind, *_: calls.append(kind) or json.dumps(self.raw))
        self.assertEqual(calls, ['report'])
        self.assertEqual(self.client.get('/api/omega/jobs/' + self.job_id).json()['status'], 'succeeded')

    def test_practice_uses_json_and_short_timeout(self):
        from unittest.mock import patch
        from app.omega.jobs import _default_generate
        with patch.dict('os.environ', {'PDCA_SUPERVISOR_PROVIDER': 'https://api.deepseek.com',
                'PDCA_SUPERVISOR_MODEL': 'deepseek-flash', 'PDCA_SUPERVISOR_API_KEY': 'test-only'}), \
                patch('app.omega.jobs.httpx.post') as post:
            post.return_value.json.return_value = {'choices': [{'finish_reason': 'stop',
                'message': {'content': '{"next_practice":"核对拒答原因。"}'}}]}
            _default_generate('practice', [{'role': 'user', 'content': 'JSON'}], 900)
            self.assertEqual(post.call_args.kwargs['json']['response_format'], {'type': 'json_object'})
            self.assertEqual(post.call_args.kwargs['timeout'], 20)

    def test_lost_source_permission_stops_second_external_call(self):
        calls = []
        def generate(kind, *_):
            calls.append(kind)
            with Session(self.engine) as db:
                db.get(User, 1).team_key = 'different-team'
                db.commit()
            return json.dumps(self.raw)
        run_once(self.engine, generate=generate)
        self.assertEqual(calls, ['report'])
        self.assertEqual(self.report_rows(), [])
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, self.job_id).status, 'failed')

    def test_changed_transcript_revision_stops_second_external_call(self):
        calls = []
        def generate(kind, *_):
            calls.append(kind)
            with Session(self.engine) as db:
                db.get(OmegaSession, self.game['id']).revision += 1
                db.commit()
            return json.dumps(self.raw)
        run_once(self.engine, generate=generate)
        self.assertEqual(calls, ['report'])
        self.assertEqual(self.report_rows(), [])
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, self.job_id).status, 'failed')


if __name__ == '__main__':
    unittest.main()
