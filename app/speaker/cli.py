"""Explicit local speaker tools. Inspection never captures or opens personal profiles."""
import argparse
import json
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from uuid import UUID
from app.core.config import Settings
from app.speaker.evaluate import synthetic_demo
from app.speaker.models import SpeakerProfile
from app.speaker.contracts import SpeakerError

class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")

def runtime_status():
    try:
        return "installed" if version("sherpa-onnx")=="1.13.8" and version("sherpa-onnx-core")=="1.13.8" else "incompatible"
    except PackageNotFoundError:
        return "unavailable"

def main(argv=None, *, write=print, read=input, settings=None, session_factory=None):
    parser=SafeParser(description="Local speaker verification; real capture requires --interactive and consent.")
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("inspect-status","inspect-policy","validate-schema","inspect-model",
                 "provision-model","smoke-backend","smoke-dpapi"):
        sub.add_parser(name)
    for name in ("enroll","verify","command"):
        cmd=sub.add_parser(name)
        cmd.add_argument("--interactive",action="store_true")
        cmd.add_argument("--profile",type=UUID)
        cmd.add_argument("--policy",type=UUID)
        cmd.add_argument("--diagnostics",action="store_true")
    profiles=sub.add_parser("profiles")
    profiles.add_argument("action",choices=["list","delete"])
    profiles.add_argument("--interactive",action="store_true")
    profiles.add_argument("--profile",type=UUID)
    evaluation=sub.add_parser("evaluate")
    evaluation.add_argument("--synthetic",required=True,action="store_true")
    calibration=sub.add_parser("calibration")
    calibration.add_argument("action",choices=["init","record","freeze","evaluate","approve"])
    calibration.add_argument("--interactive",action="store_true")
    calibration.add_argument("--profile",type=UUID)
    calibration.add_argument("--speaker",type=UUID)
    calibration.add_argument("--session",type=UUID)
    calibration.add_argument("--group",type=UUID)
    calibration.add_argument("--frozen",type=UUID)
    calibration.add_argument("--split",choices=["development","validation","test"],default="validation")
    calibration.add_argument("--language",choices=["en","hi","mr","mixed"],default="en")
    calibration.add_argument("--condition",choices=["quiet","noise","other"],default="quiet")
    calibration.add_argument("--acceptance",type=float)
    calibration.add_argument("--review",type=float)
    session=None
    try:
        args=parser.parse_args(argv)
        settings=settings or Settings()
        cfg=settings.speaker
        from app.speaker.artifacts import DEFAULT_PATH, inspect_model, provision
        path=cfg.model_path or DEFAULT_PATH
        if args.command=="evaluate":
            result=synthetic_demo().model_dump(mode="json")
        elif args.command=="validate-schema":
            SpeakerProfile.model_json_schema()
            result={"schema_version":1,"status":"valid","biometric_values_displayed":False}
        elif args.command=="inspect-policy":
            result={"status":"calibration_pending","acceptance":cfg.acceptance_threshold,
                    "review":cfg.rejection_threshold,"authorizes_pipeline":False}
        elif args.command=="inspect-status":
            result={"phase":"4B","runtime":runtime_status(),"model":"inspect-model",
                "protection":"smoke-dpapi required","authorization":"disabled_until_reviewed_policy",
                "status":"unavailable","spoof_assurance":"not_assessed"}
        elif args.command=="inspect-model":
            result=inspect_model(path)
        elif args.command=="provision-model":
            result=provision(path)
        elif args.command=="smoke-dpapi":
            from app.speaker.dpapi import DPAPIProtector
            result=DPAPIProtector().smoke()
        elif args.command=="smoke-backend":
            import numpy as np
            from app.audio.models import AudioFormat,RecordedAudio
            from app.speaker.sherpa_backend import SherpaEmbeddingEngine
            rate=16000
            seconds=max(cfg.min_duration,min(4.,cfg.max_duration))
            wave=(np.sin(np.arange(int(rate*seconds))*2*np.pi*220/rate)*4000).astype(np.int16)
            audio=RecordedAudio(format=AudioFormat(),samples=wave[:,None])
            vector=SherpaEmbeddingEngine(path,cfg).extract(audio)
            result={"status":"ready","dimension":len(vector),"finite":bool(np.isfinite(vector).all()),
                    "normalized":bool(np.isclose(np.linalg.norm(vector),1)),"biometric_data_used":False}
        else:
            if not args.interactive:
                write('{"status":"unavailable","reason":"explicit_interactive_action_required"}')
                return 2
            if session_factory is None:
                from app.speaker.interactive import LocalSpeakerSession
                session_factory=LocalSpeakerSession
            session=session_factory(settings,read=read,write=write)
            if args.command=="enroll":
                result=session.enroll(args.profile)
            elif args.command in ("verify","command"):
                profile=args.profile or cfg.default_profile_id
                if profile is None:
                    raise SpeakerError("invalid_profile")
                result=session.verify(profile,policy_id=args.policy,diagnostics=args.diagnostics,
                                      command=args.command=="command")
            elif args.command=="profiles":
                if args.action=="list":
                    result={"profiles":[str(x) for x in session.repository().list_ids()]}
                elif args.profile is not None:
                    result=session.delete(args.profile)
                else:
                    raise SpeakerError("invalid_profile")
            elif args.command=="calibration":
                from app.speaker.calibration import freeze,evaluate_private,approve_frozen
                if args.action=="record":
                    if any(value is None for value in (args.profile,args.speaker,args.session,args.group)):
                        raise SpeakerError("invalid_profile")
                    result=session.collect(args)
                else:
                    session.approve("Consent to private biometric calibration metadata processing?")
                    if args.action=="init":
                        session.protector.smoke()
                        session.records(create=True)
                        result={"status":"initialized","audio_saved":False,"calibration":"pending"}
                    elif args.action=="freeze":
                        if args.acceptance is None:
                            raise SpeakerError("calibration_pending")
                        key=freeze(session.records(),session.engine.identity,args.acceptance,args.review,consent=True)
                        result={"frozen_id":str(key),"calibration":"pending"}
                    elif args.action=="evaluate" and args.frozen is not None:
                        result=evaluate_private(session.records(),args.frozen,args.split,consent=True)
                    elif args.action=="approve" and args.frozen and args.profile:
                        session.write("Review required: engineering evidence floors do not prove security. "
                                      "Replay/deepfake protection is absent; high-risk actions need another factor.")
                        session.approve("Have you reviewed the validation report and explicitly approve this experimental threshold?")
                        key=approve_frozen(session.records(),session.repository(),args.frozen,args.profile,reviewed=True)
                        result={"approved_policy_id":str(key),"enabled_automatically":False}
                    else:
                        raise SpeakerError("invalid_profile")
        write(json.dumps(result,sort_keys=True))
        return 2 if args.command != "inspect-status" and result.get("status") in {"unavailable","invalid_profile","invalid_audio","rejected","uncertain","blocked"} else 0
    except (KeyboardInterrupt,EOFError):
        if session is not None:
            session.cancel.set()
            if session.recorder is not None:
                session.recorder.cancel()
        write('{"status":"cancelled","reason":"cancelled"}')
        return 0
    except SpeakerError as error:
        write(json.dumps({"status":"cancelled" if error.code=="cancelled" else "invalid_audio" if error.code=="invalid_audio" else "unavailable","reason":error.code}))
        return 2
    except Exception:
        write('{"status":"unavailable","reason":"invalid_configuration_or_arguments"}')
        return 2

if __name__=="__main__":
    raise SystemExit(main())
