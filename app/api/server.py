"""Explicit opt-in loopback transport; never serves files or starts capture."""
from http.server import HTTPServer, BaseHTTPRequestHandler
from app.api.application import Application
from app.api.models import Error
from app.session.models import SessionError


class Handler(BaseHTTPRequestHandler):
    server_version = "VoicePilot"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass  # Request paths, headers and exceptions never enter logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(2.)

    def handle_request(self):
        app = self.server.application
        try:
            if any(len(self.headers.get_all(name,[])) > 1 for name in
                   ("Host","Origin","Content-Length","Content-Type","X-VoicePilot-Request")):
                raise SessionError()
            if self.headers.get("Transfer-Encoding") is not None: raise SessionError()
            length = self.headers.get("Content-Length","0")
            if not length.isascii() or not length.isdigit() or len(length) > 6: raise SessionError()
            length = int(length)
            if length > app.config.max_request_bytes:
                response = app.response(413,Error(error="body_limit"))
            else:
                body = self.rfile.read(length)
                if len(body) != length: raise SessionError()
                response = app.dispatch(self.command,self.path,dict(self.headers),body)
        except Exception:
            response = app.response(400,Error(error="invalid_request"))
        self.send_response(response.status)
        for key,value in response.headers.items(): self.send_header(key,value)
        self.send_header("Content-Length",str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)
        self.close_connection = True

    do_GET = do_POST = do_DELETE = do_OPTIONS = do_PUT = do_PATCH = do_HEAD = handle_request

    def send_error(self, code, message=None, explain=None):
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Connection","close")
        self.end_headers()
        self.wfile.write(Error(error="invalid_request").model_dump_json().encode("utf-8"))
        self.close_connection = True


class Server(HTTPServer):
    allow_reuse_address = False
    request_queue_size = 4

    def handle_error(self, request, client_address):
        pass


def serve(config, *, factory=Server):
    if not config.enabled or config.host != "127.0.0.1": raise SessionError("disabled")
    application = Application(config)
    server = None
    try:
        server = factory((config.host,config.port),Handler)
        server.application = application
        server.serve_forever(poll_interval=.25)
    finally:
        application.close()
        if server is not None: server.server_close()
