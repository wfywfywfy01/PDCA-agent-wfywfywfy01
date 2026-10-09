"""Memory stays pending until its owner confirms, with current source permissions."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import User
from app.omega import coaching_models  # noqa: F401
from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaJob, OmegaReport, OmegaSegment, OmegaSession
from app.omega.memory_models import OmegaMemoryEntry, OmegaMemoryProfile, OmegaMemoryProposal, OmegaOpportunity
from app.omega.memory import (
    apply_proposal, create_context_snapshot, dismiss_proposal, profile_view,
    correction_proposal, enqueue_memory_job, propose_report_memory, refresh_proposal, require_opportunity,
)


class OmegaMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{(Path(self.temp.name) / 'memory.sqlite').as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(id=1, username="memory-seller", hashed_password="test", role="sales",
                         team_key="memory-team", sales_name="Alice")
        self.manager = User(id=2, username="memory-manager", hashed_password="test", role="manager",
                            team_key="memory-team")
        self.other = User(id=3, username="memory-other", hashed_password="test", role="sales",
                          team_key="other-team")
        self.db.add_all([self.user, self.manager, self.other])
        self.case = OmegaCase(team_key=self.user.team_key, owner_id=1, title="Memory test")
        self.db.add(self.case)
        self.db.flush()
        self.version = OmegaCaseVersion(case_id=self.case.id, version=1, snapshot_json='{}',
                                        content_hash='a' * 64, confirmed_by=1)
        self.db.add(self.version)
        self.db.flush()
        self.game = OmegaSession(case_id=self.case.id, case_version_id=self.version.id,
                                 team_key=self.user.team_key, owner_id=1, status="ended")
        self.db.add(self.game)
        self.db.flush()
        self.segment = OmegaSegment(session_id=self.game.id, seq=1, speaker="sales", text="请确认采购负责人。")
        self.db.add(self.segment)
        self.report = OmegaReport(session_id=self.game.id, input_hash='b' * 64, content_json='{}')
        self.db.add(self.report)
        self.db.commit()
        self.quote = dict(segment_id=self.segment.id, speaker="sales", start=0,
                          end=len(self.segment.text), text=self.segment.text)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def proposal(self, **changes):
        item = dict(target_kind="sales", section="learning_focus", value="下次先确认采购负责人",
                    classification="inference", quotes=[self.quote])
        item.update(changes)
        row = propose_report_memory(self.db, self.user, self.report, json.dumps({"items": [item]}))
        self.db.commit()
        return row

    def apply(self, proposal, **changes):
        body = dict(request_key="memory-apply-0001", expected_revision=proposal.revision,
                    accept_ids=[json.loads(proposal.payload_json)["items"][0]["id"]], edited_values={})
        body.update(changes)
        return apply_proposal(self.db, self.user, proposal.id, **body)

    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.auth.deps import get_current_user
        from app.database import get_session
        from app.omega.memory_router import router
        from app.omega.router import enabled
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_session] = lambda: self.db
        app.dependency_overrides[enabled] = lambda: None
        return TestClient(app)

    def database_state(self):
        with Session(self.engine) as db:
            return {table.name: [tuple(row) for row in db.execute(
                table.select().order_by(*table.primary_key.columns)).all()]
                for table in sorted(SQLModel.metadata.tables.values(), key=lambda table: table.name)}

    def real_review(self):
        dealer_id = str(uuid4())
        opportunity = OmegaOpportunity(team_key=self.user.team_key, owner_id=self.user.id,
                                       dealer_id=dealer_id, title="合作事项")
        self.db.add(opportunity)
        self.db.flush()
        self.case.dealer_id, self.case.opportunity_id = dealer_id, opportunity.id
        frozen = json.dumps({"dealer_id": dealer_id, "opportunity_id": opportunity.id})
        self.version.snapshot_json = self.game.context_snapshot_json = frozen
        self.game.mode, self.game.source_access_keys_json = "real_review", '["alice"]'
        self.db.commit()
        return dealer_id, opportunity

    def test_pending_is_not_context_and_apply_is_idempotent(self):
        proposal = self.proposal()
        frozen, sources = create_context_snapshot(self.db, self.user, self.case, {})
        self.assertEqual(json.loads(frozen)["memory_context"]["entries"], [])
        self.assertEqual(json.loads(sources), [])
        first = self.apply(proposal)
        self.assertEqual(first["status"], "applied")
        self.assertEqual(self.apply(proposal), first)
        entries = self.db.exec(select(OmegaMemoryEntry)).all()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].classification, "inference")
        frozen, sources = create_context_snapshot(self.db, self.user, self.case, {})
        self.assertEqual(json.loads(frozen)["memory_context"]["entries"][0]["id"], entries[0].id)
        self.assertEqual(json.loads(sources), [self.game.id])

    def test_changed_replay_and_stale_revision_conflict(self):
        proposal = self.proposal()
        with self.assertRaises(HTTPException) as caught:
            self.apply(proposal, expected_revision=99)
        self.assertEqual(caught.exception.status_code, 409)
        self.apply(proposal)
        with self.assertRaises(HTTPException) as caught:
            self.apply(proposal, edited_values={json.loads(proposal.payload_json)["items"][0]["id"]: "修正意见"})
        self.assertEqual(caught.exception.status_code, 409)

    def test_editor_note_keeps_quote_and_original_suggestion(self):
        proposal = self.proposal()
        item_id = json.loads(proposal.payload_json)["items"][0]["id"]
        self.apply(proposal, edited_values={item_id: "先询问对方的决策流程"})
        entry = self.db.exec(select(OmegaMemoryEntry)).one()
        self.assertEqual(entry.classification, "seller_note")
        self.assertEqual(json.loads(entry.quotes_json), [self.quote])
        self.assertEqual(json.loads(proposal.reviewed_json)["original_values"][item_id], "下次先确认采购负责人")

    def test_manager_can_read_but_cannot_apply(self):
        proposal = self.proposal()
        item_id = json.loads(proposal.payload_json)["items"][0]["id"]
        with self.assertRaises(HTTPException) as caught:
            apply_proposal(self.db, self.manager, proposal.id, request_key="manager-apply-001",
                           expected_revision=1, accept_ids=[item_id], edited_values={})
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException) as caught:
            apply_proposal(self.db, self.other, proposal.id, request_key="other-apply-0001",
                           expected_revision=1, accept_ids=[item_id], edited_values={})
        self.assertEqual(caught.exception.status_code, 404)

    def test_rehearsal_cannot_create_dealer_facts_or_counterparty_learning(self):
        with self.assertRaises(ValueError):
            self.proposal(target_kind="dealer", classification="source_fact")
        self.segment.speaker = "counterparty"
        self.segment.text = "同意下单。"
        self.db.commit()
        self.quote.update(speaker="counterparty", text=self.segment.text, end=len(self.segment.text))
        with self.assertRaises(ValueError):
            self.proposal()
        self.assertEqual(self.db.exec(select(OmegaMemoryEntry)).all(), [])

    def test_invalid_quote_and_arbitrary_target_rejected(self):
        with self.assertRaises(ValueError):
            self.proposal(quotes=[{**self.quote, "end": 999}])
        with self.assertRaises(ValueError):
            self.proposal(profile_id=str(uuid4()))

    def test_base_profile_conflict_requires_refresh_and_new_confirmation(self):
        proposal = self.proposal()
        profile = self.db.exec(select(OmegaMemoryProfile)).one()
        profile.revision += 1
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            self.apply(proposal)
        self.assertEqual(caught.exception.status_code, 409)
        refreshed = refresh_proposal(self.db, self.user, proposal.id, request_key="memory-refresh-01", expected_revision=1)
        self.assertEqual(refreshed["revision"], 2)
        self.assertEqual(refreshed["status"], "pending")
        with self.assertRaises(HTTPException):
            self.apply(proposal, expected_revision=1)
        self.apply(proposal, expected_revision=2)

    def test_dismiss_never_writes_entries(self):
        proposal = self.proposal()
        dismissed = dismiss_proposal(self.db, self.user, proposal.id, request_key="memory-dismiss-01", expected_revision=1)
        self.assertEqual(dismissed["status"], "dismissed")
        with self.assertRaises(HTTPException):
            self.apply(proposal)
        self.assertEqual(self.db.exec(select(OmegaMemoryEntry)).all(), [])

    def test_revoked_source_hides_entries_and_frozen_descendants(self):
        proposal = self.proposal()
        self.apply(proposal)
        frozen, source_ids = create_context_snapshot(self.db, self.user, self.case, {})
        descendant = OmegaSession(case_id=self.case.id, case_version_id=self.version.id,
                                  owner_id=1, team_key=self.user.team_key,
                                  context_snapshot_json=frozen, context_source_session_ids_json=source_ids)
        self.db.add(descendant)
        self.game.mode = "real_review"
        self.game.source_access_keys_json = '["revoked-owner"]'
        self.db.commit()
        view = profile_view(self.db, self.user, "sales", "1")
        self.assertEqual(view["entries"], [])
        from app.omega.policy import require_session_source
        with self.assertRaises(HTTPException) as caught:
            require_session_source(self.user, self.db, descendant)
        self.assertEqual(caught.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            self.apply(proposal)

    def test_editing_case_cannot_remove_old_snapshot_customer_permission(self):
        from app.omega.policy import require_session_source
        original_dealer = str(uuid4())
        self.version.snapshot_json = json.dumps({"dealer_id": original_dealer})
        self.case.dealer_id = ""
        self.db.commit()
        with patch("app.omega.policy.require_knowledge_access", side_effect=HTTPException(404, "revoked")):
            with self.assertRaises(HTTPException) as caught:
                require_session_source(self.user, self.db, self.game)
            self.assertEqual(caught.exception.status_code, 404)

    def test_memory_model_excludes_sources_confirmed_after_session_opened(self):
        from app.omega.memory import prepare_memory_job

        dealer_id = str(uuid4())
        self.case.dealer_id = dealer_id
        self.version.snapshot_json = json.dumps({"dealer_id": dealer_id})
        destination = OmegaCase(team_key=self.user.team_key, owner_id=1, title="Independent session")
        self.db.add(destination)
        self.db.flush()
        version = OmegaCaseVersion(case_id=destination.id, version=1, snapshot_json="{}",
                                   content_hash="c" * 64, confirmed_by=1)
        self.db.add(version)
        self.db.flush()
        frozen, sources = create_context_snapshot(self.db, self.user, destination, {})
        game = OmegaSession(case_id=destination.id, case_version_id=version.id,
                            team_key=self.user.team_key, owner_id=1, status="ended",
                            context_snapshot_json=frozen, context_source_session_ids_json=sources)
        self.db.add(game)
        self.db.flush()
        report = OmegaReport(session_id=game.id, input_hash="d" * 64, content_json="{}")
        self.db.add(report)
        self.db.commit()

        secret = "SECRET_FROM_RESTRICTED_SOURCE"
        with patch("app.omega.policy.require_knowledge_access"), patch("app.omega.memory.require_knowledge_access"):
            self.apply(self.proposal(section="strengths", value=secret))
            self.assertEqual(profile_view(self.db, self.user, "sales", "1")["entries"][0]["value"], secret)
            job = enqueue_memory_job(self.db, self.user, report, "later-source-memory-01")
            messages = prepare_memory_job(self.db, self.user, job)
            self.db.commit()
        self.assertEqual(json.loads(game.context_source_session_ids_json), [])
        self.assertNotIn(secret, messages[1]["content"])
        self.assertEqual(json.loads(messages[1]["content"])["current_context"], json.loads(frozen))

        with patch("app.omega.policy.require_knowledge_access", side_effect=HTTPException(403, "revoked")):
            self.assertEqual(profile_view(self.db, self.user, "sales", "1")["entries"], [])
            self.assertEqual(prepare_memory_job(self.db, self.user, job), messages)

    def test_memory_prompt_limits_simulation_evidence_and_keeps_real_review_sources(self):
        from app.omega.memory import memory_input_hash, prepare_memory_job
        from app.omega.reports import verify_quote

        dealer_id = str(uuid4())
        opportunity = OmegaOpportunity(team_key=self.user.team_key, owner_id=1,
                                       dealer_id=dealer_id, title="提示输入隔离测试")
        self.db.add(opportunity)
        self.db.flush()
        self.case.dealer_id, self.case.opportunity_id = dealer_id, opportunity.id
        counterparty = OmegaSegment(session_id=self.game.id, seq=2, speaker="counterparty",
                                    speaker_id="test-buyer", text="这是测试客户的付款承诺。")
        self.db.add(counterparty)
        self.db.flush()
        buyer_quote = {"segment_id": counterparty.id, "speaker": "counterparty",
                       "speaker_id": counterparty.speaker_id, "start": 0,
                       "end": len(counterparty.text), "text": counterparty.text}
        report_only_quote = {"segment_id": "not-a-current-segment", "speaker": "counterparty",
                             "start": 0, "end": 5, "text": "报告独有话"}
        self.report.content_json = json.dumps({"commitments": [{"quotes": [buyer_quote, report_only_quote]}]})
        self.game.source_access_keys_json = '["alice"]'
        self.db.commit()
        source = {self.segment.id: {"speaker": "sales", "text": self.segment.text},
                  counterparty.id: {"speaker": "counterparty", "speaker_id": counterparty.speaker_id,
                                    "text": counterparty.text}}

        with patch("app.omega.memory.require_knowledge_access"), patch("app.omega.policy.require_knowledge_access"):
            for mode in ("training", "rehearsal", "real_review"):
                with self.subTest(mode=mode):
                    self.game.mode = mode
                    frozen = {"usage": mode, "dealer_id": dealer_id, "opportunity_id": opportunity.id,
                              "stage_summary": "会前冻结阶段"}
                    self.game.context_snapshot_json = json.dumps(frozen)
                    self.db.commit()
                    job = OmegaJob(session_id=self.game.id, kind="memory", request_key="prompt-input-" + mode,
                                   request_hash="e" * 64, input_hash=memory_input_hash(self.report, self.game),
                                   session_revision=self.game.revision,
                                   payload_json=json.dumps({"report_id": self.report.id}))
                    messages = prepare_memory_job(self.db, self.user, job)
                    self.db.expunge(job)
                    prompt, data = messages[0]["content"], json.loads(messages[1]["content"])
                    self.assertEqual(data["mode"], mode)
                    self.assertEqual(data["current_context"], frozen)
                    self.assertTrue(all(verify_quote(quote, source) for quote in data["quote_candidates"]))
                    self.assertNotIn(report_only_quote, data["quote_candidates"])
                    self.assertIn("不得从report另取", prompt)
                    self.assertIn("最多3项", prompt)
                    if mode == "real_review":
                        self.assertEqual(set(data["allowed_targets"]), {"sales", "dealer", "opportunity"})
                        self.assertIn("business_context", data["sections"])
                        self.assertEqual(data["quote_candidates"], [self.quote, buyer_quote])
                    else:
                        self.assertEqual(data["allowed_targets"], ["sales"])
                        self.assertEqual(set(data["sections"]), {"learning_focus", "strengths", "growth", "practice_result"})
                        self.assertEqual(data["quote_candidates"], [self.quote])
                        self.assertIn("training或rehearsal", prompt)
                        self.assertIn("只能生成sales成长inference", prompt)
                        self.assertIn("不得生成source_fact", prompt)
                        for changes in ({"target_kind": "dealer", "quotes": [buyer_quote]},
                                        {"classification": "source_fact", "value": self.segment.text},
                                        {"quotes": [buyer_quote]}):
                            with self.assertRaises(ValueError):
                                self.proposal(**changes)
        self.assertEqual(self.db.exec(select(OmegaMemoryEntry)).all(), [])

    def test_opportunities_require_matching_dealer_and_team(self):
        dealer_id = str(uuid4())
        opportunity = OmegaOpportunity(team_key=self.user.team_key, owner_id=1,
                                       dealer_id=dealer_id, title="独立合作事项")
        self.db.add(opportunity)
        self.db.commit()
        with patch("app.omega.memory.require_knowledge_access"):
            self.assertEqual(require_opportunity(self.user, self.db, opportunity.id, dealer_id=dealer_id).id, opportunity.id)
            with self.assertRaises(HTTPException):
                require_opportunity(self.user, self.db, opportunity.id, dealer_id=str(uuid4()))
            with self.assertRaises(HTTPException):
                require_opportunity(self.other, self.db, opportunity.id, dealer_id=dealer_id)

    def test_same_dealer_opportunities_keep_frozen_model_inputs_separate(self):
        from app.omega.context import coach_messages
        from app.omega.memory import prepare_memory_job
        from app.omega.reports import WEIGHTS

        dealer_id = str(uuid4())
        sentinels = ("事项A报价120万元，阶段为法务审核，承诺周一回签。",
                     "事项B报价230万元，阶段为预算审批，承诺周五反馈。")
        cases = []
        with patch("app.omega.memory.require_knowledge_access"), patch("app.omega.policy.require_knowledge_access"):
            for index, sentinel in enumerate(sentinels):
                opportunity = OmegaOpportunity(team_key=self.user.team_key, owner_id=1,
                                               dealer_id=dealer_id, title=f"事项{index}")
                self.db.add(opportunity)
                self.db.flush()
                case = OmegaCase(team_key=self.user.team_key, owner_id=1, title=f"事项场景{index}",
                                 dealer_id=dealer_id, opportunity_id=opportunity.id)
                self.db.add(case)
                self.db.flush()
                snapshot = {"dealer_id": dealer_id, "opportunity_id": opportunity.id, "usage": "real_review"}
                version = OmegaCaseVersion(case_id=case.id, version=1, snapshot_json=json.dumps(snapshot),
                                           content_hash=str(index) * 64, confirmed_by=1)
                self.db.add(version)
                self.db.flush()
                source = OmegaSession(case_id=case.id, case_version_id=version.id, team_key=self.user.team_key,
                    owner_id=1, mode="real_review", status="ended", source_access_keys_json='["alice"]',
                    context_snapshot_json=json.dumps(snapshot))
                self.db.add(source)
                self.db.flush()
                segment = OmegaSegment(session_id=source.id, seq=1, speaker="counterparty", text=sentinel)
                report = OmegaReport(session_id=source.id, input_hash=str(index + 2) * 64, content_json="{}")
                self.db.add_all([segment, report])
                self.db.flush()
                quote = {"segment_id": segment.id, "speaker": segment.speaker, "start": 0,
                         "end": len(sentinel), "text": sentinel}
                proposal = propose_report_memory(self.db, self.user, report, json.dumps({"items": [{
                    "target_kind": "opportunity", "section": "business_context", "value": sentinel,
                    "classification": "source_fact", "quotes": [quote]}]}))
                self.db.commit()
                self.apply(proposal, request_key=f"opportunity-confirm-{index}")
                cases.append((case, version, snapshot, source.id))

            for index, (case, version, snapshot, source_id) in enumerate(cases):
                frozen, sources = create_context_snapshot(self.db, self.user, case, snapshot)
                opening = json.loads(frozen)
                self.assertEqual(json.loads(sources), [source_id])
                self.assertEqual([entry["value"] for entry in opening["memory_context"]["entries"]], [sentinels[index]])
                self.assertEqual(opening["memory_context"]["profiles"][0]["subject_id"], case.opportunity_id)
                game = OmegaSession(case_id=case.id, case_version_id=version.id, team_key=self.user.team_key,
                    owner_id=1, mode="real_review", status="ended", source_access_keys_json='["alice"]',
                    context_snapshot_json=frozen, context_source_session_ids_json=sources)
                self.db.add(game)
                self.db.flush()
                report = OmegaReport(session_id=game.id, input_hash=str(index + 4) * 64, content_json="{}")
                self.db.add(report)
                self.db.flush()
                job = enqueue_memory_job(self.db, self.user, report, f"opportunity-memory-{index}")
                self.db.commit()
                memory_input = prepare_memory_job(self.db, self.user, job)[1]["content"]
                report_input = coach_messages(opening, [], WEIGHTS)[1]["content"]
                for model_input in (memory_input, report_input):
                    self.assertIn(sentinels[index], model_input)
                    self.assertNotIn(sentinels[1 - index], model_input)
                self.assertEqual(json.loads(memory_input)["current_context"], opening)
                self.assertEqual(game.context_snapshot_json, frozen)

    def test_http_subset_confirmation_updates_each_selected_profile_once_with_audit(self):
        dealer_id, opportunity = self.real_review()
        specifications = (("sales", "learning_focus", "先确认采购负责人"),
                          ("sales", "strengths", "善于澄清决策角色"),
                          ("dealer", "next_steps", self.segment.text),
                          ("dealer", "cooperation", "排除的代理建议"),
                          ("opportunity", "business_context", "当前事项需要明确负责人"),
                          ("opportunity", "next_steps", "排除的事项建议"))
        candidates = [{"target_kind": kind, "section": section, "value": value,
                       "classification": "source_fact" if kind == "dealer" and section == "next_steps" else "inference",
                       "quotes": [self.quote]} for kind, section, value in specifications]
        with patch("app.omega.memory.require_knowledge_access"), patch("app.omega.policy.require_knowledge_access"):
            proposal = propose_report_memory(self.db, self.user, self.report, json.dumps({"items": candidates}))
            self.db.commit()
            items = json.loads(proposal.payload_json)["items"]
            selected = [items[index]["id"] for index in (0, 1, 2, 4)]
            edited = {items[1]["id"]: "销售确认后的澄清建议"}
            body = {"request_key": "subset-confirmation-01", "expected_revision": 1,
                    "accept_ids": selected, "edited_values": edited}
            with self.client() as client:
                response = client.post(f"/api/omega/memory-proposals/{proposal.id}/apply", json=body)
                self.assertEqual(response.status_code, 200, response.text)
                reviewed = response.json()["reviewed"]
                self.assertEqual(reviewed["accept_ids"], selected)
                self.assertEqual(reviewed["edited_values"], edited)
                self.assertEqual(reviewed["original_values"], {item["id"]: item["value"] for item in items if item["id"] in selected})
                self.assertEqual(response.json()["applied_by"], self.user.id)
                self.assertIsNotNone(response.json()["applied_at"])
                state = self.database_state()
                replay = client.post(f"/api/omega/memory-proposals/{proposal.id}/apply", json=body)
                self.assertEqual(replay.json(), response.json())
                self.assertEqual(self.database_state(), state)
            entries = self.db.exec(select(OmegaMemoryEntry)).all()
            self.assertEqual({entry.item_id for entry in entries}, set(selected))
            self.assertEqual(len(entries), 4)
            profiles = self.db.exec(select(OmegaMemoryProfile)).all()
            self.assertEqual({(profile.kind, profile.subject_id, profile.revision) for profile in profiles},
                             {("sales", "1", 1), ("dealer", dealer_id, 1), ("opportunity", opportunity.id, 1)})
            for entry in entries:
                self.assertEqual((entry.created_by, entry.source_session_id, entry.source_report_id, entry.proposal_id),
                                 (self.user.id, self.game.id, self.report.id, proposal.id))
                self.assertEqual(json.loads(entry.quotes_json), [self.quote])
                self.assertIsNotNone(entry.created_at)
                original = next(item for item in items if item["id"] == entry.item_id)
                self.assertEqual(entry.value, edited.get(entry.item_id, original["value"]))
                self.assertEqual(entry.classification, "seller_note" if entry.item_id in edited else original["classification"])

    def test_pending_apply_after_source_revocation_or_disabled_actor_changes_no_tables(self):
        self.real_review()
        with patch("app.omega.memory.require_knowledge_access"), patch("app.omega.policy.require_knowledge_access"):
            proposal = self.proposal()
            item_id = json.loads(proposal.payload_json)["items"][0]["id"]
            body = {"request_key": "revoked-pending-apply", "expected_revision": 1, "accept_ids": [item_id]}
            with self.client() as client:
                with patch("app.omega.policy.require_knowledge_access", side_effect=HTTPException(404, "revoked")):
                    before = self.database_state()
                    response = client.post(f"/api/omega/memory-proposals/{proposal.id}/apply", json=body)
                    self.assertEqual(response.status_code, 404, response.text)
                    self.assertEqual(self.database_state(), before)
                for active, sales_name, status in ((True, "NoSourcePermission", 404), (False, "Alice", 403)):
                    with self.subTest(active=active, sales_name=sales_name):
                        with Session(self.engine) as db:
                            actor = db.get(User, self.user.id)
                            actor.is_active, actor.sales_name = active, sales_name
                            db.commit()
                        before = self.database_state()
                        response = client.post(f"/api/omega/memory-proposals/{proposal.id}/apply", json=body)
                        self.assertEqual(response.status_code, status, response.text)
                        self.assertEqual(self.database_state(), before)
            self.db.expire_all()
            self.assertEqual(self.db.get(OmegaMemoryProposal, proposal.id).status, "pending")
            self.assertEqual(self.db.exec(select(OmegaMemoryEntry)).all(), [])

    def test_http_tampered_subject_profile_item_and_proposal_ids_write_nothing(self):
        dealer_id, opportunity = self.real_review()
        foreign_dealer = str(uuid4())
        self.other.sales_name = "Bob"
        foreign_opportunity = OmegaOpportunity(team_key=self.other.team_key, owner_id=self.other.id,
                                               dealer_id=foreign_dealer, title="其他团队事项")
        self.db.add(foreign_opportunity)
        self.db.flush()
        foreign_case = OmegaCase(team_key=self.other.team_key, owner_id=self.other.id,
            title="其他团队场景", dealer_id=foreign_dealer, opportunity_id=foreign_opportunity.id)
        self.db.add(foreign_case)
        self.db.flush()
        snapshot = json.dumps({"dealer_id": foreign_dealer, "opportunity_id": foreign_opportunity.id})
        foreign_version = OmegaCaseVersion(case_id=foreign_case.id, version=1, snapshot_json=snapshot,
                                           content_hash="f" * 64, confirmed_by=self.other.id)
        self.db.add(foreign_version)
        self.db.flush()
        foreign_game = OmegaSession(case_id=foreign_case.id, case_version_id=foreign_version.id,
            owner_id=self.other.id, team_key=self.other.team_key, mode="real_review", status="ended",
            source_access_keys_json='["bob"]', context_snapshot_json=snapshot)
        self.db.add(foreign_game)
        self.db.flush()
        sentinel = "OTHER_TEAM_MEMORY_MUST_REMAIN_PRIVATE"
        foreign_segment = OmegaSegment(session_id=foreign_game.id, seq=1, speaker="sales", text=sentinel)
        foreign_report = OmegaReport(session_id=foreign_game.id, input_hash="f" * 64, content_json="{}")
        self.db.add_all([foreign_segment, foreign_report])
        self.db.commit()
        foreign_quote = {"segment_id": foreign_segment.id, "speaker": "sales", "start": 0,
                         "end": len(sentinel), "text": sentinel}

        def authorize_dealer(actor, db, identifier):
            allowed = {self.user.team_key: dealer_id, self.other.team_key: foreign_dealer}
            if str(identifier) != allowed.get(actor.team_key):
                raise HTTPException(404, "dealer outside current scope")

        def candidates(value, quote):
            return json.dumps({"items": [{"target_kind": kind, "section": "learning_focus", "value": value,
                "classification": "inference", "quotes": [quote]} for kind in ("sales", "dealer", "opportunity")]})

        with patch("app.omega.memory.require_knowledge_access", side_effect=authorize_dealer), \
             patch("app.omega.policy.require_knowledge_access", side_effect=authorize_dealer):
            own = propose_report_memory(self.db, self.user, self.report, candidates("当前团队的确认建议", self.quote))
            foreign = propose_report_memory(self.db, self.other, foreign_report, candidates(sentinel, foreign_quote))
            self.db.commit()
            self.apply(own, accept_ids=[item["id"] for item in json.loads(own.payload_json)["items"]])
            apply_proposal(self.db, self.other, foreign.id, request_key="foreign-confirm-01", expected_revision=1,
                accept_ids=[item["id"] for item in json.loads(foreign.payload_json)["items"]], edited_values={})
            own_entries = self.db.exec(select(OmegaMemoryEntry).where(OmegaMemoryEntry.proposal_id == own.id)).all()
            foreign_entries = self.db.exec(select(OmegaMemoryEntry).where(OmegaMemoryEntry.proposal_id == foreign.id)).all()
            profiles = {profile.id: profile for profile in self.db.exec(select(OmegaMemoryProfile)).all()}
            own_entry = next(entry for entry in own_entries if profiles[entry.profile_id].kind == "sales")
            foreign_entry = next(entry for entry in foreign_entries if profiles[entry.profile_id].kind == "sales")
            own_dealer_profile = next(entry.profile_id for entry in own_entries if profiles[entry.profile_id].kind == "dealer")
            correction = correction_proposal(self.db, self.user, own_entry.profile_id, entry_id=own_entry.id,
                explanation="本人确认的修正", request_key="authorized-correction-01")
            item_id = correction["payload"]["items"][0]["id"]
            body = {"request_key": "authorized-correction-apply", "expected_revision": 1, "accept_ids": [item_id]}
            correction_body = {"request_key": "tampered-correction-01", "entry_id": own_entry.id, "explanation": "不应写入"}
            apply_path = f"/api/omega/memory-proposals/{correction['id']}/apply"
            unknown = str(uuid4())
            cases = [
                ("GET", "/api/omega/profiles?kind=sales&subject_id=3", None, 404),
                ("GET", "/api/omega/profiles?kind=sales&subject_id=01", None, 404),
                ("GET", "/api/omega/profiles?kind=sales&subject_id=unknown", None, 404),
                ("GET", f"/api/omega/profiles?kind=dealer&subject_id={foreign_dealer}", None, 404),
                ("GET", f"/api/omega/profiles?kind=opportunity&subject_id={foreign_opportunity.id}", None, 404),
                ("GET", "/api/omega/profiles?kind=unknown&subject_id=1", None, 422),
                ("GET", f"/api/omega/reports/{foreign_report.id}/memory-proposal", None, 404),
                ("GET", f"/api/omega/reports/{unknown}/memory-proposal", None, 404),
                ("POST", f"/api/omega/memory-proposals/{foreign.id}/apply", body, 404),
                ("POST", f"/api/omega/memory-proposals/{unknown}/apply", body, 404),
                ("POST", apply_path, {**body, "accept_ids": [foreign_entry.item_id]}, 422),
                ("POST", apply_path, {**body, "accept_ids": [unknown]}, 422),
                ("POST", apply_path, {**body, "accept_ids": [item_id, item_id]}, 422),
                ("POST", apply_path, {**body, "edited_values": {foreign_entry.item_id: "不应写入"}}, 422),
                ("POST", apply_path, {**body, "profile_id": foreign_entry.profile_id}, 422),
                ("POST", apply_path, {**body, "subject_id": "3"}, 422),
                ("POST", apply_path, {**body, "target_kind": "dealer"}, 422),
                ("POST", f"/api/omega/profiles/{own_entry.profile_id}/corrections",
                 {**correction_body, "entry_id": foreign_entry.id}, 404),
                ("POST", f"/api/omega/profiles/{foreign_entry.profile_id}/corrections",
                 {**correction_body, "entry_id": foreign_entry.id}, 404),
                ("POST", f"/api/omega/profiles/{unknown}/corrections", correction_body, 404),
                ("POST", f"/api/omega/profiles/{own_entry.profile_id}/corrections",
                 {**correction_body, "entry_id": unknown}, 404),
                ("POST", f"/api/omega/profiles/{own_dealer_profile}/corrections", correction_body, 404),
            ]
            with self.client() as client:
                before = self.database_state()
                for kind, subject in (("sales", "1"), ("dealer", dealer_id), ("opportunity", opportunity.id)):
                    response = client.get(f"/api/omega/profiles?kind={kind}&subject_id={subject}")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(len(response.json()["entries"]), 1)
                    self.assertNotIn(sentinel, response.text)
                self.assertEqual(client.get(f"/api/omega/reports/{self.report.id}/memory-proposal").status_code, 200)
                self.assertEqual(self.database_state(), before)
                for method, path, payload, status in cases:
                    with self.subTest(method=method, path=path, payload=payload):
                        response = client.request(method, path, json=payload)
                        self.assertEqual(response.status_code, status, response.text)
                        self.assertNotIn(sentinel, response.text)
                        self.assertEqual(self.database_state(), before)
                owner = self.user
                try:
                    self.user = self.manager
                    self.assertEqual(client.get("/api/omega/profiles?kind=sales&subject_id=1").status_code, 200)
                    self.assertEqual(client.post(apply_path, json=body).status_code, 403)
                    self.assertEqual(self.database_state(), before)
                finally:
                    self.user = owner
                response = client.post(apply_path, json=body)
                self.assertEqual(response.status_code, 200, response.text)
                changed = self.db.exec(select(OmegaMemoryEntry).where(OmegaMemoryEntry.proposal_id == correction["id"])).one()
                self.assertEqual((changed.created_by, changed.source_session_id, changed.source_report_id),
                                 (owner.id, self.game.id, self.report.id))
                self.assertEqual(changed.supersedes_id, own_entry.id)

    def test_two_profiles_rollback_when_second_write_fails(self):
        self.case.dealer_id = str(uuid4())
        self.game.context_snapshot_json = json.dumps({"dealer_id": self.case.dealer_id})
        self.game.mode = "real_review"
        self.game.source_access_keys_json = '["alice"]'
        self.db.commit()
        items = [{"target_kind": kind, "section": "learning_focus", "value": "仍需明确负责人",
                  "classification": "inference", "quotes": [self.quote]} for kind in ["sales", "dealer"]]
        with patch("app.omega.memory.require_knowledge_access"), patch("app.omega.policy.require_knowledge_access"):
            proposal = propose_report_memory(self.db, self.user, self.report, json.dumps({"items": items}))
            self.db.commit()
            item_ids = [item["id"] for item in json.loads(proposal.payload_json)["items"]]
            original = self.db.add
            calls = []
            def fail_second(row, *args, **kwargs):
                if isinstance(row, OmegaMemoryEntry):
                    calls.append(row)
                    if len(calls) == 2:
                        raise RuntimeError("injected second profile failure")
                return original(row, *args, **kwargs)
            with patch.object(self.db, "add", side_effect=fail_second):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    apply_proposal(self.db, self.user, proposal.id, request_key="atomic-failure-01",
                                   expected_revision=1, accept_ids=item_ids, edited_values={})
            self.assertEqual(self.db.exec(select(OmegaMemoryEntry)).all(), [])
            self.assertEqual([p.revision for p in self.db.exec(select(OmegaMemoryProfile)).all()], [0, 0])
            self.assertEqual(self.db.get(OmegaMemoryProposal, proposal.id).status, "pending")

    def test_real_review_memory_target_stays_with_frozen_dealer(self):
        from app.omega.memory import targets
        original, changed = str(uuid4()), str(uuid4())
        self.game.mode = "real_review"
        self.game.source_access_keys_json = '["alice"]'
        self.game.context_snapshot_json = json.dumps({"dealer_id": original})
        self.case.dealer_id = changed
        self.db.commit()
        with patch("app.omega.memory.require_knowledge_access"), patch("app.omega.policy.require_knowledge_access"):
            self.assertEqual(targets(self.db, self.user, self.game)["dealer"], original)
            proposal = self.proposal(target_kind="dealer")
            item = json.loads(proposal.payload_json)["items"][0]
            profile = self.db.get(OmegaMemoryProfile, item["profile_id"])
            self.assertEqual(profile.subject_id, original)

    def test_correction_is_pending_preserves_history_and_replays(self):
        proposal = self.proposal()
        self.apply(proposal)
        entry = self.db.exec(select(OmegaMemoryEntry)).one()
        correction = correction_proposal(self.db, self.user, entry.profile_id, entry_id=entry.id,
                            explanation="销售修正说明", request_key="memory-correction-01")
        self.assertEqual(correction["status"], "pending")
        self.assertEqual(profile_view(self.db, self.user, "sales", "1")["entries"][0]["value"], entry.value)
        apply_proposal(self.db, self.user, correction["id"], request_key="correct-confirm-01",
                       expected_revision=1, accept_ids=[correction["payload"]["items"][0]["id"]], edited_values={})
        self.assertEqual(profile_view(self.db, self.user, "sales", "1")["entries"][0]["classification"], "seller_note")
        self.assertFalse(self.db.get(OmegaMemoryEntry, entry.id).is_current)
        self.assertEqual(len(self.db.exec(select(OmegaMemoryEntry)).all()), 2)
        replay = correction_proposal(self.db, self.user, entry.profile_id, entry_id=entry.id,
                            explanation="销售修正说明", request_key="memory-correction-01")
        self.assertEqual(replay["status"], "applied")

    def test_memory_worker_failure_keeps_report_and_explicit_retry_succeeds(self):
        from app.omega.jobs import run_once
        job = enqueue_memory_job(self.db, self.user, self.report, "memory-worker-0001")
        job_id = job.id
        self.db.commit()
        self.assertTrue(run_once(self.engine, generate=lambda *args: "invalid model output"))
        self.db.expire_all()
        self.assertEqual(self.db.get(OmegaJob, job_id).status, "failed")
        self.assertIsNotNone(self.db.get(OmegaReport, self.report.id))
        self.assertEqual(self.db.exec(select(OmegaMemoryEntry)).all(), [])
        retry = enqueue_memory_job(self.db, self.user, self.report, "memory-worker-0002")
        retry_id = retry.id
        self.db.commit()
        raw = json.dumps({"items": [{"target_kind": "sales", "section": "learning_focus",
                         "value": "下次先确认负责人", "classification": "inference", "quotes": [self.quote]}]})
        self.assertTrue(run_once(self.engine, generate=lambda *args: raw))
        self.db.expire_all()
        self.assertEqual(self.db.get(OmegaJob, retry_id).status, "succeeded")
        self.assertEqual(self.db.exec(select(OmegaMemoryProposal)).one().status, "pending")
        self.assertEqual(self.db.exec(select(OmegaMemoryEntry)).all(), [])

    def test_worker_rechecks_source_after_model_returns(self):
        from app.omega.jobs import run_once
        job = enqueue_memory_job(self.db, self.user, self.report, "memory-revoke-0001")
        job_id = job.id
        self.db.commit()
        def revoke(*args):
            with Session(self.engine) as db:
                game = db.get(OmegaSession, self.game.id)
                game.mode, game.source_access_keys_json = "real_review", '["revoked"]'
                db.commit()
            return '{"items": []}'
        self.assertTrue(run_once(self.engine, generate=revoke))
        self.db.expire_all()
        self.assertEqual(self.db.get(OmegaJob, job_id).status, "failed")
        self.assertEqual(self.db.exec(select(OmegaMemoryProposal)).all(), [])

    def test_report_success_automatically_queues_proposal_and_http_can_apply(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.auth.deps import get_current_user
        from app.database import get_session
        from app.omega.jobs import run_once
        from app.omega.memory_router import router
        from app.omega.router import enabled, report_input_hash, transcript_digest
        from app.omega.reports import WEIGHTS
        self.game.transcript_hash = transcript_digest([self.segment])
        report_job = OmegaJob(session_id=self.game.id, kind="report", request_key="auto-report-0001",
                              request_hash="a" * 64, input_hash=report_input_hash(self.game),
                              session_revision=self.game.revision)
        self.db.add(report_job)
        job_id = report_job.id
        self.db.commit()
        report_content = {"outcome": {"status": "unverified", "reason": "无承诺", "quotes": []},
                          "dimensions": [{"key": key, "score": None, "reason": "证据不足", "quotes": []}
                                         for key in WEIGHTS]}
        self.assertTrue(run_once(self.engine, generate=lambda *args: json.dumps(report_content)))
        self.db.expire_all()
        report_id = self.db.get(OmegaJob, job_id).result_id
        memory_jobs = self.db.exec(select(OmegaJob).where(OmegaJob.kind == "memory")).all()
        self.assertEqual(len(memory_jobs), 1)
        self.assertEqual(json.loads(memory_jobs[0].payload_json)["report_id"], report_id)
        raw = json.dumps({"items": [{"target_kind": "sales", "section": "learning_focus",
                         "value": "下次先确认负责人", "classification": "inference", "quotes": [self.quote]}]})
        self.assertTrue(run_once(self.engine, generate=lambda *args: raw))
        self.db.expire_all()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_session] = lambda: self.db
        app.dependency_overrides[enabled] = lambda: None
        with TestClient(app) as client:
            response = client.get(f"/api/omega/reports/{report_id}/memory-proposal")
            self.assertEqual(response.status_code, 200, response.text)
            proposal = response.json()["proposal"]
            self.assertEqual(response.json()["generation"]["status"], "succeeded")
            saved = client.post(f"/api/omega/memory-proposals/{proposal['id']}/apply", json={
                "request_key": "http-auto-apply-01", "expected_revision": proposal["revision"],
                "accept_ids": [proposal["payload"]["items"][0]["id"]]})
            self.assertEqual(saved.status_code, 200, saved.text)
            profile = client.get("/api/omega/profiles?kind=sales&subject_id=1")
            self.assertEqual(profile.status_code, 200, profile.text)
            self.assertEqual(profile.json()["entries"][0]["classification"], "inference")

    def test_http_apply_rejects_unknown_fields_and_empty_selection(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.auth.deps import get_current_user
        from app.database import get_session
        from app.omega.memory_router import router
        from app.omega.router import enabled
        proposal = self.proposal()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_session] = lambda: self.db
        app.dependency_overrides[enabled] = lambda: None
        with TestClient(app) as client:
            response = client.get(f"/api/omega/reports/{self.report.id}/memory-proposal")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["proposal"]["can_apply"])
            body = {"request_key": "memory-http-0001", "expected_revision": 1, "accept_ids": []}
            self.assertEqual(client.post(f"/api/omega/memory-proposals/{proposal.id}/apply", json=body).status_code, 422)
            body.update(accept_ids=[response.json()["proposal"]["payload"]["items"][0]["id"]], classification="source_fact")
            self.assertEqual(client.post(f"/api/omega/memory-proposals/{proposal.id}/apply", json=body).status_code, 422)


class OmegaParticipantContextTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"participants": [
            {"id": "buyer", "name": "王经理", "role": "采购负责人", "is_primary": True,
             "concerns": ["采购预算"], "known_facts": ["采购自己的信息"]},
            {"id": "finance", "name": "李总", "role": "财务负责人", "is_primary": False,
             "concerns": ["付款节点"], "known_facts": ["财务自己的信息"]}],
            "seller_private": "销售私有信息", "memory_context": {"entries": [{"value": "私人教练记忆"}]}}

    def test_addressed_role_overrides_topic_then_primary_is_fallback(self):
        from app.omega.context import select_next_speaker
        self.assertEqual(select_next_speaker(self.snapshot, [{"speaker": "sales", "text": "李总，请说明采购预算"}])["id"], "finance")
        self.assertEqual(select_next_speaker(self.snapshot, [{"speaker": "sales", "text": "我们确认一下付款节点"}])["id"], "finance")
        self.assertEqual(select_next_speaker(self.snapshot, [{"speaker": "sales", "text": "欢迎大家"}])["id"], "buyer")

    def test_selected_actor_receives_own_facts_only(self):
        from app.omega.context import actor_messages
        prompt = actor_messages(self.snapshot, [{"speaker": "sales", "text": "李总，请介绍现状"}])[0]["content"]
        self.assertIn("财务自己的信息", prompt)
        self.assertNotIn("采购自己的信息", prompt)
        self.assertNotIn("销售私有信息", prompt)
        self.assertNotIn("私人教练记忆", prompt)
