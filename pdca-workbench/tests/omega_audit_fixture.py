"""Typed audit fixture for tests of worker mechanics, never model quality evidence."""
import json


def audit_aware(generate):
    def wrapped(kind, messages, limit):
        if kind != 'report_audit':
            return generate(kind, messages, limit)
        payload = json.loads(messages[-1]['content'])
        return json.dumps({'checks': [
            {'path': path, 'verdict': 'supported', 'reason': '合成结构夹具，仅验证任务发布机制。',
             'segment_ids': [item['id'] for item in payload['transcript']]}
            for path in payload['claims']]}, ensure_ascii=False)
    return wrapped
