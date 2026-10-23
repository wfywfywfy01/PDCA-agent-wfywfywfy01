"""Offline checks for the synthetic Doubao ASR probe's verdict."""
import asyncio
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from scripts import omega_voice_capability_probe as capability


STARTED = "conversation.item.input_audio_transcription.started"
COMPLETED = "conversation.item.input_audio_transcription.completed"
FAILED = "conversation.item.input_audio_transcription.failed"


class ASRProbeTests(unittest.IsolatedAsyncioTestCase):
    def test_verdict_requires_every_started_input_to_finish(self):
        self.assertFalse(capability._asr_probe_passed([
            {"type": COMPLETED, "item_id": "one"},
        ]))
        self.assertFalse(capability._asr_probe_passed([
            {"type": STARTED, "item_id": "one"},
            {"type": COMPLETED, "item_id": "one"},
            {"type": STARTED, "item_id": "two"},
        ]))
        self.assertTrue(capability._asr_probe_passed([
            {"type": STARTED, "item_id": "one", "question_id": "alias"},
            {"type": COMPLETED, "question_id": "alias"},
        ]))
        self.assertFalse(capability._asr_probe_passed([
            {"type": STARTED, "item_id": "one", "question_id": "shared"},
            {"type": STARTED, "item_id": "two", "question_id": "shared"},
            {"type": COMPLETED, "question_id": "shared"},
        ]))
        self.assertFalse(capability._asr_probe_passed([
            {"type": STARTED, "item_id": "one"},
            {"type": FAILED, "item_id": "one"},
        ]))

    async def test_probe_does_not_cancel_response_or_accept_late_started_input(self):
        class Socket:
            def __init__(self, asr_events):
                self.events = asyncio.Queue()
                self.sent = []
                self.asr_events = asr_events

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def send(self, raw):
                kind = json.loads(raw)["type"]
                self.sent.append(kind)
                if kind == "session.create":
                    self.events.put_nowait({"type": "session.created"})
                elif kind == "input_audio_buffer.commit":
                    for event in self.asr_events:
                        self.events.put_nowait(event)
                elif kind == "session.close":
                    self.events.put_nowait({"type": "session.closed"})

            async def recv(self):
                return json.dumps(await self.events.get())

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with wave.open(str(output / "synthetic-voice-0-1.wav"), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(bytes(960))
            cases = (
                ([{"type": STARTED, "item_id": "one"},
                  {"type": COMPLETED, "item_id": "one", "text": "synthetic"},
                  {"type": "response.output_audio.started"}], "passed"),
                ([{"type": STARTED, "item_id": "one"},
                  {"type": COMPLETED, "item_id": "one", "text": "synthetic"},
                  {"type": STARTED, "item_id": "two"}], "failed"),
            )
            for events, expected in cases:
                with self.subTest(expected=expected):
                    socket = Socket(events)
                    with patch.object(capability, "probe", new=AsyncMock(return_value={
                            "status": "completed", "attempts": [{"audio_bytes": 960}]})), \
                         patch.object(capability, "connect", return_value=socket), \
                         patch.object(capability, "_ASR_SETTLE_SECONDS", 0.05), \
                         patch.dict(os.environ, {"PDCA_DOUBAO_REALTIME_API_KEY": "fake"}):
                        result = await capability.probe_asr(SimpleNamespace(
                            output=output, pause_after_input=True))
                    self.assertEqual(result["status"], expected)
                    self.assertNotIn("response.cancel", socket.sent)


if __name__ == "__main__":
    unittest.main()
