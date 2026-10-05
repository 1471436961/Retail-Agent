"""M5.2 synthetic full-list conversations; no real network or model."""
import importlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from test_m4_payments import PaymentBackend, PaymentConversation
from test_m1_adapter import platform_modules
from fakes import FakeResponse
from support_agent.domain.items_intake import request_from_history, criteria_for_line
from support_agent.items_session import _prepare, build_plan
from support_agent.protocol import TurnInput, ToolOutcome, decision_from_candidate, InvalidAction, WORKFLOW_TOOL_NAMES
from support_agent.proposals import _current_records, ITEMS_LAST_CALL, InvalidProposal, present_proposals, confirmation_matches, render_proposal_set
from support_agent.state import initial_state, clone_state, InvalidState, SCHEMA_VERSION
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.turns import advance


class ItemsBackend(PaymentBackend):
    def __init__(self):
        super().__init__()
        for order in self.orders.values():
            for row in order['items']:
                row.update(name='Synthetic mug', options={'color': 'blue', 'capacity': '500 ml', 'waterproof': 'yes'})
        self.products['product_mug']['items'] = [
            {'item_id': id, 'price': price, 'options': {'color': color, 'capacity': capacity, 'waterproof': 'yes'}, 'available': True}
            for id, price, color, capacity in [('item_blue', 99, 'blue', '500 ml'), ('item_red', 15, 'red', '500 ml'),
                                              ('item_green', 10, 'green', '500 ml'), ('item_large', 20, 'red', '1 l')]]

    def request(self, method, path, body=None):
        if method == 'POST' and path.endswith('/item-modifications'):
            self.calls.append((method, path, deepcopy(body)))
            if self.failure in ('409', '422'):
                return FakeResponse(int(self.failure), {'error': {'code': 'synthetic_rejected', 'message': 'Synthetic business refusal'}})
            order = self.orders[unquote(path.split('/')[-2])]
            if order['status'] != 'pending':
                return FakeResponse(409, {'error': {'code': 'operation_not_allowed', 'message': 'Synthetic state lock'}})
            difference = 0.0
            for pair in body['replacements']:
                old = next(i for i in order['items'] if i['item_id'] == pair['existing_item_id'])
                target = next(i for p in self.products.values() for i in p['items'] if i['item_id'] == pair['replacement_item_id'])
                difference += target['price'] - old['price']
                old.update({k: deepcopy(target[k]) for k in ('item_id', 'price', 'options')})
            difference = round(difference, 2)
            if difference:
                order['payments'].append({'transaction_type': 'payment' if difference > 0 else 'refund', 'payment_method_id': body['payment_method_id'], 'amount': abs(difference)})
            elif isinstance(self.failure, str) and self.failure.startswith('zero_'):
                row = {'transaction_type': 'refund', 'payment_method_id': body['payment_method_id'], 'amount': 0}
                if self.failure == 'zero_nonzero': row['amount'] = 1
                if self.failure == 'zero_wrong_method': row['payment_method_id'] = 'card_v'
                if self.failure == 'zero_payment': row['transaction_type'] = 'payment'
                order['payments'].extend([deepcopy(row), deepcopy(row)] if self.failure == 'zero_duplicate' else [row])
            order['status'] = 'pending (items modified)'
            receipt = {k: deepcopy(order[k]) for k in ('order_id', 'status', 'items', 'payments')}
            if self.failure == 'timeout': raise TimeoutError('private_items_timeout')
            if self.failure == 'bad_receipt': receipt['private_field'] = 'rejected_private_items_body'
            if self.failure == 'wrong_items': order['items'][0]['options']['color'] = 'wrong'
            return FakeResponse(200, receipt)
        return super().request(method, path, body)


class ItemsConversation(PaymentConversation):
    def __init__(self, *, verify=True, claims=None):
        self.api = ItemsBackend()
        with patch.dict(sys.modules, platform_modules(object())):
            self.toolkit = importlib.import_module('tools').Tools(self.api, claims=claims)
        self.state = initial_state()
        if verify: self.user('a@example.test')

    def change(self, text='color to red', method='card_a', **kwargs):
        return self.user(f'Change order #TEST1 items; item item_blue: {text}; pay with {method}', **kwargs)

    def posts(self):
        return [c for c in self.api.calls if c[0] == 'POST' and c[1].endswith('/item-modifications')]

    def code(self): return self.state['history'][-1]['items_assessment']['code']

    def envelope(self, rows, method='card_a'):
        body = {'replacements': rows}
        if method is not None: body['payment_method_id'] = method
        return self.user('Change order #TEST1 items: ' + json.dumps(body))


class ItemIntakeTests(unittest.TestCase):
    def test_only_actual_user_messages_create_list_and_method_sources(self):
        text = 'Change order #TEST1 items; item item_blue: color red; pay with card_a'
        self.assertIsNone(request_from_history([{'role': 'assistant', 'content': text}, {'role': 'tool', 'content': text}]))
        request = request_from_history([{'role': 'user', 'content': text}])
        self.assertEqual(request['lines'][0]['index'], 0)
        self.assertEqual(request['method'], {'query': 'card_a', 'index': 0})

    def test_correction_replaces_one_line_and_explicit_add_keeps_an_occurrence(self):
        history = [{'role': 'user', 'content': 'Change order #TEST1 items; item item_blue: color red'},
                   {'role': 'user', 'content': 'item item_blue: color green'},
                   {'role': 'user', 'content': 'add item item_blue: color red'}]
        request = request_from_history(history)
        self.assertEqual([l['text'] for l in request['lines']], ['color green', 'color red'])
        self.assertEqual([l['index'] for l in request['lines']], [1, 2])

    def test_malformed_json_extra_keys_and_quantity_do_not_become_a_partial_list(self):
        for value in ('{"replacements":', '{"replacements":[],"confirmed":true}', '{"replacements":[{"item_id":"item_blue","quantity":2}]}'):
            request = request_from_history([{'role': 'user', 'content': 'Change order #TEST1 items: ' + value}])
            self.assertEqual(request['error'], 'quantity_change_unsupported' if 'quantity' in value else 'invalid_items_json')

    def test_unsupported_phrases_require_clarification_instead_of_being_ignored(self):
        original = ItemsBackend().orders['#TEST1']['items'][0]
        for text in ('color red if the delivery is faster', 'whatever looks nice', 'processor i9'):
            self.assertIn(criteria_for_line({'text': text}, original)['code'], {'item_condition_unresolved', 'unknown_item_attribute'})

    def test_hard_budget_ranking_preference_and_fallback_have_explicit_normalized_semantics(self):
        original = ItemsBackend().orders['#TEST1']['items'][0]
        result = criteria_for_line({'text': 'color red; price <= original; cheapest otherwise color green'}, original)
        self.assertEqual(result['decision'], 'allow')
        criteria = result['details']['criteria']
        self.assertEqual(criteria['hard'][1]['value'], {'original': 'price'})
        self.assertEqual(criteria['ranking'], [{'field': 'price', 'direction': 'min'}])
        self.assertEqual(criteria['fallbacks'][0]['change'], ['color'])
        result = criteria_for_line({'text': 'prefer color: red then green'}, original)
        self.assertEqual(result['details']['criteria']['preferences'][0]['tiers'], [['red'], ['green']])


    def test_payment_reply_does_not_clear_a_rejected_list_until_actual_correction(self):
        history = [{'role': 'user', 'content': 'Change order #TEST1 items; item item_blue: color red'},
                   {'role': 'user', 'content': 'items: {"replacements":'},
                   {'role': 'user', 'content': 'pay with card_a'}]
        self.assertEqual(request_from_history(history)['error'], 'invalid_items_json')
        history.append({'role': 'user', 'content': 'item item_blue: color green'})
        self.assertIsNone(request_from_history(history)['error'])


class ItemFlowTests(unittest.TestCase):
    def test_zero_quote_accepts_no_row_or_one_upstream_zero_refund_only(self):
        for failure in (None, 'zero_refund'):
            flow = ItemsConversation(); flow.api.products['product_mug']['items'][1]['price'] = 12.5
            flow.change(); flow.api.failure = failure; flow.user('yes')
            self.assertEqual(flow.code(), 'write_verified')
            self.assertEqual(flow.writes()[-1]['status'], 'succeeded')
            self.assertEqual(len(flow.api.orders['#TEST1']['payments']), 1 if failure is None else 2)

    def test_zero_quote_extra_nonzero_wrong_destination_or_duplicate_rows_stay_unresolved(self):
        for failure in ('zero_nonzero', 'zero_wrong_method', 'zero_duplicate', 'zero_payment'):
            with self.subTest(failure=failure):
                flow = ItemsConversation(); flow.api.products['product_mug']['items'][1]['price'] = 12.5
                flow.change(); flow.api.failure = failure; flow.user('yes')
                self.assertEqual(flow.code(), 'write_verification_unresolved')
                self.assertEqual(flow.writes()[-1]['status'], 'acknowledged')
                flow.user('yes'); self.assertEqual(len(flow.posts()), 1)

    def test_compact_eight_item_recap_keeps_every_line_and_sources_without_raw_metadata(self):
        flow = ItemsConversation(); original = flow.api.orders['#TEST1']['items'][0]
        flow.api.orders['#TEST1']['items'] = [deepcopy(original) for _ in range(8)]
        decision = flow.envelope([{'item_id': 'item_blue', 'options': {'color': 'red'}} for _ in range(8)])
        self.assertEqual(flow.code(), 'items_confirmation_required')
        presentation = next(e for e in reversed(flow.state['history']) if 'proposal_set' in e)
        self.assertLessEqual(len(presentation['presentation_note']), 4096)
        self.assertIn('Item 8:', decision.text)
        self.assertEqual(decision.text.count('original price'), 8)
        self.assertNotIn('history_index', decision.text)
        basis = next(e['items_basis'] for e in reversed(flow.state['history']) if 'items_basis' in e)
        self.assertEqual(len(basis['sources']), 8)
        for source in basis['sources']:
            self.assertEqual(flow.state['history'][source['history_index']]['content'], source['user_text'])
        self.assertEqual(decision.text.count('?'), 1)
        self.assertTrue(decision.text.endswith(ITEMS_LAST_CALL))
        self.assertEqual(flow.posts(), [])
        flow.user('yes'); self.assertEqual(flow.code(), 'write_verified')
        self.assertEqual(len(flow.posts()), 1); self.assertEqual(len(flow.posts()[0][2]['replacements']), 8)

    def test_recap_over_budget_refuses_whole_list_without_truncation_or_proposal(self):
        flow = ItemsConversation(); option = 'x' * 4500
        flow.api.orders['#TEST1']['items'][0]['options']['capacity'] = option
        for row in flow.api.products['product_mug']['items']: row['options']['capacity'] = option
        decision = flow.envelope([{'item_id': 'item_blue', 'replacement_item_id': 'item_red'}])
        self.assertEqual(flow.code(), 'items_recap_budget_exceeded')
        self.assertIn('Repeating the same input will not resolve', decision.text)
        self.assertEqual(flow.state['proposals'], [])
        self.assertFalse(any('items_basis' in e for e in flow.state['history']))
        self.assertEqual(flow.posts(), [])
        flow.user('yes'); self.assertEqual(flow.posts(), [])
        flow.user('retry'); self.assertEqual(flow.code(), 'items_recap_budget_exceeded')

    def test_runtime_initialization_failure_stops_before_refresh_and_send(self):
        flow = ItemsConversation(); flow.change(); flow.api.context.conversation_id = None
        before = deepcopy(flow.api.calls); flow.user('yes')
        self.assertEqual(flow.code(), 'items_runtime_unavailable')
        self.assertEqual(flow.api.calls, before); self.assertEqual(flow.posts(), [])

    def test_preparation_exception_rolls_back_partial_evidence_with_safe_code(self):
        flow = ItemsConversation()
        with patch('support_agent.items_session.render_items_note', side_effect=RuntimeError('private_prepare_marker')):
            flow.change()
        self.assertEqual(flow.code(), 'items_preparation_failed')
        self.assertEqual(flow.state['proposals'], [])
        self.assertNotIn('private_prepare_marker', json.dumps(flow.state)); self.assertEqual(flow.posts(), [])
        flow.user('retry'); self.assertEqual(flow.code(), 'items_confirmation_required')

    def test_repreparation_exception_after_changed_quote_keeps_zero_sends(self):
        flow = ItemsConversation(); flow.change(); flow.api.products['product_mug']['items'][1]['price'] = 16
        with patch('support_agent.items_session.render_items_note', side_effect=RuntimeError('private_reprepare_marker')):
            flow.user('yes')
        self.assertEqual(flow.code(), 'items_repreparation_failed'); self.assertEqual(flow.posts(), [])
        self.assertNotIn('private_reprepare_marker', json.dumps(flow.state))
        record = _current_records(flow.state)[0]
        self.assertFalse(confirmation_matches(flow.state, record['version'], record['spec']))

    def test_conditional_or_conflicting_methods_require_clarification_without_recap(self):
        for method in ('card_a if it is cheaper', 'card_a; pay with paypal_a'):
            flow = ItemsConversation(); flow.change(method=method)
            self.assertEqual(flow.code(), 'settlement_choice_unresolved')
            self.assertEqual(flow.state['proposals'], [])
            self.assertEqual(flow.posts(), [])
            flow.user('pay with card_a')
            self.assertEqual(flow.code(), 'items_confirmation_required')
            self.assertEqual(flow.posts(), [])

    def test_mixed_cancel_and_items_preserves_existing_conflict_diagnostic(self):
        flow = ItemsConversation(); flow.user('Cancel order #TEST1 and change items')
        self.assertEqual(flow.state['history'][-1]['cancellation_assessment']['code'], 'mixed_business_request')
        self.assertEqual(flow.state['proposals'], [])
        self.assertFalse(any(c[0] in {'POST', 'PUT'} and c[1] != '/v1/customers/search' for c in flow.api.calls))

    def test_chinese_item_options_and_customer_method_follow_same_last_call(self):
        flow = ItemsConversation()
        decision = flow.user('修改订单 #TEST1 商品; 商品 item_blue: 颜色 red; 结算方式: card_a')
        self.assertEqual(flow.code(), 'items_confirmation_required')
        self.assertIn('Anything else', decision.text)
        self.assertEqual(flow.posts(), [])
        flow.user('确认')
        self.assertEqual(flow.code(), 'write_verified')
        self.assertEqual(flow.posts()[0][2]['replacements'][0]['replacement_item_id'], 'item_red')

    def test_explicit_capacity_priority_relaxes_only_named_option_before_price(self):
        flow = ItemsConversation()
        flow.change('color red; highest capacity; cheapest')
        self.assertEqual(flow.code(), 'items_confirmation_required')
        spec = _current_records(flow.state)[0]['spec']
        self.assertEqual(spec['parameters']['replacements'][0]['replacement_item_id'], 'item_large')
        self.assertEqual(spec['amount']['value'], 7.5)
        source = next(e['items_basis']['sources'][0] for e in reversed(flow.state['history']) if 'items_basis' in e)
        self.assertEqual(source['criteria']['ranking'], [{'field': 'capacity', 'direction': 'max'}, {'field': 'price', 'direction': 'min'}])
        self.assertEqual(flow.posts(), [])

    def test_changed_budget_same_variant_still_requires_new_complete_confirmation(self):
        flow = ItemsConversation(); flow.change('color red; price <= 20')
        original = _current_records(flow.state)[0]['version']
        flow.user('item item_blue: color red; price <= 16')
        current = _current_records(flow.state)[0]
        self.assertGreater(current['version'], original)
        self.assertIsNone(current['confirmation'])
        self.assertEqual(flow.posts(), [])
        source = next(e['items_basis']['sources'][0] for e in reversed(flow.state['history']) if 'items_basis' in e)
        self.assertIn('16', source['user_text'])
        flow.user('yes'); self.assertEqual(flow.code(), 'write_verified')

    def test_natural_recap_last_call_next_consent_single_post_and_owned_readback(self):
        flow = ItemsConversation(); decision = flow.change()
        self.assertEqual(flow.code(), 'items_confirmation_required')
        self.assertEqual(flow.posts(), [])
        for token in ('Anything else', 'one submission', 'item_blue', 'item_red', '12.5', '15', '2.5', 'card_a', 'color', 'retain all other original attributes'):
            self.assertIn(token, decision.text)
        self.assertEqual(decision.text.count('?'), 1)
        self.assertTrue(decision.text.endswith(ITEMS_LAST_CALL))
        self.assertNotIn('history_index', decision.text)
        flow.user('yes')
        self.assertEqual(flow.code(), 'write_verified')
        self.assertEqual(flow.posts(), [('POST', '/v1/orders/%23TEST1/item-modifications', {
            'replacements': [{'existing_item_id': 'item_blue', 'replacement_item_id': 'item_red'}], 'payment_method_id': 'card_a'})])
        self.assertEqual(flow.api.orders['#TEST1']['status'], 'pending (items modified)')
        self.assertEqual(flow.writes()[-1]['status'], 'succeeded')
        self.assertEqual(flow.state['history'], initial_state(flow.state['history'])['history'])

    def test_missing_list_does_not_claim_completion_or_request_submission(self):
        flow = ItemsConversation(); flow.user('Change order #TEST1 items')
        self.assertEqual(flow.code(), 'complete_item_list_required')
        self.assertEqual(flow.posts(), [])
        self.assertEqual(flow.state['proposals'], [])

    def test_list_waits_for_one_customer_selected_settlement_method_even_zero_difference(self):
        flow = ItemsConversation()
        flow.api.products['product_mug']['items'][1]['price'] = 12.5
        flow.user('Change order #TEST1 items; item item_blue: color red')
        self.assertEqual(flow.code(), 'payment_method_required'); self.assertEqual(flow.posts(), [])
        flow.user('pay with card_a')
        self.assertEqual(_current_records(flow.state)[0]['spec']['amount']['value'], 0)
        self.assertEqual(flow.code(), 'items_confirmation_required')
        flow.user('yes'); self.assertEqual(flow.code(), 'write_verified')

    def test_additional_item_rebuilds_whole_list_and_does_not_submit_first_line(self):
        flow = ItemsConversation()
        extra = deepcopy(flow.api.orders['#TEST1']['items'][0]); extra['item_id'] = 'item_second'
        flow.api.orders['#TEST1']['items'].append(extra)
        flow.change(); first = _current_records(flow.state)[0]['version']
        flow.user('add item item_second: color green')
        record = _current_records(flow.state)[0]
        self.assertGreater(record['version'], first); self.assertIsNone(record['confirmation'])
        self.assertEqual(len(record['spec']['parameters']['replacements']), 2)
        self.assertEqual(record['spec']['amount']['value'], 0)
        self.assertEqual(flow.posts(), [])
        flow.user('yes'); self.assertEqual(len(flow.posts()), 1)
        self.assertEqual(len(flow.posts()[0][2]['replacements']), 2)

    def test_changed_options_require_new_complete_recap_and_fresh_confirmation(self):
        flow = ItemsConversation(); flow.change(); flow.user('item item_blue: color green')
        self.assertEqual(flow.code(), 'items_confirmation_required')
        self.assertEqual(_current_records(flow.state)[0]['spec']['amount']['value'], -2.5)
        self.assertEqual(flow.posts(), [])
        flow.user('yes'); self.assertEqual(flow.code(), 'write_verified')
        self.assertEqual(flow.posts()[0][2]['replacements'][0]['replacement_item_id'], 'item_green')

    def test_repeated_original_units_keep_order_and_full_count_without_quantity_fields(self):
        flow = ItemsConversation(); flow.api.orders['#TEST1']['items'] = [deepcopy(flow.api.orders['#TEST1']['items'][0]) for _ in range(2)]
        flow.envelope([{'item_id': 'item_blue', 'options': {'color': 'red'}}, {'item_id': 'item_blue', 'options': {'color': 'green'}}])
        spec = _current_records(flow.state)[0]['spec']
        self.assertEqual(spec['amount']['value'], 0)
        self.assertEqual(len(spec['parameters']['replacements']), 2)
        flow.user('yes'); self.assertEqual(flow.code(), 'write_verified')
        self.assertEqual([i['item_id'] for i in flow.api.orders['#TEST1']['items']], ['item_red', 'item_green'])

    def test_too_many_occurrences_and_ambiguous_original_prices_block_the_whole_list(self):
        for prices in ([12.5], [12.5, 11]):
            flow = ItemsConversation()
            row = deepcopy(flow.api.orders['#TEST1']['items'][0])
            flow.api.orders['#TEST1']['items'] = [{**deepcopy(row), 'price': p} for p in prices]
            flow.envelope([{'item_id': 'item_blue', 'options': {'color': 'red'}}] * 2)
            self.assertEqual(flow.code(), 'quantity_exceeds_order' if len(prices) == 1 else 'instance_selection_unavailable')
            self.assertEqual(flow.posts(), [])

    def test_primary_fallback_selected_then_full_recap_still_needs_consent(self):
        flow = ItemsConversation(); decision = flow.change('color silver otherwise color green')
        self.assertEqual(flow.code(), 'items_confirmation_required')
        self.assertIn('Selected branch: fallback 1', decision.text)
        self.assertEqual(flow.posts(), [])
        flow.user('yes'); self.assertEqual(flow.posts()[0][2]['replacements'][0]['replacement_item_id'], 'item_green')

    def test_tied_variants_ask_customer_then_explicit_variant_yields_fresh_recap(self):
        flow = ItemsConversation()
        flow.api.products['product_mug']['items'].append({**deepcopy(flow.api.products['product_mug']['items'][1]), 'item_id': 'item_red2'})
        flow.change(); self.assertEqual(flow.code(), 'candidate_choice_required'); self.assertEqual(flow.posts(), [])
        flow.user('item item_blue: variant item_red2')
        self.assertEqual(flow.code(), 'items_confirmation_required'); flow.user('yes')
        self.assertEqual(flow.code(), 'write_verified')

    def test_unmentioned_attributes_and_unavailable_variants_never_enter_submitted_list(self):
        for field, value, code in [('available', False, 'no_eligible_candidates'), ('options', {'color': 'red', 'capacity': '1 l', 'waterproof': 'yes'}, 'no_eligible_candidates')]:
            flow = ItemsConversation(); flow.api.products['product_mug']['items'][1][field] = value
            flow.change(); self.assertEqual(flow.code(), code); self.assertEqual(flow.posts(), [])

    def test_original_price_not_source_current_price_drives_the_quote(self):
        flow = ItemsConversation(); flow.api.products['product_mug']['items'][0]['price'] = 10000
        flow.change(); self.assertEqual(_current_records(flow.state)[0]['spec']['amount']['value'], 2.5)

    def test_full_positive_difference_requires_sufficient_gift_card_without_topup(self):
        flow = ItemsConversation(); flow.api.customers['customer_a']['payment_methods'][-1]['balance'] = 2
        flow.change(method='gift_a'); self.assertEqual(flow.code(), 'insufficient_gift_card')
        self.assertEqual(flow.posts(), [])

    def test_negative_difference_still_has_one_explicit_saved_destination(self):
        flow = ItemsConversation(); flow.change('color green', method='gift_a'); flow.user('yes')
        self.assertEqual(flow.code(), 'write_verified')
        self.assertEqual(flow.api.orders['#TEST1']['payments'][-1], {'transaction_type': 'refund', 'payment_method_id': 'gift_a', 'amount': 2.5})

    def test_every_nonpending_state_has_a_specific_deny_and_zero_item_posts(self):
        for status, code in [('pending (items modified)', 'items_modified_lock'), ('processed', 'order_processed'), ('delivered', 'action_not_allowed_in_state'), ('cancelled', 'order_cancelled')]:
            flow = ItemsConversation(); flow.api.orders['#TEST1']['status'] = status; flow.change()
            self.assertEqual(flow.code(), code); self.assertEqual(flow.posts(), [])

    def test_fulfillment_conflict_blocks_confirmed_item_submission(self):
        flow = ItemsConversation(); flow.api.orders['#TEST1']['fulfillments'] = [{'item_ids': ['item_blue'], 'tracking_id': ['synthetic']}]
        flow.change(); flow.user('yes'); self.assertEqual(flow.code(), 'fulfillment_requires_review'); self.assertEqual(flow.posts(), [])

    def test_foreign_order_is_blocked_before_order_get(self):
        flow = ItemsConversation(); flow.user('Change order #TEST2 items; item item_blue: color red; pay with card_a')
        self.assertEqual(flow.code(), 'items_order_not_owned')
        self.assertFalse(any('/%23TEST2' in c[1] for c in flow.api.calls)); self.assertEqual(flow.posts(), [])

    def test_canonical_user_identity_is_required_before_any_product_read(self):
        flow = ItemsConversation(verify=False); flow.change()
        self.assertEqual(flow.api.calls, []); self.assertFalse(flow.state['identity']['verified'])

    def test_conditional_partial_and_unrelated_assents_never_submit_complete_list(self):
        for text in ('yes if cheaper', 'only change one item', 'not yet', 'thanks', 'yes, but add another item'):
            flow = ItemsConversation(); flow.change(); flow.user(text)
            self.assertEqual(flow.posts(), [])
            self.assertFalse(any(p['status'] == 'confirmed' for p in _current_records(flow.state)))

    def test_fresh_price_change_requotes_and_waits_instead_of_sending_old_amount(self):
        flow = ItemsConversation(); flow.change(); flow.api.products['product_mug']['items'][1]['price'] = 16
        flow.user('yes'); self.assertEqual(flow.posts(), [])
        self.assertEqual(flow.code(), 'items_confirmation_required')
        self.assertEqual(_current_records(flow.state)[0]['spec']['amount']['value'], 3.5)
        self.assertIsNone(_current_records(flow.state)[0]['confirmation'])
        flow.user('yes'); self.assertEqual(flow.code(), 'write_verified')

    def test_new_competing_candidate_prevents_prior_unique_choice_from_being_sent(self):
        flow = ItemsConversation(); flow.change()
        flow.api.products['product_mug']['items'].append({**deepcopy(flow.api.products['product_mug']['items'][1]), 'item_id': 'new_tied_red'})
        flow.user('yes'); self.assertEqual(flow.code(), 'candidate_choice_required'); self.assertEqual(flow.posts(), [])

    def test_catalog_read_failure_cannot_reuse_old_variants_or_trigger_fallback(self):
        flow = ItemsConversation()
        request = flow.api.request
        def product_failure(method, path, body=None):
            if method == 'GET' and path == '/v1/catalog/products/product_mug':
                flow.api.calls.append((method, path, deepcopy(body)))
                return FakeResponse(503, {'error': {'code': 'unavailable', 'message': 'private_catalog_marker'}})
            return request(method, path, body)
        flow.change()  # A prior complete catalog must not substitute for failure.
        with patch.object(flow.api, 'request', side_effect=product_failure):
            flow.change('color silver otherwise color green')
        self.assertEqual(flow.code(), 'items_product_read_failed'); self.assertEqual(flow.posts(), [])
        self.assertTrue(any(c[1] == '/v1/catalog/products/product_mug' for c in flow.api.calls))
        self.assertNotIn('private_catalog_marker', json.dumps(flow.state))

    def test_409_and_422_are_definite_failed_operations_without_retry(self):
        for status in ('409', '422'):
            flow = ItemsConversation(); flow.change(); before = deepcopy(flow.api.orders['#TEST1']); flow.api.failure = status
            flow.user('yes'); self.assertEqual(flow.code(), 'write_rejected'); self.assertEqual(flow.writes()[-1]['status'], 'failed')
            self.assertEqual(flow.api.orders['#TEST1'], before); flow.user('yes'); self.assertEqual(len(flow.posts()), 1)

    def test_timeout_after_effect_keeps_unknown_and_new_request_cannot_repeat(self):
        flow = ItemsConversation(); flow.change(); flow.api.failure = 'timeout'; flow.user('yes')
        self.assertEqual(flow.code(), 'write_result_unknown'); self.assertEqual(flow.writes()[-1]['status'], 'unknown')
        flow.user('item item_blue: color green'); flow.user('yes'); self.assertEqual(len(flow.posts()), 1)

    def test_unusable_receipt_and_wrong_readback_cannot_claim_success(self):
        for failure in ('bad_receipt', 'wrong_items'):
            flow = ItemsConversation(); flow.change(); flow.api.failure = failure; decision = flow.user('yes')
            self.assertNotEqual(flow.code(), 'write_verified'); self.assertEqual(len(flow.posts()), 1)
            self.assertNotIn('rejected_private_items_body', json.dumps(flow.state))
            self.assertNotIn('independently verified', decision.text)

    def test_prepare_result_loss_is_recoverable_and_late_body_is_not_accepted(self):
        flow = ItemsConversation(); decision = flow.change(consume=False); call = decision.calls[0]
        _, flow.state = advance(TurnInput('tools', outcomes=()), flow.state)
        self.assertEqual(flow.code(), 'items_prepare_abandoned')
        self.assertEqual(flow.posts(), [])
        flow.user('retry'); self.assertEqual(flow.code(), 'items_confirmation_required')
        before = deepcopy(flow.state)
        _, flow.state = advance(TurnInput('tools', outcomes=(ToolOutcome(call.id, 'private_stale_body'),)), flow.state)
        self.assertEqual(flow.state['history'], before['history'])
        self.assertEqual(flow.state['proposals'], before['proposals'])
        self.assertEqual(flow.state['operations'], before['operations'])

    def test_execute_result_loss_blocks_all_other_business_and_model(self):
        flow = ItemsConversation(); flow.change(); decision = flow.user('yes', consume=False)
        call = decision.calls[0]; flow.toolkit.items_workflow(**call.arguments)
        _, flow.state = advance(TurnInput('tools', outcomes=()), flow.state)
        self.assertEqual(flow.code(), 'items_workflow_unresolved')
        for text in ('retry', 'Change default address; city: New', 'Switch order #TEST1 payment to PayPal'):
            flow.user(text); self.assertEqual(flow.code(), 'items_workflow_unresolved')
        self.assertEqual(len(flow.posts()), 1)

    def test_shared_claims_stop_duplicate_execute_snapshot_in_a_new_toolkit(self):
        flow = ItemsConversation(claims=SessionClaims()); flow.change(); decision = flow.user('yes', consume=False); call = decision.calls[0]
        payload = flow.toolkit.items_workflow(**call.arguments)
        with patch.dict(sys.modules, platform_modules(object())):
            other = importlib.import_module('tools').Tools(flow.api, claims=flow.toolkit._workflow_claims)
        other.items_workflow(**call.arguments)
        self.assertEqual(len(flow.posts()), 1)
        self.assertEqual(payload['assessment']['code'], 'write_verified')

    def test_success_locks_second_item_pass_and_other_order_changes(self):
        flow = ItemsConversation(); flow.change(); flow.user('yes'); count = len(flow.posts())
        flow.user('Change order #TEST1 items; item item_red: color green; pay with card_a')
        self.assertEqual(flow.code(), 'items_modified_lock'); self.assertEqual(len(flow.posts()), count)

    def test_cross_flow_unfinished_payment_is_not_silently_discarded(self):
        flow = ItemsConversation(); flow.user('Switch order #TEST1 payment to PayPal')
        self.assertEqual(flow.state['history'][-1]['payment_assessment']['code'], 'payment_confirmation_required')
        flow.change(); self.assertEqual(flow.code(), 'items_mixed_plan_requires_review'); self.assertEqual(flow.posts(), [])

    def test_explicit_remove_rebuilds_list_without_silent_scope_loss(self):
        flow = ItemsConversation(); flow.change(); flow.user('remove item item_blue')
        self.assertEqual(flow.code(), 'complete_item_list_required'); self.assertEqual(flow.posts(), [])


class ItemEvidenceTests(unittest.TestCase):
    def test_last_call_mode_and_text_restore_together_and_tampering_is_rejected(self):
        flow = ItemsConversation(); decision = flow.change()
        self.assertEqual(initial_state(flow.state['history'])['history'], flow.state['history'])
        for field, value in (('presentation_mode', 'unknown'), ('content', decision.text + '\nDo you confirm?')):
            state = deepcopy(flow.state); entry = next(e for e in reversed(state['history']) if 'proposal_set' in e)
            entry[field] = value
            with self.assertRaises(InvalidState): clone_state(state)
        state = deepcopy(flow.state); entry = next(e for e in reversed(state['history']) if 'proposal_set' in e)
        del entry['presentation_mode']
        with self.assertRaises(InvalidState): clone_state(state)
        # Older presentations without this optional mode keep their original
        # renderer; adding the mode does not invalidate their history.
        entry['content'] = entry['presentation_note'] + '\n\n' + render_proposal_set([event['spec'] for event in entry['proposal_set']])
        entry['items_assessment']['message'] = entry['content']
        self.assertEqual(clone_state(state)['history'], state['history'])
        with self.assertRaises(InvalidProposal): present_proposals(ItemsConversation().state, [], presentation_mode='items_last_call')
        spec = deepcopy(_current_records(flow.state)[0]['spec'])
        spec.update(action='shipping_address', parameters={'address_line_1': '123 Example St', 'address_line_2': None,
                    'city': 'Test City', 'region': 'CA', 'postal_code': '12345', 'country': 'USA'}, amount={'kind': 'not_applicable'})
        with self.assertRaisesRegex(InvalidProposal, 'Unsupported presentation mode'):
            present_proposals(flow.state, [spec], presentation_mode='items_last_call')

    def test_natural_same_order_request_merges_rows_while_explicit_json_replaces_draft(self):
        history = [{'role': 'user', 'content': 'Change order #TEST1 items; item first: color red; pay with card_a'},
                   {'role': 'user', 'content': 'Change order #TEST1 items; item second: color green'}]
        self.assertEqual([l['item_id'] for l in request_from_history(history)['lines']], ['first', 'second'])
        history.append({'role': 'user', 'content': 'Change order #TEST1 items: ' + json.dumps({'replacements': [{'item_id': 'second', 'options': {'color': 'red'}}], 'payment_method_id': 'card_a'})})
        self.assertEqual([l['item_id'] for l in request_from_history(history)['lines']], ['second'])

    def test_product_read_budget_checks_all_products_before_any_catalog_read(self):
        flow = ItemsConversation(); original = deepcopy(flow.api.orders['#TEST1']['items'][0])
        flow.api.orders['#TEST1']['items'].append({**original, 'item_id': 'item_second', 'product_id': 'product_second'})
        flow.user('Change order #TEST1 items; item item_blue: color red; item item_second: color red; pay with card_a', consume=False)
        state = deepcopy(flow.state)
        state['tool_calls_since_user'] = 9; before = len(flow.api.calls)
        _, state = _prepare(state, flow.api)
        self.assertEqual(state['history'][-1]['items_assessment']['code'], 'items_read_budget_exceeded')
        self.assertEqual(state['tool_calls_since_user'], 11)
        self.assertEqual([c[1] for c in flow.api.calls[before:]], ['/v1/customers/customer_a', '/v1/orders/%23TEST1'])
        self.assertEqual(flow.posts(), [])

    def test_oversized_dispatch_preserves_evidence_and_does_not_create_call(self):
        from support_agent.items_session import _boundary
        from support_agent.workflow_limits import MAX_WORKFLOW_ARGUMENT_BYTES
        flow = ItemsConversation(); flow.state['history'].append({'role': 'assistant', 'content': 'x' * MAX_WORKFLOW_ARGUMENT_BYTES})
        before = deepcopy(flow.state); decision, state = _boundary().dispatch(flow.state, 'prepare')
        self.assertFalse(decision.calls); self.assertIsNone(state['items_pending'])
        self.assertEqual(state['history'][:-1], before['history'])
        self.assertEqual(state['identity_evidence'], before['identity_evidence'])
        self.assertEqual(state['history'][-1]['items_assessment']['code'], 'items_argument_budget_exceeded')

    def test_one_mib_result_rejects_otherwise_valid_large_preparation_bundle(self):
        from support_agent.items_session import _boundary
        from support_agent.workflow_boundary import WorkflowBoundary
        from support_agent.workflow_limits import MAX_WORKFLOW_RESULT_BYTES
        flow = ItemsConversation(); call = flow.change(consume=False).calls[0]
        payload = flow.toolkit.items_workflow(**call.arguments)
        payload['state']['history'].insert(-1, {'role': 'assistant', 'content': 'x' * MAX_WORKFLOW_RESULT_BYTES})
        # Rebuild the ledger after adding a legitimate assistant entry; cached
        # response indices must correspond to the extended history as well.
        payload['state'] = initial_state(payload['state']['history'])
        outcome = ToolOutcome(call.id, json.dumps(payload), False)
        # This is a valid prefix extension: the only reason for refusal is size.
        _, accepted = WorkflowBoundary('items', len(outcome.content.encode('utf-8')) + 1).accept(deepcopy(flow.state), (outcome,))
        self.assertIsNone(accepted['items_pending'])
        self.assertEqual(accepted['history'][-1]['items_assessment']['code'], 'items_confirmation_required')
        _, rejected = _boundary().accept(deepcopy(flow.state), (outcome,))
        self.assertEqual(rejected['history'][-1]['items_assessment']['code'], 'items_prepare_abandoned')
        self.assertNotIn('x' * MAX_WORKFLOW_RESULT_BYTES, json.dumps(rejected)); self.assertEqual(flow.posts(), [])

    def test_preparation_result_overflow_returns_short_diagnostic_with_original_prefix(self):
        from support_agent.workflow_limits import json_bytes
        flow = ItemsConversation(); call = flow.change(consume=False).calls[0]; before = deepcopy(flow.state)
        # Fault injection lowers the real shared budget to exercise producer rollback.
        with patch('support_agent.items_session.MAX_WORKFLOW_RESULT_BYTES', json_bytes(before) + 2500):
            payload = flow.toolkit.items_workflow(**call.arguments)
        self.assertEqual(payload['assessment']['code'], 'items_result_budget_exceeded')
        self.assertEqual(payload['state']['history'][:len(before['history'])], before['history'])
        self.assertEqual(payload['state']['proposals'], []); self.assertEqual(flow.posts(), [])

    def test_post_send_result_overflow_preserves_unknown_reservation_and_never_retries(self):
        from support_agent.workflow_limits import json_bytes, WorkflowResultTooLarge
        flow = ItemsConversation(); flow.change(); call = flow.user('yes', consume=False).calls[0]
        with patch('support_agent.items_session.MAX_WORKFLOW_RESULT_BYTES', json_bytes(flow.state) + 1500):
            with self.assertRaises(WorkflowResultTooLarge): flow.toolkit.items_workflow(**call.arguments)
        _, flow.state = advance(TurnInput('tools', outcomes=(ToolOutcome(call.id, '', True),)), flow.state)
        self.assertEqual(flow.code(), 'items_workflow_unresolved')
        self.assertEqual(flow.state['items_pending']['status'], 'unknown')
        self.assertEqual(len(flow.posts()), 1); flow.user('yes'); self.assertEqual(len(flow.posts()), 1)

    def test_schema9_original_fixture_migrates_without_item_evidence_or_confirmation(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/m5_schema9_state.json').read_text())
        state = fixture['state']; self.assertEqual(state['schema_version'], 9); self.assertNotIn('items_pending', state)
        restored = clone_state(state)
        self.assertEqual(restored['schema_version'], SCHEMA_VERSION); self.assertIsNone(restored['items_pending'])
        self.assertEqual(restored['history'], state['history']); self.assertEqual(restored['proposals'], [])

    def test_legacy_schema_cannot_carry_new_item_workflow_metadata(self):
        flow = ItemsConversation(); flow.change()
        for version in range(1, 10):
            state = deepcopy(flow.state); state['schema_version'] = version
            with self.assertRaises(InvalidState): clone_state(state)

    def test_derived_conditions_and_source_indices_are_recomputed_not_trusted_from_metadata(self):
        flow = ItemsConversation(); flow.change()
        for field in ('sources', 'requested_options', 'spec', 'request'):
            state = deepcopy(flow.state); entry = next(e for e in state['history'] if 'items_basis' in e)
            entry['items_basis'][field] = []
            with self.assertRaises(InvalidState): clone_state(state)

    def test_history_restore_preserves_actual_sources_pending_and_unknown_without_sending(self):
        flow = ItemsConversation(); flow.change(); flow.api.failure = 'timeout'; flow.user('yes')
        restored = initial_state(flow.state['history'])
        self.assertEqual(restored['operations'], flow.state['operations'])
        self.assertEqual(restored['identity_evidence'], flow.state['identity_evidence'])
        self.assertEqual(restored['history'], flow.state['history'])
        self.assertEqual(clone_state(restored), restored)

    def test_all_registered_workflows_are_rejected_by_model_candidate_and_read_binding(self):
        from support_agent.read_session import bind_arguments
        flow = ItemsConversation()
        for name in WORKFLOW_TOOL_NAMES:
            with self.subTest(name=name):
                with self.assertRaisesRegex(InvalidAction, 'Model candidates cannot dispatch a business workflow'):
                    decision_from_candidate({'type': 'tool', 'name': name, 'arguments': {'session_json': '{}'}}, call_id='model-workflow')
                with self.assertRaisesRegex(InvalidAction, 'Unsupported read action or fields'):
                    bind_arguments(name, {'session_json': '{}'}, flow.state)
        # Positive controls prevent an implementation that rejects every tool.
        arguments = bind_arguments('get_order', {'order_id': '#TEST1'}, flow.state)
        decision = decision_from_candidate({'type': 'tool', 'name': 'get_order', 'arguments': arguments}, call_id='model-read')
        self.assertEqual(decision.calls[0].name, 'get_order')
        self.assertEqual(bind_arguments('get_order', {'order_id': '#TEST1'}, flow.state)['order_id'], '#TEST1')

    def test_direct_tool_snapshot_without_original_dispatch_is_rejected_before_http(self):
        flow = ItemsConversation(); calls = deepcopy(flow.api.calls)
        with self.assertRaises(ValueError): flow.toolkit.items_workflow(json.dumps(flow.state))
        self.assertEqual(flow.api.calls, calls)

    def test_preparation_transport_budget_is_checked_before_any_business_call(self):
        flow = ItemsConversation(); calls = deepcopy(flow.api.calls)
        with self.assertRaises(ValueError): flow.toolkit.items_workflow('x' * (256 * 1024 + 1))
        self.assertEqual(flow.api.calls, calls)

    def test_whole_request_read_budget_is_enforced_before_profile_get(self):
        flow = ItemsConversation(); decision = flow.change(consume=False); state = deepcopy(flow.state)
        state['tool_calls_since_user'] = 11; calls = deepcopy(flow.api.calls)
        _, state = _prepare(state, flow.api)
        self.assertEqual(state['history'][-1]['items_assessment']['code'], 'items_read_budget_exceeded')
        self.assertEqual(flow.api.calls, calls)

    def test_pending_item_workflow_blocks_model_projection(self):
        from support_agent.model_context import project_messages
        flow = ItemsConversation(); flow.change(consume=False)
        with self.assertRaises(InvalidAction): project_messages(flow.state)

    def test_handoff_after_item_result_loss_preserves_unknown_reservation(self):
        from test_m4_handoffs import HandoffBackend
        flow = ItemsConversation(); flow.change(); decision = flow.user('yes', consume=False)
        flow.user('Please transfer me to a human agent.', consume=False)
        self.assertEqual(flow.state['items_pending']['status'], 'unknown')
        self.assertEqual(flow.state['handoff']['status'], 'dispatched')
        self.assertEqual(flow.posts(), [])


if __name__ == '__main__': unittest.main()
