from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    
    def log_message(self, format, *args):
        pass  # Suppress logs

def keep_alive():
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    print("Keep-alive server started on port 8080")
