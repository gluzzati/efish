# public_server.py - Run this on your public server
import asyncio
import json
import uuid
import websockets
from aiohttp import web
import logging

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

tunnel_manager = TunnelManager()

async def websocket_handler(websocket):
    tunnel_id = None
    try:
        registration = await websocket.recv()
        reg_data = json.loads(registration)
        
        if reg_data.get("type") == "register":
            tunnel_id = reg_data.get("tunnel_id")
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
        return web.Response(text="Tunnel not available", status=503)
    
    return web.Response(
        text=response_data.get("body", ""),
        status=response_data.get("status", 200),
        headers=response_data.get("headers", {})
    )

async def main():
    websocket_server = websockets.serve(websocket_handler, "0.0.0.0", 45413)
    
    app = web.Application()
    app.router.add_route('*', '/{tunnel_id}', http_proxy_handler)
    app.router.add_route('*', '/{tunnel_id}/{path:.*}', http_proxy_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 45415)
    await site.start()
    
    logger.info("Tunnel server started:")
    logger.info("- WebSocket server on port 45413")
    logger.info("- HTTP proxy on port 45415")
    
    await asyncio.gather(websocket_server, asyncio.Event().wait())

if __name__ == "__main__":
    asyncio.run(main())