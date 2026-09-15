"""Explicit approved artifacts, not automatic history. Atomic bounded storage."""
import io
import json
import os
from pathlib import Path
import tempfile
from uuid import UUID
from app.planning.models import PlanningError
from app.pipeline.models import Trace, Details
from app.planning.risk import SENSITIVE

class TraceStore:
    def __init__(self,configuration): self.configuration=configuration
    def root(self):
        from app.speaker.private_store import private_root
        try:
            value=self.configuration.trace_root
            if value is None:
                local=os.environ.get("LOCALAPPDATA")
                if not local: raise ValueError()
                value=Path(local)/"VoicePilot"/"diagnostics"
            return private_root(value)
        except Exception: raise PlanningError("invalid_artifact") from None
    def path(self,key,suffix=".vp-trace.json"):
        if suffix not in {".vp-trace.json",".vp-audio.wav"}: raise PlanningError("invalid_artifact")
        if not isinstance(key,UUID): raise PlanningError("invalid_artifact")
        path=self.root()/(str(key)+suffix)
        if path.is_symlink() or path.is_junction(): raise PlanningError("invalid_artifact")
        return path
    def _write(self,key,data,suffix,cancel=None):
        temporary=None
        try:
            if cancel is not None and cancel.is_set(): raise PlanningError("cancelled")
            path=self.path(key,suffix)
            path.parent.mkdir(parents=True,exist_ok=True)
            self.path(key,suffix)
            if path.exists(): raise PlanningError("already_exists")
            with tempfile.NamedTemporaryFile(dir=path.parent,prefix=".vp-diagnostic-",suffix=".tmp",delete=False) as stream:
                temporary=Path(stream.name);stream.write(data);stream.flush();os.fsync(stream.fileno())
            if cancel is not None and cancel.is_set(): raise PlanningError("cancelled")
            self.path(key,suffix)
            os.link(temporary,path)  # Atomic no-overwrite publication.
            return path
        except PlanningError: raise
        except FileExistsError: raise PlanningError("already_exists") from None
        except Exception: raise PlanningError("invalid_artifact") from None
        finally:
            if temporary is not None:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass
    def save(self,trace,*,approved=False,include_text=False,text_approved=False,cancel=None):
        if not self.configuration.trace_saving_enabled or approved is not True or include_text and text_approved is not True: raise PlanningError("consent_required")
        if not isinstance(trace,Trace): raise PlanningError("invalid_artifact")
        trace=Trace.model_validate(trace.model_dump()|{"details":trace.details})
        if trace.status=="cancelled": raise PlanningError("cancelled")
        doc=trace.public(include_text=include_text)
        if "details" in doc and SENSITIVE.search(json.dumps(doc["details"])): raise PlanningError("invalid_artifact")
        doc["artifact_label"]="explicitly approved diagnostic artifact; not automatic history"
        data=json.dumps(doc,allow_nan=False,ensure_ascii=True).encode()
        if len(data)>self.configuration.max_trace_bytes: raise PlanningError("size_limit")
        return self._write(trace.trace_id,data,".vp-trace.json",cancel)
    def save_audio(self,key,audio,*,approved=False,cancel=None):
        if not self.configuration.audio_saving_enabled or approved is not True: raise PlanningError("consent_required")
        if audio.duration>self.configuration.max_audio_duration: raise PlanningError("size_limit")
        from app.audio.wav import write_pcm_wav
        stream=io.BytesIO();write_pcm_wav(audio,stream);data=stream.getvalue()
        if len(data)>int(48000*2*2*self.configuration.max_audio_duration)+128: raise PlanningError("size_limit")
        return self._write(key,data,".vp-audio.wav",cancel)
    def load(self,key,*,include_text=False):
        try:
            with self.path(key).open("rb") as source: data=source.read(self.configuration.max_trace_bytes+1)
            if len(data)>self.configuration.max_trace_bytes: raise PlanningError("size_limit")
            doc=json.loads(data)
            if doc.pop("artifact_label")!="explicitly approved diagnostic artifact; not automatic history": raise ValueError()
            details=doc.pop("details",None)
            trace=Trace.model_validate(doc)
            if doc!=trace.public(): raise ValueError()
            if trace.trace_id!=key: raise ValueError()
            if details is not None:
                details=Details.model_validate(details)
                if SENSITIVE.search(details.raw_transcript): raise ValueError()
                trace=trace.model_copy(update={"details":details})
            return trace.public(include_text=include_text)
        except PlanningError: raise
        except Exception: raise PlanningError("invalid_artifact") from None
    def list_ids(self):
        try:
            from itertools import islice
            files=tuple(islice(self.root().glob("*.vp-trace.json"),1001))
            if len(files)>1000: raise PlanningError("size_limit")
            ids=tuple(UUID(p.name.removesuffix(".vp-trace.json")) for p in files)
            for key in ids: self.path(key)
            return sorted(ids,key=str)
        except PlanningError: raise
        except Exception: raise PlanningError("invalid_artifact") from None
    def delete(self,key,*,approved=False):
        if approved is not True: raise PlanningError("consent_required")
        try: self.path(key).unlink()
        except Exception: raise PlanningError("invalid_artifact") from None
