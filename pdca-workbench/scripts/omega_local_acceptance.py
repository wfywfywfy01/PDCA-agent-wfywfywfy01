"""Browser acceptance against the running, isolated local Qwen trial.

Uses synthetic speech and the disposable local account; no customer audio or
provider credential is embedded here. Run from pdca-workbench after startup.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    base = "http://127.0.0.1:8769"
    local = Path(os.environ["LOCALAPPDATA"]) / "VertuOmega" / "local"
    login = json.loads((local / "login.json").read_text(encoding="utf-8"))
    wave = base64.b64encode((local / "trial.wav").read_bytes()).decode("ascii")
    page_errors: list[str] = []
    ws_errors: list[str] = []
    ws_events: list[str] = []
    audio_bytes = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--autoplay-policy=no-user-gesture-required"]
        )
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        def on_websocket(socket) -> None:
            if "/realtime" not in socket.url:
                return

            def on_frame(frame) -> None:
                nonlocal audio_bytes
                if isinstance(frame, bytes):
                    audio_bytes += len(frame)
                    return
                try:
                    event = json.loads(frame)
                except (TypeError, ValueError):
                    return
                ws_events.append(str(event.get("type", "")))
                if event.get("type") == "error":
                    ws_errors.append(event.get("message", ""))

            socket.on("framereceived", on_frame)

        page.on("websocket", on_websocket)
        page.goto(base + "/app/omega")
        page.get_by_label("用户名").fill(login["username"])
        page.get_by_label("密码").fill(login["password"])
        page.get_by_role("button", name="登录", exact=True).click()
        expect(page.get_by_role("heading", name="谈判陪练")).to_be_visible(timeout=15000)
        trial_case = page.get_by_role("button", name=re.compile("本机实时语音试用.*版本 1"))
        if trial_case.count():
            trial_case.click()
        else:
            page.get_by_role("button", name="新建任务").click()
            page.get_by_label("任务名称").fill("本机实时语音试用：回款谈判（虚构）")
            page.get_by_label("双方已知背景").fill("虚构场景：销售与经销商讨论一笔到期货款，需要确认书面付款时间表。")
            page.get_by_label("销售私有信息与底线").fill("内部底线：未经批准不得降价。")
            page.get_by_label("对手已知立场").fill("你是经销商采购负责人，现金流紧张，希望延后付款。")
            page.get_by_label("成功判定条件").fill("确认付款金额、日期并形成书面时间表")
            page.get_by_label("理想结果").fill("当场确认全额付款日期")
            page.get_by_label("最低可接受结果").fill("确认首付款和余款日期")
            page.get_by_label("硬底线（每行一条）").fill("未经批准不降价")
            page.get_by_label("目标金额（按所选币种填写）").fill("10000")
            page.get_by_label("最迟日期").fill("2026-10-05")
            page.get_by_role("button", name="保存草稿").click()
            expect(page.get_by_text("草稿已保存，请核对后确认目标版本。")).to_be_visible()
            page.get_by_role("button", name="确认目标版本").click()
            expect(page.get_by_role("button", name="开始新演练")).to_be_visible()
        with page.expect_response(
            lambda response: response.url.endswith("/api/omega/sessions")
            and response.request.method == "POST"
        ) as pending:
            page.get_by_role("button", name="开始新演练").click()
        session_id = pending.value.json()["id"]

        def segments() -> list[dict]:
            response = page.request.get(base + "/api/omega/sessions/" + session_id)
            assert response.status == 200, ("get_session", response.status)
            return response.json().get("segments", [])

        for turn in (1, 2):
            page.evaluate(
                """async (data) => {
                    const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
                    const context = new AudioContext();
                    const buffer = await context.decodeAudioData(bytes.buffer);
                    const source = context.createBufferSource();
                    source.buffer = buffer;
                    const destination = context.createMediaStreamDestination();
                    source.connect(destination);
                    window.__omegaTest = {context, source, destination};
                    navigator.mediaDevices.getUserMedia = async () => destination.stream;
                }""",
                wave,
            )
            page.get_by_role("button", name="开始实时对话").click()
            try:
                expect(page.get_by_role("button", name="挂断实时对话")).to_be_visible(
                    timeout=15000
                )
            except AssertionError:
                print("failed_turn", turn, "session", session_id)
                print("voice_alerts", json.dumps(page.get_by_role("alert").all_inner_texts()))
                print("voice_status", json.dumps(page.get_by_role("status").all_inner_texts()))
                print("ws_events", ws_events)
                print("page_errors", page_errors, "ws_errors", json.dumps(ws_errors))
                raise
            page.evaluate(
                """async () => {
                    await window.__omegaTest.context.resume();
                    window.__omegaTest.source.start();
                }"""
            )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and len(segments()) < turn * 2:
                page.wait_for_timeout(900)
            assert len(segments()) >= turn * 2, ("segments_after_turn", turn)
            page.get_by_role("button", name="挂断实时对话").click()
            page.wait_for_function(
                "window.__omegaTest.destination.stream.getAudioTracks()[0].readyState === 'ended'",
                timeout=5000,
            )
            try:
                expect(page.get_by_role("button", name="开始实时对话")).to_be_visible(timeout=15000)
            except AssertionError:
                print("hangup_timeout_turn", turn, "ws_events", ws_events)
                print("hangup_status", json.dumps(page.get_by_role("status").all_inner_texts()))
                print("hangup_alert", json.dumps(page.get_by_role("alert").all_inner_texts()))
                raise
            page.evaluate("async () => await window.__omegaTest.context.close()")

        page.get_by_role("button", name="结束并冻结逐字稿").click()
        expect(page.get_by_text("复盘报告需要配置文字模型和 worker。")).to_be_visible(
            timeout=10000
        )
        page.screenshot(path=str(local / "acceptance.png"), full_page=True)
        page.reload()
        expect(page.get_by_role("heading", name="谈判陪练")).to_be_visible(timeout=10000)
        page.get_by_role("button", name=re.compile("本机实时语音试用.*已结束")).first.click()
        saved = segments()
        print("session", session_id)
        print("saved_segments", [(item["speaker"], len(item["text"])) for item in saved])
        print("received_audio_bytes", audio_bytes)
        print("page_errors", page_errors, "ws_errors", ws_errors)
        print("screenshot", local / "acceptance.png")
        browser.close()
        assert len(saved) >= 4 and audio_bytes > 0 and not page_errors and not ws_errors


if __name__ == "__main__":
    main()
