"""M5.4 complete delivered exchanges; synthetic transport and real role history."""
import importlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from fakes import FakeResponse
from test_m5_items import ItemsBackend
from test_m4_payments import PaymentConversation
from test_m1_adapter import platform_modules
from support_agent.domain.items_intake import request_from_history
from support_agent.exchange_session import _prepare
from support_agent.protocol import TurnInput, ToolOutcome, WORKFLOW_TOOL_NAMES, InvalidAction, decision_from_candidate
from support_agent.proposals import _current_records
from support_agent.read_session import bind_arguments
from support_agent.state import initial_state, clone_state, InvalidState, SCHEMA_VERSION
from support_agent.turns import advance
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.workflow_limits import WorkflowResultTooLarge


class ExchangeBackend(ItemsBackend):
    def __init__(self):
        super().__init__()
        for order in self.orders.values(): order['status'] = 'delivered'
        self.read_failure = None

    def request(self, method, path, body=None):
        if method == 'GET' and self.read_failure and self.read_failure in path:
            self.calls.append((method, path, deepcopy(body)))
            return FakeResponse(503, {'error': {'code': 'synthetic_read_error', 'message': 'Synthetic failure'}})
        if method == 'POST' and path.endswith('/exchanges'):
            self.calls.append((method, path, deepcopy(body)))
            if self.failure in ('409', '422'):
                return FakeResponse(int(self.failure), {'error': {'code': 'synthetic_refusal', 'message': 'Synthetic rejection'}})
            order = self.orders[unquote(path.split('/')[-2])]
            if order['status'] != 'delivered':
                return FakeResponse(409, {'error': {'code': 'state_lock', 'message': 'Already requested'}})
            difference = 0.0
            for pair in body['replacements']:
                original = next(i for i in order['items'] if i['item_id'] == pair['existing_item_id'])
                target = next(i for p in self.products.values() for i in p['items'] if i['item_id'] == pair['replacement_item_id'])
                difference += target['price'] - original['price']
            order['status'] = 'exchange requested'
            exchange = {**deepcopy(body), 'price_difference': round(difference, 2)}
            if self.failure == 'sort_pairs': exchange['replacements'].reverse()
            if self.failure == 'independent_sort':
                old = sorted(p['existing_item_id'] for p in exchange['replacements'])
                new = sorted(p['replacement_item_id'] for p in exchange['replacements'])
                exchange['replacements'] = [dict(existing_item_id=a, replacement_item_id=b) for a,b in zip(old,new)]
            if self.failure == 'missing_pair': exchange['replacements'].pop()
            if self.failure == 'extra_pair': exchange['replacements'].append(deepcopy(exchange['replacements'][0]))
            if self.failure == 'wrong_amount': exchange['price_difference'] += 1
            if self.failure == 'wrong_method': exchange['payment_method_id'] = 'card_v'
            order['exchange'] = exchange
            receipt = {k: deepcopy(order[k]) for k in ('order_id','status','exchange')}
            if self.failure == 'timeout': raise TimeoutError('private_exchange_timeout')
            if self.failure == 'bad_receipt': receipt['private_field'] = 'rejected_private_exchange_body'
            if self.failure == 'missing_receipt': receipt.pop('exchange')
            if self.failure == 'wrong_readback': order['exchange']['price_difference'] += 1
            if self.failure == 'readback_reorder': order['exchange']['replacements'].reverse()
            if self.failure == 'wrong_status': order['status'] = 'delivered'
            return FakeResponse(200, receipt)
        return super().request(method, path, body)


class ExchangeConversation(PaymentConversation):
    def __init__(self, *, verify=True, claims=None):
        self.api = ExchangeBackend()
        with patch.dict(sys.modules, platform_modules(object())):
            self.toolkit = importlib.import_module('tools').Tools(self.api, claims=claims)
        self.state = initial_state()
        if verify: self.user('a@example.test')

    def start(self, text='color to red', method='card_a', **kwargs):
        return self.user(f'Exchange order #TEST1 items; item item_blue: {text}; pay with {method}', **kwargs)

    def envelope(self, rows, method='card_a', **kwargs):
        data = {'replacements': rows}
        if method is not None: data['payment_method_id'] = method
        return self.user('Exchange order #TEST1 items: ' + json.dumps(data), **kwargs)

    def code(self): return self.state['history'][-1]['exchange_assessment']['code']
    def posts(self): return [c for c in self.api.calls if c[0]=='POST' and c[1].endswith('/exchanges')]
    def basis(self): return next(e['exchange_basis'] for e in reversed(self.state['history']) if 'exchange_basis' in e)


class ExchangeIntakeTests(unittest.TestCase):
    def parse(self, *texts): return request_from_history([{'role':'user','content':t} for t in texts], kind='exchange')

    def test_actual_user_only_without_synthetic_envelope(self):
        text='Exchange #TEST1 items; item item_blue: color red; pay with card_a'
        self.assertIsNone(request_from_history([{'role':'assistant','content':text},{'role':'tool','content':text}],kind='exchange'))
        request=self.parse(text)
        self.assertEqual(request['lines'][0]['index'],0); self.assertEqual(request['method']['index'],0)

    def test_json_preserves_order_occurrences_and_opaque_variant(self):
        rows=[{'item_id':'item_blue','replacement_item_id':'return_exchange_red'}]*2
        request=self.parse('Exchange #TEST1 items: '+json.dumps({'replacements':rows,'payment_method_id':'card_a'}))
        self.assertEqual([r['replacement_item_id'] for r in request['lines']],['return_exchange_red']*2)
        self.assertIsNone(request['error'])

    def test_complete_json_replaces_draft_and_clears_omitted_method(self):
        request=self.parse('Exchange #TEST1 items; item item_blue: color red; pay with card_a', 'items: {"replacements":[{"item_id":"item_green","options":{"color":"red"}}]}')
        self.assertEqual([r['item_id'] for r in request['lines']],['item_green']); self.assertIsNone(request['method'])

    def test_natural_correction_merge_add_remove_keep_real_sources(self):
        r=self.parse('Exchange #TEST1 items; item item_blue: color red','item item_blue: color green','add item item_blue: color red')
        self.assertEqual([v['index'] for v in r['lines']],[1,2])
        self.assertEqual(self.parse('Exchange #TEST1 items; item item_blue: color red','remove item item_blue')['lines'],[])
        self.assertEqual(self.parse('Exchange #TEST1 items; item item_blue: color red','add item item_blue: color red','remove item item_blue')['error'],'ambiguous_item_removal')

    def test_malformed_quantity_mixed_and_multiorder_are_not_partial_requests(self):
        for text, code in [('Exchange #TEST1 items: {"replacements":','invalid_items_json'),('Exchange #TEST1 items: {"replacements":[{"item_id":"item_blue","quantity":2}]}','quantity_change_unsupported'),('Exchange #TEST1 items and return','mixed_or_quantity_request'),('Exchange #TEST1 and #TEST3 items','single_order_required')]:
            with self.subTest(text=text): self.assertEqual(self.parse(text)['error'],code)

    def test_method_tail_condition_is_not_silently_accepted(self):
        self.assertEqual(self.parse('Exchange #TEST1 items; item item_blue: color red; pay with gift_a if enough')['error'],'settlement_choice_unresolved')


class ExchangeFlowTests(unittest.TestCase):
    def test_complete_recap_next_consent_one_post_and_owned_readback(self):
        f=ExchangeConversation(); before=deepcopy(f.api.orders['#TEST1']); recap=f.start()
        self.assertEqual(f.code(),'exchange_confirmation_required'); self.assertEqual(f.posts(),[])
        for value in ('#TEST1','Delivered','Synthetic mug','item_blue','item_red','blue','red','500 ml','waterproof','12.5','15','2.50','card_a','no additions','shipment'):
            self.assertIn(value,recap.text)
        self.assertEqual(recap.text.count('?'),1)
        f.user('yes'); self.assertEqual(f.code(),'write_verified'); self.assertEqual(len(f.posts()),1)
        self.assertEqual(f.posts()[0][2],{'replacements':[{'existing_item_id':'item_blue','replacement_item_id':'item_red'}],'payment_method_id':'card_a'})
        self.assertEqual(f.api.orders['#TEST1']['items'],before['items']); self.assertEqual(f.api.orders['#TEST1']['payments'],before['payments'])
        self.assertEqual(f.writes()[0]['status'],'succeeded'); self.assertIn('not evidence',f.state['history'][-1]['content'])
        self.assertEqual(f.api.calls[-1][0],'GET'); self.assertTrue(f.api.calls[-1][1].endswith('/%23TEST1'))

    def test_negative_difference_can_use_other_saved_card_not_return_destination_rules(self):
        f=ExchangeConversation(); recap=f.start('color green',method='card_v')
        self.assertEqual(f.basis()['spec']['amount']['value'],-2.5); self.assertIn('Refund difference: 2.50',recap.text)
        f.user('yes'); self.assertEqual(f.code(),'write_verified'); self.assertEqual(f.posts()[0][2]['payment_method_id'],'card_v')

    def test_original_sources_can_swap_variants_without_pending_mutation_ambiguity(self):
        f=ExchangeConversation(); second=deepcopy(f.api.orders['#TEST1']['items'][0])
        second.update(item_id='item_red',price=15,options=deepcopy(f.api.products['product_mug']['items'][1]['options']))
        f.api.orders['#TEST1']['items'].append(second)
        # Source blue's catalog price differs from its purchase price; price comes from the order.
        f.envelope([{'item_id':'item_blue','replacement_item_id':'item_red'},{'item_id':'item_red','replacement_item_id':'item_blue'}])
        self.assertEqual(f.code(),'exchange_confirmation_required'); f.user('yes'); self.assertEqual(f.code(),'write_verified')
        self.assertEqual([p['existing_item_id'] for p in f.posts()[0][2]['replacements']],['item_blue','item_red'])

    def test_preference_fallback_is_explicit_and_recapped_before_confirmation(self):
        f=ExchangeConversation(); recap=f.start('color silver otherwise color green')
        self.assertEqual(f.code(),'exchange_confirmation_required'); self.assertIn('fallback 1',recap.text)
        self.assertEqual(f.basis()['sources'][0]['selected_branch'],1); self.assertFalse(f.posts())
        f.user('yes'); self.assertEqual(f.posts()[0][2]['replacements'][0]['replacement_item_id'],'item_green')

    def test_negative_difference_can_use_paypal_or_zero_balance_gift(self):
        for method in ('paypal_a','gift_a'):
            with self.subTest(method=method):
                f=ExchangeConversation()
                for m in f.api.customers['customer_a']['payment_methods']:
                    if m['source']=='gift_card': m['balance']=0
                f.start('color green',method=method); f.user('yes')
                self.assertEqual(f.code(),'write_verified'); self.assertEqual(f.posts()[0][2]['payment_method_id'],method)

    def test_zero_difference_requires_explicit_existing_method_and_keeps_zero(self):
        f=ExchangeConversation(); f.api.products['product_mug']['items'][1]['price']=12.5
        f.envelope([{'item_id':'item_blue','options':{'color':'red'}}],method=None)
        self.assertEqual(f.code(),'payment_method_required'); self.assertFalse(f.posts())
        f.user('pay with card_a'); self.assertEqual(f.basis()['spec']['amount']['value'],0)
        f.user('yes'); self.assertEqual(f.code(),'write_verified')

    def test_positive_gift_must_cover_entire_difference_without_split_or_fallback(self):
        f=ExchangeConversation()
        for m in f.api.customers['customer_a']['payment_methods']:
            if m['source']=='gift_card': m['balance']=2
        before=deepcopy(f.api.orders['#TEST1']); f.start(method='gift_a')
        self.assertEqual(f.code(),'insufficient_gift_card'); self.assertEqual(f.posts(),[]); self.assertEqual(f.api.orders['#TEST1'],before)
        f.user('yes'); self.assertFalse(f.posts())

    def test_chinese_request_and_explicit_variant_take_same_complete_path(self):
        f=ExchangeConversation(); f.user('换货订单 #TEST1 商品；商品 item_blue: color to red；结算方式: card_a')
        self.assertEqual(f.code(),'exchange_confirmation_required'); f.user('确认'); self.assertEqual(f.code(),'write_verified')
        g=ExchangeConversation(); g.start('variant item_red'); g.user('yes'); self.assertEqual(g.code(),'write_verified')

    def test_every_nondelivered_state_blocks_with_exact_code(self):
        codes={'pending':'action_not_allowed_in_state','pending (items modified)':'items_modified_lock','processed':'order_processed','cancelled':'order_cancelled','return requested':'return_exchange_already_requested','exchange requested':'return_exchange_already_requested'}
        for status,code in codes.items():
            with self.subTest(status=status):
                f=ExchangeConversation(); f.api.orders['#TEST1']['status']=status; f.start()
                self.assertEqual(f.code(),code); self.assertFalse(f.posts())

    def test_foreign_order_is_rejected_before_order_get(self):
        f=ExchangeConversation(); before=len(f.api.calls); f.user('Exchange #OUTSIDE items; item item_blue: color red; pay with card_a')
        self.assertEqual(f.code(),'exchange_order_not_owned'); self.assertFalse(any(c[1].endswith('/%23OUTSIDE') for c in f.api.calls[before:])); self.assertFalse(f.posts())

    def test_unverified_request_waits_for_identity_then_prepares(self):
        f=ExchangeConversation(verify=False); f.start(); self.assertEqual(f.api.calls,[])
        decision=f.user('a@example.test')
        while decision.calls: decision=f.consume(decision)
        self.assertEqual(f.code(),'exchange_confirmation_required'); self.assertFalse(f.posts())

    def test_same_variant_cross_product_unavailable_and_unknown_original_block(self):
        for variant,code in [('item_blue','unchanged_variant'),('foreign_item','target_variant_required'),('item_red','variant_unavailable')]:
            with self.subTest(variant=variant):
                f=ExchangeConversation()
                if code=='variant_unavailable': f.api.products['product_mug']['items'][1]['available']=False
                f.start('variant '+variant); self.assertEqual(f.code(),code); self.assertFalse(f.posts())
        f=ExchangeConversation(); f.envelope([{'item_id':'missing','options':{'color':'red'}}]); self.assertEqual(f.code(),'item_not_in_order')

    def test_ambiguous_same_id_instances_and_excess_occurrences_are_not_guessed(self):
        f=ExchangeConversation(); extra=deepcopy(f.api.orders['#TEST1']['items'][0]); extra['price']=9; f.api.orders['#TEST1']['items'].append(extra)
        f.start(); self.assertEqual(f.code(),'instance_selection_unavailable'); self.assertFalse(f.posts())
        g=ExchangeConversation(); g.envelope([{'item_id':'item_blue','replacement_item_id':'item_red'}]*2)
        self.assertEqual(g.code(),'quantity_exceeds_order'); self.assertFalse(g.posts())

    def test_repeated_identical_units_preserve_full_count_and_request_order(self):
        f=ExchangeConversation(); f.api.orders['#TEST1']['items']*=2
        rows=[{'item_id':'item_blue','replacement_item_id':'item_red'},{'item_id':'item_blue','replacement_item_id':'item_green'}]
        f.envelope(rows); self.assertEqual(f.basis()['spec']['amount']['value'],0)
        f.user('yes'); self.assertEqual(f.code(),'write_verified'); self.assertEqual(len(f.posts()[0][2]['replacements']),2)
        self.assertEqual(f.posts()[0][2]['replacements'][1]['replacement_item_id'],'item_green')

    def test_tie_unknown_and_unavailable_primary_do_not_invent_selection(self):
        f=ExchangeConversation(); copy=deepcopy(f.api.products['product_mug']['items'][1]); copy['item_id']='item_red2'; f.api.products['product_mug']['items'].append(copy)
        f.start(); self.assertEqual(f.code(),'candidate_choice_required'); self.assertFalse(f.posts())
        g=ExchangeConversation(); g.api.products['product_mug']['items'][1]['options']['capacity']='large'
        criteria={'hard':[{'field':'capacity','op':'gt','value':'500 ml'}], 'change':['capacity','color'], 'relax':[], 'preferences':[], 'ranking':[], 'fallbacks':[{'hard':[{'field':'color','op':'eq','value':'green'}],'change':['color'],'relax':[]}]}
        g.envelope([{'item_id':'item_blue','criteria':criteria}])
        self.assertEqual(g.code(),'comparison_unavailable'); self.assertFalse(g.posts())

    def test_addition_and_correction_require_new_whole_list_consent(self):
        f=ExchangeConversation(); f.api.orders['#TEST1']['items']*=2; f.start(); v=_current_records(f.state)[0]['version']
        f.user('add item item_blue: color green'); self.assertEqual(len(f.basis()['spec']['parameters']['replacements']),2)
        self.assertGreater(_current_records(f.state)[0]['version'],v); self.assertIsNone(_current_records(f.state)[0]['confirmation']); self.assertFalse(f.posts())
        f.user('yes'); self.assertEqual(f.code(),'write_verified'); self.assertEqual(len(f.posts()),1)

    def test_method_change_before_submission_requires_new_recap(self):
        f=ExchangeConversation(); f.start(); v=_current_records(f.state)[0]['version']; f.user('pay with card_v')
        self.assertGreater(_current_records(f.state)[0]['version'],v); self.assertIsNone(_current_records(f.state)[0]['confirmation']); self.assertFalse(f.posts())
        f.user('yes'); self.assertEqual(f.posts()[0][2]['payment_method_id'],'card_v')

    def test_partial_conditional_withdrawal_or_intervening_reply_do_not_send(self):
        for text in ('yes if cheaper','only one item','withdraw all','hello'):
            with self.subTest(text=text):
                f=ExchangeConversation(); f.start(); f.user(text); f.user('yes'); self.assertFalse(f.posts())

    def test_after_submission_no_append_method_change_second_exchange_or_return(self):
        f=ExchangeConversation(); f.start(); f.user('yes')
        for text in ('add item item_blue: color green','pay with card_v','Exchange #TEST1 items; item item_blue: color green; pay with card_a','Return #TEST1; items: item_blue; refund to original'):
            f.user(text); self.assertEqual(len(f.posts()),1); self.assertFalse(any(c[0]=='POST' and c[1].endswith('/returns') for c in f.api.calls))
        self.assertEqual(f.api.orders['#TEST1']['exchange']['payment_method_id'],'card_a')

    def test_current_target_price_change_requires_fresh_quote_and_confirmation(self):
        f=ExchangeConversation(); f.start(); f.api.products['product_mug']['items'][1]['price']=17
        f.user('yes'); self.assertFalse(f.posts()); self.assertEqual(f.code(),'exchange_confirmation_required'); self.assertEqual(f.basis()['spec']['amount']['value'],4.5)
        f.user('yes'); self.assertEqual(f.code(),'write_verified')

    def test_original_purchase_price_does_not_come_from_source_catalog(self):
        f=ExchangeConversation(); f.api.products['product_mug']['items'][0]['price']=1000; f.start()
        self.assertEqual(f.basis()['prices'][0]['original_price'],12.5); self.assertEqual(f.basis()['spec']['amount']['value'],2.5)

    def test_new_competitor_invalidates_previous_unique_candidate_before_post(self):
        f=ExchangeConversation(); f.start(); copy=deepcopy(f.api.products['product_mug']['items'][1]); copy['item_id']='new_red'; f.api.products['product_mug']['items'].append(copy)
        f.user('yes'); self.assertFalse(f.posts()); self.assertEqual(f.code(),'candidate_choice_required')

    def test_stock_status_method_removal_and_gift_balance_rechecked_at_execution(self):
        for change in ('stock','state','method','balance'):
            with self.subTest(change=change):
                f=ExchangeConversation(); f.start(method='gift_a' if change=='balance' else 'card_a')
                if change=='stock': f.api.products['product_mug']['items'][1]['available']=False
                if change=='state': f.api.orders['#TEST1']['status']='return requested'
                if change=='method': f.api.customers['customer_a']['payment_methods']=[m for m in f.api.customers['customer_a']['payment_methods'] if m['id']!='card_a']
                if change=='balance':
                    for m in f.api.customers['customer_a']['payment_methods']:
                        if m['source']=='gift_card': m['balance']=0
                f.user('yes'); self.assertFalse(f.posts())

    def test_float_difference_is_rounded_once_after_all_pairs(self):
        f=ExchangeConversation(); f.api.orders['#TEST1']['items']*=3
        targets=f.api.products['product_mug']['items'][1:]
        for target in targets: target['price']=12.505
        rows=[{'item_id':'item_blue','replacement_item_id':i['item_id']} for i in targets]
        f.envelope(rows); self.assertEqual(f.basis()['spec']['amount']['value'],0.02)
        f.user('yes'); self.assertEqual(f.code(),'write_verified')

    def test_default_exchange_float_difference_and_payload_keep_sensitive_request_order(self):
        prices=[(5.0,105.0),(105.0,5.0),(0.005,0.01)]
        orderings=[(0,1,2),(0,2,1)]
        self.assertNotEqual(orderings[0],orderings[1])
        results=[]
        for ordering,expected in zip(orderings,[0.01,0.00]):
            with self.subTest(ordering=ordering):
                f=ExchangeConversation(); original=deepcopy(f.api.orders['#TEST1']['items'][0])
                target=deepcopy(f.api.products['product_mug']['items'][1]); originals=[]
                for i,(old_price,new_price) in enumerate(prices):
                    old={**deepcopy(original),'item_id':f'source_{i}','price':old_price}; originals.append(old)
                    new={**deepcopy(target),'item_id':f'target_{i}','price':new_price}
                    f.api.products['product_mug']['items'].append(new)
                f.api.orders['#TEST1']['items']=originals
                rows=[{'item_id':f'source_{i}','replacement_item_id':f'target_{i}'} for i in ordering]
                f.envelope(rows); value=f.basis()['spec']['amount']['value']; results.append(value)
                self.assertEqual(value,expected); f.user('yes'); self.assertEqual(f.code(),'write_verified')
                self.assertEqual(f.posts()[0][2]['replacements'],[{'existing_item_id':r['item_id'],'replacement_item_id':r['replacement_item_id']} for r in rows])
        self.assertNotEqual(results[0],results[1])

    def test_bulk_all_phrase_requires_each_target_for_exchange_and_pending_items(self):
        from test_m5_items import ItemsConversation
        for factory,slot,text in [(ExchangeConversation,'exchange','Exchange #TEST1 all items'),
                                  (ExchangeConversation,'exchange','换货订单 #TEST1 全部商品'),
                                  (ExchangeConversation,'exchange','Exchange #TEST1 all items; item item_blue: color red; pay with card_a'),
                                  (ItemsConversation,'items','Change #TEST1 all items'),
                                  (ItemsConversation,'items','修改订单 #TEST1 全部商品'),
                                  (ItemsConversation,'items','Change #TEST1 all items; item item_blue: color red; pay with card_a')]:
            with self.subTest(text=text):
                f=factory(); before=deepcopy(f.api.orders); calls=deepcopy(f.api.calls)
                d=f.user(text)
                self.assertEqual(f.state['history'][-1][slot+'_assessment']['code'],'bulk_replacement_targets_required')
                self.assertIn('each original item',d.text); self.assertEqual(f.api.orders,before)
                self.assertEqual(f.api.calls,calls); self.assertFalse(f.state['proposals'])

    def test_http_409_422_are_failed_once_without_automatic_retry(self):
        for error in ('409','422'):
            with self.subTest(error=error):
                f=ExchangeConversation(); f.api.failure=error; f.start(); f.user('yes')
                self.assertEqual(f.writes()[0]['status'],'failed'); self.assertEqual(f.code(),'write_rejected'); f.user('yes'); self.assertEqual(len(f.posts()),1)

    def test_timeout_after_effect_is_unknown_and_new_version_cannot_repeat(self):
        f=ExchangeConversation(); f.api.failure='timeout'; f.start(); f.user('yes')
        self.assertEqual(f.writes()[0]['status'],'unknown'); self.assertEqual(f.code(),'write_result_unknown')
        f.api.orders['#TEST1']['status']='delivered'; f.api.orders['#TEST1'].pop('exchange',None)
        f.start('color green'); self.assertEqual(f.code(),'write_result_unresolved'); f.user('yes'); self.assertEqual(len(f.posts()),1)

    def test_bad_success_body_never_enters_history_or_proves_completion(self):
        f=ExchangeConversation(); f.api.failure='bad_receipt'; f.start(); f.user('yes')
        self.assertEqual(f.writes()[0]['status'],'unknown'); self.assertNotIn('rejected_private_exchange_body',json.dumps(f.state)); self.assertNotEqual(f.code(),'write_verified')

    def test_missing_wrong_amount_wrong_method_and_wrong_status_receipts_are_unresolved(self):
        for error in ('missing_receipt','wrong_amount','wrong_method','wrong_status'):
            with self.subTest(error=error):
                f=ExchangeConversation(); f.api.failure=error; f.start(); f.user('yes')
                self.assertNotEqual(f.code(),'write_verified'); self.assertEqual(len(f.posts()),1)

    def _two_pairs(self, failure):
        f=ExchangeConversation(); other=deepcopy(f.api.orders['#TEST1']['items'][0]); other['item_id']='item_green'; other['options']['color']='green'; other['price']=10
        f.api.orders['#TEST1']['items'].append(other); f.api.failure=failure
        f.envelope([{'item_id':'item_blue','replacement_item_id':'item_red'},{'item_id':'item_green','replacement_item_id':'item_large'}]); return f

    def test_paired_reordering_is_allowed_without_losing_association(self):
        f=self._two_pairs('sort_pairs'); requested=deepcopy(f.basis()['spec']['parameters']['replacements']); f.user('yes')
        self.assertEqual(f.code(),'write_verified'); self.assertNotEqual(requested,f.api.orders['#TEST1']['exchange']['replacements']); self.assertEqual(f.posts()[0][2]['replacements'],requested)

    def test_independent_old_new_sort_cannot_reassign_original_to_wrong_variant(self):
        f=self._two_pairs('independent_sort'); requested=deepcopy(f.basis()['spec']['parameters']['replacements']); f.user('yes')
        self.assertNotEqual(requested,f.api.orders['#TEST1']['exchange']['replacements'])
        self.assertEqual(f.writes()[0]['status'],'unknown'); self.assertNotEqual(f.code(),'write_verified'); self.assertEqual(len(f.posts()),1)

    def test_independent_sort_single_pair_and_preserved_multi_pair_can_verify(self):
        f=ExchangeConversation(); f.api.failure='independent_sort'; f.start(); f.user('yes')
        self.assertEqual(f.code(),'write_verified'); self.assertEqual(len(f.posts()),1)
        g=self._two_pairs(None)
        g.api.failure='independent_sort'
        g.envelope([{'item_id':'item_green','replacement_item_id':'item_red'},
                    {'item_id':'item_blue','replacement_item_id':'item_large'}])
        requested=deepcopy(g.basis()['spec']['parameters']['replacements']); g.user('yes')
        from collections import Counter
        observed=g.api.orders['#TEST1']['exchange']['replacements']
        self.assertNotEqual(requested,observed)
        self.assertEqual(Counter(tuple(sorted(p.items())) for p in requested),Counter(tuple(sorted(p.items())) for p in observed))
        self.assertEqual(g.code(),'write_verified'); self.assertEqual(len(g.posts()),1)

    def test_receipt_and_strong_readback_pair_order_difference_is_acknowledged_not_verified(self):
        f=self._two_pairs('readback_reorder'); f.user('yes')
        op=f.writes()[0]
        self.assertNotEqual(op['receipt']['exchange']['replacements'],f.api.orders['#TEST1']['exchange']['replacements'])
        self.assertEqual(op['status'],'acknowledged'); self.assertNotEqual(f.code(),'write_verified'); self.assertEqual(len(f.posts()),1)

    def test_identical_repeated_pairs_keep_three_occurrences_in_payload_receipt_and_readback(self):
        f=ExchangeConversation(); f.api.orders['#TEST1']['items']*=3
        f.envelope([{'item_id':'item_blue','replacement_item_id':'item_red'}]*3); f.user('yes')
        pairs=[{'existing_item_id':'item_blue','replacement_item_id':'item_red'}]*3
        self.assertEqual(f.posts()[0][2]['replacements'],pairs)
        self.assertEqual(f.writes()[0]['receipt']['exchange']['replacements'],pairs)
        self.assertEqual(f.api.orders['#TEST1']['exchange']['replacements'],pairs)
        self.assertEqual(f.code(),'write_verified'); self.assertEqual(len(f.posts()),1)

    def test_missing_extra_pair_occurrences_and_strong_readback_mismatch_never_verify(self):
        for error,status in [('missing_pair','unknown'),('extra_pair','unknown'),('wrong_readback','acknowledged')]:
            with self.subTest(error=error):
                f=ExchangeConversation(); f.api.failure=error; f.start(); f.user('yes')
                self.assertEqual(f.writes()[0]['status'],status); self.assertNotEqual(f.code(),'write_verified')

    def test_shared_store_blocks_stale_snapshot_after_toolkit_reconstruction(self):
        claims=SessionClaims(); f=ExchangeConversation(claims=claims); f.start(); d=f.user('yes',consume=False); stale=deepcopy(f.state); f.consume(d)
        f.api.orders['#TEST1']['status']='delivered' # Fault injection excludes the state gate as an explanation.
        f.api.orders['#TEST1'].pop('exchange',None)
        with patch.dict(sys.modules,platform_modules(object())): toolkit=importlib.import_module('tools').Tools(f.api,claims=claims)
        payload=toolkit.exchange_workflow(json.dumps(stale)); self.assertEqual(payload['assessment']['code'],'write_already_claimed'); self.assertEqual(len(f.posts()),1)

    def test_lost_execute_result_preserves_unknown_reservation_and_no_retry(self):
        f=ExchangeConversation(); f.start(); d=f.user('yes',consume=False); call=d.calls[0]; getattr(f.toolkit,call.name)(**call.arguments)
        _,f.state=advance(TurnInput('tools',outcomes=()),f.state); self.assertEqual(f.code(),'exchange_workflow_unresolved'); self.assertEqual(f.state['exchange_pending']['status'],'unknown')
        f.user('yes'); self.assertEqual(len(f.posts()),1)

    def test_lost_prepare_can_retry_and_late_result_cannot_pollute_new_batch(self):
        f=ExchangeConversation(); old=f.start(consume=False); call=old.calls[0]; payload=f.toolkit.exchange_workflow(**call.arguments)
        _,f.state=advance(TurnInput('tools',outcomes=()),f.state); self.assertEqual(f.code(),'exchange_prepare_abandoned')
        new=f.user('retry',consume=False); before=deepcopy(f.state); _,f.state=advance(TurnInput('tools',outcomes=(ToolOutcome(call.id,json.dumps(payload)),)),f.state)
        self.assertEqual(f.state['history'],before['history']); self.assertEqual(f.state['exchange_pending'],before['exchange_pending'])
        self.assertEqual(f.state['proposals'],before['proposals']); f.consume(new); self.assertEqual(f.code(),'exchange_confirmation_required'); self.assertFalse(f.posts())

    def test_handoff_after_unknown_does_not_clear_exchange_or_enable_model(self):
        from support_agent.model_context import project_messages
        f=ExchangeConversation(); f.api.failure='timeout'; f.start(); f.user('yes'); before=deepcopy(f.writes()); f.user('transfer me to a human',consume=False)
        self.assertEqual(f.writes(),before)
        with self.assertRaises(ValueError): project_messages(f.state)
        f.user('yes'); self.assertEqual(len(f.posts()),1)

    def test_preparation_profile_order_product_failures_have_distinct_codes(self):
        for path,code in [('/customers/','exchange_profile_read_failed'),('/orders/','exchange_order_read_failed'),('/products/','exchange_product_read_failed')]:
            with self.subTest(path=path):
                f=ExchangeConversation(); f.api.read_failure=path; f.start(); self.assertEqual(f.code(),code); self.assertFalse(f.posts())

    def test_preparation_budget_refuses_before_any_read_and_product_budget_never_splits(self):
        f=ExchangeConversation(); f.start(consume=False); state=deepcopy(f.state); state['tool_calls_since_user']=11; before=deepcopy(f.api.calls)
        _,state=_prepare(state,f.api); self.assertEqual(state['history'][-1]['exchange_assessment']['code'],'exchange_read_budget_exceeded'); self.assertEqual(f.api.calls,before)
        g=ExchangeConversation(); g.start(consume=False); state=deepcopy(g.state); state['tool_calls_since_user']=10; _,state=_prepare(state,g.api)
        self.assertEqual(state['history'][-1]['exchange_assessment']['code'],'exchange_read_budget_exceeded'); self.assertFalse(any('/products/' in c[1] for c in g.api.calls)); self.assertFalse(g.posts())

    def test_full_recap_over_budget_is_refused_not_truncated_or_split(self):
        f=ExchangeConversation(); f.api.orders['#TEST1']['items'][0]['name']='x'*4200; before=deepcopy(f.api.orders['#TEST1']); f.start()
        self.assertEqual(f.code(),'exchange_recap_budget_exceeded'); self.assertFalse(f.state['proposals']); self.assertFalse(f.writes()); f.user('yes'); self.assertFalse(f.posts()); self.assertEqual(f.api.orders['#TEST1'],before)

    def test_tool_argument_budget_blocks_before_read_claim_or_send(self):
        f=ExchangeConversation(); before=deepcopy(f.api.calls)
        with self.assertRaises(ValueError): f.toolkit.exchange_workflow('x'*(256*1024+1))
        self.assertEqual(f.api.calls,before); self.assertFalse(f.toolkit._workflow_claims.sessions)

    def test_prepare_and_runtime_exceptions_are_controlled_without_writes(self):
        f=ExchangeConversation()
        with patch('support_agent.items_session._safe_read',side_effect=RuntimeError('private')): f.start()
        self.assertEqual(f.code(),'exchange_preparation_failed'); self.assertFalse(f.posts())
        g=ExchangeConversation(); g.start()
        with patch('support_agent.items_session.ItemsRuntime',side_effect=ValueError('private')): g.user('yes')
        self.assertEqual(g.code(),'exchange_runtime_unavailable'); self.assertFalse(g.posts())

    def test_post_send_result_overflow_stays_unknown_not_zero_or_retryable(self):
        f=ExchangeConversation(); f.start(); d=f.user('yes',consume=False); call=d.calls[0]
        with patch('support_agent.items_session.MAX_WORKFLOW_RESULT_BYTES',100):
            with self.assertRaises(WorkflowResultTooLarge): f.toolkit.exchange_workflow(**call.arguments)
        _,f.state=advance(TurnInput('tools',outcomes=()),f.state); self.assertEqual(f.code(),'exchange_workflow_unresolved'); f.user('yes'); self.assertEqual(len(f.posts()),1)


class ExchangeRecoveryTests(unittest.TestCase):
    def test_original_schema11_fixture_migrates_without_exchange_consent(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/m5_schema11_state.json').read_text(encoding='utf-8')); old=fixture['state']
        self.assertEqual(old['schema_version'],11); self.assertNotIn('exchange_pending',old)
        migrated=clone_state(old); self.assertEqual(migrated['schema_version'],SCHEMA_VERSION); self.assertIsNone(migrated['exchange_pending'])
        self.assertEqual(migrated['history'],old['history']); self.assertTrue(all(p['spec']['action']!='exchange' for p in migrated['proposals']))

    def test_legacy_versions_reject_exchange_metadata_and_pending(self):
        f=ExchangeConversation(); f.start()
        for version in range(1,12):
            with self.subTest(version=version):
                state=deepcopy(f.state); state['schema_version']=version
                with self.assertRaises(InvalidState): clone_state(state)
        old=json.loads((Path(__file__).parent/'fixtures/m5_schema11_state.json').read_text(encoding='utf-8'))['state']; old['exchange_pending']={'status':'pending'}
        with self.assertRaises(InvalidState): clone_state(old)

    def test_restore_completed_sources_spec_identity_and_journal(self):
        f=ExchangeConversation(); f.start(); f.user('yes'); restored=initial_state(f.state['history'])
        for key in ('history','identity_evidence','proposals','tasks','operations','exchange_pending'): self.assertEqual(restored[key],f.state[key])
        self.assertEqual(clone_state(f.state),f.state)

    def test_basis_source_criteria_price_and_selected_variant_tampering_rejected(self):
        for field in ('source','criteria','price','variant'):
            with self.subTest(field=field):
                f=ExchangeConversation(); f.start(); state=deepcopy(f.state); basis=next(e['exchange_basis'] for e in state['history'] if 'exchange_basis' in e)
                if field=='source': basis['sources'][0]['history_index']+=1
                if field=='criteria': basis['sources'][0]['criteria']['hard'][0]['value']='green'
                if field=='price': basis['prices'][0]['original_price']=99
                if field=='variant': basis['spec']['parameters']['replacements'][0]['replacement_item_id']='item_green'
                with self.assertRaises(InvalidState): clone_state(state)
                with self.assertRaises(InvalidState): initial_state(state['history'])

    def test_future_user_or_catalog_cannot_repair_prior_basis(self):
        f=ExchangeConversation(); f.start(); state=deepcopy(f.state); entry=next(e for e in state['history'] if 'exchange_basis' in e); entry['exchange_basis']['sources'][0]['user_text']='new future claim'
        state['history'].append({'role':'user','content':'new future claim'})
        with self.assertRaises(InvalidState): clone_state(state)

    def test_real_model_tool_shape_and_binding_reject_every_internal_name(self):
        f=ExchangeConversation()
        for name in WORKFLOW_TOOL_NAMES:
            with self.subTest(name=name):
                with self.assertRaisesRegex(InvalidAction,'business workflow'): decision_from_candidate({'type':'tool','name':name,'arguments':{'session_json':json.dumps(f.state)}},call_id='model')
                with self.assertRaises(InvalidAction): bind_arguments(name,{'session_json':json.dumps(f.state)},f.state)
        args=bind_arguments('list_products',{},f.state)
        self.assertEqual(decision_from_candidate({'type':'tool','name':'list_products','arguments':args},call_id='positive').calls[0].name,'list_products')

    def test_mixed_exchange_cancel_keeps_existing_cancellation_conflict_diagnostic(self):
        f=ExchangeConversation(); f.user('Cancel and exchange order #TEST1 items')
        self.assertEqual(f.state['history'][-1]['cancellation_assessment']['code'],'mixed_business_request'); self.assertFalse(f.posts())
