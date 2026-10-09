"""Opt-in, isolated Doubao protocol probe. Never sends customer data or logs secrets."""
from __future__ import annotations

import argparse
from array import array
import asyncio
import base64
import hashlib
import json
import os
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from websockets.asyncio.client import connect

URL = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
MODEL = "1.2.6.1"


async def probe_asr(args):
    """Replay only this script's fixed synthetic phrase, at real PCM cadence."""
    synthetic = argparse.Namespace(**(vars(args) | {"case": "voice", "repeat": 1,
                                                   "synthesize": True, "independent": True}))
    created = await probe(synthetic)
    result = {"case": "asr", "synthetic_only": True, "physical_microphone": False,
              "events": [], "status": "not_run"}
    if created["status"] != "completed" or not created.get("attempts", [{}])[0].get("audio_bytes"):
        result["status"] = "synthesis_failed"
        return result
    with wave.open(str(args.output / "synthetic-voice-0-1.wav"), "rb") as wav:
        samples = array("h", wav.readframes(wav.getnframes()))
    # 24 kHz to 16 kHz; generated test input only, never production audio processing.
    downsampled = array("h", (int(samples[(index * 3) // 2]) for index in range(len(samples) * 2 // 3))).tobytes()
    key = os.environ["PDCA_DOUBAO_REALTIME_API_KEY"].strip()
    try:
        async with connect(URL, additional_headers={"X-Api-Key": key}, open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "session.create", "session": {"model": MODEL,
                "instructions": "这是固定合成音频的识别测试。只回复测试完成。",
                "audio": {"input": {"format": {"type": "pcm", "rate": 16000}},
                          "output": {"format": {"type": "pcm_s16le", "rate": 24000},
                                     "voice": "zh_female_vv_uranus_bigtts"}}}}))
            first = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if first.get("type") != "session.created":
                raise RuntimeError("handshake")
            completed = asyncio.Event()
            async def receive():
                while True:
                    event = json.loads(await ws.recv())
                    text = str(event.get("text") or event.get("transcript") or event.get("delta") or "")
                    result["events"].append({"type": event.get("type"), "field_names": sorted(event),
                        "event_id": event.get("event_id"), "item_id": event.get("item_id"),
                        "question_id": event.get("question_id"), "response_id": event.get("response_id"),
                        "text_characters": len(text),
                        "text_sha256": hashlib.sha256(text.encode()).hexdigest() if text else ""})
                    if event.get("type") == "conversation.item.input_audio_transcription.completed":
                        completed.set()
                    if event.get("type") == "response.output_audio.started":
                        await ws.send(json.dumps({"type": "response.cancel"}))
                    if event.get("type") == "session.closed":
                        return
            receiving = asyncio.create_task(receive())
            try:
                for offset in range(0, len(downsampled), 640):
                    await ws.send(json.dumps({"type": "input_audio_buffer.append",
                        "audio": base64.b64encode(downsampled[offset:offset + 640]).decode()}))
                    await asyncio.sleep(.02)
                if not args.pause_after_input:
                    for _ in range(150):
                        await ws.send(json.dumps({"type": "input_audio_buffer.append",
                            "audio": base64.b64encode(bytes(640)).decode()}))
                        await asyncio.sleep(.02)
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                if args.pause_after_input:
                    await ws.send(json.dumps({"type": "input_audio_mute.commit"}))
                    await ws.send(json.dumps({"type": "session.update", "session": {
                        "instructions": "这是固定合成音频的暂停排空测试。只回复测试完成。"}}))
                await asyncio.wait_for(completed.wait(), 8)
                await asyncio.sleep(.5)
                result["status"] = "passed"
                await ws.send(json.dumps({"type": "session.close"}))
                await asyncio.wait_for(receiving, 3)
            finally:
                if not receiving.done():
                    receiving.cancel()
                await asyncio.gather(receiving, return_exceptions=True)
    except Exception as exc:
        result["status"], result["error_type"] = "failed", type(exc).__name__
    return result


async def probe(args, *, role_index=0):
    key = os.environ.get("PDCA_DOUBAO_REALTIME_API_KEY", "").strip()
    voices = ("zh_female_vv_uranus_bigtts", "zh_male_yunzhou_jupiter_bigtts",
              "zh_male_xiaotian_uranus_bigtts")
    evidence = {"at": datetime.now(timezone.utc).isoformat(), "model": MODEL,
                "case": args.case, "repeat": args.repeat, "synthetic_only": True,
                "server_role_index": role_index, "initial_voice": voices[role_index % 3],
                "events": [], "status": "not_run", "voice_identity_verified": False}
    if not key:
        evidence["status"] = "missing_credentials"
        return evidence
    started = time.monotonic()
    try:
        async with connect(URL, additional_headers={"X-Api-Key": key},
                           open_timeout=10, max_size=2 * 1024 * 1024) as ws:
            async def send(event):
                await ws.send(json.dumps(event, ensure_ascii=False))
                evidence["events"].append({"direction": "send", "type": event["type"],
                                           "seconds": round(time.monotonic() - started, 3)})

            async def receive_window(seconds=3):
                types = []
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    try:
                        event = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.monotonic()))
                    except TimeoutError:
                        break
                    kind = str(event.get("type", "unknown"))
                    types.append(kind)
                    # Only protocol type/IDs/timing; no headers, prompts, transcripts, or error text.
                    evidence["events"].append({"direction": "receive", "type": kind,
                        "seconds": round(time.monotonic() - started, 3),
                        "error_code": str((event.get("error") or {}).get("code", ""))[:80],
                        "status_code": event.get("status_code"),
                        "field_names": sorted(event),
                        "event_id": event.get("event_id"), "response_id": event.get("response_id"),
                        "question_id": event.get("question_id"),
                        "voice": event.get("voice"), "speaker": event.get("speaker")})
                    if kind == "response.output_audio.delta":
                        chunk = base64.b64decode(event.get("delta") or "", validate=True)
                        evidence["events"][-1]["audio_chunk_bytes"] = len(chunk)
                        audio.extend(chunk)
                return types

            audio = bytearray()
            await send({"type": "session.create", "session": {"model": MODEL,
                "instructions": f"你是无客户数据的协议测试角色{role_index % 3 + 1}。只说测试完成。",
                "audio": {"input": {"format": {"type": "pcm", "rate": 16000}},
                          "output": {"format": {"type": "pcm_s16le", "rate": 24000},
                                     "voice": voices[role_index % 3]}}}})
            created = await receive_window()
            if "session.created" not in created:
                evidence["status"] = "handshake_failed"
                return evidence
            if args.case != "pause":
                await send({"type": "input_audio_mute.commit"})
            evidence["attempts"] = []
            for index in range(args.repeat):
                audio.clear()
                if args.case == "pause":
                    await send({"type": "response.cancel"})
                    await receive_window(1)
                    await send({"type": "input_audio_mute.commit"})
                    muted = await receive_window(2)
                    if args.hold_seconds:
                        await receive_window(args.hold_seconds)
                    await send({"type": "input_audio_unmute.commit"})
                    await send({"type": "session.update", "session": {
                        "instructions": "这是无客户数据的恢复测试。只说测试完成。"}})
                    result = muted + await receive_window(2)
                elif args.case == "role":
                    await send({"type": "session.update", "session": {
                        "instructions": f"你是协议测试角色{index % 3 + 1}。不含真实客户。只说测试完成。"}})
                    result = await receive_window(2)
                else:
                    voice = voices[role_index % 3] if args.independent else voices[index % 2]
                    await send({"type": "session.update", "session": {
                        "audio": {"output": {"voice": voice}}}})
                    result = await receive_window(2)
                if args.synthesize:
                    await send({"type": "speech_text_buffer.commit", "event_id": f"probe-phrase-{index}",
                                "text": "这是合成测试，没有客户数据。请确认测试音频。"})
                    result += await receive_window(6)
                evidence["attempts"].append({"index": index + 1, "received_types": result,
                    "accepted": "session.updated" in result and "error" not in result,
                    "audio_bytes": len(audio), "audio_sha256": hashlib.sha256(audio).hexdigest() if audio else ""})
                if audio:
                    args.output.mkdir(parents=True, exist_ok=True)
                    destination = args.output / f"synthetic-{args.case}-{role_index}-{index+1}.wav"
                    with wave.open(str(destination), "wb") as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(24000)
                        wav.writeframes(audio)
            await send({"type": "session.close"})
            await receive_window(1)
            evidence["status"] = "completed"
    except Exception as exc:
        evidence["status"] = "connection_failed"
        evidence["error_type"] = type(exc).__name__
        # Deliberately omit exception text: providers can echo authentication metadata.
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("pause", "role", "voice", "asr"), required=True)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--hold-seconds", type=int, choices=(0, 30, 120), default=0)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--synthesize", action="store_true", help="Synthesize only the fixed public test phrase")
    parser.add_argument("--independent", action="store_true", help="Use isolated fixed-role sessions sequentially")
    parser.add_argument("--pause-after-input", action="store_true", help="ASR only: commit and mute without trailing silence")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error("repeat must be between 1 and 20")
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    async def run():
        if args.case == "asr":
            return await probe_asr(args)
        if not args.independent:
            return await probe(args)
        sessions = []
        for index in range(args.repeat):
            sessions.append(await probe(argparse.Namespace(**(vars(args) | {"repeat": 1})), role_index=index))
        return {"status": "completed" if all(item["status"] == "completed" for item in sessions)
                else "partial", "independent": True, "sessions": sessions,
                "voice_identity_verified": False}
    result = asyncio.run(run())
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / f"doubao-{args.case}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
