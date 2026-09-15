from types import SimpleNamespace
import numpy as np
from app.audio.models import RecordedAudio,AudioFormat
from app.stt.models import TranscriptionResult,TranscriptSegment,SafeTranscriptionError

def audio():
    samples=(np.sin(np.arange(16000)*.04)*4000).astype(np.int16)
    return RecordedAudio(format=AudioFormat(),samples=samples[:,None])

def transcription(audio_id,text=" help ",status="succeeded"):
    return TranscriptionResult(audio_id=audio_id,text=text.strip() if status=="succeeded" else "",
        segments=(TranscriptSegment(text=text,start=0,end=.5),) if status=="succeeded" else (),
        language="en" if status=="succeeded" else None,processing_duration=.02,inference_duration=.01,
        source_audio_duration=1,model_name="fake",device="cpu",compute_type="int8",status=status,
        error=None if status=="succeeded" else SafeTranscriptionError(code="cancelled" if status=="cancelled" else "unusable_audio"))

class STT:
    def __init__(self,text=" help ",status="succeeded"):
        self.text,self.status=text,status;self.calls=[]
    def transcribe_audio(self,audio,*,audio_id,cancel=None):
        self.calls.append((audio,audio_id))
        return transcription(audio_id,self.text,self.status)
