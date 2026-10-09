"""Opt-in live text-model smoke with synthetic data and a disposable SQLite DB.

Checks publication, evidence validation and pending memory, not scoring quality.
Credentials are loaded selectively from --env-file and never written to evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values
import httpx
from sqlmodel import Session, select

from app.omega.jobs import _default_generate, run_once
from app.omega.memory_models import OmegaMemoryEntry, OmegaMemoryProposal
from app.omega.models import OmegaJob, OmegaReport, OmegaSegment, OmegaSession
from tests.test_omega_flow import OmegaFlowTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    names = ('PDCA_SUPERVISOR_PROVIDER', 'PDCA_SUPERVISOR_MODEL', 'PDCA_SUPERVISOR_API_KEY')
    settings = {name: values.get(name) or os.environ.get(name, '') for name in names}
    if not all(settings.values()):
        raise SystemExit('Text model configuration is incomplete')
    if settings[names[0]].rstrip('/') != 'https://api.deepseek.com':
        raise SystemExit('This acceptance probe is restricted to the configured DeepSeek service')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    evidence = {'at_utc': datetime.now(timezone.utc).isoformat(), 'synthetic_only': True,
                'model': settings[names[1]], 'scoring_quality_accepted': False, 'calls': [], 'status': 'failed'}
    fixture = OmegaFlowTests()
    fixture.setUp()

    def generate(kind, messages, limit):
        started = time.monotonic()
        try:
            result = _default_generate(kind, messages, limit)
        except Exception as exc:
            failure = {'kind': kind, 'error_type': type(exc).__name__}
            if isinstance(exc, httpx.HTTPStatusError):
                failure['http_status'] = exc.response.status_code
                failure['provider_host'] = urlsplit(str(exc.request.url)).hostname
            evidence['calls'].append(failure)
            raise
        evidence['calls'].append({'kind': kind, 'seconds': round(time.monotonic() - started, 3),
                                  'characters': len(result)})
        evidence.setdefault('synthetic_outputs', []).append({'kind': kind, 'text': result})
        return result

    try:
        with patch.dict(os.environ, settings):
            body = {**fixture.case_body(), 'title': '合成验收：试单审批', 'usage': 'training',
                    'public_brief': '这是合成训练。讨论试单，对方尚未批准。',
                    'counterparty_brief': '采购关注价格，财务关注预算，老板负责最终批准。',
                    'participants': [{'id': 'buyer', 'name': '采购', 'role': '采购', 'is_primary': True},
                                     {'id': 'finance', 'name': '财务', 'role': '财务'},
                                     {'id': 'owner', 'name': '老板', 'role': '老板'}],
                    'goal': {'outcome_type': 'new_order', 'success_condition': '取得老板对试单数量和交期的书面确认',
                             'ideal': '确认试单', 'minimum': '明确下一步确认时间', 'hard_limits': ['不承诺未经核实的折扣和交期']}}
            case = fixture.client.post('/api/omega/cases', json=body)
            case.raise_for_status()
            fixture.client.post(f"/api/omega/cases/{case.json()['id']}/confirm").raise_for_status()
            response = fixture.client.post('/api/omega/sessions', json={'case_id': case.json()['id']})
            response.raise_for_status()
            game_id = response.json()['id']
            transcript = [
                ('sales', 'sales', '先确认一下，试单除了采购意见，还需要谁批准？'),
                ('counterparty', 'buyer', '我认可产品方向，但最终得老板确认价格和交期。'),
                ('sales', 'sales', '财务，您现在主要担心预算，还是付款安排？'),
                ('counterparty', 'finance', '预算还没批，我目前不能承诺付款。'),
                ('sales', 'sales', '那我今天整理试单建议，老板明天下午能给一个审批时间吗？'),
                ('counterparty', 'owner', '我还没批准试单，先看资料。回复时间也暂时不能确定。'),
            ]
            with Session(fixture.engine) as db:
                game = db.get(OmegaSession, game_id)
                game.voice_state = 'coaching'
                for seq, (speaker, speaker_id, text) in enumerate(transcript, 1):
                    db.add(OmegaSegment(session_id=game_id, seq=seq, speaker=speaker, speaker_id=speaker_id,
                                        turn_id=f'synthetic-{seq}', text=text))
                game.revision += len(transcript)
                db.commit()
            fixture.client.post(f'/api/omega/sessions/{game_id}/coach-hints', json={'request_key': 'live-text-hint'}).raise_for_status()
            assert run_once(fixture.engine, generate=generate)
            hints = fixture.client.get(f'/api/omega/sessions/{game_id}/coach-hints').json()
            assert any(hint['status'] == 'succeeded' and hint['text'] for hint in hints), 'coach did not publish'
            fixture.client.post(f'/api/omega/sessions/{game_id}/finish', json={'request_key': 'live-text-finish'}).raise_for_status()
            # A schema rejection may schedule the existing one bounded report retry.
            for _ in range(4):
                if not run_once(fixture.engine, generate=generate):
                    break
            with Session(fixture.engine) as db:
                reports = db.exec(select(OmegaReport).where(OmegaReport.session_id == game_id)).all()
                assert len(reports) == 1, [(job.kind, job.status, job.error) for job in db.exec(select(OmegaJob)).all()]
                report = json.loads(reports[0].content_json)
                assert report['outcome']['status'] != 'achieved', 'unapproved order was scored as achieved'
                assert len(report['dimensions']) == 9
                proposal = db.exec(select(OmegaMemoryProposal).where(OmegaMemoryProposal.session_id == game_id)).one()
                assert proposal.status == 'pending'
                assert db.exec(select(OmegaMemoryEntry)).all() == [], 'unconfirmed memory became effective'
                evidence.update(status='passed', report=report, memory_proposal=json.loads(proposal.payload_json))
    except Exception as exc:
        evidence['error_type'] = type(exc).__name__
        raise
    finally:
        fixture.tearDown()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: evidence[key] for key in ('status', 'model', 'synthetic_only', 'calls')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
