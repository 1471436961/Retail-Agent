"""M5.4 delivered exchanges over the shared complete replacement lifecycle."""
from support_agent.items_session import build_plan as _build, route_items, run_items_workflow, validate_items_basis, _boundary as _shared_boundary, _prepare as _shared_prepare


def build_plan(history):
    return _build(history, kind='exchange')


def _boundary():
    return _shared_boundary('exchange')


def _prepare(state, api, notice=''):
    return _shared_prepare(state, api, notice, kind='exchange')


def route_exchange(state, text=None):
    return route_items(state, text, kind='exchange')


def run_exchange_workflow(state, api, claims):
    return run_items_workflow(state, api, claims, kind='exchange')


def validate_exchange_basis(state):
    return validate_items_basis(state, kind='exchange')
