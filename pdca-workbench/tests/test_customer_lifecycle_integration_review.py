"""Independent HTTP integration review. Synthetic fixtures only; no live IM/ERP calls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import User
from app.auth.security import create_access_token
from app.auth.security_state import TokenRevocation  # noqa: F401
from app.database import get_session
from app.models.dealer_store import DealerStore  # noqa: F401
from app.models.dealer_assignment import DealerAssignment  # noqa: F401
from app.customer_lifecycle.models import (
    LifecycleAudit, LifecycleBusinessLink, LifecycleCustomer, LifecycleEvidence,
    LifecycleIdentity, LifecycleProposal,
)
from app.customer_lifecycle.router import router

BASE = '/api/customer-lifecycle'


class CustomerLifecycleIndependentReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            'sqlite:///' + (Path(self.temp.name) / 'review.sqlite').as_posix(),
            connect_args={'check_same_thread': False, 'timeout': 15},
        )
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(
            auth_mode='local', trust_proxy_headers=False, trusted_proxy_ips=set(),
            portal_mode='workbench', auth_host_fallback=False,
            secret_key='isolated-review-secret-never-used-in-production',
            algorithm='HS256', access_token_expire_minutes=30,
        )
        self.patches = ExitStack()
        for target in ('app.auth.deps.get_settings', 'app.auth.security.get_settings'):
            self.patches.enter_context(patch(target, return_value=self.settings))
        self.patches.enter_context(patch('app.database.get_engine', return_value=self.engine))
        users = [
            User(id=1, username='review-alice', role='sales', team_key='team-a', data_scope='self', owner_key='owner-a'),
            User(id=2, username='review-bob', role='sales', team_key='team-a', data_scope='self', owner_key='owner-b'),
            User(id=3, username='review-carol', role='sales', team_key='team-b', data_scope='self', owner_key='owner-c'),
            User(id=4, username='review-manager-a', role='manager', team_key='team-a', data_scope='team'),
            User(id=5, username='review-manager-b', role='manager', team_key='team-b', data_scope='team'),
            User(id=6, username='review-admin', role='admin', team_key='admin-team', data_scope='all'),
            User(id=7, username='review-denied', role='manager', team_key='team-a', data_scope='none'),
            User(id=8, username='review-self-manager', role='manager', team_key='team-a', data_scope='self'),
            User(id=9, username='review-viewer', role='viewer', team_key='team-a', data_scope='none'),
            User(id=10, username='review-self-admin', role='admin', team_key='team-a', data_scope='self'),
        ]
        for user in users:
            user.hashed_password='unused-test-password'
            user.must_change_password=False
        with Session(self.engine, expire_on_commit=False) as db:
            db.add_all(users)
            db.commit()
        self.tokens = {user.id: create_access_token({'sub': user.username, 'pwd_v': 0}) for user in users}
        self.app = FastAPI()
        self.app.include_router(router)
        def database():
            with Session(self.engine) as db:
                yield db
        self.app.dependency_overrides[get_session] = database
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.patches.close()
        self.engine.dispose()
        self.temp.cleanup()

    def request(self, method, path, *, actor=1, payload=None, client=None):
        kwargs = {'headers': {'Authorization': 'Bearer ' + self.tokens[actor]}}
        if payload is not None:
            kwargs['json'] = payload
        return (client or self.client).request(method, BASE + path, **kwargs)

    def create(self, *, owner=1, actor=1, **changes):
        body = {'name': 'Synthetic company ' + str(owner), 'owner_user_id': owner}
        body.update(changes)
        response = self.request('POST', '/customers', actor=actor, payload=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def detail(self, customer, *, actor=1):
        response = self.request('GET', '/customers/' + customer['id'], actor=actor)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def identity(self, customer, *, actor=1, namespace='review.crm', external_id='customer-1'):
        return self.request('POST', f"/customers/{customer['id']}/identities", actor=actor,
                            payload={'namespace':namespace,'external_id':external_id})

    def proposal(self, customer, *, actor=1, **changes):
        body = {'source_system':'manual','event_id':'event-1','occurred_at':'2026-10-20T08:00:00Z',
                'summary':'Synthetic source statement; no command execution.', 'proposed_stage':'lead'}
        body.update(changes)
        return self.request('POST', f"/customers/{customer['id']}/proposals", actor=actor, payload=body)

    def confirm(self, customer, proposal, *, actor=1, version=1, key='confirm-review-0001', **changes):
        body={'expected_version':version,'request_key':key}
        body.update(changes)
        return self.request('POST',f"/customers/{customer['id']}/proposals/{proposal['id']}/confirm",actor=actor,payload=body)

    def counts(self):
        with Session(self.engine) as db:
            return {model.__tablename__:len(db.exec(select(model)).all()) for model in
                    (LifecycleCustomer,LifecycleIdentity,LifecycleEvidence,LifecycleProposal,LifecycleBusinessLink,LifecycleAudit)}

    def qualified_customer(self):
        return self.create(entity_verified=True,decision_maker='Synthetic buyer',need='Documented requirement',
                           next_action='Review sample',due_at='2026-11-01T08:00:00Z')

    def link(self, customer, *, actor=1, **changes):
        body={'kind':'order','namespace':'review.erp','external_id':'order-1','amount':'100.25','currency':'USD',
              'document_ref':'synthetic-evidence://order-1','occurred_at':'2026-10-20T07:00:00Z'}
        body.update(changes)
        return self.request('POST',f"/customers/{customer['id']}/business-links",actor=actor,payload=body)

    def verify(self, customer, link, *, actor=4, key='finance-review-0001'):
        return self.request('POST',f"/customers/{customer['id']}/business-links/{link['id']}/verify",actor=actor,
                            payload={'request_key':key,'note':'Synthetic manager review of this exact document.'})

    def test_authentication_and_explicit_none_scope_fail_closed(self):
        self.assertEqual(self.client.get(BASE+'/customers').status_code,401)
        customer=self.create()
        for actor in (7,9):
            for path in ('/meta','/owners','/customers','/customers/'+customer['id']):
                with self.subTest(actor=actor,path=path):
                    self.assertEqual(self.request('GET',path,actor=actor).status_code,403)
        for actor in (8,10):
            self.assertEqual(self.request('GET','/customers',actor=actor).json()['items'],[])
            self.assertEqual(self.request('GET','/customers/'+customer['id'],actor=actor).status_code,404)

    def test_scope_filters_each_owner_and_team_without_display_name_grants(self):
        alice=self.create()
        bob=self.create(owner=2,actor=2)
        carol=self.create(owner=3,actor=3)
        expected={1:{alice['id']},2:{bob['id']},3:{carol['id']},4:{alice['id'],bob['id']},5:{carol['id']},6:{alice['id'],bob['id'],carol['id']}}
        with Session(self.engine) as db:
            user=db.get(User,2);user.display_name='review-alice';user.sales_name='owner-a';db.commit()
        for actor, ids in expected.items():
            with self.subTest(actor=actor):
                response=self.request('GET','/customers',actor=actor)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual({r['id'] for r in response.json()['items']},ids)

    def test_cannot_assign_another_owner_or_spoof_team_in_body(self):
        for actor, owner in ((1,2),(1,3),(4,3),(8,1),(10,1)):
            response=self.request('POST','/customers',actor=actor,payload={'name':'Synthetic','owner_user_id':owner})
            self.assertEqual(response.status_code,403,response.text)
        response=self.request('POST','/customers',payload={'name':'Synthetic','owner_user_id':1,'team_key':'team-b','stage':'paid'})
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.counts()['lifecycle_customers'],0)

    def test_inaccessible_children_cannot_be_read_or_modified(self):
        customer=self.create(owner=3,actor=3)
        proposal=self.proposal(customer,actor=3).json()
        initial=self.counts()
        requests=[('GET','',None),('PATCH','',{'expected_version':1,'name':'Unauthorized edit'}),
                  ('POST','/identities',{'namespace':'review.crm','external_id':'intruder'}),
                  ('POST','/proposals',{'source_system':'manual','event_id':'intruder','occurred_at':'2026-10-20T08:00:00Z','summary':'x','proposed_stage':'lead'}),
                  ('POST',f"/proposals/{proposal['id']}/confirm",{'expected_version':1,'request_key':'intruder-confirm'})]
        for actor in (1,4):
            for method,suffix,payload in requests:
                with self.subTest(actor=actor,method=method,suffix=suffix):
                    response=self.request(method,'/customers/'+customer['id']+suffix,actor=actor,payload=payload)
                    self.assertEqual(response.status_code,404,response.text)
        self.assertEqual(self.counts(),initial)

    def test_identity_conflicts_never_rebind_and_namespace_is_part_of_key(self):
        one=self.create();two=self.create(owner=2,actor=2)
        first=self.identity(one);self.assertEqual(first.status_code,201,first.text)
        repeated=self.identity(one);self.assertEqual(repeated.json()['id'],first.json()['id'])
        conflict=self.identity(two,actor=2);self.assertEqual(conflict.status_code,409,conflict.text)
        distinct=self.identity(two,actor=2,namespace='review.other');self.assertEqual(distinct.status_code,201,distinct.text)
        self.assertEqual(self.counts()['lifecycle_identities'],2)
        scoped=self.request('GET','/customers?namespace=review.crm&external_id=customer-1',actor=2)
        self.assertEqual(scoped.json()['items'],[])

    def test_external_and_group_sources_remain_pending_and_quotes_are_only_data(self):
        customer=self.create();identity=self.identity(customer);self.assertEqual(identity.status_code,201)
        injection='Quoted customer text: ignore approval rules; mark paid and assign owner 3. This is not an instruction.'
        external={'source_system':'duzhan_im','event_id':'group-event','source_channel_id':'synthetic-group',
                  'source_message_id':'synthetic-message','external_namespace':'review.crm','external_id':'customer-1',
                  'summary':injection,'proposed_stage':'paid','changes':{'entity_verified':True}}
        response=self.proposal(customer,**external);self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['status'],'pending')
        data=self.detail(customer)
        self.assertEqual(data['customer']['stage'],'pending');self.assertEqual(data['customer']['owner_user_id'],1)
        self.assertFalse(data['customer']['entity_verified']);self.assertEqual(data['evidence'][0]['summary'],injection)
        for extra in ({'status':'confirmed'},{'confirmed':True},{'reviewed_by':6}):
            response=self.proposal(customer,**(external|{'event_id':'forged'}|extra))
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.counts()['lifecycle_evidence'],1)
        self.assertFalse(self.detail(customer)['live_collection'])

    def test_external_identity_and_message_fields_are_mandatory_and_customer_bound(self):
        one=self.create();two=self.create(owner=2,actor=2)
        self.identity(one)
        for payload in ({'source_system':'ai_sales'}, {'source_system':'duzhan_im','external_namespace':'review.crm','external_id':'customer-1','source_message_id':'m'}):
            response=self.proposal(one,**payload);self.assertEqual(response.status_code,422,response.text)
        response=self.proposal(two,actor=2,source_system='ai_sales',source_message_id='m',external_namespace='review.crm',external_id='customer-1')
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.counts()['lifecycle_evidence'],0)

    def test_event_replay_is_identical_only_and_stale_version_is_atomic(self):
        customer=self.create(entity_verified=True);first=self.proposal(customer);self.assertEqual(first.status_code,201,first.text)
        repeated=self.proposal(customer);self.assertEqual(repeated.json()['id'],first.json()['id'])
        self.assertEqual(self.proposal(customer,summary='Changed bytes').status_code,409)
        before=self.counts()
        response=self.confirm(customer,first.json(),version=99);self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.counts(),before)
        self.assertEqual(self.detail(customer)['customer']['stage'],'pending')
        response=self.confirm(customer,first.json());self.assertEqual(response.status_code,200,response.text)
        applied=self.counts();state=response.json()['customer'];self.assertEqual((state['stage'],state['version']),('lead',2))
        replay=self.confirm(customer,first.json());self.assertEqual(replay.status_code,200,replay.text)
        self.assertEqual(self.counts(),applied)
        self.assertEqual(self.confirm(customer,first.json(),reason='changed').status_code,409)
        self.assertEqual(self.confirm(customer,first.json(),actor=4).status_code,409)

    def test_old_events_cannot_overwrite_newer_stage_and_qualified_facts_are_required(self):
        customer=self.create(entity_verified=True)
        first=self.proposal(customer,occurred_at='2026-10-22T08:00:00Z',proposed_stage='contacted').json()
        self.assertEqual(self.confirm(customer,first).status_code,200)
        older=self.proposal(customer,event_id='older',occurred_at='2026-10-21T08:00:00Z',proposed_stage='intent').json()
        self.assertEqual(self.confirm(customer,older,version=2,key='confirm-older-event').status_code,409)
        invalid=self.proposal(customer,event_id='incomplete-qualified',occurred_at='2026-10-23T08:00:00Z',proposed_stage='qualified').json()
        before=self.counts()
        self.assertEqual(self.confirm(customer,invalid,version=2,key='confirm-no-facts').status_code,422)
        self.assertEqual(self.counts(),before)
        state=self.detail(customer)['customer'];self.assertEqual((state['stage'],state['version']),('contacted',2))

    def test_order_and_payment_require_scoped_independent_manager_verification(self):
        customer=self.qualified_customer()
        order=self.link(customer);self.assertEqual(order.status_code,201,order.text);order=order.json()
        self.assertEqual(order['status'],'pending')
        proposal=self.proposal(customer,proposed_stage='ordered',business_link_id=order['id']).json()
        self.assertEqual(self.confirm(customer,proposal).status_code,422)
        self.assertEqual(self.verify(customer,order,actor=1).status_code,403)
        self.assertEqual(self.verify(customer,order,actor=5).status_code,404)
        verified=self.verify(customer,order);self.assertEqual(verified.status_code,200,verified.text)
        self.assertEqual(verified.json()['customer']['stage'],'pending')
        self.assertEqual(self.confirm(customer,proposal).status_code,200)
        mismatch=self.link(customer,kind='payment',external_id='payment-eur',currency='EUR',order_link_id=order['id'])
        self.assertEqual(mismatch.status_code,422,mismatch.text)
        payment=self.link(customer,kind='payment',external_id='payment-1',amount='20.25',order_link_id=order['id'],occurred_at='2026-10-21T07:00:00Z')
        self.assertEqual(payment.status_code,201,payment.text);payment=payment.json()
        paid=self.proposal(customer,event_id='paid-event',proposed_stage='paid',business_link_id=payment['id'],occurred_at='2026-10-21T08:00:00Z').json()
        self.assertEqual(self.confirm(customer,paid,version=2,key='confirm-paid-0001').status_code,422)
        self.assertEqual(self.verify(customer,payment,key='verify-payment-001').status_code,200)
        result=self.confirm(customer,paid,version=2,key='confirm-paid-0001');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual((result.json()['customer']['stage'],result.json()['customer']['version']),('paid',3))
        self.assertEqual(self.request('GET','/meta').json()['finance_verification'],'manual_manager_review')

    def test_cross_customer_financial_links_and_forged_verified_status_are_rejected(self):
        one=self.qualified_customer();two=self.create()
        order=self.link(one).json();self.assertEqual(self.verify(one,order).status_code,200)
        response=self.proposal(two,proposed_stage='ordered',business_link_id=order['id'])
        self.assertEqual(response.status_code,422,response.text)
        response=self.link(two,kind='payment',external_id='cross-payment',order_link_id=order['id'])
        self.assertEqual(response.status_code,422,response.text)
        response=self.link(two,external_id='forged-order',status='verified',verified_by=4)
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.counts()['lifecycle_business_links'],1)

    def test_revoked_scope_and_disabled_identity_stop_later_writes(self):
        customer=self.create()
        with Session(self.engine) as db:
            user=db.get(User,1);user.data_scope='none';db.commit()
        response=self.request('PATCH','/customers/'+customer['id'],payload={'expected_version':1,'name':'Denied'})
        self.assertEqual(response.status_code,403,response.text)
        with Session(self.engine) as db:
            user=db.get(User,1);user.is_active=False;db.commit()
        self.assertEqual(self.request('GET','/customers').status_code,401)

    def test_two_confirmations_with_same_version_commit_only_once(self):
        customer=self.create(entity_verified=True)
        one=self.proposal(customer,event_id='race-a').json()
        two=self.proposal(customer,event_id='race-b').json()
        gate=Barrier(2)
        def submit(proposal, key):
            with TestClient(self.app) as client:
                gate.wait(timeout=5)
                return self.request('POST',f"/customers/{customer['id']}/proposals/{proposal['id']}/confirm",client=client,
                                    payload={'expected_version':1,'request_key':key}).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs=[executor.submit(submit,one,'concurrent-review-a'),executor.submit(submit,two,'concurrent-review-b')]
            codes=sorted(job.result(timeout=20) for job in jobs)
        self.assertEqual(codes,[200,409])
        data=self.detail(customer)
        self.assertEqual(data['customer']['version'],2)
        self.assertEqual(sum(p['status']=='confirmed' for p in data['proposals']),1)
        self.assertEqual(sum(a['action']=='proposal_confirmed' for a in data['audit']),1)


    def test_unverified_entity_cannot_enter_any_normal_business_stage(self):
        customer=self.create()
        for index, stage in enumerate(('lead','contacted','intent')):
            with self.subTest(stage=stage):
                proposal=self.proposal(customer,event_id='unverified-'+stage,proposed_stage=stage)
                self.assertEqual(proposal.status_code,201,proposal.text)
                before=self.counts()
                response=self.confirm(customer,proposal.json(),key='unverified-review-'+stage)
                self.assertEqual(response.status_code,422,response.text)
                self.assertEqual(self.counts(),before)
                data=self.detail(customer)
                self.assertEqual((data['customer']['stage'],data['customer']['version']),('pending',1))
                self.assertTrue(all(p['status']=='pending' for p in data['proposals']))
        candidate=self.proposal(customer,event_id='verified-manually',changes={'entity_verified':True}).json()
        response=self.confirm(customer,candidate,key='confirm-manual-entity')
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['customer']['entity_verified'])

    def test_physical_external_message_cannot_replay_with_changed_event_id_or_payload(self):
        customer=self.create();self.identity(customer)
        for source in ('ai_sales','duzhan_im'):
            with self.subTest(source=source):
                fields={'source_system':source,'event_id':source+'-first',
                        'source_channel_id':'synthetic-channel','source_message_id':source+'-message',
                        'external_namespace':'review.crm','external_id':'customer-1'}
                first=self.proposal(customer,**fields);self.assertEqual(first.status_code,201,first.text)
                before=self.counts()
                same=self.proposal(customer,**fields)
                self.assertEqual(same.status_code,201,same.text)
                self.assertEqual(same.json()['id'],first.json()['id'])
                for changes in ({'event_id':source+'-second'}, {'summary':'Changed evidence'},
                                {'event_id':source+'-third','proposed_stage':'paid'}):
                    response=self.proposal(customer,**(fields|changes))
                    self.assertEqual(response.status_code,409,response.text)
                self.assertEqual(self.counts(),before)
        self.assertEqual(self.detail(customer)['customer']['stage'],'pending')

    def test_upstream_alias_cannot_bypass_replay_and_interfaces_are_explicitly_pending(self):
        customer=self.create();self.identity(customer)
        fields={'source_system':'duzhan','event_id':'alias-first','source_channel_id':'synthetic-group',
                'source_message_id':'alias-message','external_namespace':'review.crm','external_id':'customer-1'}
        first=self.proposal(customer,**fields);self.assertEqual(first.status_code,201,first.text)
        repeated=self.proposal(customer,**(fields|{'source_system':'duzhan_im'}))
        self.assertEqual(repeated.status_code,201,repeated.text)
        self.assertEqual(repeated.json()['id'],first.json()['id'])
        changed=self.proposal(customer,**(fields|{'source_system':'duzhan_im','event_id':'alias-second'}))
        self.assertEqual(changed.status_code,409,changed.text)
        self.assertEqual(self.counts()['lifecycle_evidence'],1)
        meta=self.request('GET','/meta').json()
        self.assertFalse(meta['live_collection'])
        self.assertEqual(meta['integration_status'],'awaiting_upstream_interfaces')
        self.assertEqual(meta['finance_verification'],'manual_manager_review')


if __name__=='__main__':
    unittest.main()
