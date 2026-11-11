from integrations.lite_agent.column_merge_progress import model_progress
from integrations.lite_agent.state_model import RuntimeState,ExecutionEvent


def test_merge_launch_and_verification_stages_follow_actual_events():
    state=RuntimeState(task_id='synthetic',domain='multi_apps',
        instruction='Use command line to merge columns by concatenating rows',events=[])
    assert model_progress(state)['stage']=='prepare_and_merge_columns'
    state.events.append(ExecutionEvent(step=1,timestamp_utc='',executed=True,
        proposed={'kind':'adapter','action':'adapter.call','arguments':{'adapter':'os',
            'action':'command.run','payload':{'params':{
                'argv':['bash','-c','paste -d "" /tmp/a.csv /tmp/b.csv'],
                'stdout_path':'/tmp/result.csv'}}}}))
    assert model_progress(state)['stage']=='open_csv_from_visible_terminal'
    state.events.append(ExecutionEvent(step=2,timestamp_utc='',executed=True,
        proposed={'kind':'adapter','action':'adapter.call','arguments':{'adapter':'os',
            'action':'command.run','payload':{'params':{
                'argv':['libreoffice','--calc','/tmp/result.csv'],'terminal':True}}}}))
    assert model_progress(state)['stage']=='verify_open_csv'
    state.events[-1].error={'failed':True}
    assert model_progress(state)['stage']=='open_csv_from_visible_terminal'
    state.instruction='Merge pictures'
    assert model_progress(state) is None
