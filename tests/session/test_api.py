"""In-process API and byte-stream HTTP tests; no sockets or persistent servers."""
import io
import json
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
from app.api.application import Application, ROUTES
from app.api.server import Handler, serve
from app.api.cli import main
from app.core.config import Settings
from app.session.models import Configuration, SessionError, State
from app.session.catalog import capabilities


HEADERS={"Host":"127.0.0.1:8765","Origin":"http://127.0.0.1:5173",
         "Content-Type":"application/json","X-VoicePilot-Request":"1"}


def call(app,method,path,data=None,headers=None):
    response=app.dispatch(method,"/api/v1"+path,HEADERS if headers is None else headers,
                          json.dumps(data if data is not None else {}).encode() if method!="GET" else b"")
    return response.status,json.loads(response.body)


@pytest.mark.parametrize("path",["/health","/status","/capabilities","/applications","/system","/calibration","/privacy","/history"])
def test_read_routes_no_hardware(service,path):
    app=Application(service=service)
    status,body=call(app,"GET",path)
    assert status==200 and body
    assert app.service.sessions=={}


def test_complete_api_session_routes_and_history(service):
    app=Application(service=service)
    status,view=call(app,"POST","/demo/sessions",{"scenario":"ambiguous_application"})
    key=view["session_id"]
    assert status==200
    assert call(app,"GET","/sessions/"+key)[0]==200
    assert call(app,"POST",f"/sessions/{key}/activate")[1]["listening"]
    status,view=call(app,"POST",f"/sessions/{key}/capture/stop")
    assert view["state"]=="needs_clarification"
    status,view=call(app,"POST",f"/sessions/{key}/clarify",{"request_id":view["clarification"]["request_id"],"candidate_id":"chrome"})
    status,view=call(app,"POST",f"/sessions/{key}/confirm",{"request_id":view["confirmation"]["request_id"],"decision":"confirm"})
    assert status==200 and view["verified"] and not view["execution_permitted"]
    assert call(app,"GET",f"/sessions/{key}/events")[1]["last_sequence"]>0
    assert len(call(app,"GET","/history")[1]["entries"])==1
    assert call(app,"DELETE","/history/"+key)[0]==200
    assert call(app,"DELETE","/history")[0]==200
    assert call(app,"GET","/history")[1]["entries"]==[]
    assert call(app,"DELETE","/history/"+key)[0]==404


@pytest.mark.parametrize("path",["capture/cancel","cancel"])
def test_cancel_routes(service,path):
    app=Application(service=service)
    key=call(app,"POST","/demo/sessions",{"scenario":"read_volume"})[1]["session_id"]
    call(app,"POST",f"/sessions/{key}/activate")
    status,body=call(app,"POST",f"/sessions/{key}/{path}")
    assert status==200 and body["state"]=="cancelled" and body["waveform"]==[]
    assert body["banner"] == "DEMO / SIMULATION — NO REAL ACTION"


def test_emergency_and_production_routes(service):
    app=Application(service=service)
    assert call(app,"POST","/sessions")[1]["error"]=="calibration_blocked"
    assert call(app,"POST","/emergency-stop")[0]==200
    assert call(app,"GET","/status")[1]["emergency_stopped"]
    assert call(app,"POST","/emergency-stop/reset")[1]["error"]=="reset_unavailable"
    assert call(app,"POST","/demo/sessions",{"scenario":"read_volume"})[0]==409


@pytest.mark.parametrize("field,value",[("profile","PRIVATE"),("authenticated",True),("confirmed",True),
    ("command","open private"),("risk","safe"),("path","C:/private"),("adapter","module.Class"),("url","https://private")])
def test_unknown_fields_never_evidence(service,field,value):
    app=Application(service=service)
    status,body=call(app,"POST","/demo/sessions",{"scenario":"read_volume",field:value})
    assert status==400 and body["error"]=="invalid_request" and not service.sessions


@pytest.mark.parametrize("body",[b'{"scenario":"read_volume","scenario":"calculator_confirm"}',b'null',b'[]',b'{',b'{"scenario":true}',b'{"scenario":"read_volume","show_transcript":1}'])
def test_strict_json(service,body):
    response=Application(service=service).dispatch("POST","/api/v1/demo/sessions",HEADERS,body)
    assert 400 <= response.status < 500


@pytest.mark.parametrize("host",["localhost:8765","evil.test:8765","127.0.0.1.evil:8765","0.0.0.0:8765","127.0.0.1:80"])
def test_host_binding(service,host):
    assert call(Application(service=service),"GET","/health",headers=HEADERS|{"Host":host})[0]==403


@pytest.mark.parametrize("origin",["null","https://evil.test","http://localhost:5173","http://127.0.0.1:5174","*"])
def test_cors_denial(service,origin):
    response=Application(service=service).dispatch("GET","/api/v1/health",HEADERS|{"Origin":origin})
    assert response.status==403 and "Access-Control-Allow-Origin" not in response.headers


def test_csrf_preflight_and_content_type(service):
    app=Application(service=service)
    for removed in ("Origin","X-VoicePilot-Request"):
        headers={k:v for k,v in HEADERS.items() if k!=removed}
        assert call(app,"POST","/demo/sessions",{"scenario":"read_volume"},headers)[0]==403
    for content in ("text/plain","application/x-www-form-urlencoded","application/json; charset=utf-8"):
        assert call(app,"POST","/demo/sessions",{},HEADERS|{"Content-Type":content})[0]==415
    response=app.dispatch("OPTIONS","/api/v1/demo/sessions",HEADERS|{"Access-Control-Request-Method":"POST",
        "Access-Control-Request-Headers":"content-type, x-voicepilot-request"})
    assert response.status==200 and response.headers["Access-Control-Allow-Origin"]==HEADERS["Origin"]
    assert app.dispatch("OPTIONS","/api/v1/demo/sessions",HEADERS|{"Access-Control-Request-Method":"PUT"}).status==403


@pytest.mark.parametrize("path",["/../private","/sessions/%2f","/health?profile=PRIVATE","/files","/health/","/sessions/PRIVATE"])
def test_path_allowlist(service,path):
    status,body=call(Application(service=service),"GET",path)
    assert status==404 and "PRIVATE" not in json.dumps(body)


@pytest.mark.parametrize("method",["PUT","PATCH","HEAD","TRACE","CONNECT","DELETE"])
def test_method_allowlist(service,method):
    assert call(Application(service=service),method,"/health")[0]==405


def test_body_response_bounds_and_no_cache(service):
    app=Application(service=service)
    response=app.dispatch("POST","/api/v1/demo/sessions",HEADERS,b" "*4097)
    assert response.status==413 and len(response.body)<256
    assert response.headers["Cache-Control"]=="no-store"
    assert app.dispatch("GET","/api/v1/health",HEADERS,b"{}").status==400
    assert app.dispatch("GET","/api/v1/health",HEADERS|{"host":"evil"}).status==400


@pytest.mark.parametrize("field,value",[("host","0.0.0.0"),("host","localhost"),("port",True),("port",65536),
    ("allowed_origins",("*",)),("allowed_origins",("http://evil:5173",)),("max_sessions",True),
    ("production_enabled",True),("tts_enabled",True),("wake_word_enabled",True),("permanent_history_enabled",True)])
def test_config_fail_closed(field,value):
    with pytest.raises(Exception): Configuration(**{field:value})


def test_catalog_truth():
    rows={c.capability_id:c for c in capabilities()}
    assert rows["application.launch.spotify"].route=="manual_only"
    assert rows["application.launch.chrome"].availability=="not_probed"
    assert rows["brightness.mutation"].implemented is False
    assert rows["system.volume.read"].risk=="informational"
    assert rows["screen.screenshot.capture"].risk=="sensitive"


@pytest.mark.parametrize("command",["inspect-config","routes","capabilities","evaluate-demo"])
def test_safe_cli(command):
    output=[]
    assert main([command],write=output.append)==0
    assert json.loads(output[-1])
    assert main([command,"--profile","PRIVATE"],write=output.append)==2
    assert "PRIVATE" not in output[-1]


def test_serve_disabled_and_fake_shutdown():
    calls=[]
    class FakeServer:
        def __init__(self,address,handler):
            assert address==("127.0.0.1",8765) and handler is Handler
            calls.append("constructed")
        def serve_forever(self,**kwargs): calls.append("served")
        def server_close(self):
            assert self.application.service.closed
            calls.append("closed")
    with pytest.raises(SessionError): serve(Configuration(),factory=FakeServer)
    assert calls==[]
    serve(Configuration(enabled=True),factory=FakeServer)
    assert calls==["constructed","served","closed"]
    output=[]
    assert main(["serve"],write=output.append)==2
    assert main(["serve"],settings=Settings(api=Configuration(enabled=True)),write=output.append,
                server=lambda config:calls.append("cli_served"))==0
    assert calls[-1]=="cli_served"


class Connection:
    def __init__(self,request): self.input=io.BytesIO(request); self.output=io.BytesIO(); self.timeouts=[]
    def makefile(self,mode,*args): return self.input
    def sendall(self,data): self.output.write(data)
    def settimeout(self,value): self.timeouts.append(value)


@pytest.mark.parametrize("framing",[b"Content-Length: 0\r\nContent-Length: 2\r\n",b"Transfer-Encoding: chunked\r\n",b"Content-Length: -1\r\n",b"Content-Length: 5000\r\n"])
def test_http_framing_no_socket(service,framing):
    connection=Connection(b"POST /api/v1/demo/sessions HTTP/1.0\r\nHost: 127.0.0.1:8765\r\n"+framing+b"\r\n")
    Handler(connection,("127.0.0.1",1),SimpleNamespace(application=Application(service=service)))
    response=connection.output.getvalue()
    assert b"400" in response or b"413" in response
    assert b"Traceback" not in response and connection.timeouts==[2.]


def test_http_valid_health_no_socket(service):
    connection=Connection(b"GET /api/v1/health HTTP/1.0\r\nHost: 127.0.0.1:8765\r\n\r\n")
    Handler(connection,("127.0.0.1",1),SimpleNamespace(application=Application(service=service)))
    assert b"200 OK" in connection.output.getvalue() and b'"production_available":false' in connection.output.getvalue()


def test_shutdown_after_server_exception():
    closed=[]
    class FailedServer:
        def __init__(self,*args): pass
        def serve_forever(self,**kwargs): raise RuntimeError("synthetic_failure")
        def server_close(self): closed.append(self.application.service.closed)
    with pytest.raises(RuntimeError): serve(Configuration(enabled=True),factory=FailedServer)
    assert closed==[True]


def test_demo_error_envelope(service):
    status,body=call(Application(service=service),"POST","/demo/sessions",{"scenario":"unknown"})
    assert status==400 and body["mode"]=="synthetic_demo"
    assert body["banner"] == "DEMO / SIMULATION — NO REAL ACTION"
    assert body["simulation"] is True and body["execution_permitted"] is False and body["real_actions"]==0
