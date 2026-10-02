"""Offline exercise of the real thin platform entry and deterministic toolkit."""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"
sys.path.insert(0, str(AGENT))

from fakes import FakeClientAPI


class FakeAssistantMessage:
    def __init__(self, *, role, content=None, tool_calls=None):
        assert role == "assistant"
        assert bool(content) != bool(tool_calls)
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


class FakeToolCall:
    def __init__(self, *, id, name, arguments, requestor):
        self.id, self.name, self.arguments, self.requestor = id, name, arguments, requestor


class FakeMultiToolMessage:
    def __init__(self, tool_messages):
        self.tool_messages = tool_messages


class FakeToolkitBase:
    def __init__(self, client_api):
        self.client_api = client_api


def platform_modules(context):
    modules = {}
    for name in ("tau2", "tau2.data_model", "tau2.data_model.message", "tau2.environment", "tau2.environment.toolkit", "tau2.hyper", "tau2.hyper.client_api", "tau2.hyper.agent_context"):
        modules[name] = types.ModuleType(name)
    message = modules["tau2.data_model.message"]
    message.AssistantMessage = FakeAssistantMessage
    message.ToolCall = FakeToolCall
    message.MultiToolMessage = FakeMultiToolMessage
    toolkit = modules["tau2.environment.toolkit"]
    toolkit.ToolType = SimpleNamespace(READ="read")
    toolkit.is_tool = lambda kind: lambda fn: fn
    modules["tau2.hyper.client_api"].ClientAPIToolKitBase = FakeToolkitBase
    modules["tau2.hyper.agent_context"].get_agent_context = lambda: context
    return modules


class AdapterTests(unittest.TestCase):
    def test_interleaved_customer_sessions_do_not_mix_results(self):
        with patch.dict(sys.modules, platform_modules(object())):
            entry = importlib.import_module("agent")
            toolkit = importlib.import_module("tools")
            first, second = entry.create_agent(), entry.create_agent()
            api_a, api_b = FakeClientAPI(), FakeClientAPI()
            call_a, waiting_a = first.generate_next_message(SimpleNamespace(role="user", content="customer_a a@example.test"), first.get_init_state())
            call_b, waiting_b = second.generate_next_message(SimpleNamespace(role="user", content="customer_b b@example.test"), second.get_init_state())
            for agent, api, outbound, waiting, expected in ((second, api_b, call_b, waiting_b, "customer_b"), (first, api_a, call_a, waiting_a, "customer_a")):
                call = outbound.tool_calls[0]
                record = toolkit.Tools(api).lookup_customer(**call.arguments)
                reply, done = agent.generate_next_message(FakeMultiToolMessage([SimpleNamespace(id=call.id, content=json.dumps(record), error=False)]), waiting)
                self.assertEqual(done["identity"]["customer_id"], expected)
                self.assertIn(record["email"], reply.content)
                self.assertEqual(record["order_ids"], ["#TEST1"] if expected == "customer_a" else ["#TEST2"])
            # Independent email search must not load the other customer's detail.
            with self.assertRaises(ValueError):
                toolkit.Tools(api_a).lookup_customer(customer_id="customer_b", email="a@example.test")
            self.assertEqual(api_a.calls[-1][:2], ("POST", "/v1/customers/search"))

    def test_unexpected_single_tool_message_is_not_treated_as_user_text(self):
        with patch.dict(sys.modules, platform_modules(object())):
            agent = importlib.import_module("agent").create_agent()
            with self.assertRaisesRegex(ValueError, "Unsupported platform message"):
                agent.generate_next_message(SimpleNamespace(role="tool", content="customer_a a@example.test"), agent.get_init_state())

    def test_factory_turns_and_toolkit_replay(self):
        context = object()
        with patch.dict(sys.modules, platform_modules(context)):
            entry = importlib.import_module("agent")
            tools_module = importlib.import_module("tools")
            agent = entry.create_agent()
            self.assertIs(agent.context, context)
            state = agent.get_init_state()
            user = SimpleNamespace(role="user", content="customer_a a@example.test")
            outbound, waiting = agent.generate_next_message(user, state)
            self.assertIsNone(outbound.content)
            self.assertEqual(len(outbound.tool_calls), 1)
            call = outbound.tool_calls[0]
            self.assertEqual(call.name, "lookup_customer")
            self.assertEqual(call.requestor, "assistant")
            first, second = FakeClientAPI(), FakeClientAPI()
            result1 = tools_module.Tools(first).lookup_customer(**call.arguments)
            result2 = tools_module.Tools(second).lookup_customer(**call.arguments)
            self.assertEqual(result1, result2)
            self.assertEqual(first.calls, second.calls)
            self.assertEqual(len(first.calls), 2)
            incoming = FakeMultiToolMessage([SimpleNamespace(id=call.id, content=json.dumps(result1), error=False)])
            reply, final = agent.generate_next_message(incoming, json.loads(json.dumps(waiting)))
            self.assertIn("a@example.test", reply.content)
            self.assertFalse(reply.tool_calls)
            self.assertTrue(final["identity"]["verified"])
            self.assertEqual(final["operations"][0]["status"], "succeeded")

    def test_clean_agent_package_does_not_need_repo_root_or_materials(self):
        # Match the source extensions and exclusions in scripts/evaluate.mjs.
        extensions = {".py", ".ts", ".js", ".mjs", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}
        self.assertFalse(AGENT.is_symlink())
        self.assertFalse(any(p.is_symlink() for p in AGENT.rglob("*")))
        package_files = [p for p in AGENT.rglob("*") if p.is_file() and p.suffix in extensions
                         and not any(part.startswith(".") or part in {"node_modules", "__pycache__", "venv"} for part in p.relative_to(AGENT).parts)]
        self.assertLessEqual(len(package_files), 128)
        self.assertTrue(all(p.stat().st_size <= 256 * 1024 for p in package_files))
        payload = {"task": "t1", "domain": "retail_plus", "language": "python", "source": "manual",
                   "files": [{"path": p.relative_to(AGENT).as_posix(), "content": p.read_bytes().decode("utf-8")} for p in package_files]}
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), 2 * 1024 * 1024)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(AGENT)
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, "-c", "from support_agent.state import initial_state; from support_agent.turns import advance; from support_agent.protocol import TurnInput; s=initial_state(); d,s=advance(TurnInput(kind='user',content='customer_a a@example.test'),s); assert d.calls[0].name == 'lookup_customer'"],
                cwd=folder,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
