#!/usr/bin/env python3
"""
Simple HTTP Server that serves "It works!" message
Usage: python simple_server.py [port]
Default port: 8000
"""

import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.parse

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>It Works!</title>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    text-align: center; 
                    margin-top: 100px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    min-height: 100vh;
                    margin: 0;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                }}
                h1 {{ font-size: 3em; margin-bottom: 20px; }}
                p {{ font-size: 1.2em; }}
                .info {{ 
                    background: rgba(255,255,255,0.1); 
                    padding: 20px; 
                    border-radius: 10px; 
                    margin: 20px auto;
                    max-width: 500px;
                }}
            </style>
        </head>
        <body>
            <h1>🎉 It Works! 🎉</h1>
            <div class="info">
                <p><strong>Path:</strong> {self.path}</p>
                <p><strong>Method:</strong> {self.command}</p>
                <p><strong>Server:</strong> Python HTTP Server</p>
                <p><strong>Time:</strong> <span id="time"></span></p>
            </div>
            <p>Your server is running successfully!</p>
            
            <script>
                document.getElementById('time').textContent = new Date().toLocaleString();
            </script>
        </body>
        </html>
        """
        
        self.wfile.write(html.encode())
    
    def do_POST(self):
        """Handle POST requests"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response = {
            "status": "success",
            "message": "It works! POST received",
            "path": self.path,
            "method": self.command,
            "headers": dict(self.headers),
            "body": post_data.decode('utf-8', errors='ignore')
        }
        
        self.wfile.write(json.dumps(response, indent=2).encode())
    
    def do_PUT(self):
        """Handle PUT requests"""
        self.do_POST()  # Same logic as POST
    
    def do_DELETE(self):
        """Handle DELETE requests"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response = {
            "status": "success",
            "message": "It works! DELETE received",
            "path": self.path,
            "method": self.command
        }
        
        self.wfile.write(json.dumps(response, indent=2).encode())
    
    def do_OPTIONS(self):
        """Handle OPTIONS requests (CORS preflight)"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
    
    def log_message(self, format, *args):
        """Custom log format"""
        print(f"[{self.date_time_string()}] {self.client_address[0]} - {format % args}")

def main():
    # Get port from command line or use default
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Invalid port number. Using default port 8000.")
    
    # Create and start server
    server_address = ('', port)
    httpd = HTTPServer(server_address, SimpleHandler)
    
    print(f"🚀 Server starting on http://localhost:{port}")
    print(f"📡 Also accessible via http://0.0.0.0:{port}")
    print("Press Ctrl+C to stop the server")
    print("-" * 50)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
        httpd.server_close()

if __name__ == "__main__":
    main()