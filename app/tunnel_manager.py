import subprocess
import json
import uuid
import logging
import os
import redis
import time
import pyotp
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

class TunnelManager:
    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        self.nginx_base_url = "http://127.0.0.1:80"  # Shared network namespace with nginx
        
        # FRP Configuration
        self.frp_server_addr = os.getenv("FRP_SERVER_ADDR", "your_vps_ip_here")
        self.frp_server_port = int(os.getenv("FRP_SERVER_PORT", "7000"))
        self.frp_token = os.getenv("FRP_TOKEN", "your_frp_token_here")
        self.frp_config_dir = "/frp"
        
        # Dynamic port configuration
        self.shared_secret = os.getenv("DYNAMIC_PORT_SECRET", "your_shared_secret_here")
        self.base_port = int(os.getenv("DYNAMIC_BASE_PORT", "30000"))
        self.port_range = int(os.getenv("DYNAMIC_PORT_RANGE", "1000"))
        self.port_interval = int(os.getenv("DYNAMIC_PORT_INTERVAL", "300"))  # 5 minutes
        
        # FRP process management
        self.frpc_process = None
        self.current_port = None
        
    def _calculate_dynamic_port(self) -> int:
        """Calculate the current dynamic port based on shared secret and time"""
        try:
            # Use pyotp for TOTP-like calculation
            totp = pyotp.TOTP(self.shared_secret, interval=self.port_interval)
            current_time = int(time.time())
            epoch = current_time // self.port_interval
            
            # Generate a deterministic value based on the epoch
            totp_value = totp.at(epoch)
            
            # Convert to port offset within range
            port_offset = int(totp_value) % self.port_range
            dynamic_port = self.base_port + port_offset
            
            logger.debug(f"Calculated dynamic port: {dynamic_port} (epoch: {epoch})")
            return dynamic_port
            
        except Exception as e:
            logger.error(f"Error calculating dynamic port: {e}")
            # Fallback to a default port
            return self.base_port + 100
    
    def _generate_frpc_config(self, dynamic_port: int) -> str:
        """Generate FRP client configuration with the current dynamic port"""
        config_template = f"""[common]
server_addr = {self.frp_server_addr}
server_port = {self.frp_server_port}
token = {self.frp_token}

# Authentication
authentication_method = token

# Log configuration
log_file = /var/log/frpc.log
log_level = info
log_max_days = 3

[file-server]
type = tcp
local_ip = 127.0.0.1
local_port = 80
remote_port = {dynamic_port}
use_compression = true
"""
        return config_template
    
    def _write_frpc_config(self, config: str) -> bool:
        """Write FRP client configuration to file"""
        try:
            config_path = Path(f"{self.frp_config_dir}/frpc.ini")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, 'w') as f:
                f.write(config)
            
            logger.debug(f"FRP client config written to {config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error writing FRP config: {e}")
            return False
    
    def _start_frpc(self) -> bool:
        """Start FRP client process"""
        try:
            if self.frpc_process and self.frpc_process.poll() is None:
                logger.debug("FRP client already running")
                return True
            
            # Calculate current dynamic port
            current_port = self._calculate_dynamic_port()
            self.current_port = current_port
            
            # Generate and write config
            config = self._generate_frpc_config(current_port)
            if not self._write_frpc_config(config):
                return False
            
            # Start FRP client
            cmd = ["frpc", "-c", f"{self.frp_config_dir}/frpc.ini"]
            
            logger.info(f"Starting FRP client with port {current_port}")
            self.frpc_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Give it a moment to start
            time.sleep(2)
            
            if self.frpc_process.poll() is None:
                logger.info("FRP client started successfully")
                return True
            else:
                logger.error("FRP client failed to start")
                return False
                
        except Exception as e:
            logger.error(f"Error starting FRP client: {e}")
            return False
    
    def _stop_frpc(self):
        """Stop FRP client process"""
        try:
            if self.frpc_process and self.frpc_process.poll() is None:
                logger.info("Stopping FRP client")
                self.frpc_process.terminate()
                self.frpc_process.wait(timeout=10)
                logger.info("FRP client stopped")
        except Exception as e:
            logger.error(f"Error stopping FRP client: {e}")
    
    def _ensure_frp_tunnel(self) -> bool:
        """Ensure FRP tunnel is running with current dynamic port"""
        try:
            # Calculate current port
            current_port = self._calculate_dynamic_port()
            
            # If port changed or tunnel not running, restart
            if current_port != self.current_port or not self.frpc_process or self.frpc_process.poll() is not None:
                logger.info(f"Port changed from {self.current_port} to {current_port}, restarting tunnel")
                self._stop_frpc()
                return self._start_frpc()
            
            return True
            
        except Exception as e:
            logger.error(f"Error ensuring FRP tunnel: {e}")
            return False
    
    def create_tunnel(self, file_path: str, token_id: str, expires_in_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Create a tunnel for the specified file using FRP"""
        try:
            tunnel_id = str(uuid.uuid4())[:8]  # Short ID for easier management
            
            logger.info(f"Creating tunnel {tunnel_id} for {file_path}")
            
            # Ensure FRP tunnel is running
            if not self._ensure_frp_tunnel():
                logger.error("Failed to ensure FRP tunnel is running")
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
                "bytes_served": "0",
                "frp_port": self.current_port
            }
            
            tunnel_key = f"tunnel:{tunnel_id}"
            self.redis_client.hset(tunnel_key, mapping=tunnel_data)
            
            # Set expiration based on determined lifetime
            self.redis_client.expire(tunnel_key, max_seconds)
            
            # Add to active tunnels list
            self.redis_client.sadd("active_tunnels", tunnel_id)
            
            logger.info(f"Created tunnel {tunnel_id}: {public_url}")
            return tunnel_data
            
        except Exception as e:
            logger.error(f"Error creating tunnel: {e}")
            return None
    
    def destroy_tunnel(self, tunnel_id: str, reason: str = "unknown") -> bool:
        """Destroy a tunnel (just remove from Redis, keep FRP tunnel active for other tunnels)"""
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
            
            # Remove from active tunnels
            self.redis_client.srem("active_tunnels", tunnel_id)
            
            # Mark as destroyed
            tunnel_key = f"tunnel:{tunnel_id}"
            self.redis_client.hset(tunnel_key, "status", "destroyed")
            self.redis_client.hset(tunnel_key, "destroyed_at", datetime.utcnow().isoformat())
            self.redis_client.hset(tunnel_key, "destroy_reason", reason)
            
            # Remove symlink
            self._remove_tunnel_symlink(tunnel_id)
            
            logger.info(f"Destroyed tunnel {tunnel_id} (reason: {reason})")
            return True
            
        except Exception as e:
            logger.error(f"Error destroying tunnel {tunnel_id}: {e}")
            return False
    
    def get_tunnel_info(self, tunnel_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific tunnel"""
        try:
            tunnel_key = f"tunnel:{tunnel_id}"
            tunnel_data = self.redis_client.hgetall(tunnel_key)
            
            if not tunnel_data:
                return None
            
            # Convert bytes to strings for JSON serialization
            return {k.decode() if isinstance(k, bytes) else k: 
                   v.decode() if isinstance(v, bytes) else v 
                   for k, v in tunnel_data.items()}
            
        except Exception as e:
            logger.error(f"Error getting tunnel info: {e}")
            return None
    
    def list_active_tunnels(self) -> List[Dict[str, Any]]:
        """List all active tunnels"""
        try:
            active_tunnel_ids = self.redis_client.smembers("active_tunnels")
            tunnels = []
            
            for tunnel_id in active_tunnel_ids:
                tunnel_data = self.get_tunnel_info(tunnel_id.decode() if isinstance(tunnel_id, bytes) else tunnel_id)
                if tunnel_data:
                    tunnels.append(tunnel_data)
            
            return tunnels
            
        except Exception as e:
            logger.error(f"Error listing active tunnels: {e}")
            return []
    
    def _get_tunnel_url(self, tunnel_id: str, file_path: str) -> Optional[str]:
        """Get the public URL for a tunnel"""
        try:
            if not self.current_port:
                logger.error("No current FRP port available")
                return None
            
            # Construct the public URL using VPS IP and dynamic port
            public_url = f"http://{self.frp_server_addr}:{self.current_port}/files/{tunnel_id}/file"
            return public_url
            
        except Exception as e:
            logger.error(f"Error getting tunnel URL: {e}")
            return None
    
    def _cleanup_tunnel(self, tunnel_id: str):
        """Internal cleanup method"""
        try:
            # Remove symlink if provided tunnel_id
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
            
            # Check if we should stop the FRP tunnel
            remaining_active = self.redis_client.scard("active_tunnels")
            if remaining_active == 0:
                logger.info("No active tunnels after cleanup, stopping FRP tunnel")
                self._stop_frpc()
        
        return cleaned
    
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
    
    def get_frp_status(self) -> Dict[str, Any]:
        """Get FRP tunnel status"""
        try:
            status = {
                "frp_running": self.frpc_process and self.frpc_process.poll() is None,
                "current_port": self.current_port,
                "server_addr": self.frp_server_addr,
                "server_port": self.frp_server_port
            }
            
            if self.frpc_process:
                status["frp_pid"] = self.frpc_process.pid
                status["frp_returncode"] = self.frpc_process.returncode
            
            return status
            
        except Exception as e:
            logger.error(f"Error getting FRP status: {e}")
            return {"error": str(e)}
    
    def restart_frp_tunnel(self) -> bool:
        """Restart the FRP tunnel (useful for port changes)"""
        try:
            logger.info("Restarting FRP tunnel")
            self._stop_frpc()
            return self._start_frpc()
        except Exception as e:
            logger.error(f"Error restarting FRP tunnel: {e}")
            return False 