"""Opt-in real native ASR/pause adapter probe using only a fixed synthetic phrase."""
from __future__ import annotations

import argparse
from array import array
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import wave
from datetime import datetime, timezone

from dotenv import load_dotenv
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from sqlmodel import Session, SQLModel, create_engine, select
    from app.auth.models import User
    from app.omega import memory_models, coaching_models  # noqa: F401
    from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaSegment, OmegaSession
    from app.omega.realtime import (VoiceControl, _acquire, _doubao_handshake, _doubao_url,
        _receive_doubao_audio, _release, _renew)
    from omega_voice_capability_probe import probe

    result = {"at": datetime.now(timezone.utc).isoformat(), "synthetic_only": True,
              "physical_microphone": False, "status": "not_run", "events": [], "browser": []}
    synthesized = await probe(argparse.Namespace(case="voice", repeat=1, independent=True,
        synthesize=True, hold_seconds=0, output=args.output))
    if synthesized["status"] != "completed":
        result["status"] = "synthesis_failed"
        return result
    with wave.open(str(args.output / "synthetic-voice-0-1.wav"), "rb") as wav:
        source = array("h", wav.readframes(wav.getnframes()))
    pcm = array("h", (source[index * 3 // 2] for index in range(len(source) * 2 // 3))).tobytes()
    if args.silence:
        pcm = bytes(32000)
        result["digital_silence_only"] = True
    with tempfile.TemporaryDirectory() as scratch:
        engine = create_engine(f"sqlite:///{Path(scratch) / 'probe.sqlite'}")
        receiving = heartbeat = None
        control = None
        try:
            SQLModel.metadata.create_all(engine)
            user = User(id=1, username="synthetic-pause-probe", role="sales", team_key="synthetic")
            with Session(engine) as db:
                db.add(User(**user.model_dump(), hashed_password="synthetic-only"))
                case = OmegaCase(owner_id=1, team_key="synthetic", title="Synthetic native pause")
                db.add(case)
                db.flush()
                version = OmegaCaseVersion(case_id=case.id, version=1, confirmed_by=1,
                    content_hash="0" * 64, snapshot_json=json.dumps({"public_brief": "固定合成语音协议测试。"}))
                db.add(version)
                db.flush()
                game = OmegaSession(case_id=case.id, case_version_id=version.id, owner_id=1, team_key="synthetic")
                db.add(game)
                db.commit()
                session_id = game.id
            job_id, token, role = _acquire(engine, user, session_id)
            control = VoiceControl(engine, session_id, job_id, token, confirmed=True)
            control.role = role
            async def renew():
                while True:
                    await asyncio.sleep(4)
                    _renew(engine, session_id, job_id, token)
            heartbeat = asyncio.create_task(renew())
            class Browser:
                async def send_json(self, event):
                    result["browser"].append({key: event.get(key) for key in
                        ("type", "state", "audio_epoch", "request_key")})
                async def send_bytes(self, chunk):
                    result["audio_bytes_forwarded"] = result.get("audio_bytes_forwarded", 0) + len(chunk)
            browser = Browser()
            async with connect(_doubao_url, additional_headers={"X-Api-Key": os.environ[
                    "PDCA_DOUBAO_REALTIME_API_KEY"].strip()}, open_timeout=10) as socket:
                class Provider:
                    async def send(self, raw):
                        result["events"].append({"direction": "send", "type": json.loads(raw)["type"]})
                        await socket.send(raw)
                    async def recv(self):
                        raw = await socket.recv()
                        event = json.loads(raw)
                        result["events"].append({"direction": "receive", **{key: event.get(key) for key in
                            ("type", "item_id", "question_id", "response_id")}})
                        return raw
                provider = Provider()
                await _doubao_handshake(provider, role)
                receiving = asyncio.create_task(_receive_doubao_audio(browser, provider, engine,
                    session_id, job_id, token, control=control))
                for offset in range(0, len(pcm), 640):
                    control.sent_audio(pcm[offset:offset + 640])
                    await provider.send(json.dumps({"type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm[offset:offset + 640]).decode()}))
                    await asyncio.sleep(.02)
                await control.handle(browser, provider, {"type": "control", "action": "pause",
                    "request_key": "native-pause", "audio_epoch": control.epoch + 1})
                paused = control.state == "coaching"
                with Session(engine) as db:
                    parts = db.exec(select(OmegaSegment).where(OmegaSegment.session_id == session_id)).all()
                    result["saved_sales"] = sum(part.speaker == "sales" for part in parts)
                    result["saved_characters"] = sum(len(part.text) for part in parts)
                if paused:
                    await control.handle(browser, provider, {"type": "control", "action": "resume",
                        "request_key": "native-resume", "audio_epoch": control.epoch + 1})
                result["same_session_id"] = control.session_id == session_id
                result["status"] = "passed" if paused and control.state == "listening" \
                    and result["saved_sales"] == (0 if args.silence else 1) and not control.tail_incomplete else "failed"
                await provider.send(json.dumps({"type": "session.close"}))
                await asyncio.wait_for(receiving, 3)
        except Exception as exc:
            result["status"], result["error_type"] = "failed", type(exc).__name__
        finally:
            for task in (receiving, heartbeat):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (receiving, heartbeat) if task), return_exceptions=True)
            if control:
                _release(engine, control.job_id, control.token, failed=result["status"] != "passed",
                         incomplete=control.tail_incomplete or bool(control.active_inputs))
            engine.dispose()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--silence", action="store_true", help="Use only one second of exact zero PCM")
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    args.output.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(run(args))
    destination = args.output / f"native-pause-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
