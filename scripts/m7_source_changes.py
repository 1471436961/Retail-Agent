"""Explicit M7 byte changes after the frozen M6.7 manifest, never a rebaseline."""
from copy import deepcopy
from pathlib import PurePosixPath

MANIFEST = 'tests/fixtures/m7_semantic_changes.json'
SCOPE = 'Explicit M7 semantic refactor after preserved M6.7 changes; not a signature'


def validate_changes(value, previous_sha256, previous, current):
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'scope', 'previous_manifest_sha256', 'changes'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['scope'] != SCOPE or value['previous_manifest_sha256'] != previous_sha256
            or not isinstance(value['changes'], list) or not value['changes']):
        raise ValueError('Invalid M7 source change chain')
    expected, seen, added = dict(previous), set(), []
    for row in value['changes']:
        if not isinstance(row, dict) or set(row) != {'path', 'before_sha256', 'after_sha256', 'reason'}:
            raise ValueError('Invalid M7 change row')
        path = row['path']
        if (not isinstance(path, str) or path in seen or not path.startswith('agent/')
                or '\\' in path or '..' in PurePosixPath(path).parts or PurePosixPath(path).as_posix() != path
                or row['before_sha256'] != previous.get(path)
                or not isinstance(row['after_sha256'], str) or len(row['after_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in row['after_sha256'])
                or row['after_sha256'] == row['before_sha256']
                or not isinstance(row['reason'], str) or not row['reason'].strip()):
            raise ValueError('Invalid or duplicate M7 source change')
        if path not in previous:
            if not path.endswith('.py'):
                raise ValueError('Only explicitly named new production modules are admitted')
            added.append(path)
        seen.add(path)
        expected[path] = row['after_sha256']
    if expected != current:
        raise ValueError('Unrecorded M7 source or fixed fixture change')
    return {'previous_manifest_sha256': previous_sha256, 'changed_existing_files': len(seen)-len(added),
            'added_files': added, 'unchanged_previous_files': len(previous)-(len(seen)-len(added)),
            'changes': deepcopy(value['changes'])}
