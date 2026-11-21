"""Finite single-preference public contracts."""
ATOMIC_SETTINGS = {'settings.set_appearance': 'appearance',
 'settings.set_clear_on_exit': 'clear_on_exit',
 'settings.set_do_not_track': 'do_not_track',
 'settings.set_font_size': 'font_size',
 'settings.set_profile_name': 'profile_name',
 'settings.set_safe_browsing': 'safe_browsing',
 'settings.set_search_engine': 'search_engine',
 'settings.set_startup_mode': 'startup_mode'}

ATOMIC_SETTING_SCHEMAS = {'settings.set_font_size': {'description': 'Set only the Chrome font_size preference and read it '
                                           'back. Other settings are preserved.',
                            'properties': {'value': {'type': 'integer', 'minimum': 1}},
                            'required': ['value'],
                            'additionalProperties': False},
 'settings.set_do_not_track': {'description': 'Set only the Chrome do_not_track preference and '
                                              'read it back. Other settings are preserved.',
                               'properties': {'value': {'type': 'boolean'}},
                               'required': ['value'],
                               'additionalProperties': False},
 'settings.set_safe_browsing': {'description': 'Set only the Chrome safe_browsing preference and '
                                               'read it back. Other settings are preserved.',
                                'properties': {'value': {'type': 'boolean'}},
                                'required': ['value'],
                                'additionalProperties': False},
 'settings.set_profile_name': {'description': 'Set only the Chrome profile_name preference and '
                                              'read it back. Other settings are preserved.',
                               'properties': {'value': {'type': 'string', 'minLength': 1}},
                               'required': ['value'],
                               'additionalProperties': False},
 'settings.set_search_engine': {'description': 'Set only the Chrome search_engine preference and '
                                               'read it back. Other settings are preserved.',
                                'properties': {'value': {'type': 'string',
                                                         'enum': ['bing', 'google']}},
                                'required': ['value'],
                                'additionalProperties': False},
 'settings.set_appearance': {'description': 'Set only the Chrome appearance preference and read it '
                                            'back. Other settings are preserved.',
                             'properties': {'value': {'type': 'string',
                                                      'enum': ['light', 'dark', 'system']}},
                             'required': ['value'],
                             'additionalProperties': False},
 'settings.set_startup_mode': {'description': 'Set only the Chrome startup_mode preference and '
                                              'read it back. Other settings are preserved.',
                               'properties': {'value': {'type': 'string',
                                                        'enum': ['new_tab', 'continue']}},
                               'required': ['value'],
                               'additionalProperties': False},
 'settings.set_clear_on_exit': {'description': 'Set only the Chrome clear_on_exit preference and '
                                               'read it back. Other settings are preserved.',
                                'properties': {'value': {'type': 'boolean'}},
                                'required': ['value'],
                                'additionalProperties': False}}


def validate_atomic_params(action, params):
    """Validate finite scalar contracts using the guest's standard library only."""
    import math
    import re
    from .errors import AdapterError

    spec = ATOMIC_SETTING_SCHEMAS[action]
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
