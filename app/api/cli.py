"""Safe metadata/evaluation CLI; only explicit enabled serve opens a loopback socket."""
import argparse
import json
from app.core.config import Settings
from app.api.application import PREFIX, ROUTES
from app.session.catalog import capabilities
from app.session.models import SessionError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SessionError()


def main(argv=None, *, settings=None, write=print, server=None):
    try:
        parser = Parser(description="VoicePilot local API; production voice locked; no automatic capture")
        parser.add_argument("command",choices=("inspect-config","routes","capabilities","evaluate-demo","serve"))
        args = parser.parse_args(argv)
        config = (settings or Settings()).api
        if args.command == "inspect-config": write(config.model_dump_json())
        elif args.command == "routes": write(json.dumps([{"method":method,"path":PREFIX+path} for method,path in ROUTES]))
        elif args.command == "capabilities": write(json.dumps([entry.model_dump() for entry in capabilities()]))
        elif args.command == "evaluate-demo":
            from app.session.evaluation import evaluate
            report = evaluate()
            write(json.dumps(report))
            if report["correct"]["numerator"] != report["correct"]["denominator"]: return 2
        else:
            if not config.enabled: raise SessionError("disabled")
            write(json.dumps({"host":config.host,"port":config.port,"demo_enabled":config.demo_enabled,
                "production_available":False,"reason":"calibration_blocked","capture_on_startup":False}))
            if server is None:
                from app.api.server import serve
                server = serve
            server(config)
        return 0
    except KeyboardInterrupt:
        write('{"status":"cancelled"}')
        return 2
    except Exception as error:
        write(json.dumps({"error":error.code if type(error) is SessionError else "invalid_request"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
