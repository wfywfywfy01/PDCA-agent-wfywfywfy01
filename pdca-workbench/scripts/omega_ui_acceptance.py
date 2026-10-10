"""Built mobile UI against real isolated Omega HTTP/database code, with fake AI/audio.

No credentials or customer data. All fixtures are synthetic. Static server lives only
for this command and is shut down in finally. Run npm run build before this check.
"""
from __future__ import annotations

import json
import logging
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import expect, sync_playwright
from sqlmodel import Session, select

from app.omega.jobs import run_once
from app.omega.models import OmegaSession, OmegaWorkerHeartbeat
from app.omega.reports import WEIGHTS
from tests.test_omega_flow import OmegaFlowTests


def generate(kind, messages, _limit):
    if kind == 'turn':
        return '请明确下一步的负责人和确认时间。'
    if kind == 'coach_hint':
        return '先问清谁能确认采购，再争取一个明确的回复时间。'
    data = json.loads(messages[-1]['content'])
    quote = next(item for item in data['quote_candidates'] if item['speaker'] == 'sales')
    if kind == 'memory':
        return json.dumps({'items': [{'target_kind': 'sales', 'section': 'learning_focus',
            'value': '下次先明确负责人与时间', 'classification': 'inference', 'audience': 'coach_only', 'quotes': [quote]}]}, ensure_ascii=False)
    return json.dumps({'outcome': {'status': 'unverified', 'reason': '没有确认完整的下一步', 'quotes': []},
        'dimensions': [{'key': name, 'score': 6 if name == 'objections' else None,
            'reason': '回应了对方顾虑' if name == 'objections' else '本场证据不足',
            'quotes': [quote] if name == 'objections' else []} for name in WEIGHTS],
        'commitments': [], 'concession_costs': [], 'hard_limit_findings': [],
        'next_practice': '下次先明确负责人与时间。'}, ensure_ascii=False)


class Static(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        self.path = path.removeprefix('/app')
        if not Path(self.path).suffix:
            self.path = '/index.html'
        super().do_GET()


def main():
    logging.getLogger('httpx').setLevel(logging.WARNING)
    root = Path(__file__).resolve().parents[2]
    build = root / 'apps/web/dist'
    if not (build / 'index.html').is_file():
        raise RuntimeError('Build frontend before running browser acceptance')
    fixture = OmegaFlowTests()
    fixture.setUp()
    fixture.current.must_change_password = False
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Static, directory=str(build)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    errors = []
    seen_starts = []
    with Session(fixture.engine) as db:
        db.add(OmegaWorkerHeartbeat(worker_id='ui-test-worker'))
        db.commit()

    def api(route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path + ('?' + url.query if url.query else '')
        if path.startswith('/api/omega/jobs/'):
            for _ in range(3):
                if not run_once(fixture.engine, generate=generate):
                    break
        if path == '/api/omega/template-starts':
            seen_starts.append(request.post_data_json)
        if path == '/api/omega/__qa/control':
            body = request.post_data_json
            with Session(fixture.engine) as db:
                game = db.exec(select(OmegaSession).where(OmegaSession.status == 'active')).one()
                game.voice_state = 'coaching' if body['action'] == 'pause' else 'listening'
                game.audio_epoch = body['audio_epoch']
                db.commit()
            route.fulfill(status=200, json={'ok': True})
            return
        response = fixture.client.request(request.method, path, content=request.post_data,
            headers={'Content-Type': request.headers.get('content-type', 'application/json')})
        route.fulfill(status=response.status_code, body=response.content,
                      content_type=response.headers.get('content-type', 'application/json'))

    page = None
    try:
        with patch.dict(os.environ, {'PDCA_SUPERVISOR_PROVIDER': 'https://test.invalid',
            'PDCA_SUPERVISOR_MODEL': 'test-model', 'PDCA_SUPERVISOR_API_KEY': 'synthetic-test-only'}), patch('app.omega.realtime.configured', return_value=True), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.route('**/api/**', api)
            page.goto(base + '/app/omega')
            page.wait_for_timeout(1000)
            if not page.get_by_role('heading', name='今天要练什么？').count():
                print('UI startup:', page.url, page.locator('body').inner_text()[:3000], 'errors:', errors)
            expect(page.get_by_role('heading', name='今天要练什么？')).to_be_visible()
            for control in page.locator('.shell-topbar button').all():
                box = control.bounding_box()
                assert box and box['x'] >= 0 and box['x'] + box['width'] <= 390 and box['height'] >= 44, 'mobile topbar control is clipped or too small'
            for usage in ('新人培训', '会前演练', '会后复盘'):
                page.get_by_role('group', name='会议用途').get_by_role('button', name=usage).click()
                expect(page.get_by_role('group', name='场景卡').get_by_role('button').first).to_be_visible()
            page.get_by_role('group', name='会议用途').get_by_role('button', name='新人培训').click()
            page.get_by_role('button', name='调整这张场景卡').click()
            page.get_by_label('场景名称', exact=True).fill('手机验收场景')
            page.get_by_label('一句话说明目前进展').fill('已介绍价值，对方仍担心价格')
            page.get_by_role('button', name='文字开练', exact=True).click()
            expect(page.get_by_role('heading', name='手机验收场景')).to_be_visible()
            assert seen_starts[-1]['overrides'] == {'title': '手机验收场景', 'stage_summary': '已介绍价值，对方仍担心价格'}
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.get_by_label('文字发言').fill('你们哪位负责采购决策？我们约定明天下午确认。')
            page.get_by_role('button', name='发送', exact=True).click()
            expect(page.get_by_text('请明确下一步的负责人和确认时间。')).to_be_visible(timeout=10000)
            page.evaluate("""() => {
              window.__voicePackets=0;window.__controls=[];window.__controlFault='';
              const nativeSetTimeout=window.setTimeout;
              window.setTimeout=(callback,delay,...args)=>{
                if(delay===15000)window.__controlTimeout=callback;
                return nativeSetTimeout(callback,delay,...args);
              };
              const audio = window.__testAudio = new AudioContext();
              const oscillator = window.__testOscillator = audio.createOscillator();
              const output = audio.createMediaStreamDestination(); oscillator.connect(output); oscillator.start();
              window.__testStream=output.stream; navigator.mediaDevices.getUserMedia=async()=>output.stream;
              window.WebSocket=class {
                static OPEN=1;
                constructor(){this.readyState=1;this.bufferedAmount=0;window.__socket=this;setTimeout(()=>this.onmessage({data:JSON.stringify({type:'ready',audio_epoch:0})}),20)}
                async send(value){if(value instanceof ArrayBuffer){window.__voicePackets++;return}
                  if(value==='stop'){setTimeout(()=>{this.onmessage({data:JSON.stringify({type:'closed'})});this.close()},20);return}
                  const control=JSON.parse(value);window.__controls.push({...control});
                  // A provider interrupt can advance the server before the browser sees it.
                  if(control.action==='pause') control.audio_epoch++;
                  await fetch('/api/omega/__qa/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(control)});
                  if(window.__controlFault==='timeout')return;
                  if(window.__controlFault==='older-error'){
                    this.onmessage({data:JSON.stringify({type:'interrupt',audio_epoch:control.audio_epoch+1})});
                    this.onmessage({data:JSON.stringify({type:'state',state:'error',audio_epoch:control.audio_epoch,request_key:control.request_key,message:'暂停或恢复失败，麦克风保持关闭'})});return;
                  }
                  if(window.__controlFault==='tail'){
                    this.onmessage({data:JSON.stringify({type:'state',state:'error',audio_epoch:control.audio_epoch,request_key:control.request_key,message:'语音尾稿未完成，请检查逐字稿后重新演练'})});return;
                  }
                  this.onmessage({data:JSON.stringify({type:'state',state:control.action==='pause'?'coaching':'listening',audio_epoch:control.audio_epoch,request_key:control.request_key})});
                }
                close(){this.readyState=3;this.onclose?.()}
              }
            }""")
            page.get_by_role('button', name='开始实时对话').click()
            dialog = page.get_by_role('dialog', name='实时语音对话')
            expect(dialog.get_by_role('heading', name='正在听')).to_be_visible()
            page.wait_for_function('window.__voicePackets >= 3')
            page.evaluate("""() => {
                window.__socket.onmessage({data:JSON.stringify({type:'interrupt',audio_epoch:1})});
                window.__socket.onmessage({data:JSON.stringify({type:'audio',audio_epoch:1})});
                window.__socket.onmessage({data:new Int16Array(48000).buffer});
            }""")
            expect(dialog.get_by_role('heading', name='对手正在说话')).to_be_visible()
            page.evaluate("window.__socket.onmessage({data:JSON.stringify({type:'interrupt',audio_epoch:2})})")
            expect(dialog.get_by_role('heading', name='正在听')).to_be_visible()
            dialog.get_by_role('button', name='暂停，问问教练').click()
            expect(dialog.get_by_role('heading', name='教练时间')).to_be_visible()
            assert page.evaluate('window.__controls[0].audio_epoch') == 3, 'pause failed to advance the server interrupt epoch'
            expect(dialog.get_by_text('先问清谁能确认采购，再争取一个明确的回复时间。')).to_be_visible(timeout=10000)
            page.evaluate("window.__socket.onmessage({data:JSON.stringify({type:'state',state:'listening',audio_epoch:999,request_key:'stale-control'})})")
            expect(dialog.get_by_role('heading', name='教练时间')).to_be_visible()
            packet_count = page.evaluate('window.__voicePackets')
            page.wait_for_timeout(500)
            assert page.evaluate('window.__voicePackets') == packet_count, 'microphone leaked while coaching'
            page.evaluate("window.__socket.onmessage({data:JSON.stringify({type:'audio',audio_epoch:0})});window.__socket.onmessage({data:new Int16Array(24000).buffer})")
            expect(dialog.get_by_role('heading', name='教练时间')).to_be_visible()
            for label in ('继续演练', '结束通话'):
                box = dialog.get_by_role('button', name=label, exact=True).bounding_box()
                assert box and box['y'] >= 0 and box['y'] + box['height'] <= 844, 'mobile control requires scrolling'
            dialog.get_by_role('button', name='继续演练', exact=True).click()
            expect(dialog.get_by_role('heading', name='正在听')).to_be_visible()
            assert page.evaluate('window.__controls[1].audio_epoch') == 5, 'resume ignored the server-authoritative pause epoch'
            page.wait_for_function(f'window.__voicePackets > {packet_count}')
            page.evaluate("window.__socket.onmessage({data:JSON.stringify({type:'state',state:'error',audio_epoch:5,message:'语音回复失败，请恢复后重试'})})")
            expect(dialog.get_by_role('heading', name='演练已暂停')).to_be_visible()
            expect(dialog.get_by_role('alert')).to_contain_text('语音回复失败')
            packet_count = page.evaluate('window.__voicePackets')
            page.wait_for_timeout(300)
            assert page.evaluate('window.__voicePackets') == packet_count, 'microphone leaked after autonomous server error'
            dialog.get_by_role('button', name='重试恢复', exact=True).click()
            expect(dialog.get_by_role('heading', name='正在听')).to_be_visible()
            assert page.evaluate('window.__controls[2].audio_epoch') == 6

            # A matching error ACK remains relevant after an interrupt advances epoch.
            page.evaluate("window.__controlFault='older-error'")
            dialog.get_by_role('button', name='暂停，问问教练').click()
            expect(dialog.get_by_role('heading', name='演练已暂停')).to_be_visible()
            expect(dialog.locator('.omega-private-coach')).to_have_count(0)
            packet_count = page.evaluate('window.__voicePackets')
            page.wait_for_timeout(150)
            assert page.evaluate('window.__voicePackets') == packet_count, 'error ACK reopened microphone'
            page.evaluate("window.__controlFault=''")
            dialog.get_by_role('button', name='重试恢复', exact=True).click()
            expect(dialog.get_by_role('heading', name='正在听')).to_be_visible()
            assert page.evaluate('window.__controls[4].audio_epoch===window.__controls[3].audio_epoch+3'), 'error ACK rolled back interrupt epoch'

            dialog.get_by_role('button', name='暂停，问问教练').click()
            expect(dialog.get_by_role('heading', name='教练时间')).to_be_visible()
            page.evaluate("window.__controlFault='timeout'")
            dialog.get_by_role('button', name='继续演练', exact=True).click()
            expect(dialog.get_by_role('heading', name='正在恢复')).to_be_visible()
            page.evaluate('window.__controlTimeout()')
            expect(dialog.get_by_role('heading', name='演练已暂停')).to_be_visible()
            expect(dialog.get_by_role('alert')).to_contain_text('状态确认超时')
            if output := os.environ.get('OMEGA_BROWSER_SCREENSHOT'):
                page.screenshot(path=str(Path(output).with_stem(Path(output).stem + '-control-timeout')))
            packet_count = page.evaluate('window.__voicePackets')
            page.evaluate("""() => {
              const control=window.__controls.at(-1);
              window.__socket.onmessage({data:JSON.stringify({type:'state',state:'listening',audio_epoch:control.audio_epoch,request_key:control.request_key})});
              window.__socket.onmessage({data:JSON.stringify({type:'audio',audio_epoch:control.audio_epoch})});
              window.__socket.onmessage({data:new Int16Array(24000).buffer});
            }""")
            expect(dialog.get_by_role('heading', name='演练已暂停')).to_be_visible()
            page.wait_for_timeout(150)
            assert page.evaluate('window.__voicePackets') == packet_count, 'late success ACK reopened microphone after timeout'
            page.evaluate("window.__controlFault=''")
            dialog.get_by_role('button', name='重试恢复', exact=True).click()
            expect(dialog.get_by_role('heading', name='正在听')).to_be_visible()
            page.evaluate("window.__socket.onmessage({data:JSON.stringify({type:'state',state:'error',audio_epoch:0,message:'旧代次错误'})})")
            expect(dialog.get_by_role('heading', name='正在听')).to_be_visible()

            # A known incomplete tail cannot be recovered on this connection.
            page.evaluate("window.__controlFault='tail'")
            dialog.get_by_role('button', name='暂停，问问教练').click()
            expect(dialog.get_by_role('heading', name='演练已暂停')).to_be_visible()
            expect(dialog.get_by_role('alert')).to_contain_text('请结束通话')
            expect(dialog.get_by_role('alert')).to_contain_text('新开练')
            expect(dialog.get_by_role('button', name='本场无法恢复', exact=True)).to_be_disabled()
            expect(dialog.locator('.omega-private-coach')).to_have_count(0)
            if output := os.environ.get('OMEGA_BROWSER_SCREENSHOT'):
                page.screenshot(path=str(Path(output).with_stem(Path(output).stem + '-tail-error')))
            dialog.get_by_role('button', name='结束通话').click()
            expect(dialog).to_be_hidden()
            page.wait_for_function("window.__testStream.getAudioTracks()[0].readyState==='ended'")
            page.evaluate('window.__testOscillator.stop();window.__testAudio.close()')
            page.get_by_role('button', name='结束并复盘').click()
            expect(page.get_by_role('heading', name='复盘报告')).to_be_visible(timeout=10000)
            expect(page.get_by_text('复盘已生成，对话和评分已保存。', exact=True)).to_be_visible()
            expect(page.get_by_text('对话已保存，正在生成复盘。', exact=True)).to_have_count(0)
            expect(page.get_by_text('已获 6 分／可评分 10 分，暂不折算总分')).to_be_visible()
            expect(page.get_by_role('button', name='确认并更新档案')).to_be_visible(timeout=10000)
            before = fixture.client.get('/api/omega/profiles?kind=sales&subject_id=1').json()
            assert before['entries'] == [], 'pending memory already effective'
            page.get_by_role('button', name='确认并更新档案').click()
            expect(page.get_by_text('已确认，档案已更新。')).to_be_visible()
            after = fixture.client.get('/api/omega/profiles?kind=sales&subject_id=1').json()
            assert len(after['entries']) == 1
            page.get_by_role('button', name='查看档案').click()
            expect(page.get_by_text('下次先明确负责人与时间', exact=True)).to_be_visible()
            page.get_by_role('button', name='新练习', exact=True).click()
            expect(page.get_by_role('heading', name='今天要练什么？')).to_be_visible()
            page.evaluate("""() => {
              const audio=window.__testAudio=new AudioContext();
              const oscillator=window.__testOscillator=audio.createOscillator();
              const output=audio.createMediaStreamDestination(); oscillator.connect(output); oscillator.start();
              window.__testStream=output.stream; navigator.mediaDevices.getUserMedia=async()=>output.stream;
              const NativeAudioContext=window.AudioContext;
              window.__primedContexts=[];
              window.AudioContext=new Proxy(NativeAudioContext, {construct(Target,args){const context=new Target(...args);window.__primedContexts.push(context);return context;}});
            }""")
            page.get_by_role('group', name='场景卡').get_by_role('button').last.click()
            output = os.environ.get('OMEGA_BROWSER_SCREENSHOT')
            if output:
                path = Path(output)
                page.evaluate('window.scrollTo(0, 0)')
                page.screenshot(path=str(path.with_stem(path.stem + '-cards')), full_page=True)
            packet_count = page.evaluate('window.__voicePackets')
            page.get_by_role('button', name='语音开练', exact=True).click()
            expect(dialog.get_by_role('heading', name='正在听')).to_be_visible()
            page.wait_for_function(f'window.__voicePackets > {packet_count}')
            assert page.evaluate("window.__primedContexts.length===2 && window.__primedContexts.every(context=>context.state!=='closed')"), 'session selection closed or replaced the audio contexts unlocked by the tap'
            if output:
                page.screenshot(path=str(Path(output).with_stem(Path(output).stem + '-voice')))
            dialog.get_by_role('button', name='结束通话', exact=True).click()
            expect(dialog).to_be_hidden()
            page.wait_for_function("window.__testStream.getAudioTracks()[0].readyState==='ended'")
            page.wait_for_function("window.__primedContexts.every(context=>context.state==='closed')")
            page.evaluate('window.__testOscillator.stop();window.__testAudio.close()')
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert not errors, errors
            if output:
                page.screenshot(path=output, full_page=True)
            browser.close()
        print('PASS: real isolated APIs + mobile cards/edits/text/report/pending-confirmed memory/profile; mock voice matching older-epoch error, timeout, late ACK rejection, fatal-tail no-resume, microphone gate and cleanup; report-completed notice')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        fixture.tearDown()


if __name__ == '__main__':
    main()
