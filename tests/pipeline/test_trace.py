from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from threading import Event
import json
import io
import wave
import pytest
from app.core.config import Settings
from app.planning.models import Configuration,PlanningError
from app.pipeline.service import DiagnosticService
from app.pipeline.trace import TraceStore
from app.pipeline.models import Trace,Details
from tests.pipeline.helpers import audio

@pytest.fixture
def store(tmp_path):
    return TraceStore(Configuration(trace_root=tmp_path/"diagnostics",trace_saving_enabled=True,audio_saving_enabled=True))

@pytest.fixture
def trace():return DiagnosticService(Settings()).text("open Spotify")

@pytest.mark.parametrize("kind",["audio","trace","text"])
def test_operation_consent(store,trace,kind):
    with pytest.raises(PlanningError,match="consent_required"):
        if kind=="audio":store.save_audio(trace.trace_id,audio())
        elif kind=="text":store.save(trace,approved=True,include_text=True)
        else:store.save(trace)
    assert not store.root().exists()

@pytest.mark.parametrize("kind",["audio","trace"])
def test_configuration_required(tmp_path,trace,kind):
    store=TraceStore(Configuration(trace_root=tmp_path/"diagnostics"))
    with pytest.raises(PlanningError,match="consent_required"):
        if kind=="audio":store.save_audio(trace.trace_id,audio(),approved=True)
        else:store.save(trace,approved=True)
    assert not store.root().exists()

def test_trace_roundtrip_optin_and_delete(store,trace):
    p=store.save(trace,approved=True,include_text=True,text_approved=True)
    assert store.list_ids()==[trace.trace_id]
    assert "details" not in store.load(trace.trace_id)
    assert store.load(trace.trace_id,include_text=True)["details"]["raw_transcript"]=="open Spotify"
    with pytest.raises(PlanningError,match="already_exists"):store.save(trace,approved=True)
    with pytest.raises(PlanningError,match="consent_required"):store.delete(trace.trace_id)
    store.delete(trace.trace_id,approved=True)
    assert not p.exists()

def test_metadata_only(store,trace):
    p=store.save(trace,approved=True)
    assert b'raw_transcript' not in p.read_bytes() and b'Open Spotify' not in p.read_bytes()
    assert 'details' not in store.load(trace.trace_id,include_text=True)

def test_exact_wav_roundtrip(store,trace):
    a=audio();p=store.save_audio(trace.trace_id,a,approved=True)
    with wave.open(str(p),'rb') as w:
        assert w.getframerate()==16000 and w.getnchannels()==1 and w.getnframes()==16000
        assert w.readframes(16000)==a.samples.astype('<i2').tobytes()
    with pytest.raises(PlanningError,match="already_exists"):store.save_audio(trace.trace_id,a,approved=True)

@pytest.mark.parametrize("key",['../outside','C:/outside',None,'not-a-uuid'])
def test_bad_identifier(store,key):
    with pytest.raises(PlanningError):store.path(key)

def test_suffix_traversal(store):
    with pytest.raises(PlanningError):store.path(uuid4(),'/../../outside')

def test_reparse_rejected(store,monkeypatch):
    monkeypatch.setattr(Path,'is_junction',lambda p:True)
    with pytest.raises(PlanningError):store.list_ids()

def test_repo_and_sync_root_rejected(tmp_path):
    from app.speaker.profiles import REPO
    for root in (REPO/'diagnostics',tmp_path/'OneDrive'/'diagnostics'):
        with pytest.raises(PlanningError):TraceStore(Configuration(trace_root=root)).root()

def test_bounds(store,trace):
    small=TraceStore(store.configuration.model_copy(update={'max_trace_bytes':1024,'max_audio_duration':.5}))
    with pytest.raises(PlanningError,match='size_limit'):small.save(trace,approved=True)
    with pytest.raises(PlanningError,match='size_limit'):small.save_audio(trace.trace_id,audio(),approved=True)
    assert not store.root().exists()

def test_cancel_before_commit(store,trace,monkeypatch):
    import app.pipeline.trace as module
    event=Event();original=module.os.fsync
    def sync(fd):original(fd);event.set()
    monkeypatch.setattr(module.os,'fsync',sync)
    with pytest.raises(PlanningError,match='cancelled'):store.save(trace,approved=True,cancel=event)
    assert list(store.root().iterdir())==[]

def test_failed_publication_safe(store,trace,monkeypatch):
    import app.pipeline.trace as module
    def fail(*args):raise OSError('PRIVATE_PATH')
    monkeypatch.setattr(module.os,'link',fail)
    with pytest.raises(PlanningError) as error:store.save(trace,approved=True)
    assert 'PRIVATE_PATH' not in str(error.value)
    assert list(store.root().iterdir())==[]

@pytest.mark.parametrize('change',[{'embedding':[1,2,3]},{'similarity':.9},{'execution_permitted':True},{'utc_timestamp':'2026-01-01T00:00:00'}])
def test_corrupt_artifacts(store,trace,change):
    p=store.save(trace,approved=True);doc=json.loads(p.read_text());doc.update(change);p.write_text(json.dumps(doc))
    with pytest.raises(PlanningError):store.load(trace.trace_id,include_text=True)

def test_saved_size_bound(store,trace):
    p=store.save(trace,approved=True);p.write_bytes(b'x'*(store.configuration.max_trace_bytes+1))
    with pytest.raises(PlanningError,match='size_limit'):store.load(trace.trace_id)

def test_credentials_in_any_private_field_rejected(trace):
    doc=trace.details.model_dump();doc['canonical_command']='password PRIVATE_MARKER'
    with pytest.raises(Exception) as error:Details(**doc)
    assert 'PRIVATE_MARKER' not in str(error.value)+repr(error.value)

def test_cancelled_trace_not_saved(store,trace):
    cancelled=DiagnosticService(Settings()).text('help',cancel=type('C',(),{'is_set':lambda self:True})())
    with pytest.raises(PlanningError,match='cancelled'):store.save(cancelled,approved=True)
