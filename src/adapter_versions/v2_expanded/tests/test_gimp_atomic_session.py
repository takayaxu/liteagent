from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
import gimp_adapter.edit_session as sessions
from gimp_adapter.schema import parse_action_request
from gimp_adapter.errors import AdapterError
from integrations.openapa_osworld.tool_catalog import public_actions
from integrations.lite_agent.tool_catalog import build_tools,search_actions

class Runner:
    def __init__(self):
        self.operations=[]
        self.exports=[]
    def _run_image_operation(self,source,output,operation,**kwargs):
        self.operations.append((source,output,operation,kwargs))
        assert not kwargs.get('open_in_gui')
        Path(output).write_bytes(b'private xcf checkpoint')
        preview=output+'.preview.png'
        Image.new('RGB',(8,8),(120,80,40)).save(preview)
        return {'output_path':output,'preview_path':preview,'metadata':{'width':8,'height':8}}
    def export(self,source,output,**kwargs):
        self.exports.append((source,output))
        Image.new('RGB',(8,8),(120,80,40)).save(output)
        return {'output_path':output,'preview_path':output,'metadata':{'width':8,'height':8}}


def test_independent_effects_do_not_export_or_open_gui_and_keep_source(tmp_path,monkeypatch):
    monkeypatch.setattr(sessions,'SESSION_ROOT',tmp_path/'private')
    source=tmp_path/'source.png'
    Image.new('RGB',(8,8)).save(source)
    original=source.read_bytes()
    runner=Runner()
    lifecycle=SimpleNamespace(prepare=lambda *args:pytest.fail('no implicit GUI opening'))
    state,check=sessions.execute_session('image.open_session',{'path':str(source)},runner,lifecycle,1)
    assert check['passed'] and len(runner.operations)==1
    image_id=state['image_id']
    for action,operation in [('image.set_brightness','(gimp-brightness-contrast drawable 0 0)'),
                              ('image.set_contrast','(gimp-brightness-contrast drawable 0 0)'),
                              ('image.set_saturation','(gimp-hue-saturation drawable 0 0 0 0)')]:
        value=0
        params={'image_id':image_id,'value':value}
        parse_action_request({'action':action,'params':params})
        result,check=sessions.execute_session(action,params,runner,lifecycle,1)
        assert runner.operations[-1][2]==operation
        assert check['passed']
    assert not runner.exports and source.read_bytes()==original
    output=tmp_path/'user-output.png'
    saved,check=sessions.execute_session('image.save_session',{'image_id':image_id,'output_path':str(output)},runner,lifecycle,1)
    assert check['passed'] and saved['output_path']==str(output)
    assert len(runner.exports)==1 and output.exists()


def test_failed_effect_does_not_advance_edit_state(tmp_path,monkeypatch):
    monkeypatch.setattr(sessions,'SESSION_ROOT',tmp_path/'private')
    source=tmp_path/'source.png'
    Image.new('RGB',(8,8)).save(source)
    runner=Runner()
    state,_=sessions.execute_session('image.open_session',{'path':str(source)},runner,None,1)
    pointer=tmp_path/'private'/state['image_id']/'state.json'
    before=pointer.read_bytes()
    monkeypatch.setattr(sessions,'verify_specs',lambda *args:{'passed':False})
    with pytest.raises(AdapterError):
        sessions.execute_session('image.set_contrast',{'image_id':state['image_id'],'value':10},runner,None,1)
    assert pointer.read_bytes()==before


def test_legacy_and_multi_effect_calls_are_rejected():
    assert 'image.adjust' not in public_actions('gimp')
    with pytest.raises(AdapterError):
        parse_action_request({'action':'image.adjust','params':{}})
    for action in sessions.EFFECTS:
        tool=build_tools('gimp',[action],include_gui=False,include_control_tools=False,strict_generic=True)[0]
        assert set(tool['function']['parameters']['properties'])=={'image_id','value'}
        with pytest.raises(AdapterError):
            parse_action_request({'action':action,'params':{'image_id':'a'*32,'value':0,'output_path':'/tmp/leak.png'}})
        with pytest.raises(AdapterError):
            parse_action_request({'action':action,'params':{'image_id':'../escape','value':0}})

@pytest.mark.parametrize('domain',['gimp','multi_apps'])
def test_brightness_discovery_exposes_load_and_independent_effect(domain):
    actions=[m.get('downstream_action',m['action']) for m in search_actions(domain,'image brightness',strict_generic=True)]
    assert 'image.set_brightness' in actions
    assert 'image.adjust' not in actions
