"""Conservative deterministic policy, not an intent recognizer or safety guarantee."""
import re
from app.planning.models import Risk

SENSITIVE=re.compile(r"password|credential|api.?key|secret|token\s*[:=]|bearer\s|sk-[A-Za-z0-9]{12,}|ghp_[A-Za-z0-9]+|AKIA[A-Z0-9]{16}|https?://[^/\s]+:[^/\s]+@|\u092a\u093e\u0938\u0935\u0930\u094d\u0921",re.I)
PROHIBITED=re.compile(r"\b(?:buy|purchase|pay|payment|delete|erase|format|powershell|shell|python|exec|eval|subprocess|sudo|rm|settings|credentials?)\b|\$\(|```|\u092a\u093e\u0938\u0935\u0930\u094d\u0921|\u092d\u0941\u0917\u0924\u093e\u0928|\u0916\u0930\u0940\u0926|\u092e\u093f\u091f\u093e|\u0939\u091f\u093e\u0913|\u0921\u093f\u0932\u0940\u091f|\u092a\u0948\u0938\u0947",re.I)
COMMUNICATION=re.compile(r"\b(?:send|email|message)\b|\u092d\u0947\u091c|\u092a\u093e\u0920\u0935",re.I)

def input_risk(resolution):
    text=resolution.raw_transcript
    if SENSITIVE.search(text) or PROHIBITED.search(text): return Risk.PROHIBITED
    if COMMUNICATION.search(text): return Risk.HIGH
    if resolution.status!="resolved" or resolution.requires_confirmation: return Risk.MODERATE
    return Risk.INFORMATIONAL
