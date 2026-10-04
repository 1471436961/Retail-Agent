"""Compatibility names for M4.1 callers; shared budgets live in workflow_limits."""
from support_agent.workflow_limits import (
    MAX_WORKFLOW_ARGUMENT_BYTES as MAX_ADDRESS_ARGUMENT_BYTES,
    MAX_WORKFLOW_RESULT_BYTES as MAX_ADDRESS_RESULT_BYTES,
    WorkflowResultTooLarge as AddressResultTooLarge,
    check_workflow_argument as check_address_argument,
    compact_json,
    json_bytes,
)
