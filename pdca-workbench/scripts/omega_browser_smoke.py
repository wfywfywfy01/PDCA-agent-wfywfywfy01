"""Browser-only Omega flow with a deterministic same-origin API fixture.

Run against `npm run dev -- --host 127.0.0.1`; no real credentials or network APIs.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    cases = []
    sessions = []
    reviews = []
    stop_requests = []
    report = {
        "id": "report-1", "content": {
            "outcome": {"status": "unverified", "reason": "尚无书面确认", "quotes": []},
            "commitments": [], "concession_costs": [], "hard_limit_findings": [],
            "dimensions": [], "score": {"earned": 0, "available": 0, "total": None},
            "next_practice": {"动作": "下次先确认交付负责人。"},
        }, "reviews": reviews,
    }

    def respond(route):
        path = urlparse(route.request.url).path
        method = route.request.method
        body = route.request.post_data_json if method in {"POST", "PATCH"} else None
        status = 200
        result = {}
        if path == "/api/auth/me":
            result = {"id": 1, "username": "test-manager", "display_name": "测试主管", "role": "manager"}
        elif path == "/api/omega/status":
            result = {"enabled": True, "ready": True, "actor_id": 1, "role": "manager",
                      "realtime_configured": True, "model_configured": True, "worker_online": True}
        elif path == "/api/omega/team-members":
            result = [{"id": 1, "name": "测试主管"}]
        elif path == "/api/omega/templates":
            result = []
        elif path == "/api/knowledge/scope":
            result = {"dealers": []}
        elif path == "/api/omega/profiles":
            result = {"profile": None, "entries": []}
        elif path.endswith("/memory-proposal"):
            result = {"proposal": None, "generation": {"status": "succeeded"}}
        elif path == "/api/omega/assignments" and method == "GET":
            result = []
        elif path == "/api/omega/cases" and method == "GET":
            result = cases
        elif path == "/api/omega/case-draft/analyze" and method == "POST":
            result = {"draft": {
                "title": "测试回款谈判", "public_brief": "双方讨论一笔测试账款。",
                "seller_private": "不降低价格", "counterparty_brief": "对手需要明确交付日期。",
                "goal": {"outcome_type": "payment_commitment",
                         "success_condition": "确认付款日期和金额",
                         "ideal": "当场签署书面承诺", "minimum": "确认付款时间表",
                         "hard_limits": ["不能降低价格"], "amount_major": "10000",
                         "currency": "USD", "due_date": "2026-10-05"},
            }}
        elif path == "/api/omega/cases" and method == "POST":
            result = {"id": "case-1", "title": body["title"], "owner_id": 1,
                      "revision": 1, "current_version": 0, "draft_confirmed": False, "draft": body}
            cases.append(result)
            status = 201
        elif path == "/api/omega/cases/case-1/confirm":
            cases[0]["current_version"] = 1
            cases[0]["revision"] = 2
            cases[0]["draft_confirmed"] = True
            result = {"id": "version-1", "version": 1}
        elif path == "/api/omega/sessions" and method == "GET":
            result = sessions
        elif path == "/api/omega/sessions" and method == "POST":
            result = {"id": "game-1", "case_id": "case-1", "owner_id": 1,
                      "status": "active", "mode": "rehearsal", "segments": []}
            sessions.append(result)
            status = 201
        elif path == "/api/omega/sessions/game-1" and method == "GET":
            result = sessions[0]
        elif path == "/api/omega/sessions/game-1/realtime/stop" and method == "POST":
            stop_requests.append(True)
            result = {"ok": True}
        elif path == "/api/omega/sessions/game-1/turns":
            sessions[0]["segments"].append({"id": "sales-1", "seq": 1,
                                             "speaker": "sales", "text": body["text"]})
            result = {"id": "turn-job-1", "kind": "turn", "status": "queued", "result_id": "", "error": ""}
            status = 202
        elif path == "/api/omega/jobs/turn-job-1":
            if len(sessions[0]["segments"]) == 1:
                sessions[0]["segments"].append({"id": "buyer-1", "seq": 2,
                                                 "speaker": "counterparty", "text": "请发书面时间表。"})
            result = {"id": "turn-job-1", "kind": "turn", "status": "succeeded", "result_id": "", "error": ""}
        elif path == "/api/omega/sessions/game-1/finish":
            sessions[0]["status"] = "ended"
            result = sessions[0]
        elif path == "/api/omega/sessions/game-1/reports":
            result = {"id": "report-job-1", "kind": "report", "status": "queued", "result_id": "", "error": ""}
            status = 202
        elif path == "/api/omega/jobs/report-job-1":
            result = {"id": "report-job-1", "kind": "report", "status": "succeeded",
                      "result_id": "report-1", "error": ""}
        elif path == "/api/omega/reports/report-1" and method == "GET":
            result = report
        elif path == "/api/omega/reports/report-1/reviews" and method == "POST":
            reviews.append({"content": body})
            result = {"id": "review-1"}
            status = 201
        else:
            status = 404
            result = {"detail": path}
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(result, ensure_ascii=False))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.route(re.compile(r"^http://127\.0\.0\.1:5173/api/(omega|auth|meeting-center|knowledge)/"), respond)
        page.goto("http://127.0.0.1:5173/omega")
        expect(page.get_by_role("heading", name="谈判陪练")).to_be_visible()
        page.get_by_role("button", name="一句话描述自定义场景").click()
        page.get_by_label("带入手头客户").fill("明天和客户谈回款")
        page.get_by_role("button", name="整理练习").click()
        expect(page.get_by_role("heading", name="测试回款谈判")).to_be_visible()
        expect(page.get_by_text("不降低价格").first).to_be_visible()
        page.get_by_role("button", name="修改内容或更多设定").click()
        expect(page.get_by_label("任务名称")).to_have_value("测试回款谈判")
        page.get_by_role("button", name="确认并开练").click()
        expect(page.get_by_role("heading", name="测试回款谈判")).to_be_visible()
        page.evaluate("""() => {
          window.__micStopped = false
          navigator.mediaDevices.getUserMedia = () => new Promise((resolve) => {
            window.__resolveMic = resolve
          })
        }""")
        page.get_by_role("button", name="语音输入").click()
        page.get_by_role("group", name="列表类型").get_by_role("button", name=re.compile("任务")).click()
        page.locator(".omega-side .omega-link").first.click()
        page.evaluate("""() => window.__resolveMic({
          getTracks: () => [{ stop: () => { window.__micStopped = true } }]
        })""")
        page.wait_for_function("window.__micStopped === true")
        page.get_by_role("group", name="列表类型").get_by_role("button", name=re.compile("记录")).click()
        page.locator(".omega-side .omega-link").first.click()
        page.evaluate("""() => {
          window.__testMicContext = new AudioContext()
          const source = window.__testMicContext.createOscillator()
          const destination = window.__testMicContext.createMediaStreamDestination()
          source.connect(destination)
          source.start()
          window.__testMicSource = source
          window.__testMicStream = destination.stream
          navigator.mediaDevices.getUserMedia = async () => destination.stream
        }""")
        page.get_by_role("button", name="语音输入").click()
        expect(page.get_by_role("button", name="停止录音")).to_be_visible()
        page.get_by_role("group", name="列表类型").get_by_role("button", name=re.compile("任务")).click()
        page.locator(".omega-side .omega-link").first.click()
        page.wait_for_function("window.__testMicStream.getAudioTracks()[0].readyState === 'ended'")
        page.evaluate("""() => {
          window.__testMicSource.stop()
          return window.__testMicContext.close()
        }""")
        page.get_by_role("group", name="列表类型").get_by_role("button", name=re.compile("记录")).click()
        page.locator(".omega-side .omega-link").first.click()
        page.evaluate("""() => {
          window.__voicePackets = 0
          window.__voiceStops = 0
          window.__voiceGains = []
          const originalCreateGain = AudioContext.prototype.createGain
          AudioContext.prototype.createGain = function () {
            const gain = originalCreateGain.call(this)
            window.__voiceGains.push(gain)
            return gain
          }
          window.__voiceContext = new AudioContext()
          window.__voiceOscillator = window.__voiceContext.createOscillator()
          const destination = window.__voiceContext.createMediaStreamDestination()
          window.__voiceOscillator.connect(destination)
          window.__voiceOscillator.start()
          window.__voiceStream = destination.stream
          navigator.mediaDevices.getUserMedia = async () => destination.stream
          window.WebSocket = class {
            static OPEN = 1
            constructor() {
              this.readyState = 0
              this.bufferedAmount = 0
              window.__voiceSocket = this
              setTimeout(() => {
                this.readyState = 1
                this.onmessage({ data: JSON.stringify({ type: 'ready' }) })
              }, 0)
            }
            send(bytes) {
              if (bytes instanceof ArrayBuffer) window.__voicePackets++
              if (bytes === 'stop') {
                window.__voiceStops++
                setTimeout(() => {
                  this.onmessage({ data: JSON.stringify({ type: 'closed' }) })
                  this.close()
                }, 50)
              }
            }
            close() { this.readyState = 3; this.onclose?.() }
          }
        }""")
        page.set_viewport_size({"width": 390, "height": 844})
        call_button = page.get_by_role("button", name="开始实时对话").bounding_box()
        assert call_button and call_button["y"] + call_button["height"] <= 844
        page.get_by_role("button", name="开始实时对话").click()
        dialog = page.get_by_role("dialog", name="实时语音对话")
        expect(dialog).to_be_visible(timeout=5000)
        expect(dialog.get_by_role("heading", name="正在听")).to_be_visible(timeout=5000)
        expect(dialog.get_by_role("slider", name="对手音量")).to_have_value("2.5")
        page.wait_for_function("window.__voiceGains.some(gain => gain.gain.value > 2.4)")
        assert page.evaluate("""() => {
          const rect = document.querySelector('dialog').getBoundingClientRect()
          return rect.width === innerWidth && rect.height === innerHeight
            && document.documentElement.scrollWidth <= innerWidth
        }""")
        page.wait_for_function("window.__voicePackets >= 3")
        page.evaluate("""() => {
          window.__voiceSocket.onmessage({ data: JSON.stringify({ type: 'caption', speaker: 'sales', text: '测试实时发言' }) })
          window.__voiceSocket.onmessage({ data: new Int16Array(24000).buffer })
        }""")
        expect(dialog.get_by_text("你：测试实时发言")).to_be_visible()
        expect(dialog.get_by_role("heading", name="对手正在说话")).to_be_visible()
        dialog.get_by_role("slider", name="对手音量").fill("1.5")
        page.wait_for_function("window.__voiceGains.some(gain => gain.gain.value > 1.4 && gain.gain.value < 1.6)")
        page.evaluate("window.__voiceSocket.onmessage({ data: JSON.stringify({ type: 'interrupt' }) })")
        expect(dialog.get_by_role("heading", name="正在听")).to_be_visible()
        dialog.get_by_role("button", name="结束通话").click()
        expect(dialog).to_be_hidden()
        assert page.evaluate("window.__voiceStops") == 1
        assert not stop_requests, "normal hangup must preserve lease until WebSocket closes"
        page.wait_for_function("window.__voiceStream.getAudioTracks()[0].readyState === 'ended'")
        page.set_viewport_size({"width": 1280, "height": 900})
        page.evaluate("""() => { window.__voiceOscillator.stop(); return window.__voiceContext.close() }""")
        page.evaluate("""() => {
          window.__voiceContext = new AudioContext()
          window.__voiceOscillator = window.__voiceContext.createOscillator()
          const destination = window.__voiceContext.createMediaStreamDestination()
          window.__voiceOscillator.connect(destination)
          window.__voiceOscillator.start()
          window.__voiceStream = destination.stream
          navigator.mediaDevices.getUserMedia = async () => destination.stream
        }""")
        page.get_by_role("button", name="开始实时对话").click()
        expect(dialog).to_be_visible(timeout=5000)
        page.evaluate("""() => { window.__voiceSocket.onerror(); window.__voiceSocket.close() }""")
        expect(dialog).to_be_hidden()
        expect(page.get_by_role("alert").filter(has_text="实时语音网络连接失败")).to_be_visible()
        page.wait_for_function("window.__voiceStream.getAudioTracks()[0].readyState === 'ended'")
        page.evaluate("""() => { window.__voiceOscillator.stop(); return window.__voiceContext.close() }""")
        page.get_by_label("文字发言").fill("Can you confirm Friday?")
        page.get_by_role("button", name="发送", exact=True).click()
        expect(page.get_by_text("请发书面时间表。")).to_be_visible(timeout=5000)
        page.get_by_role("button", name="结束并复盘").click()
        expect(page.get_by_role("heading", name="复盘报告")).to_be_visible(timeout=5000)
        expect(page.get_by_text("下次先确认交付负责人。")).to_be_visible()
        page.get_by_label("点评").fill("继续练习锁定书面日期")
        page.get_by_role("button", name="追加点评").click()
        expect(page.get_by_text("继续练习锁定书面日期")).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function("() => document.documentElement.scrollWidth <= innerWidth", timeout=10000)
        expect(page.get_by_role("heading", name="复盘报告")).to_be_visible()
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert not overflow, "mobile horizontal overflow: " + str(page.evaluate("""() => [...document.querySelectorAll('body *')].map(node => ({
          tag: node.tagName, class: node.className, right: node.getBoundingClientRect().right
        })).filter(node => node.right > innerWidth + 1).slice(-12)"""))
        assert not errors, f"browser console errors: {errors}"
        if os.environ.get("OMEGA_BROWSER_SCREENSHOT"):
            page.screenshot(path=os.environ["OMEGA_BROWSER_SCREENSHOT"], full_page=True)
        browser.close()
    print("Omega browser smoke: create, confirm, microphone cancellation, realtime PCM/interrupt/hangup/disconnect, text fallback, report, review, narrow viewport PASS")


if __name__ == "__main__":
    main()
