# public_server.py - Run this on your public server
import asyncio
import json
import uuid
import websockets
from aiohttp import web, ClientSession
import logging
import os.path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TunnelManager:
    def __init__(self):
        self.tunnels = {}  # tunnel_id -> websocket
        self.pending_requests = {}  # request_id -> future
    
    async def register_tunnel(self, tunnel_id, websocket):
        """Register a new tunnel connection"""
        self.tunnels[tunnel_id] = websocket
        logger.info(f"Tunnel registered: {tunnel_id}")
        
    async def unregister_tunnel(self, tunnel_id):
        """Remove tunnel connection"""
        if tunnel_id in self.tunnels:
            del self.tunnels[tunnel_id]
            logger.info(f"Tunnel unregistered: {tunnel_id}")
    
    async def forward_request(self, tunnel_id, method, path, headers, body):
        """Forward HTTP request through WebSocket tunnel"""
        if tunnel_id not in self.tunnels:
            return None
            
        request_id = str(uuid.uuid4())
        
        # Prepare request data
        request_data = {
            "type": "http_request",
            "request_id": request_id,
            "method": method,
            "path": path,
            "headers": dict(headers),
            "body": body.decode('utf-8') if body else ""
        }
        
        # Create future for response
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        
        try:
            # Send request through tunnel
            websocket = self.tunnels[tunnel_id]
            await websocket.send(json.dumps(request_data))
            
            # Wait for response (with timeout)
            response = await asyncio.wait_for(future, timeout=30)
            return response
            
        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError) as e:
            logger.error(f"Tunnel error: {e}")
            return None
        finally:
            # Clean up
            self.pending_requests.pop(request_id, None)
    
    async def handle_response(self, response_data):
        """Handle response from tunnel client"""
        request_id = response_data.get("request_id")
        if request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                future.set_result(response_data)

# Global tunnel manager
tunnel_manager = TunnelManager()

async def websocket_handler(websocket):
    """Handle WebSocket connections from private clients"""
    tunnel_id = None
    try:
        # First message should be registration
        registration = await websocket.recv()
        reg_data = json.loads(registration)
        
        if reg_data.get("type") == "register":
            tunnel_id = reg_data.get("tunnel_id")
            await tunnel_manager.register_tunnel(tunnel_id, websocket)
            
            # Send confirmation
            await websocket.send(json.dumps({
                "type": "registered",
                "tunnel_id": tunnel_id
            }))
            
            # Handle responses from client
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
    """Handle HTTP requests and proxy through tunnels"""
    tunnel_id = request.match_info.get('tunnel_id')
    
    if not tunnel_id:
        return web.Response(text="Tunnel ID required", status=400)
    
    # Extract the path after the tunnel_id
    original_path = request.path_qs
    tunnel_prefix = f"/{tunnel_id}"
    
    if original_path.startswith(tunnel_prefix):
        # Remove tunnel prefix to get the actual path for the local service
        local_path = original_path[len(tunnel_prefix):]
        if not local_path:
            local_path = "/"  # Default to root if empty
            
        # SECURITY: Sanitize path to prevent traversal attacks
        # Remove query string temporarily for path validation
        path_only = local_path.split('?')[0]
        
        # Normalize path and check for traversal attempts
        normalized = os.path.normpath(path_only)
        if normalized.startswith('../') or '/../' in normalized or normalized == '..':
            logger.warning(f"Path traversal attempt blocked: {path_only}")
            return web.Response(text="Path traversal not allowed", status=403)
        
        # Restore query string if it existed
        if '?' in local_path:
            query_part = local_path[local_path.index('?'):]
            local_path = normalized + query_part
        else:
            local_path = normalized
            
        # Ensure path starts with /
        if not local_path.startswith('/'):
            local_path = '/' + local_path
            
    else:
        local_path = "/"
    
    # Read request body
    body = await request.read()
    
    logger.info(f"Proxying {request.method} {original_path} -> localhost:{tunnel_id} {local_path}")
    
    # Forward through tunnel
    response_data = await tunnel_manager.forward_request(
        tunnel_id=tunnel_id,
        method=request.method,
        path=local_path,
        headers=request.headers,
        body=body
    )
    
    if not response_data:
        return web.Response(text="Tunnel not available", status=503)
    
    # Return response
    return web.Response(
        text=response_data.get("body", ""),
        status=response_data.get("status", 200),
        headers=response_data.get("headers", {})
    )

async def main():
    # Start WebSocket server for tunnel connections
    websocket_server = websockets.serve(
        websocket_handler, 
        "0.0.0.0", 
        45413
    )
    
    # Start HTTP server for proxy requests
    app = web.Application()
    app.router.add_route('*', '/{tunnel_id}/{path:.*}', http_proxy_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 45415)
    await site.start()
    
    logger.info("Tunnel server started:")
    logger.info("- WebSocket server on port 45413")
    logger.info("- HTTP proxy on port 45415")
    logger.info("- Access tunnels at: http://yourserver.com:45415/{tunnel_id}/path")
    
    # Keep servers running
    await asyncio.gather(
        websocket_server,
        asyncio.Event().wait()  # Run forever
    )

if __name__ == "__main__":
    asyncio.run(main())