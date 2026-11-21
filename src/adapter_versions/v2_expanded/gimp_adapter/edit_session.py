"""Private XCF edit state, separate from model-selected saved/exported outputs.

Workers are short lived. Immutable revisions retain an editable GIMP document
between calls; only the session pointer advances after successful verification.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import uuid
from contextlib import contextmanager

from .errors import AdapterError
from .verifier import verify_specs

SESSION_ROOT = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'liteagent-gimp-{os.getuid()}'
EFFECTS = {'image.set_brightness': ('brightness', -127, 127),
           'image.set_contrast': ('contrast', -127, 127),
           'image.set_saturation': ('saturation', -100, 100)}
PATH = {'type': 'string', 'minLength': 1, 'pattern': r'^(?:/|~/).+'}
ID = {'type': 'string', 'pattern': r'^[0-9a-f]{32}$',
      'description': 'Exact image_id returned by image.open_session.'}
SCHEMAS = {
    'image.open_session': {'description': 'Load one existing image into private editable XCF session state. Returns image_id. Does not adjust, export, or open the GUI.',
                          'properties': {'path': PATH}, 'required': ['path'], 'additionalProperties': False},
    'image.inspect_session': {'description': 'Read the current editable image state and preview without changing it.',
                             'properties': {'image_id': ID}, 'required': ['image_id'], 'additionalProperties': False},
    'image.save_session': {'description': 'Save/export the current session image to one explicit output path. Does not adjust pixels or open the GUI. Use .xcf for editable native output or .png/.jpg for an exported raster.',
                          'properties': {'image_id': ID, 'output_path': PATH}, 'required': ['image_id', 'output_path'], 'additionalProperties': False},
    'image.open_session_gui': {'description': 'Display the current private XCF document in GIMP without saving an output or adjusting pixels. image_id must already exist.',
                              'properties': {'image_id': ID}, 'required': ['image_id'], 'additionalProperties': False},
}
for action, (effect, lower, upper) in EFFECTS.items():
    SCHEMAS[action] = {'description': f'Apply only relative {effect} adjustment to one editable image session. Updates private edit state only; no output file or GUI opening. Use image.save_session separately.',
                       'properties': {'image_id': ID, 'value': {'type': 'integer' if effect != 'saturation' else 'number', 'minimum': lower, 'maximum': upper}},
                       'required': ['image_id', 'value'], 'additionalProperties': False}


def _root() -> Path:
    SESSION_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    return SESSION_ROOT


@contextmanager
def _session(image_id):
    if not isinstance(image_id, str) or not re.fullmatch(r'[0-9a-f]{32}', image_id):
        raise AdapterError('INVALID_REQUEST', 'copy the exact image_id from image.open_session')
    directory = _root() / image_id
    if not (directory / 'state.json').is_file():
        raise AdapterError('IMAGE_SESSION_NOT_FOUND', 'open the source with image.open_session first')
    with (directory / 'lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield directory, json.loads((directory / 'state.json').read_text())


def _commit(directory, state):
    temporary = directory / 'state.json.tmp'
    temporary.write_text(json.dumps(state))
    os.replace(temporary, directory / 'state.json')


def execute_session(action, params, runner, lifecycle, timeout):
    if action == 'image.open_session':
        source = Path(params['path']).expanduser().resolve()
        if not source.is_file():
            raise AdapterError('FILE_NOT_FOUND', 'source image does not exist')
        image_id = uuid.uuid4().hex
        directory = _root() / image_id
        directory.mkdir(mode=0o700)
        result = runner._run_image_operation(str(source), str(directory / 'initial.xcf'), '', timeout_seconds=timeout)
        verification = verify_specs([{'type': 'image'}], result)
        if not verification['passed']:
            raise AdapterError('VERIFICATION_FAILED', 'session image could not be verified', verification)
        state = {'image_id': image_id, 'source_path': str(source), 'revision': 0, 'image': result}
        _commit(directory, state)
        return {'image_id': image_id, 'source_path': str(source), 'revision': 0, 'image': result}, verification
    with _session(params['image_id']) as (directory, state):
        current = state['image']
        if action == 'image.inspect_session':
            return state, verify_specs([{'type': 'image'}], current)
        if action == 'image.open_session_gui':
            return {'image_id': state['image_id'], **lifecycle.prepare(timeout, current['output_path'])}, {'passed': True, 'checks': []}
        if action == 'image.save_session':
            output = Path(params['output_path']).expanduser().resolve()
            if output == Path(state['source_path']) or output.is_relative_to(_root().resolve()):
                raise AdapterError('INVALID_REQUEST', 'save to a separate explicit user output; preserve the source and private edit state')
            if output.suffix.lower() not in {'.xcf', '.png', '.jpg', '.jpeg'}:
                raise AdapterError('INVALID_REQUEST', 'session output must be .xcf, .png, .jpg or .jpeg')
            result = runner.export(current['output_path'], str(output), timeout_seconds=timeout)
            return {'image_id': state['image_id'], **result}, verify_specs([{'type': 'image'}], result)
        effect, _, _ = EFFECTS[action]
        value = params['value']
        operation = (f'(gimp-hue-saturation drawable 0 0 0 {value})' if effect == 'saturation' else
                     f'(gimp-brightness-contrast drawable {value if effect == "brightness" else 0} {value if effect == "contrast" else 0})')
        output = directory / (uuid.uuid4().hex + '.xcf')
        result = runner._run_image_operation(current['output_path'], str(output), operation, timeout_seconds=timeout)
        checks = [{'type': 'image'}]
        if value:
            direction = 'increased' if value > 0 else 'decreased'
            checks.append({'type': f'{effect}_{direction}', 'reference_path': current['preview_path']})
        verification = verify_specs(checks, result)
        if not verification['passed']:
            raise AdapterError('VERIFICATION_FAILED', 'adjustment did not pass verification; session unchanged', verification)
        state.update(revision=state['revision'] + 1, image=result)
        _commit(directory, state)
        return {'image_id': state['image_id'], 'revision': state['revision'], 'effect': effect, 'value': value, 'image': result}, verification


def validate_atomic_params(action, params):
    """Validate finite scalar contracts using the guest's standard library only."""
    import math
    import re
    from .errors import AdapterError

    spec = SCHEMAS[action]
    properties = spec['properties']
    if set(params) - set(properties) or set(spec['required']) - set(params):
        raise AdapterError('INVALID_REQUEST', 'use only the documented parameters; required: ' + ', '.join(spec['required']))
    for field, value in params.items():
        rule = properties[field]
        kind = rule['type']
        valid = ((kind == 'string' and isinstance(value, str) and bool(value.strip()))
                 or (kind == 'boolean' and isinstance(value, bool))
                 or (kind == 'integer' and isinstance(value, int) and not isinstance(value, bool))
                 or (kind == 'number' and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)))
        if not valid:
            raise AdapterError('INVALID_REQUEST', f'params.{field} must be {kind}')
        if ('enum' in rule and value not in rule['enum']
                or 'minimum' in rule and value < rule['minimum']
                or 'maximum' in rule and value > rule['maximum']
                or 'pattern' in rule and not re.search(rule['pattern'], value)):
            raise AdapterError('INVALID_REQUEST', f'params.{field} violates its documented enum, range or pattern')
