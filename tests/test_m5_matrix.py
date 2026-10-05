"""M5.5 interactions through default user/tool turns; synthetic backend only.

Endpoint fakes are reused only for their matching routes. Subtest scenarios are
not additional unittest methods or executions of complete public business ATs.
"""
import importlib
import json
import sys
import unittest
from copy import deepcopy
from unittest.mock import patch

from test_m1_adapter import platform_modules
from test_m4_payments import PaymentConversation
from test_m4_cancellations import CancellationBackend
from test_m4_handoffs import HandoffBackend
from test_m5_returns import ReturnsBackend
from test_m5_exchanges import ExchangeBackend
from fakes import FakeResponse
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.proposals import _current_records
from support_agent.protocol import TurnInput
from support_agent.state import initial_state, clone_state
from support_agent.turns import advance


ENDPOINTS = {
    'items': '/v1/orders/%23TEST1/item-modifications',
    'returns': '/v1/orders/%23TEST1/returns',
    'exchange': '/v1/orders/%23TEST1/exchanges',
}


class MatrixBackend(ExchangeBackend):
    """Compose existing synthetic endpoint effects, never real API transports."""
    def __init__(self):
        super().__init__()
        for order in self.orders.values(): order['status'] = 'pending'

    def request(self, method, path, body=None):
        if method == 'POST' and path.endswith('/returns'):
            return ReturnsBackend.request(self, method, path, body)
        if method == 'POST' and path.endswith('/cancellations'):
            return CancellationBackend.request(self, method, path, body)
        if path.endswith('/transfers'):
            return HandoffBackend.request(self, method, path, body)
        return super().request(method, path, body)


class MatrixConversation(PaymentConversation):
    def __init__(self, kind='items', copies=1):
        self.api = MatrixBackend()
        self.kind = kind
        if kind != 'items': self.api.orders['#TEST1']['status'] = 'delivered'
        self.api.orders['#TEST1']['items'] = [deepcopy(self.api.orders['#TEST1']['items'][0]) for _ in range(copies)]
        self.claims = SessionClaims()
        with patch.dict(sys.modules, platform_modules(object())):
            self.toolkit = importlib.import_module('tools').Tools(self.api, claims=self.claims)
        self.state = initial_state()
        self.user('a@example.test')

    def start(self, method='card_a', copies=1, **kwargs):
        if self.kind == 'returns':
            return self.user('Return order #TEST1; items: ' + ','.join(['item_blue'] * copies) + '; refund to ' + method, **kwargs)
        verb = 'Change' if self.kind == 'items' else 'Exchange'
        rows = [{'item_id': 'item_blue', 'replacement_item_id': 'item_red'} for _ in range(copies)]
        return self.user(f'{verb} order #TEST1 items: ' + json.dumps({'replacements': rows, 'payment_method_id': method}), **kwargs)

    def code(self, kind=None):
        key = (kind or self.kind) + '_assessment'
        index = next(i for i in range(len(self.state['history'])-1, -1, -1)
                     if self.state['history'][i]['role'] == 'user')
        assessments = [e[key] for e in self.state['history'][index+1:] if key in e]
        if not assessments:
            raise AssertionError(f'No {key} was produced in the current user turn')
        return assessments[-1]['code']

    def business_calls(self):
        return [c for c in self.api.calls if c[0] in ('PUT', 'POST') and not c[1].endswith('/customers/search')]

    def endpoint_calls(self): return [c for c in self.api.calls if c[1] == ENDPOINTS[self.kind] and c[0] == 'POST']
    def writes(self): return [o for o in self.state['operations'] if o['mutates']]


class ProductInteractionMatrixTests(unittest.TestCase):
    def assert_restored(self, flow):
        self.assertEqual(clone_state(flow.state), flow.state)
        from support_agent.state import initial_state
        rebuilt = initial_state(flow.state['history'])
        for field in ('operations', 'proposals', 'identity_evidence', 'tasks'):
            self.assertEqual(rebuilt[field], flow.state[field], field)

    def assert_verified(self, flow):
        self.assertEqual(len(flow.endpoint_calls()), 1)
        self.assertEqual([o['status'] for o in flow.writes()], ['succeeded'])
        self.assertEqual(flow.code(), 'write_verified')
        self.assert_restored(flow)

    def test_repeated_units_submit_one_complete_payload_and_preserve_counts_across_three_flows(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=3)
                before = deepcopy(flow.api.orders['#TEST1'])
                flow.start(copies=3)
                self.assertEqual(flow.code(), kind + '_confirmation_required')
                self.assertEqual(flow.business_calls(), [])
                flow.user('yes'); self.assert_verified(flow)
                body = flow.endpoint_calls()[0][2]
                if kind == 'returns':
                    self.assertEqual(body, {'item_ids': ['item_blue']*3, 'refund_payment_method_id':'card_a'})
                else:
                    self.assertEqual(body, {'replacements': [{'existing_item_id':'item_blue','replacement_item_id':'item_red'}]*3, 'payment_method_id':'card_a'})
                if kind != 'items': self.assertEqual(flow.api.orders['#TEST1']['items'], before['items'])
                self.assertNotIn('quantity', json.dumps(body))

    def test_overcount_rejects_whole_list_without_partial_submission_on_all_three_flows(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2); before = deepcopy(flow.api.orders)
                flow.start(copies=3)
                self.assertEqual(flow.code(), 'quantity_exceeds_order')
                flow.user('yes')
                self.assertEqual(flow.business_calls(), []); self.assertEqual(flow.api.orders, before)
                self.assertEqual(_current_records(flow.state), [])

    def test_duplicate_id_with_different_original_prices_is_not_silently_assigned_on_any_flow(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2)
                flow.api.orders['#TEST1']['items'][1]['price'] = 20
                before = deepcopy(flow.api.orders)
                flow.start(copies=2)
                self.assertEqual(flow.code(), 'instance_selection_unavailable')
                self.assertEqual(flow.business_calls(), []); self.assertEqual(flow.api.orders, before)

    def test_ambiguous_remove_does_not_turn_two_identical_units_into_an_implicit_single_unit_request(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2); flow.start(copies=2)
                before = deepcopy(flow.api.orders); flow.user('remove item item_blue')
                self.assertEqual(flow.code(), 'return_remove_ambiguous' if kind == 'returns' else 'ambiguous_item_removal')
                flow.user('yes'); self.assertEqual(flow.business_calls(), []); self.assertEqual(flow.api.orders, before)

    def test_complete_reduced_list_rebuilds_version_and_only_new_full_consent_can_send(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2); flow.start(copies=2)
                previous = _current_records(flow.state)[0]['version']
                flow.start(copies=1)
                current = _current_records(flow.state)[0]
                self.assertGreater(current['version'], previous); self.assertIsNone(current['confirmation'])
                self.assertEqual(flow.business_calls(), [])
                flow.user('yes'); self.assert_verified(flow)
                body = flow.endpoint_calls()[0][2]
                self.assertEqual(len(body['item_ids' if kind == 'returns' else 'replacements']), 1)

    def test_partial_assent_to_a_complete_duplicate_list_does_not_submit_any_flow(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2); flow.start(copies=2)
                before = deepcopy(flow.api.orders); flow.user('yes, but only one item')
                self.assertFalse(any(p['status']=='confirmed' for p in _current_records(flow.state)))
                self.assertEqual(flow.business_calls(), []); self.assertEqual(flow.api.orders, before)

    def test_mixed_same_order_return_exchange_intent_requires_clarification_before_either_endpoint(self):
        for text in ('Return and exchange order #TEST1 items; items: item_blue', '订单 #TEST1 退货并换货；商品 item_blue'):
            with self.subTest(text=text):
                flow = MatrixConversation('exchange'); before = deepcopy(flow.api.orders)
                flow.user(text)
                self.assertEqual(flow.code(), 'mixed_or_quantity_request')
                flow.user('yes'); self.assertEqual(flow.business_calls(), []); self.assertEqual(flow.api.orders, before)

    def test_return_application_blocks_later_exchange_on_same_order_with_specific_state_code(self):
        flow = MatrixConversation('returns'); flow.start(); flow.user('yes'); self.assert_verified(flow)
        before = deepcopy(flow.api.orders); calls = deepcopy(flow.business_calls())
        flow.user('Exchange order #TEST1 items; item item_blue: color red; pay with card_a')
        self.assertEqual(flow.code('exchange'), 'return_exchange_already_requested')
        flow.user('yes'); self.assertEqual(flow.business_calls(), calls); self.assertEqual(flow.api.orders, before)

    def test_exchange_application_blocks_later_return_on_same_order_with_specific_state_code(self):
        flow = MatrixConversation('exchange'); flow.start(); flow.user('yes'); self.assert_verified(flow)
        before = deepcopy(flow.api.orders); calls = deepcopy(flow.business_calls())
        flow.user('Return order #TEST1; items: item_blue; refund to original')
        self.assertEqual(flow.code('returns'), 'return_exchange_already_requested')
        flow.user('yes'); self.assertEqual(flow.business_calls(), calls); self.assertEqual(flow.api.orders, before)

    def test_item_modification_lock_blocks_payment_and_cancel_without_new_charge_or_refund(self):
        for text, kind in (('Switch order #TEST1 payment to PayPal','payment'), ('Cancel order #TEST1 because no longer needed','cancellation')):
            with self.subTest(kind=kind):
                flow = MatrixConversation(); flow.start(); flow.user('yes'); self.assert_verified(flow)
                before = deepcopy(flow.api.orders); calls = deepcopy(flow.business_calls())
                flow.user(text); self.assertEqual(flow.code(kind), 'items_modified_lock')
                flow.user('yes'); self.assertEqual(flow.business_calls(), calls); self.assertEqual(flow.api.orders, before)

    def test_zero_difference_duplicate_list_with_zero_balance_gift_is_valid_for_modification_and_exchange(self):
        for kind in ('items','exchange'):
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2)
                flow.api.products['product_mug']['items'][1]['price'] = 12.5
                flow.api.customers['customer_a']['payment_methods'][-1]['balance'] = 0
                before_payments = deepcopy(flow.api.orders['#TEST1']['payments'])
                flow.start('gift_a', copies=2)
                self.assertEqual(_current_records(flow.state)[0]['spec']['amount']['value'], 0)
                self.assertEqual(flow.business_calls(), [])
                flow.user('yes'); self.assert_verified(flow)
                self.assertEqual(flow.api.orders['#TEST1']['payments'], before_payments)
                self.assertEqual(flow.endpoint_calls()[0][2]['payment_method_id'], 'gift_a')
                self.assertEqual(flow.api.customers['customer_a']['payment_methods'][-1]['balance'], 0)

    def test_zero_difference_still_requires_user_selected_method_before_full_recap(self):
        for kind in ('items','exchange'):
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind); flow.api.products['product_mug']['items'][1]['price'] = 12.5
                verb = 'Change' if kind == 'items' else 'Exchange'
                flow.user(f'{verb} order #TEST1 items; item item_blue: color red')
                self.assertEqual(flow.code(), 'payment_method_required'); self.assertEqual(_current_records(flow.state), [])
                flow.user('yes'); self.assertEqual(flow.business_calls(), [])

    def test_positive_duplicate_difference_requires_gift_to_cover_whole_list_not_one_unit(self):
        for kind in ('items','exchange'):
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2)
                flow.api.customers['customer_a']['payment_methods'][-1]['balance'] = 2.5
                before = deepcopy(flow.api.orders); methods = deepcopy(flow.api.customers)
                flow.start('gift_a', copies=2)
                self.assertEqual(flow.code(), 'insufficient_gift_card')
                flow.user('yes'); self.assertEqual(flow.business_calls(), [])
                self.assertEqual(flow.api.orders, before); self.assertEqual(flow.api.customers, methods)

    def test_customer_replaces_insufficient_gift_with_saved_card_then_confirms_new_complete_list(self):
        for kind in ('items','exchange'):
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2)
                flow.api.customers['customer_a']['payment_methods'][-1]['balance'] = 1
                flow.start('gift_a', copies=2); self.assertEqual(flow.code(), 'insufficient_gift_card')
                flow.start('card_v', copies=2)
                self.assertEqual(flow.code(), kind+'_confirmation_required'); self.assertEqual(flow.business_calls(), [])
                spec = _current_records(flow.state)[0]['spec']
                self.assertEqual(spec['amount']['value'], 5); self.assertEqual(spec['parameters']['payment_method_id'], 'card_v')
                flow.user('yes'); self.assert_verified(flow)

    def test_gift_balance_drops_after_full_recap_prevents_old_version_send_for_both_replacement_flows(self):
        for kind in ('items','exchange'):
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind, copies=2); flow.start('gift_a', copies=2)
                old = _current_records(flow.state)[0]['version']
                flow.api.customers['customer_a']['payment_methods'][-1]['balance'] = 1
                before = deepcopy(flow.api.orders); flow.user('yes')
                self.assertEqual(flow.code(), 'insufficient_gift_card'); self.assertEqual(flow.business_calls(), [])
                self.assertEqual(flow.api.orders, before)
                # Historical assent may remain recorded. It is not business
                # eligibility: the fresh balance rule blocks claim and send.
                self.assertEqual(flow.writes(), [])
                self.assertEqual(_current_records(flow.state)[0]['version'], old)

    def test_return_gift_destination_is_not_a_positive_difference_charge_and_can_have_zero_balance(self):
        flow = MatrixConversation('returns', copies=2)
        flow.api.customers['customer_a']['payment_methods'][-1]['balance'] = 0
        # Refresh before opening so this actual profile is the U7 source.
        flow.user('show my profile')
        flow.start('gift_a', copies=2); self.assertEqual(flow.code(), 'returns_confirmation_required')
        flow.user('yes'); self.assert_verified(flow)
        self.assertEqual(flow.endpoint_calls()[0][2]['refund_payment_method_id'], 'gift_a')
        self.assertEqual(flow.api.customers['customer_a']['payment_methods'][-1]['balance'], 0)
        self.assertEqual(len(flow.api.orders['#TEST1']['payments']), 1)

    def test_partial_cancellation_english_chinese_and_item_id_scope_never_become_whole_order_proposals(self):
        texts = ('Cancel only item item_blue from order #TEST1 because no longer needed',
                 'Cancel part of order #TEST1 because no longer needed',
                 '取消订单 #TEST1 中的部分商品，因为不再需要',
                 'Cancel item item_blue from order #TEST1 reason: {"reason":"no longer needed"}')
        for text in texts:
            with self.subTest(text=text):
                flow = MatrixConversation(copies=2); before = deepcopy(flow.api.orders)
                reads = deepcopy(flow.api.calls); flow.user(text)
                self.assertEqual(flow.code('cancellation'), 'cancellation_whole_order_required')
                self.assertEqual(flow.api.calls, reads)  # Error preparation does not read private records.
                self.assertEqual(_current_records(flow.state), [])
                flow.user('yes'); self.assertEqual(flow.business_calls(), []); self.assertEqual(flow.api.orders, before)

    def test_partial_cancellation_correction_invalidates_whole_order_draft_before_yes(self):
        flow = MatrixConversation(copies=2)
        flow.user('Cancel order #TEST1 because no longer needed')
        self.assertEqual(flow.code('cancellation'), 'cancellation_confirmation_required')
        before = deepcopy(flow.api.orders)
        flow.user('only item_blue'); self.assertEqual(flow.code('cancellation'), 'cancellation_whole_order_required')
        flow.user('yes'); self.assertEqual(flow.business_calls(), []); self.assertEqual(flow.api.orders, before)

    def test_retained_or_excluded_item_scope_cannot_be_promoted_to_whole_cancellation(self):
        clauses = ('but keep item_blue', 'except item_blue', 'except for item_blue',
                   'excluding item_blue', 'but retain the blue mug', 'but leave item_blue',
                   '但保留 item_blue', '除了 item_blue 以外', '但留下蓝色杯子')
        for clause in clauses:
            with self.subTest(clause=clause):
                flow=MatrixConversation(copies=2)
                before=deepcopy(flow.api.orders); calls=deepcopy(flow.api.calls)
                text=(f'取消订单 #TEST1，{clause}，因为不再需要' if clause.startswith(('但','除'))
                      else f'Cancel order #TEST1 {clause} because no longer needed')
                flow.user(text)
                self.assertEqual(flow.code('cancellation'),'cancellation_whole_order_required')
                self.assertEqual(_current_records(flow.state),[]); self.assertEqual(flow.api.calls,calls)
                flow.user('yes'); self.assertEqual(flow.business_calls(),[]); self.assertEqual(flow.api.orders,before)

    def test_retained_or_excluded_item_correction_blocks_an_existing_whole_draft(self):
        for clause in ('but keep item_blue','except item_blue','但保留 item_blue','除了 item_blue 以外'):
            with self.subTest(clause=clause):
                flow=MatrixConversation(copies=2); flow.user('Cancel order #TEST1 because no longer needed')
                self.assertEqual(flow.code('cancellation'),'cancellation_confirmation_required')
                calls=deepcopy(flow.api.calls); before=deepcopy(flow.api.orders)
                flow.user(clause)
                self.assertEqual(flow.code('cancellation'),'cancellation_whole_order_required')
                self.assertEqual(flow.api.calls,calls)
                flow.user('yes'); self.assertEqual(flow.business_calls(),[]); self.assertEqual(flow.api.orders,before)

    def test_retained_scope_execute_snapshot_rechecks_the_live_user_text_before_any_read(self):
        for clause in ('but keep item_blue','except item_blue','但保留 item_blue'):
            with self.subTest(clause=clause):
                flow=MatrixConversation(copies=2)
                with patch('support_agent.domain.cancellation_intake._partial_order_scope',return_value=False):
                    flow.user(f'Cancel order #TEST1 {clause} because no longer needed')
                    self.assertEqual(flow.code('cancellation'),'cancellation_confirmation_required')
                    decision=flow.user('yes',consume=False)
                calls=deepcopy(flow.api.calls); before=deepcopy(flow.api.orders)
                flow.consume(decision)
                self.assertEqual(flow.code('cancellation'),'cancellation_whole_order_required')
                self.assertEqual(flow.api.calls,calls); self.assertEqual(flow.api.orders,before); self.assertEqual(flow.writes(),[])

    def test_singular_and_plural_item_cancellation_both_mean_narrowed_scope(self):
        for noun in ('item item_blue','items item_blue,item_red'):
            with self.subTest(noun=noun):
                flow=MatrixConversation(copies=2); calls=deepcopy(flow.api.calls)
                flow.user(f'Cancel {noun} from order #TEST1 because no longer needed')
                self.assertEqual(flow.code('cancellation'),'cancellation_whole_order_required')
                self.assertEqual(flow.api.calls,calls); self.assertEqual(_current_records(flow.state),[])

    def test_retention_words_in_reason_data_do_not_reinterpret_whole_order_scope(self):
        from support_agent.domain.cancellation_intake import request_from_history
        for text in ('Cancel only order #TEST1 because I decided to keep my older mug',
                     'Cancel order #TEST1 reason: {"reason":"but keep item_blue; except item_red"}',
                     '取消整个订单 #TEST1，因为我保留旧杯子'):
            with self.subTest(text=text):
                request=request_from_history([{'role':'user','content':text}])
                self.assertIsNone(request['error']); self.assertEqual(request['order_id'],'#TEST1')

    def test_current_turn_code_helper_rejects_a_stale_workflow_diagnostic(self):
        flow=MatrixConversation(); flow.start()
        self.assertEqual(flow.code(),'items_confirmation_required')
        flow.user('show my profile')
        with self.assertRaisesRegex(AssertionError,'current user turn'): flow.code()

    def test_preexisting_partial_scope_execute_snapshot_is_rechecked_without_private_refresh_or_send(self):
        flow=MatrixConversation(copies=2)
        # Fault injection reproduces the earlier parser's accepted proposal;
        # the new execution boundary must block even an already-built dispatch.
        with patch('support_agent.domain.cancellation_intake._partial_order_scope',return_value=False):
            flow.user('Cancel only item item_blue from order #TEST1 because no longer needed')
            self.assertEqual(flow.code('cancellation'),'cancellation_confirmation_required')
            decision=flow.user('yes',consume=False)
        self.assertEqual(flow.state['cancellation_pending']['mode'],'execute')
        calls=deepcopy(flow.api.calls); orders=deepcopy(flow.api.orders)
        flow.consume(decision)
        self.assertEqual(flow.code('cancellation'),'cancellation_whole_order_required')
        self.assertEqual(flow.api.calls,calls); self.assertEqual(flow.api.orders,orders)
        self.assertEqual(flow.writes(),[])

    def test_explicit_new_whole_order_request_after_partial_denial_requires_fresh_confirmation_and_refunds_full_charge(self):
        flow = MatrixConversation(copies=2)
        flow.user('Cancel only item item_blue from order #TEST1 because no longer needed')
        self.assertEqual(flow.code('cancellation'), 'cancellation_whole_order_required')
        flow.user('Cancel the entire order #TEST1 because no longer needed')
        self.assertEqual(flow.code('cancellation'), 'cancellation_confirmation_required'); self.assertEqual(flow.business_calls(), [])
        flow.user('yes'); self.assertEqual(flow.code('cancellation'), 'write_verified')
        self.assertEqual(flow.business_calls(), [('POST','/v1/orders/%23TEST1/cancellations',{'reason':'no longer needed'})])
        self.assertEqual(flow.api.orders['#TEST1']['payments'], [
            {'transaction_type':'payment','payment_method_id':'card_a','amount':12.5},
            {'transaction_type':'refund','payment_method_id':'card_a','amount':12.5}])
        self.assert_restored(flow)

    def test_partial_words_in_reason_and_only_order_scope_do_not_reclassify_an_entire_cancellation(self):
        from support_agent.domain.cancellation_intake import request_from_history
        for text in ('Cancel only order #TEST1 because no longer needed',
                     'Cancel order #TEST1 reason: {"reason":"I only need one item"}'):
            with self.subTest(text=text):
                request = request_from_history([{'role':'user','content':text}])
                self.assertIsNone(request['error'])
                self.assertEqual(request['order_id'], '#TEST1')

    def test_definite_rejections_preserve_backend_and_do_not_retry_any_product_endpoint(self):
        for kind in ENDPOINTS:
            for status in (409,422):
                with self.subTest(kind=kind,status=status):
                    flow = MatrixConversation(kind, copies=2); flow.start(copies=2)
                    orders, customers = deepcopy(flow.api.orders), deepcopy(flow.api.customers)
                    original = flow.api.request
                    def request(method,path,body=None):
                        if method=='POST' and path==ENDPOINTS[kind]:
                            flow.api.calls.append((method,path,deepcopy(body)))
                            return FakeResponse(status, {'error':{'code':'synthetic_refusal','message':'matrix_private_rejection'}})
                        return original(method,path,body)
                    flow.api.request = request; flow.user('yes')
                    self.assertEqual(flow.code(), 'write_rejected'); self.assertEqual([o['status'] for o in flow.writes()], ['failed'])
                    self.assertEqual(flow.api.orders, orders); self.assertEqual(flow.api.customers, customers)
                    flow.api.request = original; flow.user('yes')
                    self.assertEqual(len(flow.endpoint_calls()), 1); self.assertNotIn('matrix_private_rejection',json.dumps(flow.state))
                    self.assert_restored(flow)

    def test_timeout_after_backend_effect_is_unknown_and_blocks_peer_workflow_new_version(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow = MatrixConversation(kind); flow.start(); original = flow.api.request
                def request(method,path,body=None):
                    response = original(method,path,body)
                    if method=='POST' and path==ENDPOINTS[kind]: raise TimeoutError('matrix_private_timeout')
                    return response
                flow.api.request=request; flow.user('yes')
                self.assertEqual(flow.code(), 'write_result_unknown'); self.assertEqual([o['status'] for o in flow.writes()], ['unknown'])
                flow.api.request=original; calls=deepcopy(flow.business_calls()); orders=deepcopy(flow.api.orders)
                flow.user('Switch order #TEST1 payment to PayPal'); flow.user('yes'); flow.start()
                self.assertEqual(flow.business_calls(),calls); self.assertEqual(flow.api.orders,orders)
                self.assertEqual([o['status'] for o in flow.writes()], ['unknown'])
                self.assertEqual(len(flow.endpoint_calls()),1); self.assertNotIn('matrix_private_timeout',json.dumps(flow.state))
                self.assert_restored(flow)

    def test_unusable_success_receipt_is_unknown_not_completed_and_never_unlocks_another_operation(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow=MatrixConversation(kind); flow.start(); original=flow.api.request
                def request(method,path,body=None):
                    response=original(method,path,body)
                    if method=='POST' and path==ENDPOINTS[kind]: return FakeResponse(200,{})
                    return response
                flow.api.request=request; flow.user('yes')
                self.assertEqual(flow.code(),'write_result_unknown'); self.assertEqual(flow.writes()[0]['status'],'unknown')
                flow.api.request=original; calls=deepcopy(flow.business_calls())
                flow.user('Cancel order #TEST1 because no longer needed'); flow.user('yes')
                self.assertEqual(flow.business_calls(),calls); self.assertEqual(len(flow.endpoint_calls()),1)
                self.assert_restored(flow)

    def test_accepted_unknown_journal_allows_profile_investigation_without_resending_or_resolving_the_write(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow=MatrixConversation(kind); flow.start(); flow.api.failure='timeout'; flow.user('yes')
                self.assertEqual(flow.code(),'write_result_unknown'); self.assertIsNone(flow.state[kind+'_pending'])
                writes=deepcopy(flow.writes()); business=deepcopy(flow.business_calls()); before=len(flow.api.calls)
                flow.api.failure=None; flow.user('show my profile')
                self.assertEqual(flow.api.calls[before:],[
                    ('POST','/v1/customers/search',{'email':'a@example.test'}),
                    ('GET','/v1/customers/customer_a',None)])
                self.assertEqual(flow.state['customer_record']['customer_id'],'customer_a')
                self.assertEqual(flow.writes(),writes); self.assertEqual(flow.business_calls(),business)
                self.assertEqual(flow.writes()[0]['status'],'unknown')
                with self.assertRaisesRegex(AssertionError,'current user turn'): flow.code()
                self.assert_restored(flow)

    def test_lost_execute_result_blocks_all_business_peers_and_profile_without_new_reads(self):
        peers = ('Switch order #TEST1 payment to PayPal',
                 'Return order #TEST1; items: item_blue; refund to original',
                 'Exchange order #TEST1 items; item item_blue: color red; pay with card_a',
                 'Change order #TEST1 items; item item_blue: color red; pay with card_a',
                 'Cancel order #TEST1 because no longer needed', 'show my profile')
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow=MatrixConversation(kind); flow.start(); call=flow.user('yes',consume=False).calls[0]
                getattr(flow.toolkit,call.name)(**call.arguments)
                _,flow.state=advance(TurnInput('tools',outcomes=()),flow.state)
                self.assertEqual(flow.code(),kind+'_workflow_unresolved')
                self.assertEqual(flow.state[kind+'_pending']['status'],'unknown')
                calls=deepcopy(flow.api.calls)
                for text in peers: flow.user(text)
                self.assertEqual(flow.api.calls,calls); self.assertEqual(len(flow.endpoint_calls()),1)
                self.assertEqual(flow.state[kind+'_pending']['status'],'unknown')
                self.assert_restored(flow)

    def test_completed_payment_switch_history_cannot_be_netted_into_a_later_cancellation(self):
        flow=MatrixConversation(); flow.switch('PayPal'); flow.user('yes')
        self.assertEqual(flow.code('payment'),'write_verified')
        before=deepcopy(flow.api.orders); calls=deepcopy(flow.business_calls())
        flow.user('Cancel order #TEST1 because no longer needed')
        self.assertEqual(flow.code('cancellation'),'cancellation_refund_history_review')
        flow.user('yes'); self.assertEqual(flow.business_calls(),calls); self.assertEqual(flow.api.orders,before)
        self.assertEqual(len(flow.api.orders['#TEST1']['payments']),3)

    def test_return_and_exchange_share_no_implicit_refund_destination_permission(self):
        flow=MatrixConversation('exchange'); flow.start('card_v')
        self.assertEqual(flow.code(),'exchange_confirmation_required')
        # A saved card is lawful for exchange but not an original/qualified
        # opening gift return destination. It cannot inherit exchange assent.
        flow.user('Return order #TEST1; items: item_blue; refund to card_v')
        self.assertEqual(flow.code('returns'),'unsupported_return_destination')
        flow.user('yes'); self.assertEqual(flow.business_calls(),[])

    def test_partial_cancellation_intent_from_assistant_or_tool_does_not_change_user_scope(self):
        from support_agent.domain.cancellation_intake import request_from_history
        history=[{'role':'user','content':'Cancel order #TEST1 because no longer needed'},
                 {'role':'assistant','content':'Cancel only item item_blue from order #TEST1'},
                 {'role':'tool','content':'only item_blue'}]
        request=request_from_history(history)
        self.assertIsNone(request['error']); self.assertEqual(request['request_index'],0)

    def test_unresolved_product_write_is_preserved_when_handoff_is_accepted(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow=MatrixConversation(kind); flow.start(); flow.api.failure='timeout'; flow.user('yes')
                self.assertEqual(flow.writes()[0]['status'],'unknown')
                before=deepcopy(flow.writes()); flow.api.failure=None
                flow.user('Please transfer me to a human agent.')
                self.assertEqual(flow.state['handoff']['status'],'accepted')
                self.assertEqual(flow.writes(),before)
                calls=deepcopy(flow.api.calls); flow.start(); flow.user('yes')
                self.assertEqual(flow.api.calls,calls)
                summary=json.loads(next(c[2]['summary'] for c in flow.api.calls if c[1].endswith('/transfers')))
                self.assertIn('unknown',json.dumps(summary)); self.assert_restored(flow)

    def test_after_success_append_and_method_change_cannot_open_a_second_complete_submission(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow=MatrixConversation(kind,copies=2); flow.start(copies=2); flow.user('yes'); self.assert_verified(flow)
                before=deepcopy(flow.api.orders); writes=deepcopy(flow.writes())
                flow.start('gift_a',copies=2)
                self.assertEqual(flow.code(),'items_modified_lock' if kind=='items' else 'return_exchange_already_requested')
                flow.user('add item item_blue'); flow.user('pay with card_v'); flow.user('yes')
                self.assertEqual(len(flow.endpoint_calls()),1); self.assertEqual(flow.api.orders,before)
                self.assertEqual(flow.writes(),writes)

    def test_shared_claim_store_reconstructed_toolkit_blocks_same_duplicate_list_even_when_backend_looks_unwritten(self):
        for kind in ENDPOINTS:
            with self.subTest(kind=kind):
                flow=MatrixConversation(kind,copies=2); flow.start(copies=2)
                call=flow.user('yes',consume=False).calls[0]
                before=deepcopy(flow.api.orders['#TEST1'])
                first=getattr(flow.toolkit,call.name)(**call.arguments)
                self.assertEqual(first['assessment']['code'],'write_verified')
                self.assertEqual(len(flow.endpoint_calls()),1)
                # Remove the state lock's cover: the real shared claim table
                # must prevent sending the stale snapshot from a new instance.
                flow.api.orders['#TEST1']=before
                with patch.dict(sys.modules,platform_modules(object())):
                    rebuilt=importlib.import_module('tools').Tools(flow.api,claims=flow.claims)
                second=getattr(rebuilt,call.name)(**call.arguments)
                self.assertEqual(second['assessment']['code'],'write_already_claimed')
                self.assertEqual(len(flow.endpoint_calls()),1); self.assertEqual(flow.api.orders['#TEST1'],before)


if __name__ == '__main__': unittest.main()
