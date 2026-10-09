"""Live controlled multi-role text/TTS probe on a temporary synthetic database; excludes physical ASR."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from sqlmodel import Session, SQLModel, create_engine, select
    from app.auth.models import User
    from app.omega import memory_models, coaching_models  # noqa: F401
    from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaSegment, OmegaSession
    from app.omega.realtime import VoiceControl, _acquire, _append, _release, _speak_multi_turn

    results = {"at": datetime.now(timezone.utc).isoformat(), "synthetic_only": True,
               "physical_microphone": False, "native_asr_tested": False,
               "roles": [], "interruption": {}, "status": "not_run"}
    people = [{"id": "buyer", "name": "采购", "role": "采购", "is_primary": True,
               "concerns": ["交付安排"], "decision_authority": "unknown"},
              {"id": "finance", "name": "财务", "role": "财务", "is_primary": False,
               "concerns": ["付款安排"], "decision_authority": "unknown"},
              {"id": "boss", "name": "老板", "role": "经理", "is_primary": False,
               "concerns": ["审批条件"], "decision_authority": "unknown"}]
    with tempfile.TemporaryDirectory() as scratch:
        engine = create_engine(f"sqlite:///{Path(scratch) / 'probe.sqlite'}")
        try:
            SQLModel.metadata.create_all(engine)
            user = User(username="omega-synthetic-probe", id=1, role="sales", team_key="synthetic-team")
            with Session(engine) as db:
                db.add(User(**user.model_dump(), hashed_password="synthetic-only"))
                case = OmegaCase(team_key=user.team_key, owner_id=1, title="Synthetic protocol test")
                db.add(case)
                db.flush()
                version = OmegaCaseVersion(case_id=case.id, version=1, confirmed_by=1,
                    content_hash="0" * 64, snapshot_json=json.dumps({"public_brief": "这是无客户数据的演练。",
                        "participants": people, "seller_private": "SYNTHETIC_PRIVATE_LIMIT"}, ensure_ascii=False))
                db.add(version)
                db.flush()
                game = OmegaSession(case_id=case.id, case_version_id=version.id, team_key=user.team_key, owner_id=1)
                db.add(game)
                db.commit()
                session_id = game.id
            job_id, token, _ = _acquire(engine, user, session_id)
            control = VoiceControl(engine, session_id, job_id, token)
            async def turn(index, person, interrupt=False):
                control.interrupt()
                turn_id, epoch = control.turn_id, control.epoch
                _append(engine, session_id, job_id, token, "sales",
                    f"{person['name']}，请说明你负责部分需要先澄清的一个条件。",
                    speaker_id="sales", turn_id=turn_id, provider_event_id=f"synthetic-sales-{index}")
                with Session(engine) as db:
                    revision = db.get(OmegaSession, session_id).revision
                started = time.monotonic()
                class Browser:
                    def __init__(self):
                        self.events, self.audio, self.first_audio_ms = [], bytearray(), None
                    async def send_json(self, event):
                        # Only routing metadata, never text, is written to evidence JSON.
                        self.events.append({key: event.get(key) for key in
                            ("type", "speaker_id", "turn_id", "audio_epoch")})
                    async def send_bytes(self, chunk):
                        if self.first_audio_ms is None:
                            self.first_audio_ms = round((time.monotonic() - started) * 1000)
                        self.audio.extend(chunk)
                        if interrupt:
                            control.interrupt()
                browser = Browser()
                await _speak_multi_turn(browser, control, turn_id, revision, epoch)
                with Session(engine) as db:
                    replies = db.exec(select(OmegaSegment).where(OmegaSegment.session_id == session_id,
                        OmegaSegment.turn_id == turn_id, OmegaSegment.speaker == "counterparty")).all()
                result = {"expected_speaker_id": person["id"], "audio_bytes": len(browser.audio),
                    "first_audio_ms": browser.first_audio_ms, "events": browser.events,
                    "saved_speaker_ids": [part.speaker_id for part in replies],
                    "audio_sha256": hashlib.sha256(browser.audio).hexdigest() if browser.audio else "",
                    "success": bool(browser.audio) and ([part.speaker_id for part in replies] == [person["id"]]
                        if not interrupt else not replies)}
                if browser.audio:
                    with wave.open(str(args.output / f"controlled-{index}-{person['id']}.wav"), "wb") as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(24000)
                        wav.writeframes(browser.audio)
                return result
            for index, person in enumerate(people):
                results["roles"].append(await turn(index, person))
                # Renew the application lease; production receiver renews every four seconds.
                from app.omega.realtime import _renew
                _renew(engine, session_id, job_id, token)
            results["interruption"] = await turn(3, people[0], interrupt=True)
            _release(engine, job_id, token, failed=False)
            results["status"] = "passed" if all(item["success"] for item in results["roles"]) \
                and results["interruption"]["success"] else "failed"
        except Exception as exc:
            results["status"], results["error_type"] = "failed", type(exc).__name__
        finally:
            engine.dispose()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    args.output.mkdir(parents=True, exist_ok=True)
    results = asyncio.run(run(args))
    destination = args.output / f"controlled-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    destination.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": results["status"], "evidence": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
