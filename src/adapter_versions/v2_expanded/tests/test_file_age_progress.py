from integrations.lite_agent.file_age_progress import model_progress
from integrations.lite_agent.state_model import RuntimeState,ExecutionEvent


def test_age_requires_real_guest_clock_then_advances_to_artifacts():
    state=RuntimeState(task_id='synthetic',domain='os',
        instruction='Compress all files under "/tmp/example" that were last modified 17 days ago',events=[])
    progress=model_progress(state)
    assert progress['suggested_argv'][2].startswith('date -Is; date -d "17 days ago"')
    assert '-mtime 17' in progress['suggested_argv'][2]
    state.events.append(ExecutionEvent(step=1,timestamp_utc='',executed=True,
        proposed={'kind':'adapter','action':'command.run','arguments':{'argv':progress['suggested_argv']}},
        result={'context_hint':{'stdout':'/tmp/example/old.txt 2026-10-01'}}))
    progress=model_progress(state)
    assert progress['stage']=='archive_and_verify_age_groups'
    assert progress['guest_age_observations'][0]['stdout']=='/tmp/example/old.txt 2026-10-01'
    state.instruction='Move every text file'
    assert model_progress(state) is None


def test_compression_receipts_advance_to_integrity_without_reclassifying_outputs():
    state=RuntimeState(task_id='synthetic',domain='os',
        instruction='Compress all files under "/tmp/example" that were last modified 17 days ago',events=[
        ExecutionEvent(step=1,timestamp_utc='',executed=True,
            proposed={'kind':'adapter','action':'command.run','arguments':{
                'argv':['bash','-c','date -Is; find /tmp/example -type f -mtime 17 -printf output']}},
            result={'context_hint':{'stdout':'/tmp/example/a 2026-10-01 10:00:00\n'}}),
        ExecutionEvent(step=2,timestamp_utc='',executed=True,
            proposed={'kind':'adapter','action':'archive.compress_file','arguments':{
                'source':'/tmp/example/a','destination':'/tmp/example/a.gz','remove_source':True}})])
    progress=model_progress(state)
    assert progress['stage']=='test_actual_archives'
    state.events.append(ExecutionEvent(step=3,timestamp_utc='',executed=True,
        proposed={'kind':'adapter','action':'command.run','arguments':{'argv':progress['suggested_argv']}},
        result={'context_hint':{'returncode':0,'stdout':''}}))
    assert model_progress(state)['stage']=='complete_verified_archives'
