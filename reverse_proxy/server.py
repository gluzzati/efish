# public_server.py - Run this on your public server
import asyncio
import json
import uuid
import websockets
from aiohttp import web
import logging
import ssl
import sys
import jwt
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TunnelManager:
    def __init__(self):
        self.tunnels = {}  # tunnel_id -> websocket
        self.pending_requests = {}  # request_id -> future
    
    async def register_tunnel(self, tunnel_id, websocket):
        self.tunnels[tunnel_id] = websocket
        logger.info(f"Tunnel registered: {tunnel_id}")
        
    async def unregister_tunnel(self, tunnel_id):
        if tunnel_id in self.tunnels:
            del self.tunnels[tunnel_id]
            logger.info(f"Tunnel unregistered: {tunnel_id}")
    
    async def forward_request(self, tunnel_id, method, path, headers, body):
        if tunnel_id not in self.tunnels:
            return None
            
        request_id = str(uuid.uuid4())
        request_data = {
            "type": "http_request",
            "request_id": request_id,
            "method": method,
            "path": path,
            "headers": dict(headers),
            "body": body.decode('utf-8') if body else ""
        }
        
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        
        try:
            await self.tunnels[tunnel_id].send(json.dumps(request_data))
            response = await asyncio.wait_for(future, timeout=30)
            return response
        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError) as e:
            logger.error(f"Tunnel error: {e}")
            return None
        finally:
            self.pending_requests.pop(request_id, None)
    
    async def handle_response(self, response_data):
        request_id = response_data.get("request_id")
        if request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                future.set_result(response_data)

# Global JWT secret - should be set via environment variable in production
JWT_SECRET = None

def verify_token(token):
    """Verify JWT token and return payload"""
    try:
        if not JWT_SECRET:
            logger.error("JWT secret not configured")
            return None
        
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        
        # Check if token is expired
        if payload.get('exp') and payload.get('exp') < time.time():
            logger.warning("Token expired")
            return None
            
        return payload
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid token: {e}")
        return None

tunnel_manager = TunnelManager()

async def websocket_handler(websocket):
    tunnel_id = None
    try:
        registration = await websocket.recv()
        reg_data = json.loads(registration)
        
        if reg_data.get("type") == "register":
            # Verify authentication token
            token = reg_data.get("token")
            if not token:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Authentication token required"
                }))
                return
            
            payload = verify_token(token)
            if not payload:
                await websocket.send(json.dumps({
                    "type": "error", 
                    "message": "Invalid authentication token"
                }))
                return
            
            tunnel_id = reg_data.get("tunnel_id")
            if not tunnel_id:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Tunnel ID required"
                }))
                return
            
            await tunnel_manager.register_tunnel(tunnel_id, websocket)
            
            await websocket.send(json.dumps({
                "type": "registered",
                "tunnel_id": tunnel_id
            }))
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "http_response":
                        await tunnel_manager.handle_response(data)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                    
    except websockets.exceptions.ConnectionClosed:
        logger.info("WebSocket connection closed")
    finally:
        if tunnel_id:
            await tunnel_manager.unregister_tunnel(tunnel_id)

async def http_proxy_handler(request):
    tunnel_id = request.match_info.get('tunnel_id')
    path = request.match_info.get('path', '')
    
    if not tunnel_id:
        return web.Response(text="Tunnel ID required", status=400)
    
    # Build local path
    local_path = f"/{path}" if path else "/"
    
    # Security: Basic path traversal check
    if '..' in local_path:
        logger.warning(f"Path traversal attempt blocked: {local_path}")
        return web.Response(text="Path traversal not allowed", status=403)
    
    body = await request.read()
    
    logger.info(f"Proxying {request.method} {request.path} -> {tunnel_id} {local_path}")
    
    response_data = await tunnel_manager.forward_request(
        tunnel_id=tunnel_id,
        method=request.method,
        path=local_path,
        headers=request.headers,
        body=body
    )
    
    if not response_data:
        request.transport.close()
        return
    
    return web.Response(
        text=response_data.get("body", ""),
        status=response_data.get("status", 200),
        headers=response_data.get("headers", {})
    )

async def main():
    global JWT_SECRET
    
    # Parse command line arguments
    args = sys.argv[1:]
    
    # JWT secret (required for authentication)
    if len(args) >= 1:
        JWT_SECRET = args[0]
        logger.info("JWT authentication enabled")
    else:
        logger.error("JWT secret required. Usage: python server.py <jwt_secret> [cert.pem] [key.pem]")
        return
    
    websocket_server = websockets.serve(websocket_handler, "0.0.0.0", 45413)
    
    app = web.Application()
    app.router.add_route('*', '/{tunnel_id}', http_proxy_handler)
    app.router.add_route('*', '/{tunnel_id}/{path:.*}', http_proxy_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # SSL configuration (optional)
    ssl_context = None
    if len(args) >= 3:
        cert_file = args[1]
        key_file = args[2]
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_file, key_file)
        logger.info(f"SSL enabled with cert: {cert_file}")
    
    if ssl_context:
        site = web.TCPSite(runner, '0.0.0.0', 45415, ssl_context=ssl_context)
        logger.info("Tunnel server started:")
        logger.info("- WebSocket server on port 45413")
        logger.info("- HTTPS proxy on port 45415")
    else:
        site = web.TCPSite(runner, '0.0.0.0', 45415)
        logger.info("Tunnel server started:")
        logger.info("- WebSocket server on port 45413")
        logger.info("- HTTP proxy on port 45415")
    
    await site.start()
    await asyncio.gather(websocket_server, asyncio.Event().wait())

if __name__ == "__main__":
    asyncio.run(main())