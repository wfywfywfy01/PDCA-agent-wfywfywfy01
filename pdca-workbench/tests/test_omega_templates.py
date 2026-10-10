"""Preset launch and automatic scoring use the existing authenticated flow."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, select

from app.auth.models import User
from app.omega.coaching_models import OmegaCoachHint
from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaJob, OmegaReport, OmegaSegment, OmegaSession
from app.omega.reports import WEIGHTS, validate_report
from app.omega.router import canonical, report_input_hash, transcript_digest
from tests import test_omega_flow as fixtures


class OmegaTemplateTests(unittest.TestCase):
    setUp = fixtures.OmegaFlowTests.setUp
    tearDown = fixtures.OmegaFlowTests.tearDown
    case_body = staticmethod(fixtures.OmegaFlowTests.case_body)

    def template(self):
        response = self.client.post('/api/omega/cases', json={**self.case_body(), 'kind': 'template'})
        self.assertEqual(response.status_code, 201, response.text)
        row = response.json()
        self.client.post(f"/api/omega/cases/{row['id']}/confirm").raise_for_status()
        return self.client.get(f"/api/omega/cases/{row['id']}").json()

    def start_body(self, template, **changes):
        return {'request_key': 'template-start-001', 'template_id': template['id'],
                'template_version': template['current_version'], 'usage': 'training',
                'dealer_id': '', 'overrides': {'title': '本次个性化练习'}, **changes}

    def test_presets_are_ready_without_company_or_customer_facts(self):
        response = self.client.get('/api/omega/templates')
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual({row['title'] for row in rows}, {'新人上手', '首次触达', '首单谈判'})
        self.assertTrue(all(row['simulation'] and row['current_version'] == 1 for row in rows))
        self.assertTrue(all(row['draft']['buyer_company'] == '' for row in rows))
        self.assertEqual(len(self.client.get('/api/omega/templates').json()), 3)

    def test_template_start_is_idempotent_and_freezes_copy(self):
        template = self.template()
        payload = self.start_body(template)
        first = self.client.post('/api/omega/template-starts', json=payload)
        again = self.client.post('/api/omega/template-starts', json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(first.json(), again.json())
        self.assertNotEqual(first.json()['case_id'], template['id'])
        game = self.client.get(f"/api/omega/sessions/{first.json()['session_id']}").json()
        self.assertEqual(game['case_snapshot']['title'], '本次个性化练习')
        self.assertEqual(game['mode'], 'training')
        self.assertEqual(self.client.get(f"/api/omega/cases/{template['id']}").json()['draft'], template['draft'])
        changed = {**template['draft'], 'revision': template['revision'], 'stage_summary': '模板后来修改'}
        self.client.patch(f"/api/omega/cases/{template['id']}", json=changed).raise_for_status()
        frozen = self.client.get(f"/api/omega/sessions/{game['id']}").json()['case_snapshot']
        self.assertEqual(frozen, game['case_snapshot'])
        self.assertEqual(self.client.post('/api/omega/template-starts', json=payload).status_code, 200)
        self.assertEqual(self.client.post('/api/omega/template-starts', json=self.start_body(
            template, request_key='new-after-edit-001')).status_code, 409)
        self.assertEqual(self.client.post('/api/omega/template-starts', json={
            **payload, 'overrides': {'title': '不同的练习'}}).status_code, 409)
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaCase).where(OmegaCase.launch_key != None)).all()), 1)

    def test_template_permissions_overrides_and_real_review(self):
        template = self.template()
        self.current = User(id=2, username='seller-b', role='sales', team_key='team-a')
        self.assertEqual(self.client.patch(f"/api/omega/cases/{template['id']}", json={
            **template['draft'], 'revision': template['revision']}).status_code, 403)
        first = self.client.post('/api/omega/template-starts', json=self.start_body(template, usage='real_review'))
        self.assertEqual(first.status_code, 201, first.text)
        self.assertIsNone(first.json()['session_id'])
        self.assertEqual(first.json()['next_action'], 'import_meeting')
        for overrides in ({'owner_id': 4}, {'team_key': 'other'}, {'memory_context': {}},
                          {'goal': {'hard_limits': []}}):
            self.assertEqual(self.client.post('/api/omega/template-starts', json=self.start_body(
                template, request_key='invalid-override-001', overrides=overrides)).status_code, 422)
        self.current = User(id=3, username='other', role='sales', team_key='team-b')
        self.assertEqual(self.client.post('/api/omega/template-starts', json=self.start_body(template)).status_code, 404)

    def test_team_manager_edits_template_and_unconfirmed_templates_stay_hidden(self):
        template = self.template()
        self.current = User(id=2, username='manager-a', role='manager', team_key='team-a')
        changed = {**template['draft'], 'revision': template['revision'], 'stage_summary': '主管已更新训练目的'}
        updated = self.client.patch(f"/api/omega/cases/{template['id']}", json=changed)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertNotIn(template['id'], {row['id'] for row in self.client.get('/api/omega/templates').json()})
        self.client.post(f"/api/omega/cases/{template['id']}/confirm").raise_for_status()
        self.assertIn(template['id'], {row['id'] for row in self.client.get('/api/omega/templates').json()})

    def test_authorized_dealer_start_drops_fictional_facts_and_rechecks_source(self):
        from fastapi import HTTPException
        dealer = '11111111-1111-1111-1111-111111111111'
        body = {**self.case_body(), 'kind': 'template', 'dealer_id': dealer,
                'buyer_company': '虚构示例公司', 'buyer_objections': ['虚构交付担忧'], 'stage_summary': '虚构客户阶段'}
        with patch('app.omega.policy.require_knowledge_access'), patch('app.omega.memory.require_knowledge_access'):
            template = self.client.post('/api/omega/cases', json=body).json()
            self.client.post(f"/api/omega/cases/{template['id']}/confirm").raise_for_status()
            template = self.client.get(f"/api/omega/cases/{template['id']}").json()
            response = self.client.post('/api/omega/template-starts', json=self.start_body(template, usage='rehearsal', dealer_id=dealer))
            self.assertEqual(response.status_code, 201, response.text)
            game = self.client.get(f"/api/omega/sessions/{response.json()['session_id']}").json()
        self.assertEqual(game['case_snapshot']['buyer_company'], '')
        self.assertEqual(game['case_snapshot']['buyer_objections'], [])
        self.assertNotIn('虚构客户阶段', game['case_snapshot']['stage_summary'])
        self.assertTrue(game['case_snapshot']['simulation'])
        with patch('app.omega.policy.require_knowledge_access', side_effect=HTTPException(403, 'revoked')):
            self.assertEqual(self.client.get(f"/api/omega/sessions/{game['id']}").status_code, 403)
            self.assertEqual(self.client.post('/api/omega/template-starts', json=self.start_body(
                template, usage='rehearsal', dealer_id=dealer)).status_code, 403)
            self.assertNotIn(template['id'], {row['id'] for row in self.client.get('/api/omega/templates').json()})

    def test_parallel_start_keeps_one_case_and_session(self):
        template = self.template()
        payload = self.start_body(template)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.client.post('/api/omega/template-starts', json=payload), range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 201])
        self.assertEqual(responses[0].json(), responses[1].json())
        with Session(self.engine) as db:
            rows = db.exec(select(OmegaCase).where(OmegaCase.launch_key == payload['request_key'])).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(db.exec(select(OmegaCaseVersion).where(OmegaCaseVersion.case_id == rows[0].id)).all()), 1)
            self.assertEqual(len(db.exec(select(OmegaSession).where(OmegaSession.case_id == rows[0].id)).all()), 1)

    def test_saved_template_cannot_drop_source_permissions(self):
        from fastapi import HTTPException
        dealer = '11111111-1111-1111-1111-111111111111'
        with patch('app.omega.policy.require_knowledge_access'):
            original = self.client.post('/api/omega/cases', json={**self.case_body(), 'kind': 'template', 'dealer_id': dealer}).json()
            version = self.client.post(f"/api/omega/cases/{original['id']}/confirm").json()
            saved = self.client.post('/api/omega/cases', json={**self.case_body(), 'kind': 'template',
                'source_template_version_id': version['id'], 'dealer_id': ''})
            self.assertEqual(saved.status_code, 201, saved.text)
            self.client.post(f"/api/omega/cases/{saved.json()['id']}/confirm").raise_for_status()
            copy = self.client.get(f"/api/omega/cases/{saved.json()['id']}").json()
            self.assertEqual(copy['source_template_version_id'], version['id'])
            self.assertEqual(self.client.patch(f"/api/omega/cases/{copy['id']}", json={
                **copy['draft'], 'source_template_version_id': None, 'revision': copy['revision']}).status_code, 422)
            source = self.client.get(f"/api/omega/cases/{original['id']}").json()
            self.client.patch(f"/api/omega/cases/{original['id']}", json={
                **source['draft'], 'dealer_id': '', 'revision': source['revision']}).raise_for_status()
        with patch('app.omega.policy.require_knowledge_access', side_effect=HTTPException(403, 'revoked')):
            self.assertEqual(self.client.get(f"/api/omega/cases/{copy['id']}").status_code, 403)
            self.assertNotIn(copy['id'], {row['id'] for row in self.client.get('/api/omega/templates').json()})

    def test_finish_atomically_queues_one_report_and_keeps_transcript(self):
        case = self.client.post('/api/omega/cases', json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post('/api/omega/sessions', json={'case_id': case['id']}).json()
        self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            'request_key': 'auto-report-turn', 'text': '请确认下一步负责人。'}).raise_for_status()
        first = self.client.post(f"/api/omega/sessions/{game['id']}/finish", json={'request_key': 'auto-finish-001'})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()['pending_job_id'])
        again = self.client.post(f"/api/omega/sessions/{game['id']}/finish", json={'request_key': 'auto-finish-002'})
        self.assertEqual(again.json()['pending_job_id'], first.json()['pending_job_id'])
        manual = self.client.post(f"/api/omega/sessions/{game['id']}/reports", json={'request_key': 'manual-report-001'})
        self.assertEqual(manual.json()['id'], first.json()['pending_job_id'])
        with Session(self.engine) as db:
            jobs = db.exec(select(OmegaJob).where(OmegaJob.session_id == game['id'], OmegaJob.kind == 'report')).all()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(len(db.exec(select(OmegaSegment).where(OmegaSegment.session_id == game['id'])).all()), 1)

    def test_real_import_automatically_queues_report_once(self):
        self.current = User(id=1, username='seller-a', role='admin', team_key='team-a')
        template = self.template()
        created = self.client.post('/api/omega/template-starts', json=self.start_body(template, usage='real_review')).json()
        meeting = {'id': 'auto-real-001', 'owner_name': 'Alice', 'start_time': '2026-01-01T00:00:00Z',
                   'transcript_segments': [{'speaker': 'Alice', 'text': '请确认日期。'}, {'speaker': 'Buyer', 'text': '还需确认。'}]}
        payload = {'case_id': created['case_id'], 'meeting_id': meeting['id'], 'speaker_map': {'Alice': 'sales', 'Buyer': 'counterparty'}}
        with patch('app.omega.real.vemory_api.meeting_detail', new=AsyncMock(return_value=(meeting, None))):
            first = self.client.post('/api/omega/real-imports', json=payload)
            again = self.client.post('/api/omega/real-imports', json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()['id'], again.json()['id'])
        self.assertTrue(first.json()['pending_job_id'])
        self.assertEqual(first.json()['pending_job_id'], again.json()['pending_job_id'])
        self.assertEqual(first.json()['goal_timing'], 'post')

    def test_real_review_can_create_focused_simulated_practice(self):
        self.current = User(id=1, username='seller-a', role='admin', team_key='team-a')
        with Session(self.engine) as db:
            db.get(User, 1).role = 'admin'
            db.commit()
        template = self.template()
        created = self.client.post('/api/omega/template-starts', json=self.start_body(template, usage='real_review')).json()
        self.assertEqual(self.client.post('/api/omega/sessions', json={'case_id': created['case_id']}).status_code, 409)
        meeting = {'id': 'focused-real-001', 'owner_name': 'Alice', 'transcript_segments': [
            {'speaker': 'Alice', 'text': '请确认日期。'}, {'speaker': 'Buyer', 'text': '还需确认。'}]}
        with patch('app.omega.real.vemory_api.meeting_detail', new=AsyncMock(return_value=(meeting, None))):
            game = self.client.post('/api/omega/real-imports', json={'case_id': created['case_id'],
                'meeting_id': meeting['id'], 'speaker_map': {'Alice': 'sales', 'Buyer': 'counterparty'}}).json()
        with Session(self.engine) as db:
            report = OmegaReport(session_id=game['id'], input_hash='focused-test', content_json=json.dumps({
                'score_weights': WEIGHTS, 'dimensions': [{'key': 'information', 'score': 3}]}))
            db.add(report)
            db.commit()
            report_id = report.id
        assignment = self.client.post('/api/omega/assignments', json={'case_id': created['case_id'],
            'source_report_id': report_id, 'target_dimension': 'information', 'assignee_id': 1})
        self.assertEqual(assignment.status_code, 201, assignment.text)
        practice = self.client.post('/api/omega/sessions', json={'case_id': created['case_id'],
            'assignment_id': assignment.json()['id']})
        self.assertEqual(practice.status_code, 201, practice.text)
        self.assertEqual(practice.json()['mode'], 'rehearsal')
        self.assertTrue(practice.json()['case_snapshot']['simulation'])
        self.assertEqual(practice.json()['case_snapshot']['goal'], game['case_snapshot']['goal'])

    def test_real_import_requires_explicit_roster_mapping_and_preserves_identity(self):
        self.current = User(id=1, username='seller-a', role='admin', team_key='team-a')
        with Session(self.engine) as db:
            db.get(User, 1).role = 'admin'
            db.commit()
        body = {**self.case_body(), 'usage': 'real_review', 'participants': [
            {'id': 'owner', 'name': '老板', 'role': '老板', 'is_primary': True},
            {'id': 'finance', 'name': '财务', 'role': '财务'}]}
        case = self.client.post('/api/omega/cases', json=body).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        meeting = {'id': 'roster-import-001', 'owner_name': 'Alice', 'transcript_segments': [
            {'speaker': 'Alice', 'text': '请确认。'}, {'speaker': 'A', 'text': '我确认采购。'},
            {'speaker': 'B', 'text': '付款还需核对。'}]}
        payload = {'case_id': case['id'], 'meeting_id': meeting['id'],
                   'speaker_map': {'Alice': 'sales', 'A': 'counterparty', 'B': 'counterparty'}}
        with patch('app.omega.real.vemory_api.meeting_detail', new=AsyncMock(return_value=(meeting, None))):
            self.assertEqual(self.client.post('/api/omega/real-imports', json=payload).status_code, 422)
            payload['participant_map'] = {'Alice': 'sales', 'A': 'owner', 'B': 'unknown'}
            self.assertEqual(self.client.post('/api/omega/real-imports', json=payload).status_code, 422)
            payload['participant_map']['B'] = 'finance'
            imported = self.client.post('/api/omega/real-imports', json=payload)
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual([part['speaker_id'] for part in imported.json()['segments']], ['sales', 'owner', 'finance'])
        self.assertEqual([part['source_speaker'] for part in imported.json()['segments']], ['Alice', 'A', 'B'])

    def test_finish_waits_for_realtime_tail_and_rolls_back_if_enqueue_fails(self):
        template = self.template()
        created = self.client.post('/api/omega/template-starts', json=self.start_body(template)).json()
        game_id = created['session_id']
        with Session(self.engine) as db:
            live = OmegaJob(session_id=game_id, kind='realtime', request_key='live-tail-test',
                            request_hash='0' * 64, status='running')
            db.add(live)
            db.add(OmegaSegment(session_id=game_id, seq=1, speaker='sales', text='请确认下一步。'))
            db.commit()
            live_id = live.id
        response = self.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'tail-finish-001'})
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaSession, game_id).status, 'active')
            db.get(OmegaJob, live_id).status = 'succeeded'
            db.commit()
        with patch('app.omega.router.enqueue_report', side_effect=ValueError('queue unavailable')):
            with self.assertRaisesRegex(ValueError, 'queue unavailable'):
                self.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'tail-finish-001'})
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaSession, game_id).status, 'active')
            self.assertEqual(len(db.exec(select(OmegaSegment).where(OmegaSegment.session_id == game_id)).all()), 1)
        ended = self.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'tail-finish-001'})
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertTrue(ended.json()['pending_job_id'])

    def test_incomplete_voice_tail_cannot_finish_or_generate_report(self):
        template = self.template()
        created = self.client.post('/api/omega/template-starts', json=self.start_body(template)).json()
        game_id = created['session_id']
        with Session(self.engine) as db:
            db.add(OmegaJob(session_id=game_id, kind='realtime', request_key='incomplete-tail',
                            request_hash='0' * 64, status='failed', error='语音尾稿未完成，请检查逐字稿后重新演练'))
            db.add(OmegaSegment(session_id=game_id, seq=1, speaker='sales', text='之前已保存的发言。'))
            db.commit()
        response = self.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'finish-incomplete'})
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            game = db.get(OmegaSession, game_id)
            self.assertEqual(game.status, 'active')
            game.status = 'ended'
            # A durable incomplete-input marker must survive a later status change.
            db.exec(select(OmegaJob).where(OmegaJob.session_id == game_id)).one().status = 'succeeded'
            db.commit()
        response = self.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'refinish-incomplete'})
        self.assertEqual(response.status_code, 409, response.text)
        response = self.client.post(f'/api/omega/sessions/{game_id}/reports', json={'request_key': 'report-incomplete'})
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaSegment).where(OmegaSegment.session_id == game_id)).all()), 1)
            self.assertEqual(db.exec(select(OmegaJob).where(OmegaJob.session_id == game_id, OmegaJob.kind == 'report')).all(), [])

    def test_report_freezes_hint_metadata_into_input_hash(self):
        template = self.template()
        game_id = self.client.post('/api/omega/template-starts', json=self.start_body(template)).json()['session_id']
        with Session(self.engine) as db:
            game = db.get(OmegaSession, game_id)
            original_snapshot = json.loads(game.context_snapshot_json)
            hint = OmegaCoachHint(session_id=game_id, request_key='hint-before-finish',
                                  context_revision=game.revision, status='succeeded', text='PRIVATE_HINT_TEXT')
            db.add(hint)
            db.add(OmegaSegment(session_id=game_id, seq=1, speaker='sales', text='请确认下一步。'))
            db.commit()
            expected = [{'id': hint.id, 'created_at': hint.created_at.isoformat(),
                         'context_revision': hint.context_revision}]
        ended = self.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'freeze-hints-finish'})
        self.assertEqual(ended.status_code, 200, ended.text)
        with Session(self.engine) as db:
            game = db.get(OmegaSession, game_id)
            snapshot = json.loads(game.context_snapshot_json)
            self.assertEqual(snapshot, {**original_snapshot, 'report_hints_used': expected})
            self.assertNotIn('PRIVATE_HINT_TEXT', game.context_snapshot_json)
            job = db.exec(select(OmegaJob).where(OmegaJob.session_id == game_id, OmegaJob.kind == 'report')).one()
            self.assertEqual(job.input_hash, report_input_hash(game))
            self.assertEqual(job.request_hash, job.input_hash)
            without_hints = game.model_copy(update={
                'context_snapshot_json': canonical({**snapshot, 'report_hints_used': []})})
            self.assertNotEqual(report_input_hash(without_hints), job.input_hash)

    def test_late_hints_do_not_change_finished_report_input_or_worker_metadata(self):
        from app.omega.jobs import run_once

        template = self.template()
        game_id = self.client.post('/api/omega/template-starts', json=self.start_body(template)).json()['session_id']
        with Session(self.engine) as db:
            hint = OmegaCoachHint(session_id=game_id, request_key='frozen-hint', context_revision=1,
                                  status='succeeded', text='PRIVATE_FROZEN_HINT')
            db.add(hint)
            db.add(OmegaSegment(session_id=game_id, seq=1, speaker='sales', text='请确认下一步。'))
            db.commit()
            hint_id = hint.id
        self.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'first-finish'}).raise_for_status()
        with Session(self.engine) as db:
            game = db.get(OmegaSession, game_id)
            frozen_json, frozen_hash = game.context_snapshot_json, report_input_hash(game)
            expected = json.loads(frozen_json)['report_hints_used']
            db.get(OmegaCoachHint, hint_id).status = 'failed'
            db.add(OmegaCoachHint(session_id=game_id, request_key='late-hint', context_revision=2,
                                 status='succeeded', text='PRIVATE_LATE_HINT'))
            db.commit()
        self.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'finish-replay'}).raise_for_status()
        manual = self.client.post(f'/api/omega/sessions/{game_id}/reports', json={'request_key': 'manual-report-replay'})
        self.assertEqual(manual.status_code, 202, manual.text)
        with Session(self.engine) as db:
            game = db.get(OmegaSession, game_id)
            self.assertEqual(game.context_snapshot_json, frozen_json)
            self.assertEqual(report_input_hash(game), frozen_hash)
            jobs = db.exec(select(OmegaJob).where(OmegaJob.session_id == game_id, OmegaJob.kind == 'report')).all()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].input_hash, frozen_hash)
        result = json.dumps({'outcome': {'status': 'unverified', 'reason': 'No evidence', 'quotes': []},
                             'dimensions': [{'key': key, 'score': None, 'reason': 'No evidence', 'quotes': []}
                                            for key in WEIGHTS], 'next_practice': '确认负责人。'})
        prompts = []
        def generate(kind, messages, limit):
            prompts.extend(messages)
            if kind == 'report_audit':
                return json.dumps(fixtures.positive_report_audit(messages))
            self.assertEqual(kind, 'report')
            return result
        self.assertTrue(run_once(self.engine, generate=generate))
        with Session(self.engine) as db:
            report = db.exec(select(OmegaReport).where(OmegaReport.session_id == game_id)).one()
            self.assertEqual(report.input_hash, frozen_hash)
            self.assertEqual(json.loads(report.content_json)['hints_used'], expected)
        self.assertNotIn('PRIVATE_FROZEN_HINT', json.dumps(prompts))
        self.assertNotIn('PRIVATE_LATE_HINT', json.dumps(prompts))

    def test_legacy_report_queue_keeps_complete_case_snapshot_and_old_report_readable(self):
        template = self.template()
        game_id = self.client.post('/api/omega/template-starts', json=self.start_body(template)).json()['session_id']
        with Session(self.engine) as db:
            game = db.get(OmegaSession, game_id)
            version = db.get(OmegaCaseVersion, game.case_version_id)
            version_json = version.snapshot_json
            game.context_snapshot_json = ''
            game.status = 'ended'
            part = OmegaSegment(session_id=game_id, seq=1, speaker='sales', text='之前的会话原话。')
            db.add(part)
            db.flush()
            game.transcript_hash = transcript_digest([part])
            old_report = OmegaReport(session_id=game_id, input_hash='legacy-report-hash',
                                     content_json=json.dumps({'next_practice': '旧报告原文'}))
            db.add(old_report)
            db.commit()
            old_report_id, old_content = old_report.id, old_report.content_json
        queued = self.client.post(f'/api/omega/sessions/{game_id}/reports', json={'request_key': 'legacy-report-request'})
        self.assertEqual(queued.status_code, 202, queued.text)
        with Session(self.engine) as db:
            game = db.get(OmegaSession, game_id)
            self.assertEqual(json.loads(game.context_snapshot_json), {**json.loads(version_json), 'report_hints_used': []})
            self.assertEqual(db.get(OmegaCaseVersion, game.case_version_id).snapshot_json, version_json)
            job = db.get(OmegaJob, queued.json()['id'])
            self.assertEqual(job.input_hash, report_input_hash(game))
            self.assertEqual(db.get(OmegaReport, old_report_id).content_json, old_content)
        readable = self.client.get(f'/api/omega/reports/{old_report_id}')
        self.assertEqual(readable.status_code, 200, readable.text)
        self.assertEqual(readable.json()['content']['next_practice'], '旧报告原文')

    def test_report_summary_uses_evidence_and_fixed_tie_order(self):
        segment = {'id': 'one', 'speaker': 'sales', 'text': '请确认下一步。'}
        quote = {'segment_id': 'one', 'speaker': 'sales', 'start': 0, 'end': len(segment['text']), 'text': segment['text']}
        body = {'outcome': {'status': 'unverified', 'reason': '尚未承诺', 'quotes': []},
                'dimensions': [{'key': key, 'score': None, 'reason': '覆盖不足', 'quotes': []} for key in WEIGHTS],
                'next_practice': '先问清负责人。'}
        for item in body['dimensions'][1:3]:
            item.update(score=6, reason=item['key'], quotes=[quote])
        checked = validate_report(json.dumps(body), [segment])
        self.assertIsNone(checked['score']['total'])
        self.assertEqual(checked['summary']['strength']['key'], 'information')
        self.assertEqual(checked['summary']['blocker']['key'], 'information')
        self.assertEqual(checked['summary']['next_step'], '先问清负责人。')
        self.assertEqual(checked['summary']['goal_progress']['status'], 'unverified')

    def test_report_keeps_total_unavailable_and_rejects_invalid_post_goal_quotes(self):
        segment = {'id': 'one', 'speaker': 'sales', 'text': '请确认下一步。'}
        quote = {'segment_id': 'one', 'speaker': 'sales', 'start': 0, 'end': len(segment['text']), 'text': segment['text']}
        body = {'outcome': {'status': 'achieved', 'reason': '承诺下一步', 'quotes': [quote]},
                'dimensions': [{'key': key, 'score': maximum, 'reason': '有原话', 'quotes': [quote]}
                               for key, maximum in WEIGHTS.items()]}
        self.assertEqual(validate_report(json.dumps(body), [segment])['score']['total'], 100)
        post = validate_report(json.dumps(body), [segment], goal_timing='post')
        self.assertIsNone(post['score']['total'])
        self.assertEqual(post['score']['available'], 75)
        body = json.loads(json.dumps(body))
        body['outcome']['quotes'][0]['text'] = '伪造原话'
        with self.assertRaisesRegex(ValueError, '引文与当前逐字稿不匹配'):
            validate_report(json.dumps(body), [segment], goal_timing='post')

    def test_report_quote_identity_comes_from_frozen_segment(self):
        from app.omega.reports import verify_quote
        segment = {'id': 'finance-one', 'speaker': 'counterparty', 'speaker_id': 'finance', 'text': '我还需确认。'}
        quote = {'segment_id': segment['id'], 'speaker': 'counterparty', 'speaker_id': 'owner',
                 'start': 0, 'end': len(segment['text']), 'text': segment['text']}
        self.assertFalse(verify_quote(quote, {segment['id']: segment}))
        quote['speaker_id'] = 'finance'
        self.assertTrue(verify_quote(quote, {segment['id']: segment}))
