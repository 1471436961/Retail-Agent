"""M6.2 default-turn combinations and cross-order monetary evidence."""
import json
import unittest
from copy import deepcopy
from decimal import Decimal, InvalidOperation, DivisionByZero, localcontext
from unittest.mock import Mock, patch

from test_m5_matrix import MatrixConversation
from test_m4_addresses import NEW
from support_agent.amount_summary import summarize_amounts, summary_request, render_summary, summary_refresh_rule
from support_agent.domain.money import display_exact_amount
from support_agent.domain.cancellation_intake import refund_recap_rule
from support_agent.state import clone_state, initial_state
from support_agent.proposals import _current_records
from support_agent.protocol import ToolOutcome, TurnInput
from support_agent.turns import advance


def replacements(order='#TEST1', verb='Change', method='card_a'):
    return f'{verb} order {order} items: ' + json.dumps({'replacements': [{'item_id':'item_blue','replacement_item_id':'item_red'}], 'payment_method_id':method})


class CombinationDialogueTests(unittest.TestCase):
    def assert_replay(self, flow):
        rebuilt = initial_state(flow.state['history'])
        for key in ('identity_evidence', 'operations', 'tasks', 'proposals'):
            self.assertEqual(rebuilt[key], flow.state[key], key)
        self.assertEqual(clone_state(flow.state), flow.state)

    def test_address_then_items_waits_for_two_real_confirmations_and_preserves_other_records(self):
        flow = MatrixConversation(); other = deepcopy(flow.api.orders['#TEST3']); profile = deepcopy(flow.api.customers)
        flow.change(); self.assertEqual(flow.code('address'), 'address_confirmation_required')
        self.assertEqual(flow.business_calls(), [])
        flow.user('yes'); self.assertEqual(flow.code('address'), 'address_updates_verified')
        flow.user(replacements()); self.assertEqual(flow.code('items'), 'items_confirmation_required')
        self.assertEqual([c[0] for c in flow.business_calls()], ['PUT'])
        flow.user('yes'); self.assertEqual(flow.code('items'), 'write_verified')
        self.assertEqual([o['name'] for o in flow.writes()], ['shipping_address', 'modify_items'])
        self.assertEqual([o['status'] for o in flow.writes()], ['succeeded']*2)
        self.assertEqual(flow.api.orders['#TEST1']['shipping_address'], NEW)
        self.assertEqual(flow.api.orders['#TEST3'], other); self.assertEqual(flow.api.customers, profile)
        self.assert_replay(flow)

    def test_mixed_address_items_message_is_clarified_before_reads_and_can_be_completed_in_order(self):
        flow = MatrixConversation(); before = deepcopy(flow.api.orders); calls = deepcopy(flow.api.calls)
        flow.user('Change order #TEST1 address and items')
        self.assertEqual(flow.code('items'), 'mixed_or_quantity_request')
        self.assertEqual(flow.api.calls, calls); self.assertEqual(flow.api.orders, before)
        self.assertEqual(_current_records(flow.state), [])
        flow.change(); flow.user('yes'); flow.user(replacements()); flow.user('yes')
        self.assertEqual([o['name'] for o in flow.writes()], ['shipping_address','modify_items'])
        self.assert_replay(flow)

    def test_default_and_order_addresses_have_two_scopes_order_first_and_no_item_price_effect(self):
        flow = MatrixConversation(); before_items = deepcopy(flow.api.orders['#TEST1']['items'])
        flow.user('Change default and order #TEST1 address: ' + json.dumps(NEW))
        self.assertEqual(flow.code('address'), 'address_confirmation_required')
        records = _current_records(flow.state)
        self.assertEqual({p['spec']['action'] for p in records}, {'shipping_address','default_shipping_address'})
        self.assertEqual(len({p['version'] for p in records}), 2); self.assertEqual(flow.business_calls(), [])
        flow.user('yes'); self.assertEqual(flow.code('address'), 'address_updates_verified')
        self.assertEqual([o['name'] for o in flow.writes()], ['shipping_address','default_shipping_address'])
        self.assertEqual(flow.api.customers['customer_a']['default_shipping_address'], NEW)
        self.assertEqual(flow.api.orders['#TEST1']['shipping_address'], NEW)
        self.assertEqual(flow.api.orders['#TEST1']['items'], before_items); self.assert_replay(flow)

    def test_order_address_success_does_not_synchronize_default_without_another_recap(self):
        flow = MatrixConversation(); old = deepcopy(flow.api.customers['customer_a']['default_shipping_address'])
        flow.change(); flow.user('yes')
        self.assertEqual(flow.api.customers['customer_a']['default_shipping_address'], old)
        flow.change('default'); self.assertEqual(flow.code('address'), 'address_confirmation_required')
        self.assertEqual(len(flow.business_calls()), 1)
        flow.user('yes'); self.assertEqual(len(flow.business_calls()), 2)

    def test_blocked_order_does_not_prevent_fresh_owned_other_order_address_confirmation(self):
        flow = MatrixConversation(); flow.api.orders['#TEST1']['status'] = 'processed'
        first = deepcopy(flow.api.orders['#TEST1'])
        flow.change(); self.assertEqual(flow.code('address'), 'address_state_not_allowed')
        self.assertEqual(flow.business_calls(), [])
        flow.change('order #TEST3'); self.assertEqual(flow.code('address'), 'address_confirmation_required')
        flow.user('yes'); self.assertEqual(flow.code('address'), 'address_updates_verified')
        self.assertEqual([o['spec']['target']['order_id'] for o in flow.writes()], ['#TEST3'])
        self.assertEqual(flow.api.orders['#TEST1'], first); self.assert_replay(flow)

    def test_two_order_item_requests_require_explicit_order_and_never_expand_into_two_writes(self):
        flow = MatrixConversation(); before = deepcopy(flow.api.orders); calls = deepcopy(flow.api.calls)
        flow.user('Change order #TEST1 and #TEST3 items: ' + json.dumps({'replacements':[{'item_id':'item_blue','replacement_item_id':'item_red'}],'payment_method_id':'card_a'}))
        self.assertEqual(flow.code('items'), 'single_order_required')
        self.assertEqual(flow.api.calls, calls); self.assertEqual(flow.api.orders, before)
        flow.user(replacements()); flow.user('yes')
        flow.user(replacements('#TEST3')); self.assertEqual(flow.code('items'), 'items_confirmation_required')
        self.assertEqual(len(flow.business_calls()), 1)
        flow.user('yes'); self.assertEqual([o['status'] for o in flow.writes()], ['succeeded']*2)
        self.assert_replay(flow)

    def test_return_then_exchange_on_distinct_orders_preserves_original_units_and_independent_consent(self):
        flow = MatrixConversation('returns'); flow.api.orders['#TEST3']['status']='delivered'
        original = {k:deepcopy(v['items']) for k,v in flow.api.orders.items()}
        flow.start(); flow.user('yes'); self.assertEqual(flow.code('returns'), 'write_verified')
        flow.user(replacements('#TEST3','Exchange')); self.assertEqual(flow.code('exchange'), 'exchange_confirmation_required')
        self.assertEqual(len(flow.business_calls()), 1)
        flow.user('yes'); self.assertEqual(flow.code('exchange'), 'write_verified')
        self.assertEqual([o['spec']['target']['order_id'] for o in flow.writes()], ['#TEST1','#TEST3'])
        self.assertEqual({k:v['items'] for k,v in flow.api.orders.items()}, original); self.assert_replay(flow)

    def test_same_order_return_exchange_conflict_does_not_change_other_order_and_can_continue_there(self):
        flow = MatrixConversation('returns'); flow.api.orders['#TEST3']['status']='delivered'
        flow.start(); flow.user('yes'); returned = deepcopy(flow.api.orders['#TEST1'])
        flow.user(replacements('#TEST1','Exchange'))
        self.assertEqual(flow.code('exchange'), 'return_exchange_already_requested')
        self.assertEqual(flow.api.orders['#TEST1'], returned); self.assertEqual(len(flow.business_calls()),1)
        flow.user(replacements('#TEST3','Exchange')); flow.user('yes')
        self.assertEqual(flow.code('exchange'), 'write_verified'); self.assert_replay(flow)

    def test_peer_order_new_presentation_never_reuses_omitted_order_confirmation(self):
        flow = MatrixConversation(); flow.user(replacements())
        old = deepcopy(_current_records(flow.state)[0])
        flow.user(replacements('#TEST3')); self.assertEqual(flow.code('items'),'items_confirmation_required')
        self.assertEqual(flow.business_calls(), [])
        flow.user('yes')
        self.assertEqual([o['spec']['target']['order_id'] for o in flow.writes()], ['#TEST3'])
        record = next(p for p in flow.state['proposals'] if p['version']==old['version'])
        self.assertEqual(record['status'], 'superseded'); self.assertIsNone(record['confirmation'])

    def test_accepted_unknown_on_one_order_allows_fresh_peer_order_but_never_completes_old_task(self):
        flow=MatrixConversation('returns'); flow.api.orders['#TEST3']['status']='delivered'
        flow.start(); flow.api.failure='timeout'; flow.user('yes')
        old=deepcopy(flow.writes()[0]); self.assertEqual(old['status'],'unknown')
        flow.api.failure=None
        flow.user(replacements('#TEST3','Exchange'))
        self.assertEqual(flow.code('exchange'),'exchange_confirmation_required')
        self.assertEqual(len(flow.business_calls()),1)
        flow.user('yes'); self.assertEqual(flow.code('exchange'),'write_verified')
        self.assertEqual(flow.writes()[0],old)
        self.assertEqual([(o['spec']['target']['order_id'],o['status']) for o in flow.writes()],[('#TEST1','unknown'),('#TEST3','succeeded')])
        flow.user('Return order #TEST1; items: item_blue; refund to card_a')
        self.assertEqual(flow.code('returns'), 'return_exchange_already_requested')
        self.assertEqual(flow.writes()[0], old)
        self.assertEqual(len(flow.business_calls()),2)
        self.assert_replay(flow)

    def test_accepted_unknown_allows_fresh_peer_returns_and_modify_items_without_reusing_consent(self):
        for kind, text in (('returns', 'Return order #TEST3; items: item_blue; refund to card_a'),
                           ('items', replacements('#TEST3'))):
            with self.subTest(kind=kind):
                flow = MatrixConversation('returns'); flow.start(); flow.api.failure = 'timeout'; flow.user('yes')
                old = deepcopy(flow.writes()[0]); flow.api.failure = None
                if kind == 'returns': flow.api.orders['#TEST3']['status'] = 'delivered'
                flow.user(text)
                self.assertEqual(flow.code(kind), kind + '_confirmation_required')
                self.assertEqual(len(flow.business_calls()), 1)
                self.assertIsNone(_current_records(flow.state)[0]['confirmation'])
                flow.user('yes'); self.assertEqual(flow.code(kind), 'write_verified')
                self.assertEqual(flow.writes()[0], old)
                self.assertEqual([(o['spec']['target']['order_id'], o['status']) for o in flow.writes()],
                                 [('#TEST1', 'unknown'), ('#TEST3', 'succeeded')])
                self.assert_replay(flow)

    def test_lost_execute_bundle_still_blocks_peer_order_and_summary_until_review(self):
        flow=MatrixConversation('returns'); flow.api.orders['#TEST3']['status']='delivered'
        flow.start(); call=flow.user('yes',consume=False).calls[0]
        flow.toolkit.returns_workflow(**call.arguments)  # effect occurred, bundle lost
        _,flow.state=advance(TurnInput('tools',outcomes=(ToolOutcome(call.id,'{}',True),)),flow.state)
        before=deepcopy(flow.api.calls)
        flow.user(replacements('#TEST3','Exchange'))
        self.assertEqual(flow.api.calls,before)
        self.assertEqual(summarize_amounts(flow.state,['#TEST1','#TEST3'])['code'],'summary_evidence_unresolved')
        self.assertEqual(flow.state['returns_pending']['status'],'unknown')

    def test_accepted_unknown_does_not_block_fresh_peer_address_payment_or_cancellation(self):
        scenarios=[('address','Change order #TEST3 address: '+json.dumps(NEW),'address_confirmation_required','address_updates_verified','#TEST3'),
                   ('address','Change default address: '+json.dumps(NEW),'address_confirmation_required','address_updates_verified',None),
                   ('payment','Switch order #TEST3 payment to PayPal','payment_confirmation_required','write_verified','#TEST3'),
                   ('cancellation','Cancel order #TEST3; reason: no longer needed','cancellation_confirmation_required','write_verified','#TEST3')]
        for kind,text,prepare_code,final_code,target_id in scenarios:
            with self.subTest(kind=kind):
                flow=MatrixConversation('returns'); flow.start(); flow.api.failure='timeout'; flow.user('yes')
                old=deepcopy(flow.writes()[0]); flow.api.failure=None
                flow.user(text); self.assertEqual(flow.code(kind),prepare_code)
                self.assertEqual(len(flow.business_calls()),1)
                flow.user('yes'); self.assertEqual(flow.code(kind),final_code)
                self.assertEqual(flow.writes()[0],old)
                self.assertEqual([(o['spec']['target'].get('order_id'),o['status']) for o in flow.writes()],[('#TEST1','unknown'),(target_id,'succeeded')])
                self.assert_replay(flow)


class CrossOrderSummaryTests(unittest.TestCase):
    def read(self, flow, oid):
        return flow.user('Read order ' + oid)

    def summary(self, flow, ids=('#TEST1','#TEST3')):
        result = summarize_amounts(flow.state, list(ids))
        self.assertEqual(result['code'],'order_amount_summary',result)
        self.assertIs(result['details']['write_authorized'], False)
        return result['details']

    def test_no_visible_refunds_are_unknown_not_zero_or_the_sum_of_original_prices(self):
        flow = MatrixConversation(); self.read(flow,'#TEST1'); self.read(flow,'#TEST3')
        details = self.summary(flow)
        self.assertEqual(details['visible_refunds'], {'total':None,'row_count':0,'method':'one_latest_snapshot_per_order_preserve_row_occurrences'})
        self.assertEqual(details['arrival'], {'amount':None,'status':'unknown'})
        self.assertEqual(details['orders'][0]['original_item_price_sum'],'12.5')
        self.assertFalse(details['settlement_verified'])
        self.assertIsNone(details['differences']['signed_total'])
        self.assertEqual(details['differences']['evidence_count'], 0)
        self.assertIsNone(details['return_estimates']['exact_original_price_sum'])
        self.assertIsNone(details['return_estimates']['display_estimate_total'])
        self.assertEqual(details['return_estimates']['evidence_count'], 0)
        self.assertIsNone(details['cancellation_original_charges']['total'])
        self.assertEqual(details['cancellation_original_charges']['evidence_count'], 0)

    def test_two_equal_rows_count_twice_but_duplicate_reads_and_order_selection_do_not(self):
        flow = MatrixConversation()
        flow.api.orders['#TEST1']['payments'] += [{'transaction_type':'refund','payment_method_id':'card_a','amount':1.005}]*2
        self.read(flow,'#TEST1'); self.read(flow,'#TEST3')
        first = self.summary(flow)
        self.read(flow,'#TEST1'); second = self.summary(flow)
        self.assertEqual(second['visible_refunds']['total'],'2.010')
        self.assertIn('Visible recorded refunds: 2.01 (2 rows).', render_summary(summarize_amounts(flow.state, ['#TEST1', '#TEST3'])))
        self.assertEqual(first['visible_refunds'],second['visible_refunds'])
        self.assertEqual([r['payment_index'] for r in second['orders'][0]['visible_refunds']],[1,2])
        self.assertEqual(summarize_amounts(flow.state,['#TEST1','#TEST1'])['code'],'invalid_summary_orders')

    def test_cancel_original_charge_and_return_estimate_do_not_mix_with_visible_refunds_or_arrival(self):
        flow = MatrixConversation(); flow.api.orders['#TEST3']['status']='delivered'
        flow.user('Cancel order #TEST1; reason: no longer needed'); flow.user('yes')
        flow.user('Return order #TEST3; items: item_blue; refund to card_a'); flow.user('yes')
        details = self.summary(flow)
        self.assertEqual(details['cancellation_original_charges']['total'],'12.5')
        self.assertEqual(details['return_estimates']['display_estimate_total'],'12.5')
        self.assertEqual(details['visible_refunds']['total'],'12.5')
        self.assertEqual(details['visible_refunds']['row_count'],1)
        self.assertIsNone(details['arrival']['amount'])
        self.assertEqual(details['orders'][1]['quotes'][0]['item_ids'],['item_blue'])
        self.assertEqual(len(details['orders'][0]['quotes']),1)

    def test_two_returns_use_selected_original_occurrences_and_sum_per_order_display_values(self):
        flow = MatrixConversation('returns'); flow.api.orders['#TEST3']['status']='delivered'
        for oid in ('#TEST1','#TEST3'):
            unit = flow.api.orders[oid]['items'][0]; unit['price']=0.005
            flow.api.orders[oid]['items']=[deepcopy(unit)]*3
        flow.user('Return order #TEST1; items: item_blue,item_blue; refund to card_a'); flow.user('yes')
        flow.user('Return order #TEST3; items: item_blue; refund to card_a'); flow.user('yes')
        details=self.summary(flow)
        self.assertEqual(details['return_estimates']['exact_original_price_sum'],'0.015')
        self.assertEqual(details['return_estimates']['display_estimate_total'],'0.02')
        self.assertEqual([q['aggregate_amount'] for row in details['orders'] for q in row['quotes']],[0.01,0.01])
        self.assertIsNone(details['visible_refunds']['total'])
        self.assertEqual([len(c[2]['item_ids']) for c in flow.business_calls()],[2,1])
        self.assertTrue(all(set(c[2])=={'item_ids','refund_payment_method_id'} for c in flow.business_calls()))

    def test_signed_differences_communicate_net_without_combining_backend_charges(self):
        flow=MatrixConversation('exchange'); flow.api.orders['#TEST3']['status']='delivered'
        flow.api.orders['#TEST3']['items'][0]['price']=20
        flow.user(replacements('#TEST1','Exchange')); flow.user('yes')
        flow.user(replacements('#TEST3','Exchange')); flow.user('yes')
        details=self.summary(flow)
        self.assertEqual(details['differences']['per_order_values'],[2.5,-5.0])
        self.assertEqual(details['differences']['signed_total'],-2.5)
        self.assertEqual(len(flow.business_calls()),2)
        self.assertTrue(all('amount' not in c[2] for c in flow.business_calls()))
        self.assertIsNone(details['visible_refunds']['total'])

    def test_failed_order_read_blocks_summary_instead_of_using_prior_snapshot(self):
        flow=MatrixConversation(); self.read(flow,'#TEST1'); self.read(flow,'#TEST3')
        call=flow.user('Read order #TEST3',consume=False).calls[0]
        _,flow.state=advance(TurnInput('tools',outcomes=(ToolOutcome(call.id,'{}',True),)),flow.state)
        self.assertEqual(summarize_amounts(flow.state,['#TEST1','#TEST3'])['code'],'summary_order_read_required')

    def test_default_summary_refreshes_owned_orders_and_emits_no_business_or_model_call(self):
        flow=MatrixConversation(); before=deepcopy(flow.api.orders)
        adapter = Mock()
        adapter.decide.side_effect = AssertionError('Summary delegated to model')
        message, flow.state = advance(TurnInput('user', 'Summarize order amounts: #TEST1, #TEST3'), flow.state, adapter)
        self.assertEqual(len(message.calls), 1)
        call = message.calls[0]
        payload = getattr(flow.toolkit, call.name)(**call.arguments)
        message, flow.state = advance(TurnInput('tools', outcomes=(ToolOutcome(call.id, json.dumps(payload)),)), flow.state, adapter)
        adapter.decide.assert_not_called()
        self.assertIn('Order amount summary:',message.text)
        self.assertIn('#TEST1: pending',message.text); self.assertIn('#TEST3: pending',message.text)
        self.assertEqual([r['order_id'] for r in self.summary(flow)['orders']],['#TEST1','#TEST3'])
        self.assertEqual(flow.business_calls(),[]); self.assertEqual(flow.api.orders,before)
        self.assertIn('do not prove refund arrival',message.text)

    def test_foreign_summary_is_denied_before_any_private_read(self):
        flow=MatrixConversation(); before=deepcopy(flow.api.calls)
        message=flow.user('汇总订单金额：#TEST1, #TEST2')
        self.assertIn('Every selected order must be in your verified references',message.text)
        self.assertEqual(summarize_amounts(flow.state,['#TEST1','#TEST2'])['code'],'summary_order_not_owned')
        self.assertEqual(flow.api.calls,before)

    def test_missing_read_result_invalidates_old_snapshot_without_reclassifying_it_as_zero(self):
        flow=MatrixConversation(); self.read(flow,'#TEST1'); self.read(flow,'#TEST3')
        flow.user('Read order #TEST3',consume=False)
        _,flow.state=advance(TurnInput('tools',outcomes=()),flow.state)
        self.assertEqual(summarize_amounts(flow.state,['#TEST1','#TEST3'])['code'],'summary_order_read_required')

    def test_unknown_write_has_estimate_and_visible_effect_but_no_completion_or_arrival(self):
        flow=MatrixConversation('returns'); flow.start(); flow.api.failure='timeout'; flow.user('yes')
        self.assertEqual(flow.writes()[0]['status'],'unknown')
        flow.api.failure=None; self.read(flow,'#TEST1')
        details=self.summary(flow,('#TEST1',))
        self.assertEqual(details['orders'][0]['quotes'][0]['status'],'unknown')
        self.assertIsNone(details['visible_refunds']['total']); self.assertIsNone(details['arrival']['amount'])
        self.assertEqual(len(flow.business_calls()),1)

    def test_failed_application_does_not_enter_submitted_estimates(self):
        flow=MatrixConversation('returns'); flow.start(); flow.api.failure='409'; flow.user('yes')
        self.assertEqual(flow.writes()[0]['status'],'failed')
        details=self.summary(flow,('#TEST1',))
        self.assertEqual(details['orders'][0]['quotes'],[])
        self.assertIsNone(details['return_estimates']['display_estimate_total'])
        self.assertEqual(details['return_estimates']['evidence_count'], 0)

    def test_unverified_summary_never_reports_private_amounts(self):
        self.assertEqual(summarize_amounts(initial_state(),['#TEST1'])['code'],'summary_identity_required')

    def test_summary_is_deterministic_owned_json_and_independent_of_decimal_context(self):
        flow=MatrixConversation(); self.read(flow,'#TEST1'); self.read(flow,'#TEST3')
        before=deepcopy(flow.state)
        expected=summarize_amounts(flow.state,['#TEST1','#TEST3'])
        with localcontext() as context:
            context.prec=2
            actual=summarize_amounts(flow.state,['#TEST1','#TEST3'])
        self.assertEqual(actual,expected); self.assertEqual(flow.state,before)
        actual['details']['orders'][0]['source']['call_id']='changed'
        self.assertEqual(summarize_amounts(flow.state,['#TEST1','#TEST3']),expected)
        json.dumps(expected,allow_nan=False)

    def test_summary_parser_requires_explicit_ids_and_does_not_parse_instruction_data(self):
        self.assertEqual(summary_request('汇总订单金额：#TEST3，#TEST1'),['#TEST3','#TEST1'])
        self.assertIsNone(summary_request('Return order #TEST1; items: summarize order amounts #TEST3'))
        self.assertIsNone(summary_request('Summarize order amounts'))

    def test_exact_display_is_shared_with_cancellation_and_does_not_round_or_change_evidence(self):
        for value, expected in (('12.5','12.50'), ('2.010','2.01'), ('2.005','2.005'),
                                ('0','0.00'), ('1E-5','0.00001'), ('-2.5000','-2.50')):
            with self.subTest(value=value):
                self.assertEqual(display_exact_amount(Decimal(value)), expected)
        flow = MatrixConversation()
        flow.api.orders['#TEST1']['payments'][0]['amount'] = 2.010
        recap = refund_recap_rule(flow.api.orders['#TEST1']['payments'], flow.api.customers['customer_a']['payment_methods'])
        flow.user('Cancel order #TEST1; reason: no longer needed'); flow.user('yes')
        result = summarize_amounts(flow.state, ['#TEST1'])
        self.assertEqual(result['details']['cancellation_original_charges']['total'], '2.01')
        self.assertIn('Cancellation original charges total: ' + recap['details']['display_total'], render_summary(result))
        self.assertEqual(flow.business_calls()[0][2], {'reason':'no longer needed'})

    def test_actual_zero_quotes_and_visible_rows_are_zero_with_positive_evidence_counts(self):
        for kind in ('returns', 'items', 'cancellation'):
            with self.subTest(kind=kind):
                flow = MatrixConversation('returns' if kind == 'returns' else 'items')
                if kind == 'returns':
                    flow.api.orders['#TEST1']['items'][0]['price'] = 0
                    flow.start()
                elif kind == 'items':
                    flow.api.products['product_mug']['items'][1]['price'] = flow.api.orders['#TEST1']['items'][0]['price']
                    flow.start()
                else:
                    flow.api.orders['#TEST1']['payments'][0]['amount'] = 0
                    flow.user('Cancel order #TEST1; reason: no longer needed')
                flow.user('yes'); self.assertEqual(flow.code(kind), 'write_verified')
                details = self.summary(flow, ('#TEST1',))
                category = {'returns':'return_estimates', 'items':'differences', 'cancellation':'cancellation_original_charges'}[kind]
                amount_key = {'returns':'display_estimate_total', 'items':'signed_total', 'cancellation':'total'}[kind]
                self.assertEqual(Decimal(str(details[category][amount_key])), Decimal(0))
                self.assertEqual(details[category]['evidence_count'], 1)
                if kind == 'cancellation':
                    self.assertEqual(details['visible_refunds']['row_count'], 1)
                    self.assertEqual(Decimal(details['visible_refunds']['total']), Decimal(0))

    def test_filtered_latest_list_omission_invalidates_old_order_snapshot(self):
        flow = MatrixConversation(); self.read(flow, '#TEST1'); self.read(flow, '#TEST3')
        flow.api.orders['#TEST3']['status'] = 'delivered'
        flow.user('List pending orders')
        self.assertEqual(flow.state['operations'][-1]['name'], 'list_customer_orders')
        self.assertEqual(flow.state['operations'][-1]['status'], 'succeeded')
        self.assertEqual(summarize_amounts(flow.state, ['#TEST1', '#TEST3'])['code'], 'summary_order_read_required')
        self.assertEqual(self.summary(flow, ('#TEST1',))['orders'][0]['order_id'], '#TEST1')

    def large_profile(self):
        flow = MatrixConversation()
        refs = ['#TEST1', '#TEST3'] + ['#EXTRA' + str(i) for i in range(31)]
        flow.api.customers['customer_a']['order_ids'] = refs
        flow.user('Read profile')  # accept the real expanded profile, not a state patch
        self.assertEqual(len(flow.state['customer_record']['order_ids']), 33)
        return flow

    def test_large_profile_refreshes_only_selected_orders_using_existing_get_tools(self):
        flow = self.large_profile(); before = len(flow.api.calls)
        message = flow.user('Summarize order amounts: #TEST1, #TEST3', consume=False)
        tools = []
        while message.calls:
            self.assertLess(len(tools), 3)
            tools.append(message.calls[0].name)
            message = flow.consume(message)
        self.assertEqual(tools, ['get_order', 'get_order'])
        self.assertIn('Order amount summary:', message.text)
        order_paths = [c[1] for c in flow.api.calls[before:] if c[1].startswith('/v1/orders/')]
        self.assertEqual(order_paths, ['/v1/orders/%23TEST1', '/v1/orders/%23TEST3'])
        self.assertEqual(flow.business_calls(), [])

    def test_large_profile_excess_selection_returns_specific_budget_code_before_reading(self):
        flow = self.large_profile(); before = deepcopy(flow.api.calls)
        ids = flow.state['customer_record']['order_ids'][:13]
        message = flow.user('Summarize order amounts: ' + ', '.join(ids))
        self.assertEqual(summary_refresh_rule(flow.state, ids)['code'], 'summary_read_budget_exceeded')
        self.assertIn('Select fewer exact order IDs or ask for human assistance', message.text)
        self.assertEqual(flow.api.calls, before); self.assertFalse(message.calls)

    def test_arithmetic_exceptions_become_specific_safe_result_without_guessed_amount(self):
        flow = MatrixConversation(); self.read(flow, '#TEST1')
        for error in (InvalidOperation, DivisionByZero, OverflowError):
            with self.subTest(error=error.__name__), patch('support_agent.amount_summary.exact_sum', side_effect=error('injected arithmetic error')):
                result = summarize_amounts(flow.state, ['#TEST1'])
                self.assertEqual(result['code'], 'summary_amount_unavailable')
                self.assertEqual(result['decision'], 'needs_information')
                self.assertNotIn('orders', result['details'])

    def test_invalid_order_inputs_pending_read_and_handoff_have_distinct_diagnostics(self):
        flow = MatrixConversation()
        for ids in (None, '#TEST1', [], [None], [2], ['']):
            with self.subTest(ids=ids):
                result = summarize_amounts(flow.state, ids)
                self.assertEqual(result['code'], 'invalid_summary_orders')
                self.assertTrue(result['details']['input_error'])
        flow.user('Read order #TEST1', consume=False)
        self.assertEqual(summarize_amounts(flow.state, ['#TEST1'])['code'], 'summary_evidence_unresolved')
        flow = MatrixConversation(); flow.user('transfer me to a human')
        self.assertEqual(summarize_amounts(flow.state, ['#TEST1'])['code'], 'summary_handoff_blocks_reads')
