"""The official collected package must work without the source repository."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_official_collector_contains_entry_points_and_original_package_layout(self):
        spec=importlib.util.spec_from_file_location("official_collector",ROOT/"scripts/lab_eval.py")
        collector=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        files=collector.collect(ROOT)
        self.assertEqual({f["path"] for f in files},
                         {"agent.py","tools.py","policy.md","agent.json","THIRD-PARTY-NOTICES.txt",
                          "support_agent/__init__.py","support_agent/application.py","support_agent/state.py",
                          "support_agent/config.py","support_agent/adapters/__init__.py",
                          "support_agent/adapters/customer_api.py","support_agent/adapters/customer_tools.py",
                          "support_agent/domain/__init__.py","support_agent/domain/customer.py",
                          "support_agent/domain/preferences.py"})
        self.assertEqual(json.loads(next(f["content"] for f in files if f["path"]=="agent.json"))["domain"],"retail_plus")
        self.assertLess(sum(len(f["content"].encode("utf-8")) for f in files),2*1024*1024)

    def test_isolated_uploaded_directory_imports_and_calls_the_real_gateway(self):
        temporary=ROOT/".test-tmp"
        temporary.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary,prefix="retail-upload-") as directory:
            upload=Path(directory)/"agent"
            shutil.copytree(ROOT/"agent",upload,ignore=shutil.ignore_patterns("__pycache__"))
            code=r'''
import os,sys
from pathlib import Path
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo'}:raise RuntimeError('Offline isolated import forbids network')
sys.addaudithook(audit)
upload=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(upload))
from unittest.mock import patch
from tau2.hyper.agent_context import build_agent_context,activate_agent_context
from tau2.hyper.client_api import ClientAPI
from tau2.data_model.message import AssistantMessage,UserMessage
import agent,tools
assert Path(agent.__file__).resolve().parent==upload
assert Path(tools.__file__).resolve().parent==upload
kit=tools.Tools(ClientAPI(lambda _: (_ for _ in ()).throw(AssertionError('Unexpected API call'))))
context=build_agent_context(domain='retail_plus',tools=list(kit.get_tools().values()),resource_root=upload,
                            model_configs=[{'model':'offline/package'}])
with activate_agent_context(context):application=agent.create_agent()
assert application.__class__.__module__=='support_agent.application'
assert application.__class__.__name__=='CustomerAgent'
with patch('tau2.hyper.agent_context.generate',return_value=AssistantMessage(role='assistant',content='What is your email address?')) as inference:
    reply,state=application.generate_next_message(UserMessage(role='user',content='Please help me exchange a shirt.'),application.get_init_state())
assert reply.content=='What is your email address?'
assert inference.call_count==1
assert len(inference.call_args.kwargs['tools'])==18
import json
json.dumps(state,allow_nan=False)
print('ISOLATED_UPLOAD_OK network_attempts=0 real_model_calls=0')
'''
            env=dict(os.environ)
            env.pop("PYTHONPATH",None)
            result=subprocess.run([sys.executable,"-I","-B","-c",code,str(upload)],cwd=directory,
                                  env=env,text=True,encoding="utf-8",errors="replace",capture_output=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stderr[-5000:])
            self.assertIn("ISOLATED_UPLOAD_OK network_attempts=0 real_model_calls=0",result.stdout)


if __name__=="__main__":
    unittest.main()
