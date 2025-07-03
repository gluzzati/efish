import subprocess
import json
import uuid
import logging
import os
import redis
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

class TunnelManager:
    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        self.nginx_base_url = "http://127.0.0.1:80"  # Shared network namespace with nginx
        
    def create_tunnel(self, file_path: str, token_id: str, expires_in_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Create a tailscale funnel for the specified file"""
        try:
            tunnel_id = str(uuid.uuid4())[:8]  # Short ID for easier management
            
            # Ensure there's a persistent funnel routing all requests to nginx
            # Tailscale funnel can only have one configuration, so we use a catch-all
            logger.info(f"Creating tunnel {tunnel_id} for {file_path}")
            
            if not self._ensure_persistent_funnel():
                logger.error("Failed to ensure persistent funnel is running")
                return None
            
            # Create symlink for secure access
            if not self._create_tunnel_symlink(tunnel_id, file_path):
                logger.error(f"Failed to create symlink for tunnel {tunnel_id}")
                self._cleanup_tunnel(tunnel_id)
                return None
            
            # Get the public URL
            public_url = self._get_tunnel_url(tunnel_id, file_path)
            if not public_url:
                logger.error("Failed to get public URL for tunnel")
                self._cleanup_tunnel(tunnel_id)
                self._remove_tunnel_symlink(tunnel_id)
                return None
            
            # Determine tunnel lifetime
            if expires_in_seconds is not None:
                max_seconds = expires_in_seconds
            else:
                # Fallback to token TTL if expiration not provided directly
                token_key = f"token:{token_id}"
                token_ttl = self.redis_client.ttl(token_key)
                if token_ttl > 0:
                    max_seconds = token_ttl
                else:
                    max_seconds = int(os.getenv("MAX_TUNNEL_SECONDS", "3600"))

            expires_at = datetime.utcnow() + timedelta(seconds=max_seconds)
            
            tunnel_data = {
                "tunnel_id": tunnel_id,
                "token_id": token_id,
                "file_path": file_path,
                "public_url": public_url,
                "internal_url": f"http://file-server:80/files/{tunnel_id}/{file_path}",
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": expires_at.isoformat(),
                "max_seconds": max_seconds,
                "status": "active",
                "bytes_served": "0"
            }
            
            tunnel_key = f"tunnel:{tunnel_id}"
            self.redis_client.hset(tunnel_key, mapping=tunnel_data)
            
            # Set expiration based on determined lifetime
            self.redis_client.expire(tunnel_key, max_seconds)
            
            # Add to active tunnels list
            self.redis_client.sadd("active_tunnels", tunnel_id)
            
            logger.info(f"Created tunnel {tunnel_id}: {public_url}")
            return tunnel_data
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout creating tailscale tunnel")
            return None
        except Exception as e:
            logger.error(f"Error creating tunnel: {e}")
            return None
    
    def destroy_tunnel(self, tunnel_id: str, reason: str = "unknown") -> bool:
        """Destroy a tunnel (just remove from Redis, keep funnel active for other tunnels)"""
        try:
            # Get tunnel info first
            tunnel_data = self.get_tunnel_info(tunnel_id)
            if not tunnel_data:
                logger.warning(f"Tunnel {tunnel_id} not found")
                return False
            
            # Check if already destroyed
            if tunnel_data.get("status") == "destroyed":
                logger.debug(f"Tunnel {tunnel_id} already destroyed")
                return True
            
            logger.info(f"Destroying tunnel {tunnel_id} (Reason: {reason})")
            
            # Update status in Redis
            tunnel_key = f"tunnel:{tunnel_id}"
            self.redis_client.hset(tunnel_key, "status", "destroyed")
            self.redis_client.hset(tunnel_key, "destroyed_at", datetime.utcnow().isoformat())
            
            # Remove symlink for security
            self._remove_tunnel_symlink(tunnel_id)
            
            # Remove from active tunnels
            self.redis_client.srem("active_tunnels", tunnel_id)
            
            # Only reset funnel if no other active tunnels exist
            remaining_tunnels = self.list_active_tunnels()
            if len(remaining_tunnels) == 0:
                logger.info("No more active tunnels, deactivating funnel")
                self._reset_funnel()
            else:
                logger.debug(f"Keeping funnel active, {len(remaining_tunnels)} tunnels remaining")
            
            logger.info(f"Destroyed tunnel {tunnel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error destroying tunnel {tunnel_id}: {e}")
            return False
    
    def get_tunnel_info(self, tunnel_id: str) -> Optional[Dict[str, Any]]:
        """Get tunnel information from Redis"""
        tunnel_key = f"tunnel:{tunnel_id}"
        tunnel_data = self.redis_client.hgetall(tunnel_key)
        
        if not tunnel_data:
            return None
        
        return {
            "tunnel_id": tunnel_id,
            **tunnel_data
        }
    
    def list_active_tunnels(self) -> List[Dict[str, Any]]:
        """List all active tunnels"""
        active_tunnel_ids = self.redis_client.smembers("active_tunnels")
        tunnels = []
        
        for tunnel_id in active_tunnel_ids:
            tunnel_info = self.get_tunnel_info(tunnel_id)
            if tunnel_info and tunnel_info.get("status") == "active":
                tunnels.append(tunnel_info)
            else:
                # Clean up stale reference
                self.redis_client.srem("active_tunnels", tunnel_id)
        
        return tunnels
    
    def _get_tunnel_url(self, tunnel_id: str, file_path: str) -> Optional[str]:
        """Get the public URL for a tunnel"""
        try:
            # Get tailscale status to find the public hostname
            result = subprocess.run(
                ["docker", "exec", "tailscale-tunnel", "tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error("Failed to get tailscale status")
                return None
            
            status = json.loads(result.stdout)
            
            # Extract the tailnet name or public hostname
            # This is simplified - actual implementation depends on tailscale setup
            self_node = status.get("Self", {})
            hostname = self_node.get("DNSName", "").rstrip(".")
            
            if not hostname:
                logger.error("Could not determine tailscale hostname")
                return None
            
            # Construct the public URL - all requests go through the persistent funnel to nginx
            public_url = f"https://{hostname}/files/{tunnel_id}/{file_path.lstrip('/')}"
            return public_url
            
        except Exception as e:
            logger.error(f"Error getting tunnel URL: {e}")
            return None
    
    def _cleanup_tunnel(self, tunnel_id: str):
        """Internal cleanup method"""
        try:
            subprocess.run(
                ["docker", "exec", "tailscale-tunnel", "tailscale", "funnel", "reset"],
                capture_output=True,
                timeout=10
            )
        except:
            pass  # Best effort cleanup
        
        # Also remove symlink if provided tunnel_id
        try:
            self._remove_tunnel_symlink(tunnel_id)
        except:
            pass  # Best effort cleanup
    
    def cleanup_expired_tunnels(self) -> int:
        """Clean up expired tunnels (called by background task)"""
        active_tunnel_ids = self.redis_client.smembers("active_tunnels")
        cleaned = 0
        
        for tunnel_id in active_tunnel_ids:
            tunnel_key = f"tunnel:{tunnel_id}"
            ttl = self.redis_client.ttl(tunnel_key)
            
            # If tunnel expired or doesn't exist, clean it up
            if ttl <= 0:
                if self.destroy_tunnel(tunnel_id, reason="expired"):
                    cleaned += 1
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired tunnels")
            
            # Check if we should deactivate the funnel
            remaining_active = self.redis_client.scard("active_tunnels")
            if remaining_active == 0:
                logger.info("No active tunnels after cleanup, deactivating funnel")
                self._reset_funnel()
        
        return cleaned
    
    def _ensure_persistent_funnel(self) -> bool:
        """Ensure a persistent funnel is running that routes all traffic to nginx"""
        try:
            # Check if funnel is already running
            result = subprocess.run(
                ["docker", "exec", "tailscale-tunnel", "tailscale", "funnel", "status"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # If funnel is already active, we're good
            if result.returncode == 0 and "Funnel on" in result.stdout:
                logger.debug("Persistent funnel already active")
                return True
            
            # Create persistent funnel that routes ALL traffic to nginx
            # Tailscale funnel only supports localhost/127.0.0.1
            cmd = [
                "tailscale", "funnel", 
                "--bg",
                "localhost:80"  # Funnel requirement: must be localhost
            ]
            
            logger.info("Creating funnel (on-demand activation)")
            
            result = subprocess.run(
                ["docker", "exec", "tailscale-tunnel"] + cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to create funnel: {result.stderr}")
                return False
            
            logger.info("Funnel activated successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error ensuring funnel: {e}")
            return False
    
    def _reset_funnel(self):
        """Reset the tailscale funnel to turn it off"""
        try:
            subprocess.run(
                ["docker", "exec", "tailscale-tunnel", "tailscale", "funnel", "reset"],
                capture_output=True,
                timeout=10
            )
            logger.info("Funnel deactivated (no active tunnels)")
        except Exception as e:
            logger.error(f"Error deactivating funnel: {e}")
    
    def is_funnel_active(self) -> bool:
        """Check if the tailscale funnel is currently active"""
        try:
            result = subprocess.run(
                ["docker", "exec", "tailscale-tunnel", "tailscale", "funnel", "status"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0 and "Funnel on" in result.stdout
        except Exception as e:
            logger.error(f"Error checking funnel status: {e}")
            return False
    
    def _create_tunnel_symlink(self, tunnel_id: str, file_path: str) -> bool:
        """Create a symlink for tunnel-specific file access"""
        try:
            # Create tunnel directory
            tunnel_dir = Path(f"/tunnels/{tunnel_id}")
            tunnel_dir.mkdir(parents=True, exist_ok=True)
            
            # Create symlink to the actual file using consistent name "file"
            # This allows URLs to be modified without breaking access
            source_file = Path(f"/data/{file_path}")
            target_link = tunnel_dir / "file"  # Always use "file" as the symlink name
            
            # Create the symlink
            if target_link.exists() or target_link.is_symlink():
                target_link.unlink()  # Remove existing symlink/file
            
            target_link.symlink_to(source_file)
            
            logger.debug(f"Created symlink: {target_link} -> {source_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating symlink for tunnel {tunnel_id}: {e}")
            return False
    
    def _remove_tunnel_symlink(self, tunnel_id: str):
        """Remove the symlink directory for a tunnel"""
        try:
            import shutil
            tunnel_dir = Path(f"/tunnels/{tunnel_id}")
            
            if tunnel_dir.exists():
                shutil.rmtree(tunnel_dir)
                logger.debug(f"Removed tunnel directory: {tunnel_dir}")
            
        except Exception as e:
            logger.error(f"Error removing symlink for tunnel {tunnel_id}: {e}") 