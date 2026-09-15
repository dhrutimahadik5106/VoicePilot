"""Deliberate diagnostic CLI. No automatic retention or executable adapters."""
import argparse
import json
from threading import Event
from time import perf_counter
from uuid import UUID,uuid4
from app.core.config import Settings
from app.planning.models import PlanningError
from app.pipeline.service import DiagnosticService,SpeakerInspection
from app.pipeline.trace import TraceStore

class Parser(argparse.ArgumentParser):
    def error(self,message): raise PlanningError("invalid_artifact")

def render(document,write):
    write("MODE: "+document["mode"].upper()+" | "+document["authentication"].upper())
    write("DIAGNOSTIC / SIMULATION | EXECUTION: DISABLED | Real actions: 0")
    write("Trace: "+document["trace_id"]+" | UTC: "+document["utc_timestamp"])
    write(f"Capture: {document['duration']:.3f}s; audio saved: {document['audio_saved']}")
    write("Speech-to-text: "+document["stt_status"]+"; language: "+str(document["language"]))
    details=document.get("details")
    if details:
        for field in ("raw_transcript","stt_normalized_transcript","resolver_normalized_transcript","canonical_command"):
            write(field.replace("_"," ")+": "+json.dumps(details[field],ensure_ascii=True))
        write("Resolved entities: "+json.dumps(details["entities"],ensure_ascii=True))
    else: write("Transcript and entity text: hidden (explicit --show-transcript required)")
    write("Command resolution: "+document["resolver_status"]+"; intent: "+str(document["intent"]))
    write("Resolver evidence: "+", ".join(document["resolver_reasons"]))
    plan=document.get("plan")
    if plan:
        write("Plan: "+plan["status"])
        descriptions={"launch":"Propose application launch","search_media":"Propose media search",
            "play_media":"Propose playback","control_media":"Propose playback control",
            "volume":"Propose volume adjustment","present":"Present simulated help","verify":"Check simulated observation"}
        for step in plan["steps"]:
            write(f"  {step['order']}. {descriptions[step['action']]} [simulated]; depends on {step['dependencies']}")
        write(f"Risk: {plan['overall_risk']}; confirmation: {plan['requires_confirmation']}")
    simulation=document.get("simulation")
    write("Simulation: "+(simulation["status"] if simulation else "not run"))
    write("Diagnostic run: "+document["status"]+"; reason: "+document["reason"])
    write(f"Timings: capture={document['capture_seconds']:.3f}s STT={document['stt_seconds']:.3f}s planning={document['planning_seconds']:.3f}s total={document['total_seconds']:.3f}s")

def main(argv=None,*,settings=None,service=None,recorder=None,read=input,write=print,control=None):
    parser=Parser(description="Explicit diagnostic/simulation tools; never execution")
    sub=parser.add_subparsers(dest="mode",required=True)
    for mode in ("unauthenticated-text","unauthenticated-voice","authenticated"):
        p=sub.add_parser(mode)
        if mode=="unauthenticated-text": p.add_argument("text",nargs="?")
        else: p.add_argument("--seconds",type=float,default=8)
        if mode=="authenticated":
            p.add_argument("--profile",type=UUID,required=True)
            p.add_argument("--policy",type=UUID)
        p.add_argument("--session",action="store_true")
        p.add_argument("--show-transcript",action="store_true")
        p.add_argument("--save-trace",action="store_true")
        if mode!="unauthenticated-text": p.add_argument("--save-audio",action="store_true")
        p.add_argument("--json",action="store_true")
    p=sub.add_parser("traces")
    p.add_argument("action",choices=["list","inspect","delete"])
    p.add_argument("--id",type=UUID)
    p.add_argument("--show-transcript",action="store_true")
    event=Event()
    try:
        args=parser.parse_args(argv);settings=settings or Settings();cfg=settings.planning
        if args.mode!="traces":
            cfg=cfg.model_copy(update={"trace_saving_enabled":args.save_trace,"audio_saving_enabled":getattr(args,"save_audio",False)})
        store=TraceStore(cfg)
        reader=read
        if getattr(args,"json",False) and read is input:
            import sys
            def reader(prompt):
                print(prompt,file=sys.stderr)
                return read()
        def notice(message):
            if getattr(args,"json",False):
                write(json.dumps({"label":"diagnostic/simulation","mode":args.mode,"event":"notice","message":message,"execution_permitted":False}))
            else: write(message)
        def yes(prompt): return reader(prompt+" Type yes to approve: ").strip().lower()=="yes"
        if args.mode=="traces":
            if args.action=="list": write(json.dumps({"label":"diagnostic artifacts; not history","execution_permitted":False,"traces":[str(x) for x in store.list_ids()]}));return 0
            if args.id is None: raise PlanningError("invalid_artifact")
            if args.action=="inspect": write(json.dumps(store.load(args.id,include_text=args.show_transcript),sort_keys=True));return 0
            if not yes("Delete only this selected diagnostic trace? Saved audio is separate."): raise PlanningError("cancelled")
            store.delete(args.id,approved=True);write("DIAGNOSTIC: selected trace deleted. Execution disabled.");return 0
        if args.mode!="unauthenticated-text":
            import math
            if not math.isfinite(args.seconds) or not .1<=args.seconds<=min(settings.audio_max_duration_seconds,settings.stt_max_duration_seconds): raise PlanningError()
        service=service or DiagnosticService(settings,verifier=SpeakerInspection(settings,getattr(args,"policy",None)) if args.mode=="authenticated" else None)
        session_id=uuid4()
        for turn in range(cfg.session_limit if args.session else 1):
            audio=None
            if args.mode=="unauthenticated-text":
                text=args.text if turn==0 and args.text is not None else reader("DIAGNOSTIC text (blank cancels): ")
                if not text: raise PlanningError("cancelled")
                trace=service.text(text,session_id=session_id,cancel=event)
            else:
                notice("DIAGNOSTIC / SIMULATION. Execution disabled. Authentication: "+("required; pending policy denies access" if args.mode=="authenticated" else "UNAUTHENTICATED"))
                if reader("Press Enter to START one capture; type anything to cancel: ")!="": raise PlanningError("cancelled")
                if recorder is None:
                    from app.audio.recorder import SoundDeviceRecorder
                    recorder=SoundDeviceRecorder(settings)
                if control is None:
                    from app.audio.cli import terminal_control
                    control=terminal_control
                start=perf_counter();captured=recorder.record(args.seconds,control=control)
                if captured.status!="succeeded": raise PlanningError("cancelled" if captured.status=="cancelled" else "unavailable")
                audio=captured.audio
                trace=service.audio(audio,authenticated=args.mode=="authenticated",profile_id=getattr(args,"profile",None),
                    session_id=session_id,cancel=event,capture_seconds=max(0,perf_counter()-start))
            if trace.status=="cancelled" or event.is_set(): raise PlanningError("cancelled")
            if trace.reason=="sensitive_input" and audio is not None:
                notice("Sensitive input withheld; diagnostic audio persistence is unavailable.")
                audio=None
            if getattr(args,"save_audio",False) and audio is not None:
                if yes("Persist this diagnostic WAV locally? It may contain private speech."):
                    path=store.save_audio(trace.trace_id,audio,approved=True,cancel=event)
                    trace=trace.model_copy(update={"audio_saved":True})
                    notice("DIAGNOSTIC audio explicitly saved: "+str(path))
            if args.save_trace:
                if yes("Persist this diagnostic trace"+(" INCLUDING displayed transcripts/entities?" if args.show_transcript else " WITHOUT transcripts?")):
                    path=store.save(trace,approved=True,include_text=args.show_transcript,text_approved=args.show_transcript,cancel=event)
                    notice("DIAGNOSTIC trace explicitly saved: "+str(path))
            document=trace.public(include_text=args.show_transcript)
            if args.json: write(json.dumps(document,sort_keys=True))
            else: render(document,write)
            del audio
            if not args.session: return 0 if trace.status=="completed" else 2
            if turn+1>=cfg.session_limit: break
            if reader("Enter for another diagnostic turn; anything else finishes: ")!="": break
        return 0
    except (KeyboardInterrupt,EOFError):
        event.set()
        if recorder is not None: recorder.cancel()
        write('{"label":"diagnostic/simulation","status":"cancelled","execution_permitted":false}')
        return 0
    except PlanningError as error:
        write(json.dumps({"label":"diagnostic/simulation","status":"cancelled" if error.code=="cancelled" else "blocked","reason":error.code,"execution_permitted":False}))
        return 0 if error.code=="cancelled" else 2
    except Exception:
        write('{"label":"diagnostic/simulation","status":"blocked","reason":"unavailable","execution_permitted":false}')
        return 2

if __name__=="__main__": raise SystemExit(main())
