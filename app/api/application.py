"""In-process HTTP dispatch; no socket, capture or native resource access."""
from dataclasses import dataclass
import json
import re
from uuid import UUID

from app.planning.models import Model
from app.session.models import Configuration, SessionError
from app.session.service import SessionService
from app.session.catalog import capabilities
from app.api.models import (Empty, CreateDemo, Clarify, Confirm, Status, Catalog, Privacy,
                            Events, History, Acknowledged, Error)

ROUTES = (
    ("GET","/health"),("GET","/status"),("GET","/capabilities"),("GET","/applications"),
    ("GET","/system"),("GET","/calibration"),("GET","/privacy"),
    ("POST","/demo/sessions"),("POST","/sessions"),("GET","/sessions/{id}"),
    ("GET","/sessions/{id}/events"),("POST","/sessions/{id}/activate"),
    ("POST","/sessions/{id}/capture/stop"),("POST","/sessions/{id}/capture/cancel"),
    ("POST","/sessions/{id}/clarify"),("POST","/sessions/{id}/confirm"),
    ("POST","/sessions/{id}/cancel"),("GET","/history"),("DELETE","/history/{id}"),
    ("DELETE","/history"),("POST","/emergency-stop"),("POST","/emergency-stop/reset"),
)
PREFIX = "/api/v1"
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict
    body: bytes


class Application:
    def __init__(self, config=None, *, service=None):
        self.config = config or Configuration()
        self.service = service or SessionService(self.config)

    def response(self, status, document, origin=None):
        if not isinstance(document, Model): raise SessionError()
        headers = {"Content-Type":"application/json", "Cache-Control":"no-store", "X-Content-Type-Options":"nosniff",
                   "Referrer-Policy":"no-referrer", "Vary":"Origin", "Connection":"close"}
        if origin in self.config.allowed_origins: headers["Access-Control-Allow-Origin"] = origin
        body = document.model_dump_json().encode("utf-8")
        if len(body) > 1048576:
            return Response(500,headers,Error(error="unavailable").model_dump_json().encode("utf-8"))
        return Response(status,headers,body)

    def dispatch(self, method, path, headers=None, body=b""):
        origin = None
        try:
            normalized = {}
            for key,value in (headers or {}).items():
                if key.lower() in normalized: raise SessionError()
                normalized[key.lower()] = value
            headers = normalized
            origin = headers.get("origin")
            if headers.get("host") != "127.0.0.1:" + str(self.config.port):
                return self.response(403,Error(error="host_denied"))
            if origin is not None and origin not in self.config.allowed_origins:
                return self.response(403,Error(error="origin_denied"))
            if type(path) is not str or len(path) > 160 or "?" in path or "%" in path or not path.startswith(PREFIX + "/"):
                return self.response(404,Error(error="not_found"),origin)
            route = path[len(PREFIX):]
            matched = [(m,p) for m,p in ROUTES if re.fullmatch(p.replace("{id}",UUID_PATTERN),route)]
            if not matched: return self.response(404,Error(error="not_found"),origin)
            if method == "OPTIONS":
                requested = headers.get("access-control-request-method")
                requested_headers = {x.strip().lower() for x in headers.get("access-control-request-headers","").split(",") if x.strip()}
                if origin is None or requested not in {m for m,_ in matched} or not requested_headers <= {"content-type","x-voicepilot-request"}:
                    return self.response(403,Error(error="origin_denied"),origin)
                result = self.response(200,Empty(),origin)
                result.headers.update({"Access-Control-Allow-Methods":", ".join(sorted({m for m,_ in matched})),
                    "Access-Control-Allow-Headers":"Content-Type, X-VoicePilot-Request"})
                return result
            if method not in {m for m,_ in matched}:
                return self.response(405,Error(error="method_not_allowed"),origin)
            if type(body) is not bytes or len(body) > self.config.max_request_bytes:
                return self.response(413,Error(error="body_limit"),origin)
            if method == "GET":
                if body: raise SessionError()
            else:
                if origin is None or headers.get("x-voicepilot-request") != "1":
                    return self.response(403,Error(error="origin_denied"),origin)
                if headers.get("content-type") != "application/json":
                    return self.response(415,Error(error="content_type"),origin)
            schema = CreateDemo if route == "/demo/sessions" else Clarify if route.endswith("/clarify") else Confirm if route.endswith("/confirm") else Empty
            if method != "GET":
                # Duplicate JSON keys are rejected rather than silently reinterpreted.
                def pairs(items):
                    result = {}
                    for key,value in items:
                        if key in result: raise SessionError()
                        result[key] = value
                    return result
                json.loads(body, object_pairs_hook=pairs)
                request = schema.model_validate_json(body)
            else: request = Empty()
            document = self.route(method,route,request)
            return self.response(200,document,origin)
        except SessionError as error:
            code = error.code if error.code != "ok" else "invalid_request"
            return self.response(404 if code == "not_found" else 400 if code == "invalid_request" else 409,Error(error=code),origin)
        except Exception:
            return self.response(400,Error(error="invalid_request"),origin)

    def route(self, method, path, request):
        service = self.service
        if path in {"/health","/status","/calibration"}:
            return Status(emergency_stopped=service.hub.stopped.is_set())
        if path in {"/capabilities","/applications","/system"}:
            entries = capabilities()
            if path == "/applications": entries = tuple(c for c in entries if c.capability_id.startswith("application."))
            if path == "/system": entries = tuple(c for c in entries if c.capability_id.startswith("system."))
            return Catalog(capabilities=entries)
        if path == "/privacy": return Privacy(history_limit=self.config.max_history,event_limit=self.config.max_events)
        if path == "/demo/sessions": return service.create(request.scenario,request.show_transcript)
        if path == "/sessions": return service.production()
        if path == "/emergency-stop":
            service.emergency_stop()
            return Acknowledged(result="emergency_stopped")
        if path == "/emergency-stop/reset": return service.reset_emergency_stop()
        if path == "/history":
            with service.lock:
                if method == "DELETE":
                    service.history.clear()
                    return Acknowledged(result="cleared")
                for session in tuple(service.sessions.values()): session.check()
                return History(entries=tuple(service.history),limit=self.config.max_history)
        if path.startswith("/history/"):
            key = UUID(path.rsplit("/",1)[1])
            with service.lock:
                entry = next((row for row in service.history if row.session_id == key),None)
                if entry is None: raise SessionError("not_found")
                service.history.remove(entry)
            return Acknowledged(result="deleted")
        pieces = path.split("/")
        key = UUID(pieces[2])
        suffix = "/".join(pieces[3:])
        if suffix == "events":
            with service.lock:
                service.action(key,"view")
                events = tuple(service.sessions[key].events)
                return Events(events=events,first_sequence=events[0].sequence if events else 0,
                              last_sequence=events[-1].sequence if events else 0)
        action = {"":"view","activate":"activate","capture/stop":"stop_capture","capture/cancel":"cancel",
                  "cancel":"cancel","clarify":"clarify","confirm":"confirm"}[suffix]
        return service.action(key,action,**request.model_dump())

    def close(self):
        self.service.close()
