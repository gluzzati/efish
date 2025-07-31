# private_client.py - Run this on your private PC
import asyncio
import json
import websockets
import aiohttp
import logging
import sys
import jwt
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TunnelClient:
    def __init__(self, server_url, tunnel_id, local_port, jwt_secret):
        self.server_url = server_url
        self.tunnel_id = tunnel_id
        self.local_port = local_port
        self.jwt_secret = jwt_secret
        self.websocket = None
        
    async def connect(self):
        try:
            self.websocket = await websockets.connect(self.server_url)
            
            # Generate JWT token
            payload = {
                'tunnel_id': self.tunnel_id,
                'exp': time.time() + 3600  # 1 hour expiry
            }
            token = jwt.encode(payload, self.jwt_secret, algorithm='HS256')
            
            registration = {
                "type": "register",
                "tunnel_id": self.tunnel_id,
                "token": token
            }
            await self.websocket.send(json.dumps(registration))
            
            response = await self.websocket.recv()
            data = json.loads(response)
            
            if data.get("type") == "registered":
                logger.info(f"Tunnel registered: {self.tunnel_id}")
                return True
            elif data.get("type") == "error":
                logger.error(f"Registration failed: {data.get('message')}")
                return False
            else:
                logger.error("Registration failed")
                return False
                
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    async def forward_to_local(self, request_data):
        try:
            local_url = f"http://localhost:{self.local_port}{request_data['path']}"
            
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=request_data['method'],
                    url=local_url,
                    headers=request_data.get('headers', {}),
                    data=request_data.get('body', '')
                ) as response:
                    
                    body = await response.text()
                    
                    return {
                        "type": "http_response",
                        "request_id": request_data["request_id"],
                        "status": response.status,
                        "headers": dict(response.headers),
                        "body": body
                    }
                    
        except Exception as e:
            logger.error(f"Local request failed: {e}")
            return {
                "type": "http_response",
                "request_id": request_data["request_id"],
                "status": 502,
                "headers": {},
                "body": f"Local service error: {str(e)}"
            }
    
    async def handle_requests(self):
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    
                    if data.get("type") == "http_request":
                        response = await self.forward_to_local(data)
                        await self.websocket.send(json.dumps(response))
                        
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                except Exception as e:
                    logger.error(f"Request handling error: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Connection error: {e}")
    
    async def run(self):
        while True:
            try:
                if await self.connect():
                    await self.handle_requests()
                else:
                    logger.error("Failed to connect, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await asyncio.sleep(5)
            finally:
                if self.websocket:
                    await self.websocket.close()

async def main():
    if len(sys.argv) != 5:
        print("Usage: python client.py <server_ws_url> <tunnel_id> <local_port> <jwt_secret>")
        print("Example: python client.py ws://yourserver.com:45413 my_pc 8000 your_secret_key")
        return
    
    server_url = sys.argv[1]
    tunnel_id = sys.argv[2] 
    local_port = int(sys.argv[3])
    jwt_secret = sys.argv[4]
    
    client = TunnelClient(server_url, tunnel_id, local_port, jwt_secret)
    await client.run()

if __name__ == "__main__":
    asyncio.run(main())