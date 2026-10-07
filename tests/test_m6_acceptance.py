"""M6.7 regressions from concrete requirements, never AT success by association."""
from copy import deepcopy
import unittest

from test_m5_exchanges import ExchangeConversation
from test_m5_items import ItemsConversation
from support_agent.adapters.write_runtime import SessionWriteRuntime, SessionClaims
from support_agent.domain.catalog import resolve_replacements
from support_agent.proposals import _current_records
from support_agent.state import clone_state
import json


class ReturnEligibilityInquiryTests(unittest.TestCase):
    def test_can_i_return_question_prepares_only_and_waits_for_real_assent(self):
        from test_m5_returns import ReturnsConversation
        flow = ReturnsConversation()
        flow.user('Can I return order #TEST1; items: item_blue; refund to card_a?')
        self.assertEqual(flow.code(), 'returns_confirmation_required')
        self.assertFalse(flow.posts())
        self.assertIsNone(_current_records(flow.state)[0]['confirmation'])
        self.assertEqual(flow.api.orders['#TEST1']['status'], 'delivered')

    def test_later_eligibility_question_explains_one_application_limit_without_second_send(self):
        from test_m5_returns import ReturnsConversation
        flow = ReturnsConversation(); flow.start(); flow.user('yes')
        before = deepcopy(flow.api.orders)
        flow.user('Can I return order #TEST1; items: item_blue; refund to card_a?')
        self.assertEqual(flow.code(), 'return_exchange_already_requested')
        self.assertEqual(len(flow.posts()), 1)
        self.assertEqual(flow.api.orders, before)


class WholeCancellationScopeRecapTests(unittest.TestCase):
    def test_old_partial_cancellation_diagnostic_cannot_swallow_read_after_new_item_workflow(self):
        from test_m5_matrix import MatrixConversation
        flow = MatrixConversation('items')
        flow.user('Cancel only item item_blue from order #TEST1')
        self.assertEqual(flow.code('cancellation'), 'cancellation_whole_order_required')
        import json
        criteria = {'hard': [{'field': 'color', 'op': 'eq', 'value': 'red'},
                             {'field': 'price', 'op': 'lte', 'value': 200}],
                    'change': ['color'], 'relax': [], 'preferences': [], 'fallbacks': [], 'ranking': []}
        flow.user('Change order #TEST1 items: ' + json.dumps({'replacements': [
            {'item_id': 'item_blue', 'criteria': criteria}], 'payment_method_id': 'card_a'}))
        flow.user('yes')
        self.assertEqual(flow.code('items'), 'write_verified')
        before = deepcopy(flow.business_calls())
        decision = flow.user('Read order #TEST1')
        self.assertIn('Owned order records:', decision.text)
        self.assertIn('pending (items modified)', decision.text)
        self.assertEqual(flow.business_calls(), before)

    def test_recap_names_every_original_unit_and_occurrence_before_assent(self):
        from test_m4_cancellations import CancellationConversation
        flow = CancellationConversation()
        original = deepcopy(flow.api.orders['#TEST1']['items'][0])
        flow.api.orders['#TEST1']['items'] = [original, deepcopy(original)]
        decision = flow.cancel()
        self.assertIn('Complete original item list for this whole-order cancellation:', decision.text)
        self.assertEqual(decision.text.count('"item_id": "' + original['item_id'] + '"'), 2)
        self.assertIn(original['name'], decision.text)
        self.assertFalse(flow.posts())


class VisibleTiedCandidateTests(unittest.TestCase):
    def test_explicit_corrected_action_owns_its_json_instead_of_old_opposite_draft(self):
        import json
        from test_m5_matrix import MatrixConversation
        for kind, first, corrected in (('items', 'Exchange', 'Change'), ('exchange', 'Change', 'Exchange')):
            flow = MatrixConversation(kind)
            body = json.dumps({'replacements': [{'item_id': 'item_blue', 'replacement_item_id': 'item_red'}],
                               'payment_method_id': 'card_a'})
            flow.user(first + ' order #TEST1 items: ' + body)
            self.assertEqual(flow.business_calls(), [])
            flow.user(corrected + ' order #TEST1 items: ' + body)
            self.assertEqual(flow.code(kind), kind + '_confirmation_required')
            self.assertEqual(flow.business_calls(), [])
            flow.user('yes')
            self.assertEqual(flow.code(kind), 'write_verified')
            self.assertEqual([row['spec']['action'] for row in flow.writes()],
                             ['modify_items' if kind == 'items' else 'exchange'])

    def test_both_workflows_display_all_tied_ids_prices_options_without_selecting(self):
        for flow_type in (ItemsConversation, ExchangeConversation):
            flow = flow_type()
            target = deepcopy(flow.api.products['product_mug']['items'][1])
            target['item_id'] = 'another_tied_red'
            flow.api.products['product_mug']['items'].append(target)
            decision = flow.change() if flow_type is ItemsConversation else flow.start()
            self.assertEqual(flow.code(), 'candidate_choice_required')
            for item_id in ('item_red', 'another_tied_red'):
                self.assertIn(item_id, decision.text)
            self.assertIn('"price": ' + str(target['price']), decision.text)
            self.assertIn('"options":', decision.text)
            self.assertFalse(flow.posts())
            self.assertEqual(_current_records(flow.state), [])

    def test_oversized_tie_is_refused_without_truncated_options_or_hidden_choice(self):
        flow = ItemsConversation()
        target = deepcopy(flow.api.products['product_mug']['items'][1])
        target['item_id'] = 'another_tied_red'
        flow.api.products['product_mug']['items'].append(target)
        flow.api.orders['#TEST1']['items'][0]['options']['capacity'] = 'x' * 4500
        for row in flow.api.products['product_mug']['items']:
            row['options']['capacity'] = 'x' * 4500
        decision = flow.change()
        self.assertEqual(flow.code(), 'items_selection_budget_exceeded')
        self.assertNotIn('x' * 4500, decision.text)
        self.assertFalse(flow.posts())
        self.assertEqual(_current_records(flow.state), [])


class WithdrawnWorkflowReplacementTests(unittest.TestCase):
    def test_real_unsent_withdrawal_allows_fresh_return_recap_and_separate_consent(self):
        from test_m5_matrix import MatrixConversation
        from support_agent.tasks import inspect_task_plan
        flow = MatrixConversation('exchange'); flow.start()
        old = deepcopy(_current_records(flow.state)[0])
        flow.user('withdraw all')
        self.assertEqual(_current_records(flow.state)[0]['status'], 'withdrawn')
        self.assertEqual(inspect_task_plan(flow.state)['details']['tasks'][0]['assessment']['code'], 'proposal_withdrawn')
        flow.user('Return order #TEST1; items: item_blue; refund to card_a')
        self.assertEqual(flow.code('returns'), 'returns_confirmation_required')
        self.assertEqual(flow.business_calls(), [])
        current = _current_records(flow.state)[0]
        self.assertGreater(current['version'], old['version']); self.assertIsNone(current['confirmation'])
        flow.user('yes'); self.assertEqual(flow.code('returns'), 'write_verified')
        self.assertEqual([o['spec']['action'] for o in flow.writes()], ['return'])
        self.assertEqual(clone_state(flow.state), flow.state)

    def test_different_request_without_withdrawal_preserves_unfinished_conflict(self):
        from test_m5_matrix import MatrixConversation
        flow = MatrixConversation('exchange'); flow.start()
        flow.user('Return order #TEST1; items: item_blue; refund to card_a')
        self.assertEqual(flow.code('returns'), 'returns_mixed_plan_requires_review')
        flow.user('yes'); self.assertEqual(flow.business_calls(), [])

    def test_withdrawn_unsent_exchange_allows_a_separately_confirmed_profile_address(self):
        from test_m5_matrix import MatrixConversation
        from test_m4_addresses import NEW
        import json
        flow=MatrixConversation('exchange');flow.start();flow.user('withdraw all')
        decision=flow.user('Change default address: '+json.dumps(NEW))
        self.assertIn('address_confirmation_required',str(flow.state['history'][-1]))
        self.assertFalse(flow.business_calls());flow.user('yes')
        self.assertEqual([o['spec']['action'] for o in flow.writes()],['default_shipping_address'])
        self.assertEqual(flow.api.customers['customer_a']['default_shipping_address'],NEW)

    def test_withdrawn_proposal_stays_withdrawn_after_new_text_and_cannot_reconfirm(self):
        from test_m5_matrix import MatrixConversation
        from support_agent.proposals import observe_user, check_confirmation
        flow = MatrixConversation('exchange'); flow.start(); flow.user('withdraw all')
        record = deepcopy(_current_records(flow.state)[0])
        for text in ('Read order #TEST1', 'yes', 'confirm all'):
            state = deepcopy(flow.state); state['history'].append({'role':'user','content':text})
            observe_user(state,len(state['history'])-1)
            self.assertEqual(_current_records(state)[0],record)
            self.assertEqual(check_confirmation(state,record['version'],record['spec'])['code'],'proposal_withdrawn')

    def test_withdrawal_does_not_discard_unknown_attempt_or_permit_same_record_return(self):
        from test_m5_matrix import MatrixConversation
        from support_agent.workflow_boundary import unfinished_other_tasks
        flow = MatrixConversation('exchange'); flow.start(); flow.api.failure='timeout'; flow.user('yes')
        old = deepcopy(flow.writes()[0]); self.assertEqual(old['status'],'unknown')
        # Restore backend status only to expose the attempted-journal guard.
        flow.api.orders['#TEST1']['status']='delivered'; flow.api.orders['#TEST1'].pop('exchange')
        flow.user('withdraw all')
        self.assertTrue(unfinished_other_tasks(flow.state,{'return'},target=old['spec']['target']))
        flow.user('Return order #TEST1; items: item_blue; refund to card_a')
        self.assertEqual(flow.code('returns'),'returns_mixed_plan_requires_review')
        self.assertEqual(flow.writes()[0],old); self.assertEqual(len(flow.business_calls()),1)


class OriginalPurchaseAnalysisTests(unittest.TestCase):
    def test_product_history_total_keeps_duplicate_units_and_uses_original_prices(self):
        from support_agent.read_session import _purchase_groups
        first=self.order();second=deepcopy(first);second['order_id']='#OTHER'
        first['items'].insert(0,deepcopy(first['items'][0]))
        groups=_purchase_groups([first,second])
        self.assertEqual(groups[0]['unit_count'],5)
        self.assertEqual(groups[0]['original_price_total'],'140.00')
        self.assertEqual([u['order_id'] for u in groups[0]['units']],['#TEST1']*3+['#OTHER']*2)

    def test_different_products_cannot_merge_by_equal_name_or_price(self):
        from support_agent.read_session import _purchase_groups
        order=self.order();order['items'][1]['product_id']='product_other'
        order['items'][1]['name']=order['items'][0]['name']
        groups=_purchase_groups([order])
        self.assertEqual([g['unit_count'] for g in groups],[1,1])
        self.assertEqual([g['original_price_total'] for g in groups],['20.00','40.00'])

    def order(self):
        from test_m5_matrix import MatrixBackend
        order=deepcopy(MatrixBackend().orders['#TEST1'])
        first=order['items'][0];first['price']=20
        second=deepcopy(first);second.update(item_id='item_second',name='Second purchase',price=40)
        order['items']=[first,second]
        order['payments']=[{'transaction_type':'payment','payment_method_id':'card_a','amount':60},
                           {'transaction_type':'refund','payment_method_id':'card_a','amount':20}]
        return order

    def test_highest_purchase_uses_original_price_and_keeps_payment_and_refund_separate(self):
        from support_agent.read_session import _purchase_amounts,format_reads
        order=self.order();value=_purchase_amounts(order)
        self.assertEqual(value['highest_original_price_units'],[{'item_id':'item_second','name':'Second purchase','price':40}])
        self.assertEqual((value['original_item_total'],value['recorded_charge_total'],value['visible_refund_total']),('60.00','60.00','20.00'))
        text=format_reads([('get_order',{},order)])
        self.assertIn('"original_item_total": "60.00"',text)
        self.assertIn('"highest_original_price_units": [{"item_id": "item_second"',text)
        self.assertFalse(value['settlement_verified'])

    def test_equal_highest_units_and_duplicate_refund_rows_are_not_collapsed(self):
        from support_agent.read_session import _purchase_amounts
        order=self.order();order['items'][0]['price']=40;order['payments'].append(deepcopy(order['payments'][1]))
        value=_purchase_amounts(order)
        self.assertEqual(len(value['highest_original_price_units']),2)
        self.assertEqual((value['original_item_total'],value['visible_refund_total']),('80.00','40.00'))

    def test_missing_payment_evidence_is_unknown_but_actual_zero_charge_is_zero(self):
        from support_agent.read_session import _purchase_amounts
        order=self.order();order['payments']=[];value=_purchase_amounts(order)
        self.assertIsNone(value['recorded_charge_total']);self.assertIsNone(value['visible_refund_total'])
        order['payments']=[{'transaction_type':'payment','payment_method_id':'card_a','amount':0}]
        self.assertEqual(_purchase_amounts(order)['recorded_charge_total'],'0.00')

    def test_retained_original_sum_subtracts_only_requested_occurrences_not_current_prices(self):
        from support_agent.read_session import _purchase_amounts
        order=self.order();order['items'].insert(0,deepcopy(order['items'][0]))
        order['return_request']={'item_ids':['item_blue'],'refund_payment_method_id':'card_a'}
        value=_purchase_amounts(order)
        self.assertEqual(value['retained_original_total'],'60.00')
        self.assertEqual([i['item_id'] for i in value['retained_original_units']],['item_blue','item_second'])

    def test_ambiguous_duplicate_original_unit_prices_make_retained_sum_unavailable(self):
        from support_agent.read_session import _purchase_amounts
        order=self.order();other=deepcopy(order['items'][0]);other['price']=21;order['items'].insert(0,other)
        order['return_request']={'item_ids':['item_blue'],'refund_payment_method_id':'card_a'}
        value=_purchase_amounts(order)
        self.assertIsNone(value['retained_original_total']);self.assertIsNone(value['retained_original_units'])


class ExplicitCapabilityTests(unittest.TestCase):
    def test_split_order_payment_keeps_existing_workflow_diagnostic(self):
        from test_m4_payments import PaymentConversation
        flow = PaymentConversation()
        flow.switch('split across two cards')
        self.assertEqual(flow.code(), 'single_method_required')
        self.assertFalse(flow.puts())

    def test_email_change_explained_without_lookup_of_new_address_or_account_read(self):
        from support_agent.read_session import advance
        from support_agent.protocol import TurnInput
        from support_agent.state import initial_state
        decision,state=advance(TurnInput('user','Change my profile email to new@example.test'),initial_state())
        self.assertFalse(decision.calls);self.assertIn('cannot change your profile email',decision.text)
        self.assertFalse(state['identity']['verified']);self.assertEqual(state['operations'],[])

    def test_new_saved_method_split_payment_purchase_and_restore_are_explained_without_authorization(self):
        from support_agent.read_session import advance
        from support_agent.protocol import TurnInput
        from support_agent.state import initial_state
        for text,explanation in [('Add a new payment method','through the website'),
                                 ('Split payment between two cards','covering the full order'),
                                 ('Place a new order','cannot place a new order'),
                                 ('Undo cancellation','cannot be restored')]:
            with self.subTest(text=text):
                decision,state=advance(TurnInput('user',text),initial_state())
                self.assertFalse(decision.calls);self.assertIn(explanation,decision.text)
                self.assertEqual(state['operations'],[]);self.assertEqual(state['handoff']['status'],'not_requested')

    def test_business_json_values_cannot_trigger_an_unsupported_capability_intent(self):
        from support_agent.read_session import capability_reply
        self.assertIsNone(capability_reply('Change order #TEST1 items: {"options":{"name":"change email"}}'))
        self.assertIsNone(capability_reply('Read order #TEST1'))


class ProductPriceAnalysisTests(unittest.TestCase):
    def test_lowest_available_price_excludes_out_of_stock_and_preserves_equal_price_choices(self):
        from support_agent.read_session import format_reads
        import json
        rows=[dict(item_id='absent',price=1,available=False,options={'color':'blue'}),
              dict(item_id='first',price=5,available=True,options={'color':'red'}),
              dict(item_id='second',price=5,available=True,options={'color':'black'}),
              dict(item_id='costly',price=9,available=True,options={'color':'white'})]
        text=format_reads([('get_product',{},dict(product_id='product_shirt',name='Shirt',items=rows))])
        actual=json.loads(text.split('no purchase permission): ')[1])
        self.assertEqual(actual,dict(product_id='product_shirt',price=5,variants=rows[1:3]))

    def test_no_available_variant_is_unavailable_not_zero_price(self):
        from support_agent.read_session import format_reads
        import json
        text=format_reads([('get_product',{},dict(product_id='product_shirt',name='Shirt',items=[dict(item_id='absent',price=1,available=False,options={})]))])
        self.assertEqual(json.loads(text.split('no purchase permission): ')[1]),dict(product_id='product_shirt',price=None,variants=[]))


class IndividualDifferenceDisplayTests(unittest.TestCase):
    def test_complete_exchange_recap_displays_both_charge_and_refund_without_replacing_total(self):
        flow=ExchangeConversation()
        from support_agent.items_session import render_items_note
        flow.start();data=deepcopy(flow.basis())
        first=data['prices'][0];first.update(original_price=40,new_price=45)
        second=deepcopy(first);second.update(original_item_id='other_original',new_item_id='other_new',original_price=50,new_price=45)
        data['prices'].append(second);data['sources'].append(deepcopy(data['sources'][0]));data['spec']['amount']['value']=0
        text=render_items_note(data,kind='exchange')
        self.assertIn('Item 1 displayed additional charge: 5.00',text)
        self.assertIn('Item 2 displayed refund difference: 5.00',text)
        self.assertIn('Zero difference: 0.00',text)
        self.assertIn('not by adding rounded line displays',text)

    def test_per_line_display_does_not_change_the_original_ordered_total(self):
        from support_agent.items_session import render_items_note
        flow=ExchangeConversation();flow.start();data=deepcopy(flow.basis())
        data['prices'][0].update(original_price=0,new_price=0.005)
        data['prices'].append(deepcopy(data['prices'][0]));data['sources'].append(deepcopy(data['sources'][0]));data['spec']['amount']['value']=0.01
        before=deepcopy(data);text=render_items_note(data,kind='exchange')
        self.assertIn('signed price difference 0.01',text);self.assertEqual(data,before)


class SameVariantExchangeTests(unittest.TestCase):
    def test_same_variant_delivered_replacement_needs_recap_then_one_verified_application(self):
        flow = ExchangeConversation()
        # Equal current/original prices isolate same-variant permission from quote changes.
        flow.api.products['product_mug']['items'][0]['price'] = 12.5
        before = deepcopy(flow.api.orders['#TEST1']['items'])
        decision = flow.start('same variant')
        self.assertEqual(flow.code(), 'exchange_confirmation_required')
        self.assertFalse(flow.posts())
        self.assertIn('item_blue -> item_blue', decision.text)
        self.assertEqual(flow.basis()['spec']['amount']['value'], 0)
        self.assertEqual(_current_records(flow.state)[0]['status'], 'proposed')
        flow.user('yes')
        self.assertEqual(flow.code(), 'write_verified')
        self.assertEqual(len(flow.posts()), 1)
        self.assertEqual(flow.posts()[0][2], {'replacements': [
            {'existing_item_id': 'item_blue', 'replacement_item_id': 'item_blue'}],
            'payment_method_id': 'card_a'})
        self.assertEqual(flow.api.orders['#TEST1']['items'], before)
        self.assertEqual(clone_state(flow.state), flow.state)

    def test_same_variant_exchange_uses_current_quote_not_guessed_zero(self):
        flow = ExchangeConversation()
        flow.start('same variant')
        self.assertEqual(flow.code(), 'exchange_confirmation_required')
        self.assertEqual(flow.basis()['spec']['amount']['value'], 86.5)
        flow.user('yes')
        self.assertEqual(flow.code(), 'write_verified')
        self.assertEqual(flow.api.orders['#TEST1']['exchange']['price_difference'], 86.5)

    def test_pending_same_variant_still_refuses_noop_without_write(self):
        flow = ItemsConversation()
        before = deepcopy(flow.api.orders)
        flow.change('same variant')
        self.assertEqual(flow.code(), 'unchanged_variant')
        flow.user('yes')
        self.assertFalse(flow.posts())
        self.assertEqual(flow.api.orders, before)

    def test_same_variant_exchange_checks_stock_and_refreshes_before_send(self):
        for before_recap in (True, False):
            with self.subTest(before_recap=before_recap):
                flow = ExchangeConversation()
                if before_recap:
                    flow.api.products['product_mug']['items'][0]['available'] = False
                flow.start('same variant')
                if before_recap:
                    self.assertEqual(flow.code(), 'variant_unavailable')
                else:
                    self.assertEqual(flow.code(), 'exchange_confirmation_required')
                    flow.api.products['product_mug']['items'][0]['available'] = False
                flow.user('yes')
                self.assertFalse(flow.posts())
                self.assertEqual(flow.api.orders['#TEST1']['status'], 'delivered')

    def test_only_exact_supported_same_variant_phrase_resolves_from_user_original(self):
        for text in ('同款', '相同规格', 'identical replacement', 'same item'):
            flow = ExchangeConversation()
            flow.start(text)
            self.assertEqual(flow.code(), 'exchange_confirmation_required')
            self.assertEqual(flow.basis()['sources'][0]['criteria'], {'variant': 'item_blue'})
            self.assertFalse(flow.posts())

    def test_same_variant_permission_is_strict_internal_flag_default_off(self):
        flow = ExchangeConversation()
        order = flow.api.orders['#TEST1']
        pairs = [{'existing_item_id': 'item_blue', 'replacement_item_id': 'item_blue'}]
        products = [flow.api.products['product_mug']]
        for flag, expected in ((False, 'unchanged_variant'), (True, 'replacements_eligible'),
                               (1, 'invalid_matching_mode'), ('true', 'invalid_matching_mode')):
            result = resolve_replacements(order['items'], pairs, products,
                                          requested_options=[{}], allow_same_variant=flag)
            self.assertEqual(result['code'], expected)

    def test_same_variant_write_business_guard_still_binds_action_and_options(self):
        flow = ExchangeConversation()
        flow.start('same variant')
        spec = flow.basis()['spec']
        runtime = SessionWriteRuntime(flow.api, claims=SessionClaims(), requested_options=[{}])
        self.assertEqual(runtime.assess_business(flow.state, spec)['code'], 'replacements_eligible')
        pending = ItemsConversation(); pending.change()
        changed = deepcopy(next(e['items_basis']['spec'] for e in reversed(pending.state['history']) if 'items_basis' in e))
        changed['parameters']['replacements'][0]['replacement_item_id'] = 'item_blue'
        # Use a pending order so the state guard cannot mask the variant guard.
        runtime = SessionWriteRuntime(pending.api, claims=SessionClaims(), requested_options=[{}])
        self.assertEqual(runtime.assess_business(pending.state, changed)['code'], 'unchanged_variant')

    def test_same_variant_exchange_does_not_unlock_second_submission(self):
        flow = ExchangeConversation(); flow.start('same variant'); flow.user('yes')
        self.assertEqual(flow.code(), 'write_verified')
        before = deepcopy(flow.api.orders)
        flow.start('same variant'); flow.user('yes')
        self.assertEqual(len(flow.posts()), 1)
        self.assertEqual(flow.api.orders, before)
class WholeOrderBudgetTests(unittest.TestCase):
    def flow(self):
        from test_m5_matrix import MatrixConversation
        flow = MatrixConversation('items')
        item = flow.api.orders['#TEST1']['items'][0]; item['price'] = 20
        other = deepcopy(item); other.update(item_id='item_unchanged',price=30)
        flow.api.orders['#TEST1']['items'].append(other)
        flow.api.products['product_mug']['items'][1]['price'] = 12
        return flow

    def request(self, flow, limit, rows=None):
        return flow.user('Change order #TEST1 items: ' + json.dumps({
            'replacements':rows or [{'item_id':'item_blue','replacement_item_id':'item_red'}],
            'payment_method_id':'card_a','max_total_price':limit}))

    def test_budget_counts_unchanged_units_and_allows_exact_equality(self):
        flow = self.flow(); decision = self.request(flow,42)
        self.assertEqual(flow.code(),'items_confirmation_required')
        basis = next(e['items_basis'] for e in reversed(flow.state['history']) if 'items_basis' in e)
        self.assertEqual(basis['budget']['whole_order_target_total'],'42.00')
        self.assertIn('Whole-order target total: 42.00',decision.text)
        self.assertFalse(flow.business_calls()); flow.user('yes')
        self.assertEqual(flow.code(),'write_verified')
        self.assertEqual(flow.api.orders['#TEST1']['items'][1]['price'],30)
        self.assertEqual(set(flow.business_calls()[0][2]),{'replacements','payment_method_id'})

    def test_budget_excludes_no_units_and_cannot_be_mistaken_for_difference(self):
        flow = self.flow(); before = deepcopy(flow.api.orders)
        self.request(flow,41.99)
        self.assertEqual(flow.code(),'whole_order_budget_unreachable')
        self.assertEqual(_current_records(flow.state),[])
        flow.user('yes'); self.assertEqual(flow.business_calls(),[])
        self.assertEqual(flow.api.orders,before)

    def test_changed_unchanged_unit_price_is_rechecked_before_send(self):
        flow = self.flow(); self.request(flow,42)
        flow.api.orders['#TEST1']['items'][1]['price']=31
        flow.user('yes')
        self.assertEqual(flow.code(),'whole_order_budget_unreachable')
        self.assertEqual(flow.business_calls(),[])
        self.assertEqual(flow.api.orders['#TEST1']['status'],'pending')

    def test_changed_target_price_cannot_cross_budget_using_prior_confirmation(self):
        flow = self.flow(); self.request(flow,42)
        flow.api.products['product_mug']['items'][1]['price']=13
        flow.user('yes')
        self.assertEqual(flow.code(),'whole_order_budget_unreachable')
        self.assertEqual(flow.business_calls(),[])

    def test_invalid_budget_boolean_string_negative_and_nonfinite_are_input_errors(self):
        for limit in (True,'42',-1,float('inf')):
            flow=self.flow(); self.request(flow,limit)
            self.assertEqual(flow.code(),'invalid_items_json')
            self.assertFalse(flow.business_calls()); self.assertEqual(_current_records(flow.state),[])

    def test_budget_preserves_repeated_unit_counts(self):
        flow=self.flow(); item=deepcopy(flow.api.orders['#TEST1']['items'][0])
        flow.api.orders['#TEST1']['items']=[item,deepcopy(item)]
        rows=[{'item_id':'item_blue','replacement_item_id':'item_red'}]*2
        self.request(flow,23.99,rows)
        self.assertEqual(flow.code(),'whole_order_budget_unreachable')
        self.assertEqual(flow.business_calls(),[])
        self.request(flow,24,rows)
        self.assertEqual(flow.code(),'items_confirmation_required')
        basis=next(e['items_basis'] for e in reversed(flow.state['history']) if 'items_basis' in e)
        self.assertEqual(basis['budget']['whole_order_target_total'],'24.00')
        self.assertEqual(len(basis['spec']['parameters']['replacements']),2)

    def test_restored_budget_and_real_user_source_cannot_be_forged(self):
        flow=self.flow(); self.request(flow,42)
        clone_state(flow.state)
        bad=deepcopy(flow.state)
        entry=next(e for e in reversed(bad['history']) if 'items_basis' in e)
        entry['items_basis']['budget']['max_total_price']=999
        from support_agent.state import InvalidState
        with self.assertRaises(InvalidState): clone_state(bad)


class ReadOnlyScopeAnalysisTests(unittest.TestCase):
    def user(self,flow,text):
        decision=flow.user(text)
        for _ in range(12):
            if not decision.calls:
                return decision
            decision=flow.consume(decision)
        self.fail('Read-only request exceeded its bounded tool steps')

    def estimate(self,flow,ids,order='#TEST1'):
        return self.user(flow,'Estimate selected items order '+order+': '+json.dumps({'item_ids':ids}))

    def test_selected_estimate_uses_original_prices_and_cannot_confirm_a_return(self):
        from test_m5_matrix import MatrixConversation
        flow=MatrixConversation('items');flow.api.orders['#TEST1']['items'][0]['price']=0.005
        flow.api.products['product_mug']['items'][0]['price']=999
        decision=self.estimate(flow,['item_blue'])
        self.assertIn('"exact_price_sum": "0.005"',decision.text)
        self.assertIn('"aggregate_amount": 0.01',decision.text)
        self.assertIn('not cancellation or return eligibility',decision.text)
        self.assertEqual(_current_records(flow.state),[]);flow.user('yes')
        self.assertEqual(flow.business_calls(),[])

    def test_selected_duplicate_count_and_ambiguous_prices_are_preserved(self):
        from test_m5_matrix import MatrixConversation
        flow=MatrixConversation('items',copies=2)
        for item in flow.api.orders['#TEST1']['items']:item['price']=20
        self.assertIn('"aggregate_amount": 40.0',self.estimate(flow,['item_blue']*2).text)
        flow.api.orders['#TEST1']['items'][1]['price']=21
        self.assertIn('scope_analysis_instance_selection_unavailable',self.estimate(flow,['item_blue']).text)
        self.assertEqual(flow.business_calls(),[])

    def test_current_read_failure_cannot_reuse_previous_estimate_snapshot(self):
        from test_m5_matrix import MatrixConversation
        flow=MatrixConversation('items');self.estimate(flow,['item_blue'])
        from support_agent.protocol import TurnInput, ToolOutcome
        from support_agent.turns import advance
        decision=flow.user('Estimate selected items order #TEST1: '+json.dumps({'item_ids':['item_blue']}),consume=False)
        decision,flow.state=advance(TurnInput('tools',outcomes=(ToolOutcome(decision.calls[0].id,'',error=True),)),flow.state)
        self.assertNotIn('potential_refund_estimate',decision.text)
        self.assertIn('lookup failed',decision.text)
        self.assertEqual(flow.business_calls(),[])

    def test_foreign_scope_refused_before_private_read(self):
        from test_m5_matrix import MatrixConversation
        flow=MatrixConversation('items'); before=deepcopy(flow.api.calls)
        self.assertIn('scope_analysis_order_not_owned',self.estimate(flow,['item_blue'],'#TEST2').text)
        self.assertEqual(flow.api.calls,before)

    def test_invalid_selection_and_extra_authority_are_refused_without_io(self):
        from test_m5_matrix import MatrixConversation
        for body in ({'item_ids':['item_blue'],'confirmed':True},{'item_ids':[]},{'item_ids':[True]}):
            flow=MatrixConversation('items'); before=deepcopy(flow.api.calls)
            decision=flow.user('Estimate selected items order #TEST1: '+json.dumps(body))
            self.assertIn('scope_analysis_input_error',decision.text)
            self.assertEqual(flow.api.calls,before)

    def test_comparison_reranks_actual_prices_and_ties_require_customer_choice(self):
        from test_m5_matrix import MatrixConversation
        flow=MatrixConversation('exchange')
        flow.api.orders['#TEST1']['items'][0]['price']=20
        flow.api.products['product_mug']['items'][1]['price']=0
        request='Compare return and exchange order #TEST1: '+json.dumps({
            'item_ids':['item_blue'],'replacements':[{'item_id':'item_blue','replacement_item_id':'item_red'}]})
        decision=self.user(flow,request)
        self.assertIn('"most_saving_option": "customer_choice_required"',decision.text)
        self.assertIn('"mutually_exclusive_same_order": true',decision.text)
        self.assertEqual(_current_records(flow.state),[])
        flow.api.products['product_mug']['items'][1]['price']=1
        self.assertIn('"most_saving_option": "return"',self.user(flow,request).text)
        self.assertEqual(flow.business_calls(),[])

    def test_unknown_or_unavailable_target_cannot_become_zero_savings(self):
        from test_m5_matrix import MatrixConversation
        flow=MatrixConversation('exchange');flow.api.products['product_mug']['items'][1]['available']=False
        request='Compare return and exchange order #TEST1: '+json.dumps({
            'item_ids':['item_blue'],'replacements':[{'item_id':'item_blue','replacement_item_id':'item_red'}]})
        decision=self.user(flow,request)
        self.assertIn('scope_analysis_variant_unavailable',decision.text)
        self.assertNotIn('most_saving_option',decision.text)
        self.assertFalse(flow.business_calls())

    def test_large_selected_estimate_is_refused_without_truncation_or_proposal(self):
        from test_m5_matrix import MatrixConversation
        flow=MatrixConversation('items');flow.api.orders['#TEST1']['items'][0]['name']='x'*4500
        decision=self.estimate(flow,['item_blue'])
        self.assertIn('scope_analysis_display_budget_exceeded',decision.text)
        self.assertNotIn('x'*4500,decision.text)
        self.assertEqual(_current_records(flow.state),[]);self.assertFalse(flow.business_calls())

    def test_modified_noun_cancellation_scope_is_not_whole_order_permission(self):
        from test_m5_matrix import MatrixConversation
        for text in ('Cancel office items from order #TEST1 because no longer needed',
                     'Cancel the hiking item from order #TEST1 because ordered by mistake'):
            flow=MatrixConversation('items');before=deepcopy(flow.api.calls)
            flow.user(text)
            self.assertEqual(flow.code('cancellation'),'cancellation_whole_order_required')
            self.assertEqual(flow.api.calls,before);self.assertEqual(_current_records(flow.state),[])

    def test_scope_words_inside_reason_do_not_reclassify_whole_order_cancel(self):
        from test_m5_matrix import MatrixConversation
        flow=MatrixConversation('items')
        flow.user('Cancel order #TEST1 because no longer needed')
        self.assertEqual(flow.code('cancellation'),'cancellation_confirmation_required')
        self.assertFalse(flow.business_calls())
