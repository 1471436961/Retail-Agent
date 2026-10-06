"""Reviewed root causes with source references and actual regression outcomes.

This is a finite register, not a retrospective execution of every old failure.
Narrative classifications are reviewed judgments, not inferred by an AST.
"""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REGISTER = 'tests/fixtures/m6_defects.json'
WRAPPER = 'test_m6_defects.DefectRegisterTests.test_registered_regressions_have_valid_fix_and_source_references'
CATEGORIES = ('rule_understanding', 'tool_parameters', 'confirmation_flow',
              'dialogue_omission', 'runtime_compatibility')
KINDS = ('production', 'test_infrastructure')
SCOPE = 'finite reviewed defects and current regressions; not all historical failures or business ATs'


def _file(root, name):
    if (not isinstance(name, str) or name != PurePosixPath(name).as_posix()
            or not name or '\\' in name or ':' in name or PurePosixPath(name).is_absolute()
            or any(part.startswith('.') for part in PurePosixPath(name).parts)):
        raise ValueError('Noncanonical defect source path')
    path = root / name
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Missing or external defect source')
    return path


def _symbols(path):
    result = {}
    def visit(nodes, prefix=''):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                result[name] = node.lineno
                if isinstance(node, ast.ClassDef): visit(node.body, name + '.')
    visit(ast.parse(path.read_text(encoding='utf-8')).body)
    return result


def load_register(root=ROOT):
    return json.loads(_file(root, REGISTER).read_text(encoding='utf-8'))


def source_inputs(root=ROOT):
    """Include historical narrative sources so changing them invalidates a run."""
    if not (root / REGISTER).is_file(): return []
    return sorted({_file(root, row['origin']['path']) for row in load_register(root)['incidents']})


def _validate_register(value, root=ROOT):
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'scope', 'incidents', 'notes'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['scope'] != SCOPE or not isinstance(value['incidents'], list) or not value['incidents']
            or not isinstance(value['notes'], list) or any(not isinstance(n, str) or not n.strip() for n in value['notes'])):
        raise ValueError('Invalid defect register envelope')
    ids = set(); witnesses = set(); checked = []
    for row in value['incidents']:
        if (not isinstance(row, dict) or set(row) != {'id','category','kind','phase','symptom','root_cause','fix','origin','fix_sites','tests'}
                or row['category'] not in CATEGORIES or row['kind'] not in KINDS
                or row['phase'] not in {'historical','current'}
                or any(not isinstance(row[k], str) or not row[k].strip() for k in ('id','symptom','root_cause','fix'))
                or row['id'] in ids):
            raise ValueError('Invalid or duplicate defect incident')
        ids.add(row['id'])
        origin = row['origin']
        if (not isinstance(origin, dict) or set(origin) != {'path','contains'}
                or not isinstance(origin['contains'], str) or not origin['contains']
                or origin['contains'] not in _file(root, origin['path']).read_text(encoding='utf-8')):
            raise ValueError('Defect narrative source does not match')
        if not isinstance(row['fix_sites'], list) or not row['fix_sites'] or not isinstance(row['tests'], list) or not row['tests']:
            raise ValueError('Defect requires fix sites and regressions')
        refs = []
        for site in row['fix_sites']:
            if not isinstance(site, dict) or set(site) != {'path','symbol'}:
                raise ValueError('Invalid fix reference')
            symbols = _symbols(_file(root, site['path']))
            if site['symbol'] not in symbols: raise ValueError('Missing fix symbol')
            refs.append({**site, 'line':symbols[site['symbol']]})
        if len(row['tests']) != len(set(row['tests'])): raise ValueError('Duplicate regression reference')
        test_refs = []
        for test_id in row['tests']:
            if not isinstance(test_id, str) or len(test_id.split('.')) != 3:
                raise ValueError('Invalid regression ID')
            module, cls, method = test_id.split('.')
            if not module.startswith('test_') or not method.startswith('test_'):
                raise ValueError('Invalid regression ID')
            name = 'tests/' + module + '.py'; symbol = cls + '.' + method
            symbols = _symbols(_file(root, name))
            if symbol not in symbols: raise ValueError('Missing regression method')
            test_refs.append({'test_id':test_id, 'path':name, 'line':symbols[symbol]})
        witness = tuple(sorted(row['tests']))
        if witness in witnesses: raise ValueError('Duplicate incident regression set')
        witnesses.add(witness)
        checked.append({**row, 'fix_sites':refs, 'test_references':test_refs})
    if {row['category'] for row in checked} != set(CATEGORIES):
        raise ValueError('All five root-cause categories must be represented')
    return checked


def validate_register(value, root=ROOT):
    try:
        return _validate_register(value, root)
    except (KeyError, TypeError, AttributeError, SyntaxError, OSError) as error:
        raise ValueError('Malformed defect source or reference') from error


def closure(report, root=ROOT, value=None):
    checked = validate_register(load_register(root) if value is None else value, root)
    files = report.get('source_files', {}); outcomes = report.get('results', {})
    inputs = {REGISTER, 'scripts/defect_register.py'}
    for row in checked:
        inputs.add(row['origin']['path'])
        inputs.update(site['path'] for site in row['fix_sites'])
        inputs.update(ref['path'] for ref in row['test_references'])
        if any(outcomes.get(test) != 'passed' for test in row['tests']):
            raise ValueError('Registered regression was not executed successfully')
    hashes = {name:hashlib.sha256(_file(root, name).read_bytes()).hexdigest() for name in sorted(inputs)}
    if any(files.get(name) != digest for name, digest in hashes.items()):
        raise ValueError('Defect references differ from run source hashes')
    return {'scope':SCOPE, 'run_id':report['run_id'], 'source_sha256':report['source_sha256'],
            'inputs':hashes, 'incident_count':len(checked),
            'by_category':{key:sum(row['category']==key for row in checked) for key in CATEGORIES},
            'by_kind':{key:sum(row['kind']==key for row in checked) for key in KINDS},
            'new_incidents':sum(row['phase']=='current' for row in checked),
            'unique_regressions':len({test for row in checked for test in row['tests']}),
            'incidents':checked, 'complete_business_ats_executed':0}


def trace_defects(report):
    if WRAPPER not in report['results']:
        if REGISTER in report.get('source_files', {}):
            raise ValueError('Defect register wrapper was not executed')
        return None
    if report['results'][WRAPPER] != 'passed': raise ValueError('Defect register check did not pass')
    return closure(report)
