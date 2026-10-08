"""Production factory + actual SDK dispatch, with an offline scripted gateway.

These tests verify integration and authorization boundaries, not real-model
language quality. Original user utterances are retained without rewriting.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
sys.path.insert(0, str(ROOT / 'agent'))
from support_agent.semantics import annotate, validate_candidate
from support_agent.protocol import InvalidAction
from support_agent.state import initial_state, clone_state, InvalidState


def candidate(action, arguments=None, identity=None, message=''):
    return dict(action=action, arguments=arguments or {}, identity=identity or {}, sources=[], message=message)


class SemanticCandidateTests(unittest.TestCase):
    def test_original_name_postal_sources_are_not_fixed_phrase_parser(self):
        text = "I'm Amira Caldwell, and my zip code is 70168."
        history = [{'role': 'user', 'content': text}]
        result = candidate('clarify', identity=dict(first_name='Amira', last_name='Caldwell', postal_code='70168'))
        result['sources'] = [{'index': 0, 'quote': text}]
        annotate(history, 0, result)
        state = initial_state(history)
        self.assertEqual(state['verification_draft'], result['identity'])
        self.assertEqual(state['history'][0]['content'], text)

    def test_assistant_and_tool_content_cannot_supply_user_authority(self):
        for role in ('assistant', 'tool'):
            history = [{'role': role, 'content': 'Amira Caldwell 70168'}, {'role': 'user', 'content': 'hello'}]
            result = candidate('clarify', identity={'first_name': 'Amira'})
            result['sources'] = [{'index': 0, 'quote': 'Amira'}]
            with self.assertRaises(InvalidAction):
                validate_candidate(result, history, 1)

    def test_invented_identity_or_nonexact_source_is_rejected(self):
        history = [{'role': 'user', 'content': 'My postal code is 70168.'}]
        result = candidate('clarify', identity={'first_name': 'Amira'})
        result['sources'] = [{'index': 0, 'quote': history[0]['content']}]
        with self.assertRaises(InvalidAction):
            validate_candidate(result, history, 0)
        result['identity'] = {}
        result['sources'][0]['quote'] = '70169'
        with self.assertRaises(InvalidAction):
            validate_candidate(result, history, 0)

    def test_privilege_fields_and_internal_write_tool_names_are_rejected(self):
        history = [{'role': 'user', 'content': 'please help'}]
        result = candidate('read', {'name': 'exchange_workflow', 'arguments': {}})
        result['sources'] = [{'index': 0, 'quote': 'please help'}]
        with self.assertRaises(InvalidAction):
            validate_candidate(result, history, 0)
        result = candidate('respond', message='hello')
        result['verified'] = True
        with self.assertRaises(InvalidAction):
            validate_candidate(result, history, 0)

    def test_consent_cannot_reuse_previous_user_quote_or_follow_a_tool_result(self):
        history = [{'role': 'user', 'content': 'yes'}, {'role': 'user', 'content': 'not yet'}]
        result = candidate('consent', {'assignments': [{'version': 1, 'decision': 'confirm'}]})
        result['sources'] = [{'index': 0, 'quote': 'yes'}]
        with self.assertRaises(InvalidAction):
            validate_candidate(result, history, 1)
        result['sources'] = [{'index': 1, 'quote': 'not yet'}]
        with self.assertRaises(InvalidAction):
            validate_candidate(result, history, 1, allow_consent=False)
        result = candidate('handoff')
        result['sources'] = [{'index': 1, 'quote': 'not yet'}]
        with self.assertRaises(InvalidAction):
            validate_candidate(result, history, 1, allow_consent=False)
        result['sources'] = [{'index': 0, 'quote': 'yes'}]
        with self.assertRaises(InvalidAction):
            validate_candidate(result, history, 1)

    def test_changed_original_text_invalidates_interpretation(self):
        history = [{'role': 'user', 'content': 'My email is a@example.test'}]
        result = candidate('clarify', identity={'email': 'a@example.test'})
        result['sources'] = [{'index': 0, 'quote': history[0]['content']}]
        annotate(history, 0, result)
        state = initial_state(history)
        state['history'][0]['content'] = 'Different original user text'
        with self.assertRaises(InvalidState):
            clone_state(state)


class NativeSemanticTests(unittest.TestCase):
    def make_flow(self, *, delivered=False):
        from tau2.environment.environment import Environment
        from tau2.hyper.client_api import ClientAPI, ClientAPIContext, ClientAPIToolKitBase
        from tau2.hyper.agent_context import build_agent_context, activate_agent_context
        from tau2.hyper.sandbox.candidate_server import _find_subclass
        from loguru import logger
        logger.disable('tau2.environment.environment')
        from test_m5_matrix import MatrixBackend
        import agent
        import tools
        backend = MatrixBackend()
        if delivered:
            backend.orders['#TEST1']['status'] = 'delivered'
        def transport(value):
            response = backend.request(value['method'], value['path'], body=value.get('body'))
            return {'status_code': response.status_code, 'body': response.body, 'headers': {}, 'elapsed_seconds': 0}
        cls = _find_subclass(tools, ClientAPIToolKitBase)
        self.assertIs(cls, tools.Tools)
        toolkit = cls(ClientAPI(transport, context=ClientAPIContext(conversation_id='m7-semantic-test')))
        context = build_agent_context(domain='retail_plus', tools=list(toolkit.get_tools().values()),
                 resource_root=ROOT / 'agent', model_configs=[{'model': 'openai/enterprise-haiku'}])
        with activate_agent_context(context):
            application = agent.create_agent()
        flow = dict(backend=backend, toolkit=toolkit, context=context, application=application,
                    environment=Environment('retail_plus', '', toolkit), state=application.get_init_state(), responses=[], calls=0)
        def generate(**kwargs):
            from tau2.data_model.message import AssistantMessage
            flow['calls'] += 1
            if not flow['responses']:
                raise AssertionError('Unexpected model call')
            output = deepcopy(flow['responses'].pop(0))
            host = json.loads(kwargs['messages'][-1].content.split('\n', 1)[1])
            if isinstance(output, dict):
                if not output['sources']:
                    source = host['user_sources'][-1]
                    output['sources'] = [{'index': source['index'], 'quote': source['text']}]
                output = json.dumps(output)
            return AssistantMessage(role='assistant', content=output)
        flow['generate'] = generate
        return flow

    def turn(self, flow, text, responses):
        from tau2.data_model.message import UserMessage, MultiToolMessage
        flow['responses'].extend(responses)
        with patch.object(type(flow['context'].model_gateway), 'generate', side_effect=flow['generate']):
            message, state = flow['application'].generate_next_message(UserMessage(role='user', content=text), flow['state'])
            for _ in range(12):
                if not message.tool_calls:
                    break
                results = [flow['environment'].get_response(call) for call in message.tool_calls]
                self.assertTrue(all(not result.error for result in results))
                message, state = flow['application'].generate_next_message(MultiToolMessage(role='tool', tool_messages=results), state)
            else:
                self.fail('Unbounded dispatch loop')
        self.assertFalse(flow['responses'], 'Planned semantic stages were not consumed')
        flow['state'] = clone_state(state)
        self.assertNotIn('session_block', state)
        return message

    def identify(self, flow):
        self.turn(flow, 'My email is a@example.test', [candidate('clarify', identity={'email': 'a@example.test'}),
                  candidate('respond', message='How can I help with your order?')])
        self.assertTrue(flow['state']['identity']['verified'])

    def prepare_exchange(self, flow):
        self.identify(flow)
        args = {'order_id': '#TEST1', 'replacements': [{'item_id': 'item_blue', 'options': {'color': 'red'}}],
                'payment_method_id': 'card_a'}
        text = 'I want to exchange my mug for a red one of the same capacity, order #TEST1. Use my Mastercard.'
        self.turn(flow, text, [candidate('read', {'name': 'get_order', 'arguments': {'order_id': '#TEST1'}}),
                  candidate('read', {'name': 'get_product', 'arguments': {'product_id': 'product_mug'}}),
                  candidate('exchange', args)])
        from support_agent.proposals import _current_records
        return _current_records(flow['state'])[0]['version']

    def posts(self, flow):
        return [(m, p, b) for m, p, b in flow['backend'].calls if m in {'POST', 'PUT'} and not p.endswith('/search')]

    def test_factory_enables_model_and_real_sdk_keeps_scalar_types(self):
        flow = self.make_flow()
        from support_agent.adapters.semantic_model import SemanticAdapter
        self.assertIsInstance(flow['application'].model_adapter, SemanticAdapter)
        self.identify(flow)
        self.turn(flow, 'Please show order #TEST1', [candidate('read', {'name': 'get_order', 'arguments': {'order_id': '#TEST1'}}),
                  candidate('respond', message='Your order is pending.')])
        self.assertGreater(flow['calls'], 0)
        order_result = next(json.loads(e['content']) for e in flow['state']['history'] if e['role'] == 'tool'
                            and '"items"' in e['content'])
        self.assertIsInstance(order_result['items'][0]['price'], (int, float))

    def test_natural_exchange_and_nonwhitelisted_assent_send_once(self):
        flow = self.make_flow(delivered=True)
        version = self.prepare_exchange(flow)
        self.turn(flow, "Yep, that's exactly what I want. Please go ahead.",
                  [candidate('consent', {'assignments': [{'version': version, 'decision': 'confirm'}]})])
        self.assertEqual(len(self.posts(flow)), 1)
        self.assertEqual(flow['backend'].orders['#TEST1']['status'], 'exchange requested')
        restored = flow['application'].get_init_state(flow['state']['history'])
        self.assertNotIn('session_block', restored)
        self.assertEqual(restored['operations'], flow['state']['operations'])

    def test_added_condition_never_becomes_confirmation(self):
        flow = self.make_flow(delivered=True)
        version = self.prepare_exchange(flow)
        self.turn(flow, 'Yes, but only if shipping is free.',
                  [candidate('consent', {'assignments': [{'version': version, 'decision': 'condition'}]})])
        self.assertEqual(self.posts(flow), [])
        self.assertEqual(flow['state']['proposals'][-1]['status'], 'needs_review')

    def test_old_version_cannot_be_confirmed_by_new_user(self):
        flow = self.make_flow(delivered=True)
        version = self.prepare_exchange(flow)
        self.turn(flow, 'Please proceed.', [candidate('consent', {'assignments': [{'version': version + 1, 'decision': 'confirm'}]})])
        self.assertEqual(self.posts(flow), [])

    def test_foreign_order_is_blocked_before_order_api(self):
        flow = self.make_flow()
        self.identify(flow)
        self.turn(flow, 'Show another order', [candidate('read', {'name': 'get_order', 'arguments': {'order_id': '#FOREIGN'}})])
        self.assertFalse(any('#FOREIGN' in p or '%23FOREIGN' in p for _, p, _ in flow['backend'].calls))

    def test_malformed_model_candidate_is_refused_not_regex_fallback(self):
        flow = self.make_flow()
        reply = self.turn(flow, 'a@example.test', ['not JSON'])
        self.assertFalse(flow['state']['identity']['verified'])
        self.assertEqual(flow['backend'].calls, [])
        self.assertIn('unavailable', reply.content)

    def test_failed_model_on_literal_yes_cannot_leave_legacy_consent_in_live_or_restored_state(self):
        flow = self.make_flow(delivered=True)
        self.prepare_exchange(flow)
        self.turn(flow, 'yes', ['not JSON'])
        self.assertEqual(self.posts(flow), [])
        self.assertFalse(any(p['status']=='confirmed' for p in flow['state']['proposals']))
        restored = flow['application'].get_init_state(flow['state']['history'])
        self.assertNotIn('session_block', restored)
        self.assertFalse(any(p['status']=='confirmed' for p in restored['proposals']))

    def test_screenshot_name_and_postal_reach_independent_backend_verification(self):
        flow = self.make_flow()
        flow['backend'].customers['customer_a']['name'] = {'first_name': 'Amira', 'last_name': 'Caldwell'}
        flow['backend'].customers['customer_a']['default_shipping_address']['postal_code'] = '70168'
        text = "I'm Amira Caldwell, and my zip code is 70168. I'm afraid I don't remember my email address."
        fields = {'first_name': 'Amira', 'last_name': 'Caldwell', 'postal_code': '70168'}
        self.turn(flow, text, [candidate('clarify', identity=fields), candidate('respond', message='Your account is verified.')])
        self.assertTrue(flow['state']['identity']['verified'])
        self.assertEqual(flow['state']['identity_evidence']['inputs']['first_name'], 'Amira')
        self.assertEqual(flow['state']['history'][0]['content'], text)
        restored = flow['application'].get_init_state(flow['state']['history'])
        self.assertEqual(restored['identity_evidence'], flow['state']['identity_evidence'])

    def test_partial_identity_accumulates_across_turns(self):
        flow = self.make_flow()
        self.turn(flow, "I'm Ada Example", [candidate('clarify', identity={'first_name': 'Ada', 'last_name': 'Example'}, message='What is your postal code?')])
        self.assertFalse(flow['state']['identity']['verified'])
        self.turn(flow, '90001 is my zip', [candidate('clarify', identity={'postal_code': '90001'}),
                  candidate('respond', message='I found your account.')])
        self.assertTrue(flow['state']['identity']['verified'])

    def test_other_business_planners_use_typed_meaning_and_actual_sdk_returns(self):
        rows = [
            ('items', 'Please make the mug red, keeping its capacity, and use Mastercard.',
             {'order_id': '#TEST1', 'replacements': [{'item_id': 'item_blue', 'options': {'color': 'red'}}], 'payment_method_id': 'card_a'}, '/item-modifications'),
            ('returns', 'I would like to return the mug and refund to the original method.',
             {'order_id': '#TEST1', 'item_ids': ['item_blue'], 'all_items': False, 'destination': {'kind': 'original'}}, '/returns'),
            ('payment', 'Switch to PayPal for this order.',
             {'order_id': '#TEST1', 'selection': {'query': 'paypal_a', 'fallback': None, 'exact': True}}, '/payment-method'),
            ('cancellation', 'Please cancel the entire order because I accidentally placed it.',
             {'order_id': '#TEST1', 'reason': 'ordered by mistake', 'scope': 'whole_order', 'conditional': False, 'original_refunds': True}, '/cancellations'),
            ('address', 'Ship it to 123 Main St, Springfield, IL 62704, US.',
             {'order_ids': ['#TEST1'], 'default': False, 'all_orders': False, 'source': {'kind': 'record'},
              'fields': {'address_line_1': '123 Main St', 'city': 'Springfield', 'region': 'IL', 'postal_code': '62704', 'country': 'US'}, 'full': True}, '/shipping-address'),
        ]
        from support_agent.proposals import _current_records
        for action, text, args, endpoint in rows:
            with self.subTest(action=action):
                flow = self.make_flow(delivered=action == 'returns')
                self.identify(flow)
                self.turn(flow, text, [candidate(action, args)])
                records = _current_records(flow['state'])
                self.assertEqual(len(records), 1)
                self.turn(flow, "That sounds good, let's do it.", [candidate('consent', {'assignments': [{'version': records[0]['version'], 'decision': 'confirm'}]})])
                writes = self.posts(flow)
                self.assertEqual(len(writes), 1)
                self.assertTrue(writes[0][1].endswith(endpoint), writes)
                restored = flow['application'].get_init_state(flow['state']['history'])
                self.assertNotIn('session_block', restored)
                self.assertEqual(restored['operations'], flow['state']['operations'])

    def test_partial_cancellation_is_not_promoted_to_whole_order(self):
        flow = self.make_flow()
        self.identify(flow)
        args = {'order_id': '#TEST1', 'reason': 'ordered by mistake', 'scope': 'partial',
                'conditional': False, 'original_refunds': True}
        reply = self.turn(flow, 'Cancel just the mug, keeping everything else.', [candidate('cancellation', args)])
        self.assertEqual(self.posts(flow), [])
        self.assertEqual(flow['state']['proposals'], [])
        self.assertEqual(flow['state']['history'][-1]['cancellation_assessment']['code'], 'cancellation_whole_order_required')

    def test_return_destination_correction_cannot_move_opening_to_accept_a_late_gift_card(self):
        flow = self.make_flow(delivered=True)
        self.identify(flow)
        args = {'order_id': '#TEST1', 'item_ids': ['item_blue'], 'all_items': False, 'destination': {'kind': 'original'}}
        self.turn(flow, 'Please return the mug and refund the original method.', [candidate('returns', args)])
        from support_agent.domain.returns_intake import request_from_history
        opening = request_from_history(flow['state']['history'])['opening_request_index']
        flow['backend'].customers['customer_a']['payment_methods'].append({'id':'late_gift','source':'gift_card','balance':0})
        self.turn(flow, 'Please refresh my saved payment methods.',
                  [candidate('read', {'name':'read_customer_profile','arguments':{}}), candidate('respond', message='The saved methods were refreshed.')])
        args['destination'] = {'kind':'saved','query':'late_gift','exact':True}
        self.turn(flow, 'For that return, refund to the gift card I just added.', [candidate('returns', args)])
        self.assertEqual(request_from_history(flow['state']['history'])['opening_request_index'], opening)
        self.assertEqual(flow['state']['history'][-1]['returns_assessment']['code'], 'gift_card_not_eligible_at_opening')
        self.assertEqual(self.posts(flow), [])

    def test_supervisor_request_transfers_without_identity_lookup(self):
        flow = self.make_flow()
        reply = self.turn(flow, 'Could you get a supervisor to help me with this?', [candidate('handoff')])
        self.assertEqual(len(self.posts(flow)), 1)
        self.assertTrue(self.posts(flow)[0][1].endswith('/transfers'))
        self.assertEqual(flow['state']['handoff']['status'], 'accepted')
        self.assertFalse(flow['state']['identity']['verified'])
        restored = flow['application'].get_init_state(flow['state']['history'])
        self.assertEqual(restored['handoff'], flow['state']['handoff'])

    def test_model_after_read_cannot_create_human_transfer_permission(self):
        flow = self.make_flow()
        self.identify(flow)
        self.turn(flow, 'Please show my order.',
                  [candidate('read', {'name':'get_order','arguments':{'order_id':'#TEST1'}}), candidate('handoff')])
        self.assertEqual(self.posts(flow), [])
        self.assertEqual(flow['state']['handoff']['status'], 'not_requested')

    def test_every_read_uses_real_sdk_return_consumption(self):
        flow = self.make_flow()
        self.identify(flow)
        rows = [('read_customer_profile', {}), ('list_customer_orders', {'status': ''}),
                ('get_order', {'order_id': '#TEST1'}), ('get_product', {'product_id': 'product_mug'}),
                ('get_item', {'item_id': 'item_blue'}), ('list_products', {})]
        for name, args in rows:
            with self.subTest(name=name):
                self.turn(flow, 'Please check my records.', [candidate('read', {'name': name, 'arguments': args}),
                          candidate('respond', message='The requested records were read.')])
                self.assertNotIn('session_block', flow['state'])

    def test_amount_summary_is_computed_by_host_without_model_totals(self):
        flow = self.make_flow()
        self.identify(flow)
        before = flow['calls']
        reply = self.turn(flow, 'Could you summarize the amounts for my order?',
                          [candidate('summary', {'order_ids': ['#TEST1']})])
        self.assertEqual(flow['calls'], before + 1)
        self.assertIn('unknown', reply.content)
        self.assertEqual(self.posts(flow), [])

    def test_selected_item_analysis_uses_host_math_and_creates_no_proposal(self):
        flow = self.make_flow(delivered=True)
        self.identify(flow)
        reply = self.turn(flow, 'What could I get back if I returned my mug?',
                          [candidate('analysis', {'order_id': '#TEST1', 'item_ids': ['item_blue'], 'replacements': []})])
        self.assertIn('potential_refund_estimate', reply.content)
        self.assertEqual(flow['state']['proposals'], [])
        self.assertEqual(flow['state']['tasks'], [])
        self.assertEqual(self.posts(flow), [])

    def test_correction_creates_new_recap_and_old_consent_does_not_write(self):
        flow = self.make_flow(delivered=True)
        old = self.prepare_exchange(flow)
        args = {'order_id': '#TEST1', 'replacements': [{'item_id': 'item_blue', 'options': {'color': 'black'}}],
                'payment_method_id': 'card_a'}
        # Add an available variant as a fixed backend input before the correction.
        item = deepcopy(flow['backend'].products['product_mug']['items'][0])
        item.update(item_id='item_black'); item['options']['color']='black'
        flow['backend'].products['product_mug']['items'].append(item)
        self.turn(flow, 'Actually make it black instead, keeping the same capacity and payment method.',
                  [candidate('exchange', args)])
        from support_agent.proposals import _current_records
        current = _current_records(flow['state'])[0]
        self.assertNotEqual(current['version'], old)
        self.assertEqual(current['status'], 'proposed')
        self.turn(flow, 'Proceed with the previous quote.',
                  [candidate('consent', {'assignments': [{'version': old, 'decision': 'confirm'}]})])
        self.assertEqual(self.posts(flow), [])

    def test_fresh_factory_and_toolkit_restore_do_not_repeat_completed_write(self):
        flow = self.make_flow(delivered=True)
        version = self.prepare_exchange(flow)
        self.turn(flow, 'Please go ahead.', [candidate('consent', {'assignments': [{'version': version, 'decision': 'confirm'}]})])
        from tau2.hyper.agent_context import activate_agent_context
        from tau2.environment.environment import Environment
        import agent
        restored = flow['application'].get_init_state(deepcopy(flow['state']['history']))
        with activate_agent_context(flow['context']):
            flow['application'] = agent.create_agent()
        flow['toolkit'] = type(flow['toolkit'])(flow['toolkit'].client_api, claims=flow['toolkit']._workflow_claims)
        flow['environment'] = Environment('retail_plus', '', flow['toolkit'])
        flow['state'] = restored
        self.turn(flow, 'Proceed again.', [candidate('consent', {'assignments': [{'version': version, 'decision': 'confirm'}]})])
        self.assertEqual(len(self.posts(flow)), 1)

    def test_missing_runtime_model_refuses_without_identity_regex_fallback(self):
        import agent
        from tau2.hyper.agent_context import activate_agent_context
        from dataclasses import replace
        flow = self.make_flow()
        # Native SDK normally requires a configured model. This explicit host
        # fault must fail closed, rather than enabling the old phrase parser.
        context = replace(flow['context'], model_gateway=None)
        with activate_agent_context(context):
            application = agent.create_agent()
        from tau2.data_model.message import UserMessage
        message, state = application.generate_next_message(UserMessage(role='user', content='a@example.test'), application.get_init_state())
        self.assertFalse(message.tool_calls)
        self.assertFalse(state['identity']['verified'])
        self.assertIn('unavailable', message.content)

    def test_lost_execute_result_does_not_delegate_retry_or_accept_late_result(self):
        from tau2.data_model.message import UserMessage, MultiToolMessage
        flow = self.make_flow(delivered=True)
        version = self.prepare_exchange(flow)
        flow['responses'].append(candidate('consent', {'assignments': [{'version': version, 'decision': 'confirm'}]}))
        with patch.object(type(flow['context'].model_gateway), 'generate', side_effect=flow['generate']):
            message, state = flow['application'].generate_next_message(UserMessage(role='user', content='Go ahead please.'), flow['state'])
        self.assertEqual(len(message.tool_calls), 1)
        late = flow['environment'].get_response(message.tool_calls[0])
        flow['state'] = state  # Deliberately lose the execution result.
        before = flow['calls']
        self.turn(flow, 'Please try again, or check the order.', [])
        self.assertEqual(flow['calls'], before)
        self.assertEqual(flow['state']['exchange_pending']['status'], 'unknown')
        message, state = flow['application'].generate_next_message(MultiToolMessage(role='tool', tool_messages=[late]), flow['state'])
        self.assertEqual(state['exchange_pending']['status'], 'unknown')
        self.assertEqual(len(self.posts(flow)), 1)

    def test_lost_read_can_start_new_request_without_inventing_old_read_success(self):
        from tau2.data_model.message import UserMessage
        flow = self.make_flow()
        self.identify(flow)
        intent = candidate('read', {'name': 'get_order', 'arguments': {'order_id': '#TEST1'}})
        flow['responses'].append(intent)
        with patch.object(type(flow['context'].model_gateway), 'generate', side_effect=flow['generate']):
            message, state = flow['application'].generate_next_message(UserMessage(role='user', content='Please show my order.'), flow['state'])
        self.assertEqual(len(message.tool_calls), 1)
        flow['state'] = state  # Lose a READ result, not a mutating execution.
        self.turn(flow, 'Please read the order again.', [intent, candidate('respond', message='The fresh order was read.')])
        old = next(o for o in flow['state']['operations'] if o['call_id']==message.tool_calls[0].id)
        self.assertEqual(old['status'], 'unknown')
        self.assertEqual(self.posts(flow), [])

    def test_duplicate_read_result_is_not_model_authority_or_a_permanent_dialogue_block(self):
        from tau2.data_model.message import ToolMessage, MultiToolMessage
        flow = self.make_flow()
        self.identify(flow)
        result = next(e for e in reversed(flow['state']['history']) if e['role']=='tool')
        duplicate = ToolMessage(role='tool', id=result['id'], content=result['content'], error=False)
        _, flow['state'] = flow['application'].generate_next_message(MultiToolMessage(role='tool', tool_messages=[duplicate]), flow['state'])
        self.turn(flow, 'Thank you.', [candidate('respond', message='You are welcome.')])
        self.assertTrue(flow['state']['identity']['verified'])
        self.assertEqual(self.posts(flow), [])


if __name__ == '__main__':
    network_attempts = []
    def network_audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            network_attempts.append(event)
            raise RuntimeError('Offline semantic worker forbids network')
    sys.addaudithook(network_audit)
    result = unittest.main(exit=False)
    if network_attempts:
        print('Offline network audit failed; attempts:', len(network_attempts))
        sys.exit(1)
    print('network_attempts:0 real_model_calls:0 (scripted gateway only)')
    sys.exit(0 if result.result.wasSuccessful() else 1)
