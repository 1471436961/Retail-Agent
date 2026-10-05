"""M5.3 actual user/default tools/complete consent/return application, offline."""
import importlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from test_m5_items import ItemsBackend
from test_m4_payments import PaymentConversation
from test_m1_adapter import platform_modules
from fakes import FakeResponse
from support_agent.domain.returns_intake import request_from_history
from support_agent.returns_session import build_plan, _prepare
from support_agent.protocol import TurnInput, ToolOutcome, WORKFLOW_TOOL_NAMES, decision_from_candidate, InvalidAction
from support_agent.proposals import _current_records, confirmation_matches
from support_agent.read_session import bind_arguments
from support_agent.state import initial_state, clone_state, InvalidState, SCHEMA_VERSION
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.turns import advance


class ReturnsBackend(ItemsBackend):
    def __init__(self):
        super().__init__()
        for order in self.orders.values(): order['status']='delivered'

    def request(self, method, path, body=None):
        if method=='POST' and path.endswith('/returns'):
            self.calls.append((method,path,deepcopy(body)))
            if self.failure in ('409','422'):
                return FakeResponse(int(self.failure),{'error':{'code':'synthetic_rejection','message':'Synthetic refusal'}})
            order=self.orders[unquote(path.split('/')[-2])]
            if order['status']!='delivered': return FakeResponse(409,{'error':{'code':'operation_not_allowed','message':'Already processed'}})
            order['status']='return requested'
            order['return_request']={**deepcopy(body),'item_ids':sorted(body['item_ids'])}
            receipt={k:deepcopy(order[k]) for k in ('order_id','status','return_request')}
            if self.failure=='timeout': raise TimeoutError('private_return_timeout')
            if self.failure=='bad_receipt': receipt['private_marker']='private_return_body'
            if self.failure=='missing_receipt': receipt.pop('return_request')
            if self.failure=='wrong_readback': order['return_request']['item_ids']=['item_wrong']
            if self.failure=='wrong_destination': order['return_request']['refund_payment_method_id']='card_v'
            if self.failure=='wrong_status': order['status']='delivered'
            return FakeResponse(200,receipt)
        return super().request(method,path,body)


class ReturnsConversation(PaymentConversation):
    def __init__(self, *, verify=True, claims=None, copies=1):
        self.api=ReturnsBackend()
        self.api.orders['#TEST1']['items'] *= copies
        self.api.orders['#TEST1']['items']=deepcopy(self.api.orders['#TEST1']['items'])
        with patch.dict(sys.modules,platform_modules(object())):
            self.toolkit=importlib.import_module('tools').Tools(self.api,claims=claims)
        self.state=initial_state()
        if verify: self.user('a@example.test')

    def start(self, ids='item_blue', destination='original', **kwargs):
        return self.user(f'Return order #TEST1; items: {ids}; refund to {destination}',**kwargs)

    def code(self): return self.state['history'][-1]['returns_assessment']['code']
    def posts(self): return [c for c in self.api.calls if c[0]=='POST' and c[1].endswith('/returns')]
    def basis(self): return next(e['returns_basis'] for e in reversed(self.state['history']) if 'returns_basis' in e)


class ReturnIntakeTests(unittest.TestCase):
    def parse(self,*texts): return request_from_history([{'role':'user','content':t} for t in texts])

    def test_only_actual_user_text_creates_request(self):
        text='Return #TEST1; items: item_blue; refund to original'
        self.assertIsNone(request_from_history([{'role':'assistant','content':text},{'role':'tool','content':text}]))
        self.assertEqual(self.parse(text)['opening_request_index'],0)

    def test_complete_json_preserves_duplicate_units_and_exact_id_as_data(self):
        result=self.parse('Return #TEST1 items: '+json.dumps({'item_ids':['item_blue','item_blue'],'refund_payment_method_id':'cancel_and_return'}))
        self.assertEqual(result['item_ids'],['item_blue','item_blue'])
        self.assertEqual(result['destination']['query'],'cancel_and_return')
        self.assertIsNone(result['error'])

    def test_json_replaces_full_list_and_clears_omitted_destination(self):
        result=self.parse('Return #TEST1; items: item_blue; refund to original','items: {"item_ids":["item_red"]}')
        self.assertEqual(result['item_ids'],['item_red']); self.assertIsNone(result['destination'])
        self.assertEqual(result['opening_request_index'],0); self.assertEqual(result['list_index'],1)

    def test_natural_full_list_replaces_and_add_preserves_occurrences(self):
        result=self.parse('Return #TEST1; items: item_blue','add item item_blue','items: item_red')
        self.assertEqual(result['item_ids'],['item_red'])
        duplicate=self.parse('Return #TEST1; items: item_blue','add item item_blue')
        self.assertEqual(duplicate['item_ids'],['item_blue','item_blue'])

    def test_remove_requires_unambiguous_one_instance(self):
        self.assertEqual(self.parse('Return #TEST1; items: item_blue,item_blue','remove item item_blue')['error'],'return_remove_ambiguous')
        self.assertEqual(self.parse('Return #TEST1; items: item_blue,item_red','remove item item_red')['item_ids'],['item_blue'])

    def test_all_items_and_chinese_clause_are_explicit(self):
        result=self.parse('退货订单 #TEST1；商品: 全部；退款至 原路')
        self.assertTrue(result['all_items']); self.assertEqual(result['destination'],{'kind':'original'})

    def test_named_natural_fields_do_not_become_partial_method_or_item_values(self):
        result=self.parse('Return #TEST1; item_ids=item_blue; refund_payment_method_id=gift_a')
        self.assertIsNone(result['error']); self.assertEqual(result['item_ids'],['item_blue']); self.assertEqual(result['destination']['query'],'gift_a')

    def test_returning_to_prior_order_keeps_that_orders_first_request_index(self):
        result=self.parse('Return #TEST1; items: item_blue','Return #TEST3; items: item_blue','Return #TEST1; items: item_blue; refund to original')
        self.assertEqual(result['opening_request_index'],0); self.assertEqual(result['list_index'],2)

    def test_malformed_list_extra_fields_and_nonstring_method_are_input_errors(self):
        for body in ('{"item_ids":"item_blue"}','{"item_ids":["item_blue"],"quantity":2}', '{"item_ids":["item_blue"],"refund_payment_method_id":1}', '{"item_ids":'):
            with self.subTest(body=body): self.assertTrue(self.parse('Return #TEST1 items: '+body)['error'].startswith('invalid_'))

    def test_conditional_destination_requires_clarification_then_valid_correction(self):
        text='Return #TEST1; items: item_blue; refund to gift card if available'
        self.assertEqual(self.parse(text)['error'],'refund_destination_unresolved')
        corrected=self.parse(text,'refund to original')
        self.assertIsNone(corrected['error']); self.assertEqual(corrected['destination_index'],1)

    def test_destination_correction_does_not_erase_invalid_list(self):
        result=self.parse('Return #TEST1; items: bad value','refund to original')
        self.assertEqual(result['error'],'invalid_return_list')

    def test_mixed_action_and_two_orders_do_not_become_return_parameters(self):
        self.assertEqual(self.parse('Return #TEST1; items: item_blue; cancel order')['error'],'mixed_return_request')
        self.assertEqual(self.parse('Return #TEST1 and #TEST3; items: item_blue')['error'],'return_order_required')


class ReturnFlowTests(unittest.TestCase):
    def test_default_prepare_complete_recap_next_consent_one_post_owned_readback(self):
        flow=ReturnsConversation(); before=deepcopy(flow.api.orders['#TEST1']['payments']); recap=flow.start()
        self.assertEqual(flow.code(),'returns_confirmation_required'); self.assertFalse(flow.posts())
        for text in ('delivered','item_blue','Synthetic mug','original options','original price 12.5','Exact selected original-price sum: 12.5','Estimated refund: 12.50','Mastercard','3-6 business days','one complete return request','does not prove refund'):
            self.assertIn(text,recap.text)
        flow.user('yes')
        self.assertEqual(flow.code(),'write_verified'); self.assertEqual(len(flow.posts()),1)
        self.assertEqual(flow.posts()[0],('POST','/v1/orders/%23TEST1/returns',{'item_ids':['item_blue'],'refund_payment_method_id':'card_a'}))
        self.assertEqual(flow.api.orders['#TEST1']['payments'],before)
        self.assertEqual(flow.writes()[0]['status'],'succeeded')
        self.assertIn('application only',flow.state['history'][-1]['content'])
        post_index=flow.api.calls.index(flow.posts()[0]); self.assertTrue(any(c[0]=='GET' and c[1].endswith('/%23TEST1') for c in flow.api.calls[post_index+1:]))

    def test_estimate_uses_original_price_not_catalog_and_half_up_midpoint(self):
        flow=ReturnsConversation(); flow.api.orders['#TEST1']['items'][0]['price']=0.005
        flow.start(); estimate=flow.basis()['estimate']
        self.assertEqual(estimate['exact_price_sum'],'0.005'); self.assertEqual(estimate['aggregate_amount'],0.01)
        self.assertTrue(estimate['amount_is_estimate']); self.assertFalse(estimate['aggregation_contract_verified']); self.assertFalse(estimate['settlement_verified'])
        self.assertFalse(any('/products' in c[1] for c in flow.api.calls))

    def test_identical_duplicate_units_keep_counts_and_original_price_sum(self):
        flow=ReturnsConversation(copies=2); flow.start('item_blue,item_blue'); flow.user('yes')
        self.assertEqual(flow.code(),'write_verified'); self.assertEqual(flow.posts()[0][2]['item_ids'],['item_blue','item_blue'])
        self.assertEqual(flow.basis()['estimate']['aggregate_amount'],25)

    def test_mixed_ids_accept_sorted_receipt_and_readback_without_losing_counts(self):
        flow=ReturnsConversation(copies=2)
        red=deepcopy(flow.api.orders['#TEST1']['items'][0]); red['item_id']='item_red'
        flow.api.orders['#TEST1']['items']=[red,deepcopy(flow.api.orders['#TEST1']['items'][0]),deepcopy(red)]
        requested=['item_red','item_blue','item_red']
        flow.start(','.join(requested)); self.assertFalse(flow.posts()); flow.user('yes')
        self.assertEqual(flow.code(),'write_verified'); self.assertEqual(len(flow.posts()),1)
        self.assertEqual(flow.posts()[0][2]['item_ids'],requested)
        operation=flow.writes()[0]
        expected=['item_blue','item_red','item_red']
        self.assertNotEqual(requested,expected)
        self.assertEqual(operation['receipt']['return_request']['item_ids'],expected)
        self.assertEqual(flow.api.orders['#TEST1']['return_request']['item_ids'],expected)
        self.assertEqual(operation['status'],'succeeded')

    def test_missing_or_extra_occurrence_in_receipt_or_readback_cannot_verify(self):
        for stage in ('receipt','readback'):
            for changed in (['item_blue','item_red'],['item_blue','item_red','item_red','item_red']):
                with self.subTest(stage=stage,changed=changed):
                    flow=ReturnsConversation(copies=2)
                    red=deepcopy(flow.api.orders['#TEST1']['items'][0]); red['item_id']='item_red'
                    flow.api.orders['#TEST1']['items']=[red,deepcopy(flow.api.orders['#TEST1']['items'][0]),deepcopy(red)]
                    flow.start('item_red,item_blue,item_red')
                    request=flow.api.request
                    def altered(method,path,body=None):
                        response=request(method,path,body)
                        if method=='POST' and path.endswith('/returns'):
                            if stage=='receipt':
                                data=response.json(); data['return_request']['item_ids']=changed
                                return FakeResponse(200,data)
                            flow.api.orders['#TEST1']['return_request']['item_ids']=deepcopy(changed)
                        return response
                    with patch.object(flow.api,'request',side_effect=altered): flow.user('yes')
                    self.assertEqual(len(flow.posts()),1)
                    self.assertEqual(flow.writes()[0]['status'],'unknown' if stage=='receipt' else 'acknowledged')
                    self.assertNotEqual(flow.code(),'write_verified')

    def test_excess_occurrence_and_foreign_item_have_specific_denials(self):
        for ids,code in [('item_blue,item_blue','quantity_exceeds_order'),('item_other','item_not_in_order')]:
            flow=ReturnsConversation(); flow.start(ids); self.assertEqual(flow.code(),code); self.assertFalse(flow.posts())

    def test_different_same_id_instances_need_selection_evidence(self):
        flow=ReturnsConversation(copies=2); flow.api.orders['#TEST1']['items'][1]=deepcopy(flow.api.orders['#TEST1']['items'][1]); flow.api.orders['#TEST1']['items'][1]['price']=13
        flow.start(); self.assertEqual(flow.code(),'instance_selection_unavailable'); self.assertFalse(flow.posts())

    def test_all_items_produces_one_complete_list(self):
        flow=ReturnsConversation(copies=2); flow.start('all'); self.assertEqual(flow.basis()['spec']['parameters']['item_ids'],['item_blue','item_blue'])
        flow.user('确认'); self.assertEqual(len(flow.posts()),1)

    def test_every_nondelivered_exact_state_has_code_and_no_post(self):
        codes={'pending':'action_not_allowed_in_state','pending (items modified)':'items_modified_lock','processed':'order_processed','cancelled':'order_cancelled','return requested':'return_exchange_already_requested','exchange requested':'return_exchange_already_requested'}
        for status,code in codes.items():
            with self.subTest(status=status):
                flow=ReturnsConversation(); flow.api.orders['#TEST1']['status']=status; flow.start(); self.assertEqual(flow.code(),code); self.assertFalse(flow.posts())

    def test_foreign_order_denied_before_order_get(self):
        flow=ReturnsConversation(); before=len(flow.api.calls); flow.user('Return #OTHER; items: item_blue; refund to original')
        self.assertEqual(flow.code(),'returns_order_not_owned'); self.assertFalse(any(c[0]=='GET' and '/orders/' in c[1] for c in flow.api.calls[before:])); self.assertFalse(flow.posts())

    def test_unverified_request_needs_identity_before_private_reads_then_continues(self):
        flow=ReturnsConversation(verify=False); flow.start(); self.assertFalse(flow.api.calls)
        flow.consume(flow.user('a@example.test'))
        self.assertEqual(flow.code(),'returns_confirmation_required'); self.assertTrue(flow.state['identity_evidence'])

    def test_multiple_destinations_require_customer_choice_not_arbitrary_gift(self):
        flow=ReturnsConversation(); flow.user('Return #TEST1; items: item_blue')
        self.assertEqual(flow.code(),'refund_destination_choice_required'); self.assertFalse(flow.state['proposals'])
        flow.user('refund to original'); self.assertEqual(flow.basis()['spec']['parameters']['refund_payment_method_id'],'card_a')

    def test_unique_legal_current_destination_can_be_recapped_without_extra_choice(self):
        for method_id,label in (('card_a','Mastercard'),('gift_a','gift')):
            with self.subTest(method_id=method_id):
                flow=ReturnsConversation()
                flow.api.customers['customer_a']['payment_methods']=[m for m in flow.api.customers['customer_a']['payment_methods'] if m['id']==method_id]
                # Read the gift into the accepted profile BEFORE opening the
                # request; the original card remains the historical charge.
                flow.user('profile')
                recap=flow.user('Return #TEST1; items: item_blue')
                self.assertEqual(flow.code(),'returns_confirmation_required')
                self.assertEqual(flow.basis()['spec']['parameters']['refund_payment_method_id'],method_id)
                self.assertFalse(flow.posts()); self.assertIsNone(_current_records(flow.state)[0]['confirmation'])
                self.assertIn(label,recap.text)
                flow.user('yes'); self.assertEqual(flow.code(),'write_verified'); self.assertEqual(len(flow.posts()),1)
                self.assertEqual(flow.posts()[0][2]['refund_payment_method_id'],method_id)

    def test_malformed_saved_methods_preserve_specific_fact_diagnostic(self):
        flow=ReturnsConversation(); flow.api.customers['customer_a']['payment_methods'][0]['extra']='invalid'
        flow.start()
        self.assertEqual(flow.code(),'refund_destination_facts_required')
        self.assertFalse(flow.posts()); self.assertFalse(flow.state['proposals'])

    def test_original_destination_comes_from_charge_not_historical_refund(self):
        flow=ReturnsConversation(); flow.api.orders['#TEST1']['payments'].append({'transaction_type':'refund','payment_method_id':'card_v','amount':1})
        flow.start(); self.assertEqual(flow.basis()['spec']['parameters']['refund_payment_method_id'],'card_a'); flow.user('yes'); self.assertEqual(flow.code(),'write_verified')

    def test_refunds_without_original_charge_are_unknown_not_zero(self):
        flow=ReturnsConversation(); flow.api.orders['#TEST1']['payments']=[{'transaction_type':'refund','payment_method_id':'card_a','amount':12.5}]
        flow.start(); self.assertEqual(flow.code(),'original_charges_required'); self.assertFalse(flow.posts())

    def test_multiple_original_instruments_need_explicit_one_choice(self):
        flow=ReturnsConversation(); flow.api.orders['#TEST1']['payments'].append({'transaction_type':'payment','payment_method_id':'card_v','amount':1})
        flow.start(); self.assertEqual(flow.code(),'original_refund_choice_ambiguous')
        flow.user('refund to card_v'); self.assertEqual(flow.basis()['spec']['parameters']['refund_payment_method_id'],'card_v')

    def test_unrelated_card_and_paypal_are_not_legal_return_destinations(self):
        for choice in ('card_v','paypal_a'):
            flow=ReturnsConversation(); flow.start(destination=choice); self.assertEqual(flow.code(),'unsupported_return_destination'); self.assertFalse(flow.posts())

    def test_opening_saved_gift_with_zero_balance_is_eligible_without_charge_check(self):
        flow=ReturnsConversation(); flow.api.customers['customer_a']['payment_methods'][-1]['balance']=0
        flow.start(destination='gift_a'); self.assertEqual(flow.code(),'returns_confirmation_required'); self.assertIn('immediate',flow.state['history'][-1]['content'])
        flow.user('yes'); self.assertEqual(flow.code(),'write_verified')

    def test_gift_added_after_opening_cannot_backfill_through_new_recap(self):
        flow=ReturnsConversation(); flow.start(); frozen=deepcopy(flow.basis()['opening_payment_methods'])
        flow.api.customers['customer_a']['payment_methods'].append({'id':'late_gift','source':'gift_card','balance':0})
        flow.user('refund to late_gift'); self.assertEqual(flow.code(),'gift_card_not_eligible_at_opening'); self.assertFalse(flow.posts())
        self.assertEqual(flow.basis()['opening_payment_methods'],frozen)

    def test_profile_read_before_opening_proves_added_gift_eligibility(self):
        flow=ReturnsConversation(); flow.api.customers['customer_a']['payment_methods'].append({'id':'before_gift','source':'gift_card','balance':0})
        flow.user('profile'); flow.start(destination='before_gift'); self.assertEqual(flow.code(),'returns_confirmation_required'); flow.user('yes'); self.assertEqual(flow.code(),'write_verified')

    def test_switching_order_and_back_does_not_make_late_gift_eligible(self):
        flow=ReturnsConversation(); flow.start(); first=deepcopy(flow.basis()['opening_payment_methods'])
        flow.api.customers['customer_a']['payment_methods'].append({'id':'late_gift','source':'gift_card','balance':0})
        flow.user('Return #TEST3; items: item_blue; refund to original'); flow.start(destination='late_gift')
        self.assertEqual(flow.code(),'gift_card_not_eligible_at_opening'); self.assertFalse(flow.posts())
        self.assertEqual(request_from_history(flow.state['history'])['opening_request_index'],next(i for i,e in enumerate(flow.state['history']) if e['role']=='user' and e['content'].startswith('Return order #TEST1')))
        self.assertNotIn('late_gift',[m['id'] for m in first]); self.assertEqual(clone_state(flow.state),flow.state)

    def test_unverified_opening_freezes_first_verified_profile_not_later_refresh(self):
        flow=ReturnsConversation(verify=False); flow.start(destination='gift_a'); flow.consume(flow.user('a@example.test'))
        frozen=deepcopy(flow.basis()['opening_payment_methods']); flow.api.customers['customer_a']['payment_methods'].append({'id':'late_gift','source':'gift_card','balance':0})
        flow.user('refund to late_gift'); self.assertEqual(flow.code(),'gift_card_not_eligible_at_opening'); self.assertNotIn('late_gift',[m['id'] for m in frozen])

    def test_destination_change_requires_new_complete_confirmation(self):
        flow=ReturnsConversation(); flow.start(); old=deepcopy(_current_records(flow.state)[0]); flow.user('refund to gift_a')
        self.assertGreater(_current_records(flow.state)[0]['version'],old['version']); self.assertFalse(confirmation_matches(flow.state,old['version'],old['spec'])); self.assertFalse(flow.posts())
        flow.user('yes'); self.assertEqual(flow.posts()[0][2]['refund_payment_method_id'],'gift_a')

    def test_append_and_remove_change_whole_list_without_partial_submission(self):
        flow=ReturnsConversation(copies=2); flow.start(); flow.user('add item item_blue'); self.assertFalse(flow.posts()); self.assertEqual(len(flow.basis()['spec']['parameters']['item_ids']),2)
        flow.user('yes'); self.assertEqual(len(flow.posts()),1)

    def test_partial_condition_withdrawal_and_nonadjacent_yes_do_not_submit(self):
        for text in ('yes if cheaper','only one item','withdraw all','yes but add another item'):
            flow=ReturnsConversation(); flow.start(); flow.user(text); self.assertFalse(flow.posts()); flow.user('yes'); self.assertFalse(flow.posts())

    def test_success_locks_out_second_return_or_append(self):
        flow=ReturnsConversation(copies=2); flow.start(); flow.user('yes'); flow.user('add item item_blue')
        self.assertEqual(flow.code(),'return_exchange_already_requested'); flow.user('yes'); self.assertEqual(len(flow.posts()),1)

    def test_changed_original_price_rebuilds_estimate_without_sending_old_version(self):
        flow=ReturnsConversation(); flow.start(); flow.api.orders['#TEST1']['items'][0]['price']=20; flow.user('yes')
        self.assertEqual(flow.code(),'returns_confirmation_required'); self.assertFalse(flow.posts()); self.assertEqual(flow.basis()['estimate']['aggregate_amount'],20)
        flow.user('yes'); self.assertEqual(flow.code(),'write_verified')

    def test_delivered_status_change_before_execution_blocks(self):
        flow=ReturnsConversation(); flow.start(); flow.api.orders['#TEST1']['status']='processed'; flow.user('yes')
        self.assertEqual(flow.code(),'order_processed'); self.assertFalse(flow.posts())

    def test_removed_gift_before_execution_requires_review_and_no_post(self):
        flow=ReturnsConversation(); flow.start(destination='gift_a'); flow.api.customers['customer_a']['payment_methods']=[m for m in flow.api.customers['customer_a']['payment_methods'] if m['id']!='gift_a']; flow.user('yes')
        self.assertEqual(flow.code(),'payment_method_not_saved'); self.assertFalse(flow.posts())

    def test_http_409_and_422_are_failed_once_without_retry(self):
        for failure in ('409','422'):
            flow=ReturnsConversation(); flow.start(); flow.api.failure=failure; flow.user('yes'); self.assertEqual(flow.writes()[0]['status'],'failed'); self.assertEqual(flow.code(),'write_rejected'); flow.user('yes'); self.assertEqual(len(flow.posts()),1)

    def test_timeout_after_backend_effect_stays_unknown_and_cannot_repeat(self):
        flow=ReturnsConversation(); flow.start(); flow.api.failure='timeout'; flow.user('yes')
        self.assertEqual(flow.code(),'write_result_unknown'); self.assertEqual(flow.writes()[0]['status'],'unknown'); self.assertEqual(flow.api.orders['#TEST1']['status'],'return requested')
        flow.start(); flow.user('yes'); self.assertEqual(len(flow.posts()),1)

    def test_invalid_success_receipt_is_unknown_without_private_body_acceptance(self):
        for failure in ('bad_receipt','missing_receipt'):
            flow=ReturnsConversation(); flow.start(); flow.api.failure=failure; flow.user('yes')
            self.assertEqual(flow.writes()[0]['status'],'unknown'); self.assertNotIn('private_return_body',json.dumps(flow.state)); self.assertNotEqual(flow.code(),'write_verified')

    def test_wrong_strong_readback_never_proves_application(self):
        for failure in ('wrong_readback','wrong_destination','wrong_status'):
            flow=ReturnsConversation(); flow.start(); flow.api.failure=failure; flow.user('yes')
            self.assertEqual(flow.writes()[0]['status'],'acknowledged'); self.assertNotEqual(flow.code(),'write_verified'); self.assertEqual(len(flow.posts()),1)

    def test_lost_execute_bundle_reserves_unknown_without_false_zero_writes(self):
        flow=ReturnsConversation(); flow.start(); decision=flow.user('yes',consume=False); action=decision.calls[0]
        getattr(flow.toolkit,action.name)(**action.arguments)
        _,flow.state=advance(TurnInput('tools',outcomes=()),flow.state)
        self.assertEqual(flow.code(),'returns_workflow_unresolved'); self.assertEqual(flow.state['returns_pending']['status'],'unknown')
        flow.user('profile'); flow.start(); self.assertEqual(len(flow.posts()),1); self.assertIsNotNone(flow.state['returns_pending'])

    def test_lost_read_only_prepare_is_recoverable_and_late_result_ignored(self):
        flow=ReturnsConversation(); decision=flow.start(consume=False); action=decision.calls[0]; payload=getattr(flow.toolkit,action.name)(**action.arguments)
        _,flow.state=advance(TurnInput('tools',outcomes=()),flow.state); self.assertEqual(flow.code(),'returns_prepare_abandoned'); self.assertIsNone(flow.state['returns_pending'])
        flow.user('retry'); before=deepcopy(flow.state)
        _,flow.state=advance(TurnInput('tools',outcomes=(ToolOutcome(action.id,json.dumps(payload)),)),flow.state)
        self.assertEqual(flow.state['proposals'],before['proposals']); self.assertFalse(flow.posts())

    def test_shared_claim_store_prevents_new_toolkit_from_resending_snapshot(self):
        claims=SessionClaims(); flow=ReturnsConversation(claims=claims); flow.start(); action=flow.user('yes',consume=False).calls[0]
        original_order=deepcopy(flow.api.orders['#TEST1'])
        first=flow.toolkit.returns_workflow(**action.arguments); self.assertEqual(len(flow.posts()),1)
        # Fault injection: make the backend look pre-write again, so a state
        # gate cannot mask a broken shared-store claim. Retain the real claim.
        flow.api.orders['#TEST1']=original_order
        with patch.dict(sys.modules,platform_modules(object())): other=importlib.import_module('tools').Tools(flow.api,claims=claims)
        second=other.returns_workflow(**action.arguments)
        self.assertEqual(len(flow.posts()),1); self.assertEqual(second['assessment']['code'],'write_already_claimed'); self.assertEqual(first['assessment']['code'],'write_verified')

    def test_handoff_preserves_unknown_return_reservation_and_stops_model_projection(self):
        flow=ReturnsConversation(); flow.start(); flow.user('yes',consume=False); flow.user('transfer me to a human',consume=False)
        self.assertEqual(flow.state['returns_pending']['status'],'unknown')
        from support_agent.model_context import project_messages
        with self.assertRaises(InvalidAction): project_messages(flow.state)

    def test_read_budget_is_checked_before_profile_or_order_calls(self):
        flow=ReturnsConversation(); flow.start(consume=False); flow.state['tool_calls_since_user']=11; before=deepcopy(flow.api.calls)
        _,state=_prepare(flow.state,flow.api); self.assertEqual(state['history'][-1]['returns_assessment']['code'],'returns_read_budget_exceeded'); self.assertEqual(flow.api.calls,before)

    def test_profile_and_order_read_failure_have_specific_codes(self):
        from support_agent.address_session import _safe_read
        for name,code in [('read_customer_profile','returns_profile_read_failed'),('get_order','returns_order_read_failed')]:
            flow=ReturnsConversation()
            def read(state,api,tool,args): return (None,'failed') if tool==name else _safe_read(state,api,tool,args)
            with patch('support_agent.returns_session._safe_read',side_effect=read): flow.start()
            self.assertEqual(flow.code(),code); self.assertFalse(flow.posts())

    def test_recap_budget_refuses_complete_request_without_truncating_or_splitting(self):
        flow=ReturnsConversation(); flow.api.orders['#TEST1']['items'][0]['name']='Synthetic '+('x'*4200); flow.start()
        self.assertEqual(flow.code(),'returns_recap_budget_exceeded'); self.assertFalse(flow.posts()); self.assertFalse(flow.state['proposals']); self.assertFalse(any('returns_basis' in e for e in flow.state['history']))

    def test_many_original_units_exceed_recap_budget_without_partial_proposal_or_send(self):
        flow=ReturnsConversation(copies=40); original=deepcopy(flow.api.orders['#TEST1'])
        flow.start('all')
        self.assertEqual(flow.code(),'returns_recap_budget_exceeded'); self.assertFalse(flow.posts())
        self.assertFalse(flow.state['proposals']); self.assertFalse(flow.writes())
        self.assertFalse(any('returns_basis' in e for e in flow.state['history']))
        self.assertEqual(flow.api.orders['#TEST1'],original)
        self.assertEqual(request_from_history(flow.state['history'])['all_items'],True)
        flow.user('yes'); self.assertFalse(flow.posts()); self.assertFalse(flow.state['proposals'])

    def test_preparation_exception_is_safe_and_runtime_exception_sends_nothing(self):
        flow=ReturnsConversation()
        with patch('support_agent.returns_session._prepare',side_effect=ValueError('private_error')): flow.start()
        self.assertEqual(flow.code(),'returns_preparation_failed'); self.assertNotIn('private_error',json.dumps(flow.state))
        flow=ReturnsConversation(); flow.start()
        with patch('support_agent.returns_session.ReturnsRuntime',side_effect=ValueError('private_error')): flow.user('yes')
        self.assertEqual(flow.code(),'returns_runtime_unavailable'); self.assertFalse(flow.posts())

    def test_tool_argument_and_result_limits_stop_side_effects_before_send(self):
        claims=SessionClaims(); flow=ReturnsConversation(claims=claims); decision=flow.start(consume=False); before=deepcopy(flow.state)
        calls=deepcopy(flow.api.calls)
        stores=deepcopy((claims.sessions,claims.dispatched,claims.handoffs))
        with self.assertRaises(ValueError): flow.toolkit.returns_workflow('x'*(256*1024+1))
        self.assertEqual(flow.api.calls,calls)
        self.assertEqual((claims.sessions,claims.dispatched,claims.handoffs),stores)
        with patch('support_agent.returns_session.MAX_WORKFLOW_RESULT_BYTES',5000): payload=flow.toolkit.returns_workflow(**decision.calls[0].arguments)
        self.assertEqual(payload['assessment']['code'],'returns_result_budget_exceeded'); self.assertFalse(flow.posts()); self.assertEqual(payload['state']['proposals'],before['proposals'])
        self.assertEqual((claims.sessions,claims.dispatched,claims.handoffs),stores)

    def test_post_send_result_overflow_keeps_unknown_reservation_and_no_resend(self):
        from support_agent.workflow_limits import WorkflowResultTooLarge
        flow=ReturnsConversation(); flow.start(); action=flow.user('yes',consume=False).calls[0]
        with patch('support_agent.returns_session.MAX_WORKFLOW_RESULT_BYTES',5000):
            with self.assertRaises(WorkflowResultTooLarge): flow.toolkit.returns_workflow(**action.arguments)
        self.assertEqual(len(flow.posts()),1)
        _,flow.state=advance(TurnInput('tools',outcomes=(ToolOutcome(action.id,'unavailable',True),)),flow.state)
        self.assertEqual(flow.state['returns_pending']['status'],'unknown'); self.assertEqual(flow.code(),'returns_workflow_unresolved')
        flow.user('yes'); self.assertEqual(len(flow.posts()),1)

    def test_inbound_oversized_prepare_result_is_not_parsed_or_accepted(self):
        flow=ReturnsConversation(); action=flow.start(consume=False).calls[0]
        _,flow.state=advance(TurnInput('tools',outcomes=(ToolOutcome(action.id,'x'*(1024*1024+1)),)),flow.state)
        self.assertEqual(flow.code(),'returns_prepare_abandoned'); self.assertFalse(flow.posts()); self.assertFalse(flow.state['proposals']); self.assertNotIn('x'*100,json.dumps(flow.state))


class ReturnRecoveryTests(unittest.TestCase):
    def test_shared_business_kinds_restore_and_block_every_peer_without_handoff(self):
        from support_agent.workflow_registry import WORKFLOW_KINDS
        from support_agent.workflow_boundary import WorkflowBoundary
        from support_agent.workflow_limits import MAX_WORKFLOW_RESULT_BYTES
        self.assertEqual(WORKFLOW_KINDS,('address','payment','cancellation','items','returns'))
        self.assertNotIn('handoff',WORKFLOW_KINDS)
        self.assertEqual(WORKFLOW_TOOL_NAMES,frozenset(k+'_workflow' for k in WORKFLOW_KINDS)|{'handoff_workflow'})
        for unknown in ('handoff','exchange','model_supplied_kind'):
            with self.subTest(unknown=unknown), self.assertRaises(ValueError):
                WorkflowBoundary(unknown,MAX_WORKFLOW_RESULT_BYTES)
        flow=ReturnsConversation()
        for kind in WORKFLOW_KINDS:
            with self.subTest(kind=kind):
                decision,state=WorkflowBoundary(kind,MAX_WORKFLOW_RESULT_BYTES).dispatch(flow.state,'prepare')
                self.assertEqual(decision.calls[0].name,kind+'_workflow')
                self.assertEqual([k for k in WORKFLOW_KINDS if state[k+'_pending'] is not None],[kind])
                self.assertEqual(initial_state(state['history'])[kind+'_pending'],state[kind+'_pending'])
                for peer in WORKFLOW_KINDS:
                    with self.subTest(peer=peer), self.assertRaises(InvalidAction):
                        WorkflowBoundary(peer,MAX_WORKFLOW_RESULT_BYTES).dispatch(state,'prepare')
                self.assertFalse(flow.posts())

    def test_real_schema10_fixture_migrates_without_inventing_return_consent(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/m5_schema10_state.json').read_text(encoding='utf-8'))
        self.assertEqual(fixture['source_commit'],'a0308d7e81a7ec3ae7786fbfe1829f56be4f3f88')
        state=fixture['state']; self.assertEqual(state['schema_version'],10); self.assertNotIn('returns_pending',state)
        migrated=clone_state(state); self.assertEqual(migrated['schema_version'],SCHEMA_VERSION); self.assertIsNone(migrated['returns_pending']); self.assertEqual(migrated['proposals'],state['proposals'])

    def test_legacy_schema_cannot_carry_return_metadata_or_pending(self):
        flow=ReturnsConversation(); flow.start()
        for version in (1,2,3,4,5,6,7,8,9,10):
            with self.subTest(version=version):
                damaged=deepcopy(flow.state); damaged['schema_version']=version
                with self.assertRaises(InvalidState): clone_state(damaged)

    def test_restore_and_clone_keep_sources_list_opening_and_completed_journal(self):
        flow=ReturnsConversation(); flow.start(); flow.user('yes'); restored=initial_state(flow.state['history'])
        for key in ('history','identity_evidence','proposals','operations','returns_pending'): self.assertEqual(restored[key],flow.state[key])
        self.assertEqual(clone_state(flow.state),flow.state)

    def test_basis_tampering_of_sources_estimate_or_opening_is_rejected(self):
        flow=ReturnsConversation(); flow.start()
        for key in ('sources','estimate','opening_profile_index','opening_payment_methods','spec'):
            damaged=deepcopy(flow.state); entry=next(e for e in damaged['history'] if 'returns_basis' in e); entry['returns_basis'][key]=None
            entry['content']='Return intake evidence: '+json.dumps(entry['returns_basis'],sort_keys=True)
            with self.subTest(key=key), self.assertRaises(InvalidState): clone_state(damaged)

    def test_future_gift_or_user_evidence_cannot_repair_past_basis(self):
        flow=ReturnsConversation(); flow.start(); index=next(i for i,e in enumerate(flow.state['history']) if 'returns_basis' in e)
        flow.api.customers['customer_a']['payment_methods'].append({'id':'late_gift','source':'gift_card','balance':1}); flow.user('refund to original')
        self.assertEqual(flow.state['history'][index]['returns_basis']['spec']['parameters']['refund_payment_method_id'],'card_a')
        self.assertEqual(initial_state(flow.state['history'])['history'][index],flow.state['history'][index])

    def test_real_model_candidate_shape_and_binding_reject_all_workflow_names(self):
        from support_agent.protocol import ToolAction
        flow=ReturnsConversation()
        self.assertIn('returns_workflow',WORKFLOW_TOOL_NAMES)
        for name in WORKFLOW_TOOL_NAMES:
            with self.subTest(name=name):
                with self.assertRaisesRegex(InvalidAction,'business workflow'): decision_from_candidate({'type':'tool','name':name,'arguments':{'session_json':json.dumps(flow.state)}},call_id='model')
                with self.assertRaises(InvalidAction): bind_arguments(name,{'session_json':json.dumps(flow.state)},flow.state)


if __name__=='__main__': unittest.main()
