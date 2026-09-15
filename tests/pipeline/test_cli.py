import json
from types import SimpleNamespace
from uuid import UUID,uuid4
import pytest
from app.core.config import Settings
from app.planning.models import Configuration
from app.pipeline.cli import main
from app.pipeline.service import DiagnosticService
from app.pipeline.trace import TraceStore
from app.speaker.models import VerificationResult
from tests.pipeline.helpers import STT,audio

def setup(tmp_path,text="open Spotify"):
    settings=Settings(planning=Configuration(trace_root=tmp_path/"artifacts"))
    service=DiagnosticService(settings,stt=STT(text))
    recorded=[]
    def record(*args,**kwargs):recorded.append(1);return SimpleNamespace(status="succeeded",audio=audio())
    recorder=SimpleNamespace(record=record,cancel=lambda:None)
    return settings,service,recorder,recorded

def run(args,tmp_path,answers=(),text="open Spotify"):
    settings,service,recorder,recorded=setup(tmp_path,text)
    replies=iter(answers);out=[];prompts=[]
    def read(prompt):prompts.append(prompt);return next(replies)
    code=main(args,settings=settings,service=service,recorder=recorder,read=read,write=out.append,control=lambda:None)
    return code,out,prompts,settings,recorded

def test_text_syntax_and_default_privacy(tmp_path):
    code,out,prompts,settings,calls=run(['unauthenticated-text','open Spotify'],tmp_path)
    assert code==0 and not calls and not prompts
    combined='\n'.join(out)
    for stage in ('MODE:','Capture:','Speech-to-text:','Command resolution:','Plan:','Risk:','Simulation:','Timings:'):
        assert stage in combined
    assert 'Open Spotify' not in combined and 'EXECUTION: DISABLED' in combined
    assert not settings.planning.trace_root.exists()

def test_text_json_optin(tmp_path):
    code,out,*_=run(['unauthenticated-text','open Spotify','--show-transcript','--json'],tmp_path)
    doc=json.loads(out[-1]);assert code==0 and doc['details']['canonical_command']=='Open Spotify'
    assert doc['authentication']=='unauthenticated_diagnostic' and not doc['execution_permitted']

def test_voice_without_saving(tmp_path):
    code,out,_,settings,calls=run(['unauthenticated-voice','--seconds','1','--show-transcript','--json'],tmp_path,[''])
    assert code==0 and calls==[1] and not settings.planning.trace_root.exists()
    assert all(isinstance(json.loads(line),dict) for line in out)
    assert json.loads(out[-1])['details']['raw_transcript']=='open Spotify'

@pytest.mark.parametrize('approve',['yes','no'])
def test_audio_consent(tmp_path,approve):
    code,out,prompts,settings,calls=run(['unauthenticated-voice','--seconds','1','--save-audio'],tmp_path,['',approve])
    assert code==0 and calls==[1]
    assert any('WAV' in p for p in prompts)
    files=list(settings.planning.trace_root.glob('*.vp-audio.wav'))
    assert len(files)==(approve=='yes')
    if files:assert str(files[0]) in '\n'.join(out)
    assert not settings.planning.audio_saving_enabled

@pytest.mark.parametrize('approve',['yes','no'])
@pytest.mark.parametrize('show',[True,False])
def test_trace_consent(tmp_path,approve,show):
    args=['unauthenticated-voice','--seconds','1','--save-trace']+(['--show-transcript'] if show else [])
    code,out,prompts,settings,calls=run(args,tmp_path,['',approve])
    assert code==0 and not settings.planning.trace_saving_enabled
    assert any(('INCLUDING' if show else 'WITHOUT') in p for p in prompts)
    files=list(settings.planning.trace_root.glob('*.vp-trace.json'))
    assert len(files)==(approve=='yes')
    if files:assert ('details' in json.loads(files[0].read_text()))==show

def test_trace_management_syntax(tmp_path):
    settings,service,recorder,calls=setup(tmp_path)
    trace=service.text('help')
    store=TraceStore(settings.planning.model_copy(update={'trace_saving_enabled':True}))
    store.save(trace,approved=True,include_text=True,text_approved=True)
    out=[]
    assert main(['traces','list'],settings=settings,write=out.append)==0
    assert str(trace.trace_id) in out[-1]
    assert main(['traces','inspect','--id',str(trace.trace_id),'--show-transcript'],settings=settings,write=out.append)==0
    assert json.loads(out[-1])['details']['raw_transcript']=='help'
    assert main(['traces','delete','--id',str(trace.trace_id)],settings=settings,read=lambda _:'no',write=out.append)==0
    assert store.path(trace.trace_id).exists()
    assert main(['traces','delete','--id',str(trace.trace_id)],settings=settings,read=lambda _:'yes',write=out.append)==0
    assert not store.path(trace.trace_id).exists()

def test_authenticated_pending_syntax(tmp_path):
    settings,service,recorder,calls=setup(tmp_path)
    def verify(a,p,*,audio_id,cancel=None):
        return VerificationResult(attempt_id=uuid4(),audio_id=audio_id,profile_id=p,status='unavailable',reason='calibration_pending')
    service.verifier=SimpleNamespace(verify=verify);out=[]
    assert main(['authenticated','--profile',str(uuid4()),'--seconds','1','--json'],settings=settings,service=service,
        recorder=recorder,read=lambda _:'',write=out.append,control=lambda:None)==2
    doc=json.loads(out[-1]);assert doc['reason']=='access_denied' and doc['stt_status']=='not_called'
    assert not service.stt.calls and calls==[1]

def test_cancel_no_artifacts(tmp_path):
    code,out,_,settings,calls=run(['unauthenticated-voice','--save-audio','--save-trace'],tmp_path,['cancel'])
    assert code==0 and not calls and not settings.planning.trace_root.exists()

def test_cancel_before_save_discards(tmp_path):
    settings,service,recorder,calls=setup(tmp_path);out=[];answers=iter([''])
    def read(prompt):
        if 'Persist' in prompt:raise KeyboardInterrupt()
        return next(answers)
    assert main(['unauthenticated-voice','--save-audio','--save-trace'],settings=settings,service=service,recorder=recorder,
        read=read,write=out.append,control=lambda:None)==0
    assert not settings.planning.trace_root.exists()
    assert 'raw_transcript' not in '\n'.join(out)

@pytest.mark.parametrize('seconds',['nan','inf','0','121'])
def test_invalid_capture_bound(tmp_path,seconds):
    code,out,_,_,calls=run(['unauthenticated-voice','--seconds',seconds],tmp_path)
    assert code==2 and not calls

def test_bounded_session(tmp_path):
    settings,service,recorder,calls=setup(tmp_path)
    settings=settings.model_copy(update={'planning':settings.planning.model_copy(update={'session_limit':2})})
    replies=iter(['','help']);out=[]
    assert main(['unauthenticated-text','help','--session','--json'],settings=settings,service=service,
        read=lambda _:next(replies),write=out.append)==0
    docs=[json.loads(x) for x in out]
    assert len(docs)==2 and docs[0]['session_id']==docs[1]['session_id']
    assert docs[0]['trace_id']!=docs[1]['trace_id']

def test_invalid_arguments_private(tmp_path):
    out=[];assert main(['traces','inspect','--id','PRIVATE_MARKER'],write=out.append)==2
    assert 'PRIVATE_MARKER' not in '\n'.join(out)


def test_voice_session_is_deliberate_and_bounded(tmp_path):
    settings,service,recorder,calls=setup(tmp_path)
    settings=settings.model_copy(update={'planning':settings.planning.model_copy(update={'session_limit':2})})
    answers=iter(['','','']);out=[]
    assert main(['unauthenticated-voice','--seconds','1','--session','--json'],settings=settings,
        service=service,recorder=recorder,read=lambda _:next(answers),write=out.append,control=lambda:None)==0
    traces=[json.loads(x) for x in out if 'trace_id' in json.loads(x)]
    assert calls==[1,1] and len(traces)==2
    assert traces[0]['session_id']==traces[1]['session_id']
    assert traces[0]['trace_id']!=traces[1]['trace_id']

def test_interactive_text_avoids_positional_input(tmp_path):
    code,out,_,_,calls=run(['unauthenticated-text','--json'],tmp_path,['help'])
    assert code==0 and not calls and json.loads(out[-1])['intent']=='help'


def test_sensitive_speech_cannot_be_saved_as_audio(tmp_path):
    code,out,prompts,settings,calls=run(['unauthenticated-voice','--save-audio','--show-transcript'],
        tmp_path,[''],text='password PRIVATE_MARKER')
    assert code==2 and calls==[1]
    assert not settings.planning.trace_root.exists()
    assert not any('Persist' in p for p in prompts)
    assert 'PRIVATE_MARKER' not in '\n'.join(out)
