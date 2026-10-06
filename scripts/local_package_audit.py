"""Offline deployment/source audit. Findings contain locations, never secrets."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
RUNNER='tests/sdk_m6_package_checks.py'
WRAPPER='test_m6_package.NativePackageTests.test_isolated_uploaded_package_with_real_sdk'
SCOPE='local deployment payload and isolated SDK; no classroom or real model cost measurement'
LIMITS={'files':128,'file_bytes':256*1024,'payload_bytes':2*1024*1024}
SECRET_RULES={
    'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'provider_key':r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}',
    'github_token':r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})',
    'aws_access_key':r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'literal_bearer':r'(?i)\bBearer\s+[A-Za-z0-9._-]{20,}',
    'credential_assignment':r'''(?im)(?:["']?(?:api_key|access_token|password|secret_key|client_secret)["']?\s*[:=]\s*["'][^"'\r\n]{8,}["']|^[ \t]*["']?(?:api_key|access_token|password|secret_key|client_secret)["']?[ \t]*[:=][ \t]*[A-Za-z0-9_./+=:@-]{8,}[ \t\r]*(?:\#[^\r\n]*)?$)''',
}
FORBIDDEN_IMPORTS=('os','sys','subprocess','socket','requests','httpx','urllib.request','importlib','logging','pickle','_pickle','marshal')

def sha(value):
    return hashlib.sha256(value).hexdigest()

def payloads(files,node_files=None):
    manifest=json.loads(next(r['content'] for r in files if r['path']=='agent.json'))
    return {'manual_node':{'task':'t1','domain':manifest['domain'],'language':manifest['language'],
                           'source':'manual','files':node_files or files},
            'github_python':{'task':'t1','source':'github','commit_sha':'0'*40,'files':files,
                             'language':manifest['language'],'domain':manifest['domain'],'case_ids':None}}

def encode_payload(name,value):
    # Match evaluate.mjs JSON.stringify and lab_eval.api json.dumps respectively.
    return json.dumps(value,ensure_ascii=name=='github_python',
                      **({} if name=='github_python' else {'separators':(',',':')})).encode('utf-8')

def scan_text(name,text):
    findings=[]
    for rule,pattern in SECRET_RULES.items():
        for match in re.finditer(pattern,text):
            findings.append({'path':name,'line':text.count('\n',0,match.start())+1,'rule':rule})
    return findings

def audit_files(files,raw_sizes=None,*,payload_limit=LIMITS['payload_bytes'],node_files=None):
    if not isinstance(files,list) or not files or len(files)>LIMITS['files']:
        raise ValueError('file_count_budget')
    names=[]; findings=[]; imports={}; sizes={}; content_hashes={}
    for row in files:
        if not isinstance(row,dict) or set(row)!={'path','content'} or not isinstance(row['path'],str) or not isinstance(row['content'],str):
            raise ValueError('invalid_file_record')
        name,text=row['path'],row['content']; path=PurePosixPath(name)
        if (not name or name!=path.as_posix() or path.is_absolute() or '\\' in name or ':' in name or '\x00' in name
                or any(p.startswith('.') or p in {'tests','scripts','materials','__pycache__','venv','node_modules'} for p in path.parts)
                or path.stem.casefold() in {'secrets','credentials','id_rsa','id_ed25519'}):
            raise ValueError('forbidden_package_path')
        if name in names: raise ValueError('duplicate_package_path')
        names.append(name); sizes[name]=len(text.encode('utf-8'))
        if sizes[name]>LIMITS['file_bytes'] or (raw_sizes is not None and raw_sizes[name]>LIMITS['file_bytes']):
            raise ValueError('single_file_budget')
        content_hashes[name]=sha(text.encode('utf-8')); findings.extend(scan_text(name,text))
    if not {'agent.py','tools.py','agent.json'}<=set(names): raise ValueError('missing_entrypoints')
    manifest=json.loads(next(r['content'] for r in files if r['path']=='agent.json'))
    if manifest!={'protocol':'hyper-lab-v1','language':'python','domain':'retail_plus'}:
        raise ValueError('unexpected_manifest')
    for row in files:
        name,text=row['path'],row['content']
        if not name.endswith('.py'): continue
        tree=ast.parse(text,filename=name); refs=[]
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or '']
                if isinstance(node,ast.ImportFrom) and node.level:
                    findings.append({'path':name,'line':node.lineno,'rule':'relative_import_review'}); continue
                for module in modules:
                    refs.append(module); head=module.split('.')[0]
                    local=module.replace('.','/')
                    if head in {'agent','tools','support_agent'}:
                        if local+'.py' not in names and local+'/__init__.py' not in names:
                            findings.append({'path':name,'line':node.lineno,'rule':'missing_local_import'})
                    elif head!='tau2' and head not in sys.stdlib_module_names:
                        findings.append({'path':name,'line':node.lineno,'rule':'undeclared_dependency'})
                    if any(module==p or module.startswith(p+'.') for p in FORBIDDEN_IMPORTS):
                        findings.append({'path':name,'line':node.lineno,'rule':'direct_io_or_logging_import'})
            if isinstance(node,ast.Constant) and isinstance(node.value,str):
                if re.search(r'(?i)(?:[a-z]:[\\/]|/(?:home|Users|tmp|workspace)/|(?:^|[\\/])(?:\.venv|tests|scripts|materials)[\\/])',node.value):
                    findings.append({'path':name,'line':node.lineno,'rule':'external_path_literal'})
            if isinstance(node,ast.Call):
                fn=node.func; method=fn.id if isinstance(fn,ast.Name) else fn.attr if isinstance(fn,ast.Attribute) else ''
                if method in {'print','open','read_bytes','eval','exec','__import__','import_module','write_text','write_bytes','mkdir','unlink'}:
                    findings.append({'path':name,'line':node.lineno,'rule':'output_dynamic_or_filesystem_call'})
                if method=='compile' and (isinstance(fn,ast.Name) or ast.unparse(fn.value)=='builtins'):
                    findings.append({'path':name,'line':node.lineno,'rule':'output_dynamic_or_filesystem_call'})
                if method=='read_text' and not (name=='support_agent/config.py' and 'agent.json' in ast.unparse(fn) and '__file__' in ast.unparse(fn)):
                    findings.append({'path':name,'line':node.lineno,'rule':'external_file_read'})
        imports[name]=sorted(set(refs))
    if node_files is not None:
        if sorted((r['path'],r['content'].replace('\r\n','\n').replace('\r','\n')) for r in node_files)!=sorted((r['path'],r['content']) for r in files):
            raise ValueError('Collector text differs beyond newline normalization')
    encoded={key:encode_payload(key,value) for key,value in payloads(files,node_files).items()}
    for key,value in encoded.items():
        if len(value)>payload_limit: raise ValueError('submission_payload_budget:'+key)
        findings.extend(scan_text('submission:'+key,value.decode('utf-8')))
    if findings:
        # Only file/line/rule is emitted; matched text is never a diagnostic.
        raise ValueError('source_audit_rejected:'+json.dumps(findings,sort_keys=True))
    return {'file_count':len(files),'source_text_bytes':sum(sizes.values()),'max_text_file_bytes':max(sizes.values()),
            'content_hashes':content_hashes,'payload_bytes':{k:len(v) for k,v in encoded.items()},
            'payload_sha256':{k:sha(v) for k,v in encoded.items()},'imports':imports,
            'scan':{'files':len(files),'payloads':len(encoded),'rules':sorted(SECRET_RULES),'findings':[]}}

def audit_package(root=ROOT):
    directory=root/'agent'
    if any(getattr(p,'is_junction',lambda:False)() for p in [directory,*directory.rglob('*')]):
        raise ValueError('Package junctions are not accepted')
    spec=importlib.util.spec_from_file_location('m65_collect',root/'scripts/lab_eval.py')
    collector=importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
    files=collector.collect(root)
    raw={r['path']:(root/'agent'/r['path']).stat().st_size for r in files}
    # Execute the actual source-only Node collector and JSON.stringify; never its
    # main(), which reads credentials and submits. Fail if that extraction changes.
    source=(root/'scripts/evaluate.mjs').read_text(encoding='utf-8')
    start=source.index('async function collect('); end=source.index('async function main(){')
    node=shutil.which('node')
    if node is None: raise ValueError('Node collector runtime required; no skip')
    code="import {readFile,readdir,lstat} from 'node:fs/promises'; import {relative,join} from 'node:path';\n"+source[start:end]+"\nconst files=await collect(process.argv[1]); const manifest=JSON.parse(files.find(f=>f.path==='agent.json').content); const payload={task:'t1',domain:manifest.domain,language:manifest.language,source:'manual',files}; process.stdout.write(JSON.stringify({files,payload:JSON.stringify(payload)}));"
    run=subprocess.run([node,'--input-type=module','-e',code,str(root/'agent')],capture_output=True,text=True,encoding='utf-8',timeout=30)
    if run.returncode: raise ValueError('Node source collector failed')
    observed=json.loads(run.stdout); node_files=observed['files']
    result=audit_files(files,raw,node_files=node_files)
    node_bytes=observed['payload'].encode('utf-8')
    if result['payload_sha256']['manual_node']!=sha(node_bytes):
        raise ValueError('Node serialization differs from audited payload')
    result.update(raw_source_bytes=sum(raw.values()),max_raw_file_bytes=max(raw.values()),
                  raw_sha256={r['path']:sha((root/'agent'/r['path']).read_bytes()) for r in files})
    return result,files

def verify_copied_package(directory,expected):
    """Read actual copied bytes before/after SDK use, not the upload input again."""
    directory=Path(directory)
    paths=[directory,*directory.rglob('*')]
    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in paths):
        raise ValueError('Copied package links are not accepted')
    actual={p.relative_to(directory).as_posix():sha(p.read_bytes()) for p in paths if p.is_file()}
    if actual!=expected:
        raise ValueError('Copied package byte hashes differ from upload')
    return actual

def metadata(parent):
    paths=(RUNNER,'scripts/local_package_audit.py','scripts/lab_eval.py','scripts/evaluate.mjs')
    return {'mode':'isolated_uploaded_package','runner':RUNNER,**parent,
            'inputs':{p:sha((ROOT/p).read_bytes()) for p in paths}}

def validate_batch(value,parent):
    expected,_=audit_package()
    if (not isinstance(value,dict) or set(value)!={'scope','execution','package','isolated','measurement'}
            or value['scope']!=SCOPE or value['execution']!=metadata(parent) or value['package']!=expected):
        raise ValueError('Package observations or provenance mismatch')
    isolated=value['isolated']
    fixed={'sdk_version':'1.0.1','module_origins_inside_package':True,'read_tools':8,'write_tools':7,
           'factory_fresh':True,'private_error_marker_absent':True,'network_attempts':0,
           'transport_calls':1,'model_calls':0,'copied_content_sha256':expected['content_hashes']}
    if not isinstance(isolated,dict) or isolated!=fixed or any(type(isolated[k]) is not type(v) for k,v in fixed.items()):
        raise ValueError('Isolated package/runtime observations mismatch')
    measurement={'status':'not_measured','real_model_calls':0,'token_total':None,'cost_total':None}
    if value['measurement']!=measurement:
        raise ValueError('Unmeasured model cost cannot become a zero or estimate')
    return value

def trace_package(report):
    if 'package_batch' not in report:
        if report['results'].get(WRAPPER)=='passed': raise ValueError('Package wrapper passed without observations')
        return None
    if report['results'].get(WRAPPER)!='passed': raise ValueError('Package observations lack passed wrapper')
    value=validate_batch(report['package_batch'],{'run_id':report['run_id'],'source_sha256':report['source_sha256']})
    return {'scope':SCOPE,'execution':value['execution'],'package':value['package'],
            'isolated':value['isolated'],'model_measurement':value['measurement'],'complete_business_ats_executed':0}
