"""Native M6.7 preserved rule-port dialogue runner; no model or network.

Reuse the SDK harness, not its existing AT associations. New fixed business
fixtures and their direct assertions are validated independently.
"""
import sdk_m6_checks as native  # Installs network guard before SDK import.
import argparse
from copy import deepcopy
import json
from urllib.parse import unquote
from business_acceptance import load_manifest, metadata, validate_batch, verify_business_scenario, SCOPE
from support_agent.workflow_registry import WORKFLOW_KINDS


class BusinessBackend(native.MatrixBackend):
    """Local backend model: gift effects follow actually appended payment rows.

    Pending modifications/cancellations can change stored gift balances.
    Return/exchange applications do not thereby prove a refund or settlement.
    This is synthetic state, never an observation of a payment processor.
    """
    def request(self, method, path, body=None):
        order_id = unquote(path.split('/')[-2]) if method == 'POST' and path.endswith(('/item-modifications', '/cancellations')) else None
        before = len(self.orders[order_id]['payments']) if order_id else 0
        response = super().request(method, path, body)
        if order_id and response.status_code == 200:
            order = self.orders[order_id]
            methods = {m['id']: m for m in self.customers[order['customer_id']]['payment_methods']}
            for row in order['payments'][before:]:
                instrument = methods[row['payment_method_id']]
                if instrument['source'] == 'gift_card':
                    instrument['balance'] += row['amount'] * (1 if row['transaction_type'] == 'refund' else -1)
        return response


def execute(scenario):
    evidence = []
    def observe(event, message, state, toolkit, backend):
        if event != 'reply':
            return
        basis = {kind: next((deepcopy(e[kind + '_basis']) for e in reversed(state['history'])
                             if kind + '_basis' in e), None) for kind in ('items', 'returns', 'exchange')}
        evidence.append({'basis': basis, 'identity': deepcopy(state['identity']),
                         'user_sources':[{'history_index':i,'text':e['content']} for i,e in enumerate(state['history']) if e['role']=='user'],
                         'task_requests':[{'action':t['action'],'target':deepcopy(t['target'])} for t in state['tasks']],
                         'workflow_diagnostics':[{'workflow':kind,'code':e[kind+'_assessment']['code']} for e in state['history']
                                                 for kind in WORKFLOW_KINDS if kind+'_assessment' in e],
                         'operations': deepcopy(state['operations']),
                         'business_operations': deepcopy([o for o in state['operations'] if o['mutates']])})
    def verify(s, r):
        verify_business_scenario(s, {**r, 'evidence':evidence})
    result = native.execute(scenario, observer=observe, backend_factory=BusinessBackend, verifier=verify)
    result['evidence'] = evidence
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-run-id', required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    parent = {'run_id': args.parent_run_id, 'source_sha256': args.source_sha256}
    manifest = load_manifest()
    value = {'scope': SCOPE, 'execution': metadata(parent), 'network_attempts': 0,
             'results': [execute(s) for s in manifest['dialogues']['scenarios']]}
    value['network_attempts'] = len(native.network_attempts)
    validate_batch(value, manifest, parent)
    print('M6_BUSINESS_JSON=' + json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    print('M6_BUSINESS_CHECK_PASSED; native rule-port turns and direct local atomic assertions; network attempts 0')
