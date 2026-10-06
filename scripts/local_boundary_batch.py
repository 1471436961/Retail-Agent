"""Fixed M6.4 native fault matrix; observations never become business ATs."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNNER='tests/sdk_m6_boundary_checks.py'
WRAPPER='test_m6_boundaries.NativeBoundaryTests.test_sdk_receipts_and_model_adapter_with_fake_gateway'
SCOPE='real SDK boundaries with synthetic effects; not classroom or complete business AT execution'
CASES=(('order_address','address','shipping_address'),('default_address','address','default_shipping_address'),
       ('whole_gift_payment','payment','payment_method'),('whole_cancellation','cancellation','cancel'),
       ('complete_items','items','modify_items'),('complete_return','returns','return'),
       ('complete_exchange','exchange','exchange'),('human','handoff','handoff'))
MODES=('valid','list_body','authority_fields','wrong_target')
GATEWAY_CASES=('read_positive','reply_is_not_dispatch','injected_context_workflow_is_filtered','derived_context_is_not_authority',
               'address_workflow','payment_workflow','cancellation_workflow','items_workflow',
               'returns_workflow','exchange_workflow','handoff_workflow',
               'extra_confirmed','foreign_customer','foreign_order','wrong_type','model_context_overflow')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def metadata(parent):
    files=(RUNNER,'scripts/local_boundary_batch.py','tests/sdk_m6_replay_checks.py','tests/sdk_m6_checks.py',
           'tests/fixtures/m6_dialogues.json','tests/fixtures/m6_combinations.json','tests/fixtures/m6_3_source_baseline.json')
    return {'mode':'native_sdk','runner':RUNNER,'sdk_version':'1.0.1',**parent,
            'inputs':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}}


def _validate_batch(value,parent):
    if (not isinstance(value,dict) or set(value)!={'scope','execution','network_attempts','receipts','gateway'}
            or value['scope']!=SCOPE or value['execution']!=metadata(parent)
            or type(value['network_attempts']) is not int or value['network_attempts']!=0):
        raise ValueError('Invalid native boundary provenance or network evidence')
    expected=[(sid,kind,action,mode) for sid,kind,action in CASES for mode in MODES]
    if not isinstance(value['receipts'],list) or len(value['receipts'])!=len(expected):
        raise ValueError('Missing fixed receipt coverage')
    for row, (sid,kind,action,mode) in zip(value['receipts'],expected):
        status=('accepted' if kind=='handoff' else 'succeeded') if mode=='valid' else 'unknown'
        if (set(row)!={'id','kind','action','mode','status','sends','extra_sends','receipt_retained','backend_changed'}
                or (row['id'],row['kind'],row['action'],row['mode'])!=(sid,kind,action,mode)
                or row['status']!=status or type(row['sends']) is not int or row['sends']!=1
                or type(row['extra_sends']) is not int or row['extra_sends']!=0
                or row['receipt_retained'] is not (mode=='valid')
                or row['backend_changed'] is not (kind!='handoff')):
            raise ValueError('Receipt fault disagrees with fixed status/send/effect oracle')
    if not isinstance(value['gateway'],list) or [r.get('id') for r in value['gateway']]!=list(GATEWAY_CASES):
        raise ValueError('Missing fixed gateway coverage')
    for row in value['gateway']:
        if (set(row)!={'id','accepted','http_calls','workflow_exposed'}
                or row['accepted'] is not (row['id'] in {'read_positive','reply_is_not_dispatch'})
                or type(row['http_calls']) is not int or row['http_calls']!=0
                or row['workflow_exposed'] is not False):
            raise ValueError('Gateway accepted an unauthorized action or made a request')
    return value


def validate_batch(value,parent):
    try:
        return _validate_batch(value,parent)
    except (TypeError,KeyError,AttributeError,IndexError) as error:
        raise ValueError('Malformed native boundary observations') from error


def trace_boundaries(report):
    if 'boundary_batch' not in report:
        if report['results'].get(WRAPPER)=='passed':
            raise ValueError('Native boundary wrapper passed without observations')
        return None
    if report['results'].get(WRAPPER)!='passed':
        raise ValueError('Boundary observations require their actual passed wrapper')
    value=validate_batch(report['boundary_batch'],{'run_id':report['run_id'],'source_sha256':report['source_sha256']})
    return {'scope':SCOPE,'execution':value['execution'],'wrapper_test_id':WRAPPER,
            'receipt_scenarios':len(value['receipts']),'gateway_scenarios':len(value['gateway']),
            'complete_business_ats_executed':0}
