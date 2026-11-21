"""Finite single-setting contracts; no model-selected key or multi-value input."""
from __future__ import annotations

ATOMIC_SETTINGS = {'debugging.set_focus_editor_on_break': ('debug.focusEditorOnBreak', None),
 'debugging.set_inline_values': ('debug.inlineValues', None),
 'debugging.set_internal_console': ('debug.internalConsoleOptions', None),
 'debugging.set_open_debug_view': ('debug.openDebug', None),
 'debugging.set_show_breakpoints_in_overview_ruler': ('debug.showBreakpointsInOverviewRuler', None),
 'debugging.set_show_inline_breakpoint_candidates': ('debug.showInlineBreakpointCandidates', None),
 'editor.set_minimap_enabled': ('editor.minimap.enabled', None),
 'editor.set_smooth_scrolling': ('editor.smoothScrolling', None),
 'editor.set_sticky_scroll_enabled': ('editor.stickyScroll.enabled', None),
 'editor.set_wrap_tabs': ('workbench.editor.wrapTabs', None),
 'editor.set_word_wrap_column': ('editor.wordWrapColumn', None),
 'editor.set_line_numbers': ('editor.lineNumbers',
                             {'off': 'off',
                              'on': 'on',
                              'relative': 'relative',
                              'interval': 'interval'}),
 'editor.set_render_whitespace': ('editor.renderWhitespace',
                                  {'none': 'none',
                                   'boundary': 'boundary',
                                   'selection': 'selection',
                                   'trailing': 'trailing',
                                   'all': 'all'}),
 'editor.set_word_wrap': ('editor.wordWrap',
                          {'off': 'off',
                           'on': 'on',
                           'at_column': 'wordWrapColumn',
                           'bounded': 'bounded'}),
 'files.set_insert_final_newline': ('files.insertFinalNewline', None),
 'files.set_trim_final_newlines': ('files.trimFinalNewlines', None),
 'files.set_trim_trailing_whitespace': ('files.trimTrailingWhitespace', None),
 'files.set_auto_save': ('files.autoSave',
                         {'off': 'off',
                          'after_delay': 'afterDelay',
                          'on_focus_change': 'onFocusChange',
                          'on_window_change': 'onWindowChange'}),
 'files.set_auto_save_delay_ms': ('files.autoSaveDelay', None),
 'files.set_hot_exit': ('files.hotExit',
                        {'off': 'off',
                         'on_exit': 'onExit',
                         'on_exit_and_window_close': 'onExitAndWindowClose'})}

ATOMIC_SETTING_SCHEMAS = {'debugging.set_focus_editor_on_break': {'description': 'Set only debug.focusEditorOnBreak. '
                                                        'Whether a debugger break moves cursor '
                                                        'focus to the editor. Set false to '
                                                        'preserve focus in the Debug Console or '
                                                        'other current debug view. Other settings '
                                                        'are preserved.',
                                         'properties': {'value': {'type': 'boolean',
                                                                  'description': 'Whether a '
                                                                                 'debugger break '
                                                                                 'moves cursor '
                                                                                 'focus to the '
                                                                                 'editor. Set '
                                                                                 'false to '
                                                                                 'preserve focus '
                                                                                 'in the Debug '
                                                                                 'Console or other '
                                                                                 'current debug '
                                                                                 'view.'},
                                                        'path': {'type': 'string',
                                                                 'minLength': 1,
                                                                 'description': 'Optional '
                                                                                'settings.json '
                                                                                'path; omit for '
                                                                                'active user '
                                                                                'settings.'}},
                                         'required': ['value'],
                                         'additionalProperties': False},
 'debugging.set_inline_values': {'description': 'Set only debug.inlineValues. Whether variable '
                                                'values appear inline while debugging. Other '
                                                'settings are preserved.',
                                 'properties': {'value': {'type': 'string',
                                                          'enum': ['auto', 'off', 'on'],
                                                          'description': 'Whether variable values '
                                                                         'appear inline while '
                                                                         'debugging.'},
                                                'path': {'type': 'string',
                                                         'minLength': 1,
                                                         'description': 'Optional settings.json '
                                                                        'path; omit for active '
                                                                        'user settings.'}},
                                 'required': ['value'],
                                 'additionalProperties': False},
 'debugging.set_internal_console': {'description': 'Set only debug.internalConsoleOptions. When '
                                                   'the internal Debug Console opens '
                                                   'automatically. Other settings are preserved.',
                                    'properties': {'value': {'type': 'string',
                                                             'enum': ['neverOpen',
                                                                      'openOnFirstSessionStart',
                                                                      'openOnSessionStart'],
                                                             'description': 'When the internal '
                                                                            'Debug Console opens '
                                                                            'automatically.'},
                                                   'path': {'type': 'string',
                                                            'minLength': 1,
                                                            'description': 'Optional settings.json '
                                                                           'path; omit for active '
                                                                           'user settings.'}},
                                    'required': ['value'],
                                    'additionalProperties': False},
 'debugging.set_open_debug_view': {'description': 'Set only debug.openDebug. When VS Code opens '
                                                  'the Run and Debug view automatically. Other '
                                                  'settings are preserved.',
                                   'properties': {'value': {'type': 'string',
                                                            'enum': ['neverOpen',
                                                                     'openOnDebugBreak',
                                                                     'openOnFirstSessionStart',
                                                                     'openOnSessionStart'],
                                                            'description': 'When VS Code opens the '
                                                                           'Run and Debug view '
                                                                           'automatically.'},
                                                  'path': {'type': 'string',
                                                           'minLength': 1,
                                                           'description': 'Optional settings.json '
                                                                          'path; omit for active '
                                                                          'user settings.'}},
                                   'required': ['value'],
                                   'additionalProperties': False},
 'debugging.set_show_breakpoints_in_overview_ruler': {'description': 'Set only '
                                                                     'debug.showBreakpointsInOverviewRuler. '
                                                                     'Whether the editor overview '
                                                                     'ruler shows breakpoints. '
                                                                     'Other settings are '
                                                                     'preserved.',
                                                      'properties': {'value': {'type': 'boolean',
                                                                               'description': 'Whether '
                                                                                              'the '
                                                                                              'editor '
                                                                                              'overview '
                                                                                              'ruler '
                                                                                              'shows '
                                                                                              'breakpoints.'},
                                                                     'path': {'type': 'string',
                                                                              'minLength': 1,
                                                                              'description': 'Optional '
                                                                                             'settings.json '
                                                                                             'path; '
                                                                                             'omit '
                                                                                             'for '
                                                                                             'active '
                                                                                             'user '
                                                                                             'settings.'}},
                                                      'required': ['value'],
                                                      'additionalProperties': False},
 'debugging.set_show_inline_breakpoint_candidates': {'description': 'Set only '
                                                                    'debug.showInlineBreakpointCandidates. '
                                                                    'Whether inline breakpoint '
                                                                    'candidates are shown in the '
                                                                    'editor. Other settings are '
                                                                    'preserved.',
                                                     'properties': {'value': {'type': 'boolean',
                                                                              'description': 'Whether '
                                                                                             'inline '
                                                                                             'breakpoint '
                                                                                             'candidates '
                                                                                             'are '
                                                                                             'shown '
                                                                                             'in '
                                                                                             'the '
                                                                                             'editor.'},
                                                                    'path': {'type': 'string',
                                                                             'minLength': 1,
                                                                             'description': 'Optional '
                                                                                            'settings.json '
                                                                                            'path; '
                                                                                            'omit '
                                                                                            'for '
                                                                                            'active '
                                                                                            'user '
                                                                                            'settings.'}},
                                                     'required': ['value'],
                                                     'additionalProperties': False},
 'editor.set_minimap_enabled': {'description': 'Set only editor.minimap.enabled. Whether the '
                                               'editor minimap is visible. Other settings are '
                                               'preserved.',
                                'properties': {'value': {'type': 'boolean',
                                                         'description': 'Whether the editor '
                                                                        'minimap is visible.'},
                                               'path': {'type': 'string',
                                                        'minLength': 1,
                                                        'description': 'Optional settings.json '
                                                                       'path; omit for active user '
                                                                       'settings.'}},
                                'required': ['value'],
                                'additionalProperties': False},
 'editor.set_smooth_scrolling': {'description': 'Set only editor.smoothScrolling. Whether editor '
                                                'scrolling is animated smoothly. Other settings '
                                                'are preserved.',
                                 'properties': {'value': {'type': 'boolean',
                                                          'description': 'Whether editor scrolling '
                                                                         'is animated smoothly.'},
                                                'path': {'type': 'string',
                                                         'minLength': 1,
                                                         'description': 'Optional settings.json '
                                                                        'path; omit for active '
                                                                        'user settings.'}},
                                 'required': ['value'],
                                 'additionalProperties': False},
 'editor.set_sticky_scroll_enabled': {'description': 'Set only editor.stickyScroll.enabled. '
                                                     'Whether sticky scopes remain visible at the '
                                                     'editor top. Other settings are preserved.',
                                      'properties': {'value': {'type': 'boolean',
                                                               'description': 'Whether sticky '
                                                                              'scopes remain '
                                                                              'visible at the '
                                                                              'editor top.'},
                                                     'path': {'type': 'string',
                                                              'minLength': 1,
                                                              'description': 'Optional '
                                                                             'settings.json path; '
                                                                             'omit for active user '
                                                                             'settings.'}},
                                      'required': ['value'],
                                      'additionalProperties': False},
 'editor.set_wrap_tabs': {'description': 'Set only workbench.editor.wrapTabs. Whether editor tabs '
                                         'wrap onto multiple rows when horizontal space is '
                                         'insufficient. Other settings are preserved.',
                          'properties': {'value': {'type': 'boolean',
                                                   'description': 'Whether editor tabs wrap onto '
                                                                  'multiple rows when horizontal '
                                                                  'space is insufficient.'},
                                         'path': {'type': 'string',
                                                  'minLength': 1,
                                                  'description': 'Optional settings.json path; '
                                                                 'omit for active user settings.'}},
                          'required': ['value'],
                          'additionalProperties': False},
 'editor.set_word_wrap_column': {'description': 'Set only editor.wordWrapColumn. Positive editor '
                                                'column used by at_column or bounded wrapping. '
                                                'This may also be changed independently of the '
                                                'current word-wrap mode. Other settings are '
                                                'preserved.',
                                 'properties': {'value': {'type': 'integer',
                                                          'minimum': 1,
                                                          'maximum': 1000,
                                                          'description': 'Positive editor column '
                                                                         'used by at_column or '
                                                                         'bounded wrapping. This '
                                                                         'may also be changed '
                                                                         'independently of the '
                                                                         'current word-wrap mode.'},
                                                'path': {'type': 'string',
                                                         'minLength': 1,
                                                         'description': 'Optional settings.json '
                                                                        'path; omit for active '
                                                                        'user settings.'}},
                                 'required': ['value'],
                                 'additionalProperties': False},
 'editor.set_line_numbers': {'description': 'Set only editor.lineNumbers. Editor line-number '
                                            'display mode. Other settings are preserved.',
                             'properties': {'value': {'type': 'string',
                                                      'enum': ['interval', 'off', 'on', 'relative'],
                                                      'description': 'Editor line-number display '
                                                                     'mode.'},
                                            'path': {'type': 'string',
                                                     'minLength': 1,
                                                     'description': 'Optional settings.json path; '
                                                                    'omit for active user '
                                                                    'settings.'}},
                             'required': ['value'],
                             'additionalProperties': False},
 'editor.set_render_whitespace': {'description': 'Set only editor.renderWhitespace. Which '
                                                 'whitespace characters the editor renders '
                                                 'visibly. Other settings are preserved.',
                                  'properties': {'value': {'type': 'string',
                                                           'enum': ['all',
                                                                    'boundary',
                                                                    'none',
                                                                    'selection',
                                                                    'trailing'],
                                                           'description': 'Which whitespace '
                                                                          'characters the editor '
                                                                          'renders visibly.'},
                                                 'path': {'type': 'string',
                                                          'minLength': 1,
                                                          'description': 'Optional settings.json '
                                                                         'path; omit for active '
                                                                         'user settings.'}},
                                  'required': ['value'],
                                  'additionalProperties': False},
 'editor.set_word_wrap': {'description': 'Set only editor.wordWrap. Text wrapping behavior: off, '
                                         'on at the viewport, at_column at the configured column, '
                                         'or bounded at the smaller of viewport and column. Other '
                                         'settings are preserved.',
                          'properties': {'value': {'type': 'string',
                                                   'enum': ['at_column', 'bounded', 'off', 'on'],
                                                   'description': 'Text wrapping behavior: off, on '
                                                                  'at the viewport, at_column at '
                                                                  'the configured column, or '
                                                                  'bounded at the smaller of '
                                                                  'viewport and column.'},
                                         'path': {'type': 'string',
                                                  'minLength': 1,
                                                  'description': 'Optional settings.json path; '
                                                                 'omit for active user settings.'}},
                          'required': ['value'],
                          'additionalProperties': False},
 'files.set_insert_final_newline': {'description': 'Set only files.insertFinalNewline. Whether '
                                                   'saving inserts a final newline when missing. '
                                                   'Other settings are preserved.',
                                    'properties': {'value': {'type': 'boolean',
                                                             'description': 'Whether saving '
                                                                            'inserts a final '
                                                                            'newline when '
                                                                            'missing.'},
                                                   'path': {'type': 'string',
                                                            'minLength': 1,
                                                            'description': 'Optional settings.json '
                                                                           'path; omit for active '
                                                                           'user settings.'}},
                                    'required': ['value'],
                                    'additionalProperties': False},
 'files.set_trim_final_newlines': {'description': 'Set only files.trimFinalNewlines. Whether '
                                                  'saving removes extra final newlines. Other '
                                                  'settings are preserved.',
                                   'properties': {'value': {'type': 'boolean',
                                                            'description': 'Whether saving removes '
                                                                           'extra final newlines.'},
                                                  'path': {'type': 'string',
                                                           'minLength': 1,
                                                           'description': 'Optional settings.json '
                                                                          'path; omit for active '
                                                                          'user settings.'}},
                                   'required': ['value'],
                                   'additionalProperties': False},
 'files.set_trim_trailing_whitespace': {'description': 'Set only files.trimTrailingWhitespace. '
                                                       'Whether saving removes trailing '
                                                       'whitespace. Other settings are preserved.',
                                        'properties': {'value': {'type': 'boolean',
                                                                 'description': 'Whether saving '
                                                                                'removes trailing '
                                                                                'whitespace.'},
                                                       'path': {'type': 'string',
                                                                'minLength': 1,
                                                                'description': 'Optional '
                                                                               'settings.json '
                                                                               'path; omit for '
                                                                               'active user '
                                                                               'settings.'}},
                                        'required': ['value'],
                                        'additionalProperties': False},
 'files.set_auto_save': {'description': 'Set only files.autoSave. Automatic save mode: off, '
                                        'after_delay, on_focus_change, or on_window_change. Other '
                                        'settings are preserved.',
                         'properties': {'value': {'type': 'string',
                                                  'enum': ['after_delay',
                                                           'off',
                                                           'on_focus_change',
                                                           'on_window_change'],
                                                  'description': 'Automatic save mode: off, '
                                                                 'after_delay, on_focus_change, or '
                                                                 'on_window_change.'},
                                        'path': {'type': 'string',
                                                 'minLength': 1,
                                                 'description': 'Optional settings.json path; omit '
                                                                'for active user settings.'}},
                         'required': ['value'],
                         'additionalProperties': False},
 'files.set_auto_save_delay_ms': {'description': 'Set only files.autoSaveDelay. Delay in '
                                                 'milliseconds used by after_delay autosave; it '
                                                 'can be updated independently when that mode is '
                                                 'already active. Other settings are preserved.',
                                  'properties': {'value': {'type': 'integer',
                                                           'minimum': 1,
                                                           'maximum': 3600000,
                                                           'description': 'Delay in milliseconds '
                                                                          'used by after_delay '
                                                                          'autosave; it can be '
                                                                          'updated independently '
                                                                          'when that mode is '
                                                                          'already active.'},
                                                 'path': {'type': 'string',
                                                          'minLength': 1,
                                                          'description': 'Optional settings.json '
                                                                         'path; omit for active '
                                                                         'user settings.'}},
                                  'required': ['value'],
                                  'additionalProperties': False},
 'files.set_hot_exit': {'description': 'Set only files.hotExit. Whether unsaved editors are '
                                       'restored after exit. Other settings are preserved.',
                        'properties': {'value': {'type': 'string',
                                                 'enum': ['off',
                                                          'on_exit',
                                                          'on_exit_and_window_close'],
                                                 'description': 'Whether unsaved editors are '
                                                                'restored after exit.'},
                                       'path': {'type': 'string',
                                                'minLength': 1,
                                                'description': 'Optional settings.json path; omit '
                                                               'for active user settings.'}},
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
