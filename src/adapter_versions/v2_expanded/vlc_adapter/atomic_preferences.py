"""One finite preference per public action."""
ATOMIC_PREFERENCES = {'preferences.set_allow_multiple_instances': 'allow_multiple_instances',
 'preferences.set_exit_after_playback': 'exit_after_playback',
 'preferences.set_global_play_pause_hotkey': 'global_play_pause_hotkey',
 'preferences.set_maximum_volume_percent': 'maximum_volume_percent',
 'preferences.set_minimal_interface': 'minimal_interface',
 'preferences.set_recording_directory': 'recording_directory',
 'preferences.set_show_background_cone': 'show_background_cone',
 'preferences.set_volume_slider_color': 'volume_slider_color'}

ATOMIC_PREFERENCE_SCHEMAS = {'preferences.set_global_play_pause_hotkey': {'description': 'Set only the VLC '
                                                             'global_play_pause_hotkey preference. '
                                                             'VLC global Play/Pause key name, for '
                                                             'example Media Play Pause. Other '
                                                             'preferences are preserved. This does '
                                                             'not restart VLC or open media.',
                                              'properties': {'value': {'type': 'string',
                                                                       'minLength': 1,
                                                                       'description': 'VLC global '
                                                                                      'Play/Pause '
                                                                                      'key name, '
                                                                                      'for example '
                                                                                      'Media Play '
                                                                                      'Pause.'}},
                                              'required': ['value'],
                                              'additionalProperties': False},
 'preferences.set_maximum_volume_percent': {'description': 'Set only the VLC '
                                                           'maximum_volume_percent preference. '
                                                           'Maximum volume shown by the VLC Qt '
                                                           'interface, as a percentage. Other '
                                                           'preferences are preserved. This does '
                                                           'not restart VLC or open media.',
                                            'properties': {'value': {'type': 'integer',
                                                                     'minimum': 0,
                                                                     'maximum': 300,
                                                                     'description': 'Maximum '
                                                                                    'volume shown '
                                                                                    'by the VLC Qt '
                                                                                    'interface, as '
                                                                                    'a '
                                                                                    'percentage.'}},
                                            'required': ['value'],
                                            'additionalProperties': False},
 'preferences.set_volume_slider_color': {'description': 'Set only the VLC volume_slider_color '
                                                        'preference. One #RRGGBB color applied to '
                                                        'all VLC volume-slider states. Other '
                                                        'preferences are preserved. This does not '
                                                        'restart VLC or open media.',
                                         'properties': {'value': {'type': 'string',
                                                                  'pattern': '^#[0-9A-Fa-f]{6}$',
                                                                  'description': 'One #RRGGBB '
                                                                                 'color applied to '
                                                                                 'all VLC '
                                                                                 'volume-slider '
                                                                                 'states.'}},
                                         'required': ['value'],
                                         'additionalProperties': False},
 'preferences.set_minimal_interface': {'description': 'Set only the VLC minimal_interface '
                                                      'preference. True hides the normal playback '
                                                      'controls in window mode. Other preferences '
                                                      'are preserved. This does not restart VLC or '
                                                      'open media.',
                                       'properties': {'value': {'type': 'boolean',
                                                                'description': 'True hides the '
                                                                               'normal playback '
                                                                               'controls in window '
                                                                               'mode.'}},
                                       'required': ['value'],
                                       'additionalProperties': False},
 'preferences.set_exit_after_playback': {'description': 'Set only the VLC exit_after_playback '
                                                        'preference. Whether VLC exits '
                                                        'automatically when playback ends. Other '
                                                        'preferences are preserved. This does not '
                                                        'restart VLC or open media.',
                                         'properties': {'value': {'type': 'boolean',
                                                                  'description': 'Whether VLC '
                                                                                 'exits '
                                                                                 'automatically '
                                                                                 'when playback '
                                                                                 'ends.'}},
                                         'required': ['value'],
                                         'additionalProperties': False},
 'preferences.set_allow_multiple_instances': {'description': 'Set only the VLC '
                                                             'allow_multiple_instances preference. '
                                                             'Whether desktop-opened files may '
                                                             'start independent VLC instances. '
                                                             'Other preferences are preserved. '
                                                             'This does not restart VLC or open '
                                                             'media.',
                                              'properties': {'value': {'type': 'boolean',
                                                                       'description': 'Whether '
                                                                                      'desktop-opened '
                                                                                      'files may '
                                                                                      'start '
                                                                                      'independent '
                                                                                      'VLC '
                                                                                      'instances.'}},
                                              'required': ['value'],
                                              'additionalProperties': False},
 'preferences.set_show_background_cone': {'description': 'Set only the VLC show_background_cone '
                                                         'preference. Whether the VLC cone is '
                                                         'shown in the empty-player background. '
                                                         'Other preferences are preserved. This '
                                                         'does not restart VLC or open media.',
                                          'properties': {'value': {'type': 'boolean',
                                                                   'description': 'Whether the VLC '
                                                                                  'cone is shown '
                                                                                  'in the '
                                                                                  'empty-player '
                                                                                  'background.'}},
                                          'required': ['value'],
                                          'additionalProperties': False},
 'preferences.set_recording_directory': {'description': 'Set only the VLC recording_directory '
                                                        'preference. Exact absolute directory '
                                                        'selected by the model. Discover the '
                                                        'home/standard user directory first when '
                                                        'its path is unknown. Other preferences '
                                                        'are preserved. This does not restart VLC '
                                                        'or open media.',
                                         'properties': {'value': {'type': 'string',
                                                                  'minLength': 1,
                                                                  'pattern': '^/.*',
                                                                  'description': 'Exact absolute '
                                                                                 'directory '
                                                                                 'selected by the '
                                                                                 'model. Discover '
                                                                                 'the '
                                                                                 'home/standard '
                                                                                 'user directory '
                                                                                 'first when its '
                                                                                 'path is '
                                                                                 'unknown.'}},
                                         'required': ['value'],
                                         'additionalProperties': False}}


def validate_atomic_params(action, params):
    """Validate finite scalar contracts using the guest's standard library only."""
    import math
    import re
    from .errors import AdapterError

    spec = ATOMIC_PREFERENCE_SCHEMAS[action]
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
