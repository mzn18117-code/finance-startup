from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write("BOT IS RUNNING".encode())

def run():
    server = HTTPServer(("0.0.0.0", 8080), H)
    server.serve_forever()
