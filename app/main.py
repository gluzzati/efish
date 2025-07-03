from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import redis
import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

from token_service import TokenService
from tunnel_manager import TunnelManager
from monitor import DownloadMonitor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global services
redis_client = None
token_service = None
tunnel_manager = None
download_monitor = None

# Request models
class GenerateLinkRequest(BaseModel):
    file_path: str
    expires_in_seconds: Optional[int] = 3600

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global redis_client, token_service, tunnel_manager, download_monitor
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_client = redis.from_url(redis_url, decode_responses=True)
    
    # Test Redis connection
    try:
        redis_client.ping()
        logger.info("Connected to Redis successfully")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise
    
    # Initialize services
    token_service = TokenService(redis_client)
    tunnel_manager = TunnelManager(redis_client)
    download_monitor = DownloadMonitor(redis_client, tunnel_manager)
    logger.info("Services initialized successfully")
    
    # Start monitoring in background
    import asyncio
    monitoring_task = asyncio.create_task(download_monitor.start_monitoring())
    logger.info("Download monitoring started")
    
    yield
    
    # Shutdown
    monitoring_task.cancel()
    if redis_client:
        redis_client.close()

app = FastAPI(
    title="Ephemeral File Sharing",
    description="Secure, temporary file sharing with tailscale tunnels",
    version="1.0.0",
    lifespan=lifespan
)

# Serve static files (frontend)
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the web frontend"""
    try:
        frontend_path = "/app/web/index.html"
        if os.path.exists(frontend_path):
            with open(frontend_path, 'r') as f:
                return HTMLResponse(content=f.read())
        else:
            return HTMLResponse(content="<h1>Frontend not found</h1>", status_code=404)
    except Exception as e:
        logger.error(f"Error serving frontend: {e}")
        return HTMLResponse(content="<h1>Error loading frontend</h1>", status_code=500)

@app.get("/api/files")
async def list_files():
    """List available files for download"""
    try:
        nas_mount = os.getenv("NAS_MOUNT_PATH", "/data")
        
        if not os.path.exists(nas_mount):
            return {"files": [], "error": "Data directory not found"}
        
        files = []
        for item in os.listdir(nas_mount):
            item_path = os.path.join(nas_mount, item)
            if os.path.isfile(item_path):
                files.append(item)
        
        files.sort()
        return files
        
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail="Failed to list files")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test Redis connection
        redis_client.ping()
        return {
            "status": "healthy",
            "redis": "connected",
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

@app.post("/generate-link")
async def generate_link(request: GenerateLinkRequest):
    """Generate signed download link and create tunnel immediately"""
    try:
        # Validate file exists
        file_path = request.file_path.lstrip('/')
        nas_mount = os.getenv("NAS_MOUNT_PATH", "/data")
        full_path = os.path.join(nas_mount, file_path)
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=400, detail="Path is not a file")
        
        # Generate token
        token = token_service.generate_token(
            file_path=file_path,
            expires_in_seconds=request.expires_in_seconds
        )
        
        # Create tunnel immediately (like before)
        base_url = os.getenv("BASE_URL", "http://localhost:8000")
        download_url = f"{base_url}/download/{token}"
        
        # Get token data to extract token_id
        token_data = token_service.validate_token(token)
        if not token_data:
            raise HTTPException(status_code=400, detail="Failed to validate generated token")
        
        token_id = token_data["token_id"]
        
        # Create tunnel
        tunnel_data = tunnel_manager.create_tunnel(
            file_path, token_id, request.expires_in_seconds
        )
        if not tunnel_data:
            raise HTTPException(status_code=500, detail="Failed to create tunnel")
        
        # Mark token as used with tunnel ID
        token_service.mark_token_used(token_id, tunnel_data["tunnel_id"])
        
        return {
            "download_url": tunnel_data["public_url"],  # Return public tunnel URL directly
            "tunnel_id": tunnel_data["tunnel_id"],
            "token": token,
            "file_path": file_path,
            "expires_in_seconds": request.expires_in_seconds
        }
        
    except Exception as e:
        logger.error(f"Error generating link: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate link")


@app.api_route("/download/{token}", methods=["GET", "HEAD"])
async def download_webhook(token: str, request: Request):
    """Webhook endpoint that creates tunnel and returns public URL"""
    try:
        # Log request details for debugging WhatsApp issue
        user_agent = request.headers.get("user-agent", "unknown")
        client_ip = request.client.host if request.client else "unknown"
        logger.info(f"Download request: {request.method} from {client_ip}, User-Agent: {user_agent[:100]}")
        
        # Allow HEAD requests without consuming the token (for link previews)
        is_head_request = request.method == "HEAD"
        
        # Validate token
        token_data = token_service.validate_token(token)
        if not token_data:
            # Return 444 (close connection) instead of 401 for expired/invalid tokens
            return Response(status_code=444)
        
        token_id = token_data["token_id"]
        file_path = token_data["file_path"]
        
        # For HEAD requests, just return basic info without consuming token or creating tunnel
        if is_head_request:
            return Response(
                status_code=200,
                headers={
                    "Content-Type": "application/json",
                    "X-File-Path": file_path,
                    "X-Token-Valid": "true"
                }
            )
        
        # Mark token as used for GET requests only
        
        tunnel_data = tunnel_manager.create_tunnel(file_path, token_id)
        if not tunnel_data:
            return Response(status_code=444)
        
        # Mark token as used with tunnel ID
        token_service.mark_token_used(token_id, tunnel_data["tunnel_id"])
        
        return {
            "public_url": tunnel_data["public_url"],
            "tunnel_id": tunnel_data["tunnel_id"],
            "file_path": file_path,
            "message": "Tunnel created successfully. Download will be available for a limited time."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating tunnel: {e}")
        return Response(status_code=444)

@app.get("/admin/tunnels")
async def list_active_tunnels():
    """List active tunnels with download statistics"""
    try:
        tunnels = tunnel_manager.list_active_tunnels()
        
        # Enhance with download statistics
        enhanced_tunnels = []
        for tunnel in tunnels:
            tunnel_id = tunnel.get("tunnel_id")
            download_stats = download_monitor.get_download_stats(tunnel_id)
            
            enhanced_tunnel = {**tunnel}
            if download_stats:
                enhanced_tunnel.update({
                    "download_stats": download_stats,
                    "last_activity": download_stats.get("last_activity"),
                    "is_downloading": download_stats.get("is_active", False)
                })
            
            enhanced_tunnels.append(enhanced_tunnel)
        
        return {
            "active_tunnels": enhanced_tunnels,
            "count": len(enhanced_tunnels)
        }
    except Exception as e:
        logger.error(f"Error listing tunnels: {e}")
        raise HTTPException(status_code=500, detail="Failed to list tunnels")

@app.get("/admin/history")
async def tunnel_history():
    """Past tunnel history"""
    try:
        # Get all tunnel keys from Redis
        pattern = "tunnel:*"
        tunnel_keys = redis_client.keys(pattern)
        
        history = []
        for key in tunnel_keys:
            tunnel_data = redis_client.hgetall(key)
            if tunnel_data:
                tunnel_id = key.split(":", 1)[1]
                history.append({
                    "tunnel_id": tunnel_id,
                    **tunnel_data
                })
        
        # Sort by creation time (newest first)
        history.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return {
            "tunnel_history": history,
            "count": len(history)
        }
    except Exception as e:
        logger.error(f"Error getting tunnel history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get tunnel history")

@app.delete("/admin/tunnels/{tunnel_id}")
async def terminate_tunnel(tunnel_id: str):
    """Manual tunnel termination"""
    try:
        success = tunnel_manager.destroy_tunnel(tunnel_id)
        if not success:
            raise HTTPException(status_code=404, detail="Tunnel not found or already destroyed")
        
        return {
            "message": f"Tunnel {tunnel_id} terminated successfully",
            "tunnel_id": tunnel_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error terminating tunnel: {e}")
        raise HTTPException(status_code=500, detail="Failed to terminate tunnel")

# Removed internal validation endpoint - nginx now serves files directly
# Security is handled by tunnel creation validation and Tailscale Funnel routing

@app.get("/admin/tunnels/{tunnel_id}/stats")
async def get_tunnel_stats(tunnel_id: str):
    """Get detailed statistics for a specific tunnel"""
    try:
        tunnel_info = tunnel_manager.get_tunnel_info(tunnel_id)
        if not tunnel_info:
            raise HTTPException(status_code=404, detail="Tunnel not found")
        
        download_stats = download_monitor.get_download_stats(tunnel_id)
        
        # Get file info for context
        file_path = tunnel_info.get("file_path")
        file_size = None
        if file_path:
            nas_mount = os.getenv("NAS_MOUNT_PATH", "/data")
            full_path = os.path.join(nas_mount, file_path.lstrip('/'))
            if os.path.exists(full_path):
                file_size = os.path.getsize(full_path)
        
        return {
            "tunnel_info": tunnel_info,
            "download_stats": download_stats,
            "file_size": file_size,
            "download_progress": {
                "bytes_served": int(tunnel_info.get("bytes_served", 0)),
                "file_size": file_size,
                "percentage": round((int(tunnel_info.get("bytes_served", 0)) / file_size * 100), 2) if file_size and file_size > 0 else 0
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tunnel stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get tunnel stats")

@app.get("/admin/monitor/status")
async def get_monitor_status():
    """Get monitoring system status"""
    try:
        # Get system stats
        active_tunnels = tunnel_manager.list_active_tunnels()
        
        # Count active downloads by checking which tunnels have active connections
        active_downloads = 0
        if download_monitor:
            for tunnel in active_tunnels:
                tunnel_id = tunnel.get("tunnel_id")
                stats = download_monitor.get_download_stats(tunnel_id)
                if stats and stats.get("active_connections", 0) > 0:
                    active_downloads += 1
        
        # Get Redis stats
        redis_info = redis_client.info() if redis_client else {}
        
        return {
            "monitor_active": download_monitor is not None,
            "active_downloads": active_downloads,
            "active_tunnels_count": len(active_tunnels),
            "funnel_active": tunnel_manager.is_funnel_active() if tunnel_manager else False,
            "stall_timeout_seconds": download_monitor.stall_timeout if download_monitor else None,
            "max_tunnel_seconds": download_monitor.max_tunnel_seconds if download_monitor else None,
            "redis_connected": redis_client.ping() if redis_client else False,
            "redis_memory_usage": redis_info.get("used_memory_human", "unknown"),
            "uptime": redis_info.get("uptime_in_seconds", 0)
        }
    except Exception as e:
        logger.error(f"Error getting monitor status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get monitor status")

@app.post("/admin/cleanup")
async def force_cleanup():
    """Force cleanup of expired tunnels and tokens"""
    try:
        cleaned_tunnels = tunnel_manager.cleanup_expired_tunnels()
        cleaned_tokens = token_service.cleanup_expired_tokens()
        
        return {
            "message": "Cleanup completed",
            "cleaned_tunnels": cleaned_tunnels,
            "cleaned_tokens": cleaned_tokens
        }
    except Exception as e:
        logger.error(f"Error during forced cleanup: {e}")
        raise HTTPException(status_code=500, detail="Failed to perform cleanup")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 