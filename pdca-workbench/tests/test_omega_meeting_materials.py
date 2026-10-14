"""Meeting cards and one-session materials use the authenticated Omega flow."""
import io
import json
import unittest
from zipfile import ZipFile

from openpyxl import Workbook
from pypdf import PdfWriter

from app.omega.context import actor_messages, coach_messages
from app.omega.reports import WEIGHTS, report_summary, validate_report
from app.omega.realtime import _voice_role
from tests import test_omega_flow as fixtures


class MeetingMaterialTests(unittest.TestCase):
    setUp = fixtures.OmegaFlowTests.setUp
    tearDown = fixtures.OmegaFlowTests.tearDown
    case_body = staticmethod(fixtures.OmegaFlowTests.case_body)

    def test_meeting_cards_cover_the_full_lifecycle(self):
        response = self.client.get('/api/omega/templates')
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        expected = {
            '破冰会议', '方案推进会议', '试订单推进', '合作启动培训', '终销培训',
            '市场营销支持会议', '新品培训', '店铺周会', '店铺月会', '临时自定义会议',
            '开店准备会议', '补货复购会议', '售后问题协调会议',
        }
        featured = {row['title']: row for row in rows if row.get('card_group') != 'drill'}
        self.assertTrue(expected <= set(featured))
        for title in expected:
            card = featured[title]
            self.assertTrue(card['material_hint'])
            self.assertEqual(len(card['draft']['participants']), 1)
            self.assertTrue(card['draft']['participants'][0]['is_primary'])
            self.assertTrue(card['draft']['goal']['success_condition'])

    def test_material_extract_and_launch_are_session_scoped(self):
        response = self.client.post('/api/omega/materials/extract', files={
            'file': ('meeting.txt', '客户提问：试订单交期怎样核对？'.encode('utf-8'), 'text/plain')})
        self.assertEqual(response.status_code, 200, response.text)
        material = {**response.json(), 'purpose': 'reference', 'visibility': 'shared'}
        card = next(row for row in self.client.get('/api/omega/templates').json()
                    if row['title'] == '试订单推进')
        body = {'request_key': 'meeting-material-001', 'template_id': card['id'],
                'template_version': card['current_version'], 'usage': 'training',
                'overrides': {'meeting_topic': '核对试单政策和交货条件',
                              'meeting_materials': [material]}}
        started = self.client.post('/api/omega/template-starts', json=body)
        self.assertEqual(started.status_code, 201, started.text)
        game = self.client.get(f"/api/omega/sessions/{started.json()['session_id']}").json()
        self.assertEqual(game['case_snapshot']['meeting_materials'], [material])
        self.assertEqual(game['case_snapshot']['meeting_topic'], '核对试单政策和交货条件')
        self.assertEqual(self.client.get(f"/api/omega/cases/{card['id']}").json()['draft']['meeting_materials'], [])

    def test_private_material_only_reaches_coach(self):
        snapshot = {**self.case_body(), 'meeting_type': 'enablement',
                    'meeting_topic': '练习门店培训', 'meeting_materials': [
                        {'name': '内部底线.txt', 'purpose': 'reference', 'visibility': 'coach',
                         'text': '内部折扣审批边界'}]}
        actor = actor_messages(snapshot, [])[0]['content']
        coach = coach_messages(snapshot, [], WEIGHTS)[1]['content']
        self.assertNotIn('内部折扣审批边界', actor)
        self.assertIn('内部折扣审批边界', coach)
        self.assertIn('练习门店培训', actor)

    def test_real_meeting_does_not_inherit_simulated_participants(self):
        card = next(row for row in self.client.get('/api/omega/templates').json()
                    if row['title'] == '破冰会议')
        result = self.client.post('/api/omega/template-starts', json={
            'request_key': 'real-meeting-setup-001', 'template_id': card['id'],
            'template_version': card['current_version'], 'usage': 'real_review',
            'overrides': {'meeting_topic': '核对真实会议目标'}})
        self.assertEqual(result.status_code, 201, result.text)
        snapshot = self.client.get(f"/api/omega/cases/{result.json()['case_id']}").json()['draft']
        self.assertEqual(snapshot['participants'], [])
        self.assertEqual(snapshot['buyer_name'], '')
        self.assertEqual(snapshot['meeting_topic'], '核对真实会议目标')

    def test_template_cannot_store_temporary_materials(self):
        body = {**self.case_body(), 'kind': 'template', 'meeting_materials': [
            {'name': '内部资料.txt', 'purpose': 'reference', 'visibility': 'coach', 'text': '只供本次'}]}
        self.assertEqual(self.client.post('/api/omega/cases', json=body).status_code, 422)

    def test_blank_material_content_is_rejected_at_api_boundary(self):
        body = {**self.case_body(), 'meeting_materials': [
            {'name': '会议资料.txt', 'purpose': 'reference', 'visibility': 'shared', 'text': '  '}]}
        self.assertEqual(self.client.post('/api/omega/cases', json=body).status_code, 422)

    def test_training_card_uses_training_role_and_applicable_scorecard(self):
        card = next(row for row in self.client.get('/api/omega/templates').json()
                    if row['title'] == '合作启动培训')
        snapshot = card['draft']
        role = actor_messages(snapshot, [])[0]['content']
        self.assertIn('simulated trainee', role)
        self.assertNotIn('buyer in a training negotiation', role)
        weights = snapshot['score_weights']
        self.assertEqual(weights['concessions'], 0)
        self.assertEqual(sum(weights.values()), 100)
        report = {'outcome': {'status': 'unverified', 'reason': '', 'quotes': []},
                  'dimensions': [{'key': key, 'score': None, 'reason': '', 'quotes': []}
                                 for key in WEIGHTS]}
        validated = validate_report(json.dumps(report), [], weights=weights)
        self.assertIsNone(validated['score']['total'])
        self.assertIsNone(report_summary(validated)['blocker'])

    def test_maximum_allowed_materials_fit_default_voice_card(self):
        for card in self.client.get('/api/omega/templates').json()[:13]:
            snapshot = card['draft']
            snapshot['meeting_materials'] = [
                {'name': f'资料{index}.txt', 'purpose': 'content', 'visibility': 'shared',
                 'text': '产品培训' * 450, 'truncated': True} for index in range(3)]
            self.assertLessEqual(len(_voice_role(snapshot)), 8000, card['title'])

    def test_docx_text_and_invalid_files(self):
        content = io.BytesIO()
        with ZipFile(content, 'w') as archive:
            archive.writestr('word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>培训命题：介绍品牌文化</w:t></w:r></w:p></w:body></w:document>')
        response = self.client.post('/api/omega/materials/extract', files={
            'file': ('training.docx', content.getvalue(),
                     'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('介绍品牌文化', response.json()['text'])
        slides = io.BytesIO()
        with ZipFile(slides, 'w') as archive:
            archive.writestr('ppt/slides/slide1.xml',
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>新品卖点培训</a:t>'
                '</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
        response = self.client.post('/api/omega/materials/extract', files={
            'file': ('launch.pptx', slides.getvalue(),
                     'application/vnd.openxmlformats-officedocument.presentationml.presentation')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('新品卖点培训', response.json()['text'])
        book = Workbook()
        book.active['A1'] = '本月终销'
        book.active['B1'] = 42
        sheet = io.BytesIO()
        book.save(sheet)
        response = self.client.post('/api/omega/materials/extract', files={
            'file': ('store.xlsx', sheet.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('本月终销', response.json()['text'])
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        blank_pdf = io.BytesIO()
        writer.write(blank_pdf)
        self.assertEqual(self.client.post('/api/omega/materials/extract', files={
            'file': ('scan.pdf', blank_pdf.getvalue(), 'application/pdf')}).status_code, 422)
        long_text = self.client.post('/api/omega/materials/extract', files={
            'file': ('long.txt', ('本场资料' * 500).encode('utf-8'), 'text/plain')}).json()
        self.assertTrue(long_text['truncated'])
        self.assertEqual(len(long_text['text']), 1800)
        self.assertEqual(self.client.post('/api/omega/materials/extract', files={
            'file': ('wrong.pdf', b'not a PDF', 'application/pdf')}).status_code, 422)
        self.assertEqual(self.client.post('/api/omega/materials/extract', files={
            'file': ('huge.txt', b'a' * (5 * 1024 * 1024 + 1), 'text/plain')}).status_code, 413)


if __name__ == '__main__':
    unittest.main()
