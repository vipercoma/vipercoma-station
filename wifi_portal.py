"""Small redirect endpoint used only while the local setup hotspot is active."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self): self.redirect()
    def do_HEAD(self): self.redirect()
    def do_POST(self): self.redirect()
    def redirect(self):
        self.send_response(302)
        self.send_header("Location", "http://10.77.0.1:8080/setup")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()
    def log_message(self, *_): pass

ThreadingHTTPServer(("10.77.0.1", 80), Handler).serve_forever()
