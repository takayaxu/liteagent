from types import SimpleNamespace
from integrations.lite_agent.terminal_default_progress import model_progress


def event(step,action,args=None,body=None):
    return SimpleNamespace(step=step,executed=True,error=None,proposed={'kind':'adapter','action':action,'arguments':args or {}},result=body or {})


def state(events):
    return SimpleNamespace(domain='os',instruction='Set terminal to 110x35 permanently after reboot',events=events)


def test_saved_defaults_are_not_actual_window_verification():
    s=state([])
    assert model_progress(s)['next_setting']=={'key':'default-size-columns','value':110}
    s.events=[event(1,'terminal.default_profile.set_setting',{'key':'default-size-columns','value':110},{'result':{'key':'default-size-columns','value':110}}),
              event(2,'terminal.default_profile.set_setting',{'key':'default-size-rows','value':35},{'result':{'key':'default-size-rows','value':35}})]
    assert model_progress(s)['stage']=='open_new_terminal'
    s.events.append(event(3,'command.run',{'argv':['echo','35 110']}))
    assert model_progress(s)['stage']=='open_new_terminal'
    s.events.append(event(4,'terminal.launch',{'argv':['bash']}))
    p=model_progress(s)
    assert p['stage']=='type_real_tty_probe'
    s.events.append(SimpleNamespace(step=5,executed=True,error=None,proposed={'kind':'gui','arguments':{'action':'type','text':'stty size'}},result={}))
    assert model_progress(s)['stage']=='submit_real_tty_probe'
    s.events.append(SimpleNamespace(step=6,executed=True,error=None,proposed={'kind':'gui','arguments':{'action':'press','key':'enter'}},result={}))
    assert model_progress(s)['stage']=='review_actual_tty_output'


def test_unrelated_terminal_requests_unchanged():
    s=state([])
    s.instruction='Show current terminal time'
    assert model_progress(s) is None
