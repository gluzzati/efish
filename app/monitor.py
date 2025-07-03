import asyncio
import os
import time
import logging
import subprocess
import json
from typing import Dict, Set, Optional
from datetime import datetime, timedelta
import redis
from tunnel_manager import TunnelManager

logger = logging.getLogger(__name__)

class DownloadMonitor:
    def __init__(self, redis_client: redis.Redis, tunnel_manager: TunnelManager):
        self.redis_client = redis_client
        self.tunnel_manager = tunnel_manager
        self.stall_timeout = int(os.getenv("STALL_TIMEOUT_SECONDS", "300"))  # 5 minutes
        self.max_tunnel_seconds = int(os.getenv("MAX_TUNNEL_SECONDS", "3600"))  # 1 hour
        self.check_interval = 30  # Check every 30 seconds
        
        # Track last known connection counts for each tunnel
        self.last_connection_counts = {}
        
    async def start_monitoring(self):
        """Start the background monitoring loop"""
        logger.info("Starting download monitor (System-based tracking)")
        
        # Start monitoring tasks
        tasks = [
            asyncio.create_task(self._monitor_nginx_connections()),
            asyncio.create_task(self._monitor_tunnel_health()),
            asyncio.create_task(self._cleanup_expired_tunnels()),
            asyncio.create_task(self._monitor_funnel_state())
        ]
        
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        finally:
            logger.info("Download monitor stopped")
    
    async def _monitor_nginx_connections(self):
        """Monitor nginx connections and track downloads via system commands"""
        logger.info("Starting nginx connection monitoring")
        
        while True:
            try:
                # Get nginx stats
                nginx_stats = await self._get_nginx_stats()
                
                # Get active connections per tunnel
                tunnel_connections = await self._get_tunnel_connections()
                
                # Update download tracking
                await self._update_download_tracking(tunnel_connections, nginx_stats)
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error monitoring nginx connections: {e}")
                await asyncio.sleep(30)
    
    async def _get_nginx_stats(self) -> Dict:
        """Get nginx statistics via stub_status"""
        try:
            result = subprocess.run([
                "docker", "exec", "file-server", 
                "curl", "-s", "http://localhost/nginx-status"
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                # Parse nginx status output
                lines = result.stdout.strip().split('\n')
                stats = {}
                if len(lines) >= 3:
                    # Active connections: 1
                    stats['active_connections'] = int(lines[0].split(':')[1].strip())
                    # server accepts handled requests
                    # 1 1 1
                    numbers = lines[2].split()
                    if len(numbers) >= 3:
                        stats['accepts'] = int(numbers[0])
                        stats['handled'] = int(numbers[1])
                        stats['requests'] = int(numbers[2])
                
                return stats
            else:
                logger.warning(f"Failed to get nginx stats: {result.stderr}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting nginx stats: {e}")
            return {}
    
    async def _get_tunnel_connections(self) -> Dict[str, int]:
        """Get active connections per tunnel by parsing nginx access logs"""
        tunnel_connections = {}
        
        try:
            # Get recent log entries (last 60 seconds)
            result = subprocess.run([
                "docker", "exec", "file-server",
                "tail", "-n", "100", "/var/log/nginx/access.log"
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                current_time = datetime.utcnow()
                
                for line in result.stdout.strip().split('\n'):
                    # Only track actual file downloads, not courtesy page views
                    if '/download-file/' in line and '200' in line:
                        # Extract tunnel ID from URL
                        parts = line.split()
                        if len(parts) >= 7:
                            url = parts[6]  # Request URL
                            if '/download-file/' in url:
                                # Parse /download-file/tunnel_id/filename
                                url_parts = url.split('/')
                                if len(url_parts) >= 3 and url_parts[1] == 'download-file':
                                    tunnel_id = url_parts[2]
                                    
                                    # Extract timestamp and check if recent
                                    timestamp_str = ' '.join(parts[3:5]).strip('[]')
                                    try:
                                        log_time = datetime.strptime(timestamp_str, '%d/%b/%Y:%H:%M:%S %z')
                                        log_time = log_time.replace(tzinfo=None)  # Remove timezone
                                        
                                        # Only count recent connections (last 60 seconds)
                                        if (current_time - log_time).seconds <= 60:
                                            tunnel_connections[tunnel_id] = tunnel_connections.get(tunnel_id, 0) + 1
                                            
                                            # Count bytes for actual file downloads only
                                            if len(parts) >= 10:
                                                method = parts[5].strip('"').split()[0] if len(parts) > 5 else ""
                                                status = parts[8] if len(parts) > 8 else ""
                                                bytes_sent = parts[9]
                                                
                                                # Only count bytes for actual file downloads:
                                                # - GET requests with 200 status to /download-file/ endpoint
                                                if (method == "GET" and status == "200" and bytes_sent.isdigit()):
                                                    bytes_val = int(bytes_sent)
                                                    
                                                    # Record all bytes from actual file downloads
                                                    if bytes_val > 0:
                                                        await self._record_download_bytes(tunnel_id, bytes_val)
                                    except:
                                        pass  # Skip invalid timestamps
            
            return tunnel_connections
            
        except Exception as e:
            logger.error(f"Error getting tunnel connections: {e}")
            return {}
    
    async def _record_download_bytes(self, tunnel_id: str, bytes_sent: int):
        """Record bytes served for a tunnel"""
        try:
            tunnel_key = f"tunnel:{tunnel_id}"
            
            # Check if tunnel exists
            if self.redis_client.exists(tunnel_key):
                # Increment bytes served
                current_total = self.redis_client.hincrby(tunnel_key, "bytes_served", bytes_sent)
                
                # Update last activity
                self.redis_client.hset(tunnel_key, "last_activity", datetime.utcnow().isoformat())
                
                logger.info(f"Updated tunnel {tunnel_id}: +{bytes_sent} bytes (total: {current_total})")
                
                # Check if download is complete
                await self._check_download_completion(tunnel_id)
                
        except Exception as e:
            logger.error(f"Error recording download bytes: {e}")
    
    async def _check_download_completion(self, tunnel_id: str):
        """Check if download is complete based on file size vs bytes served"""
        try:
            tunnel_info = self.tunnel_manager.get_tunnel_info(tunnel_id)
            if not tunnel_info:
                return
            
            # Skip if tunnel is already destroyed or marked as complete
            tunnel_status = tunnel_info.get("status")
            if tunnel_status != "active":
                return
            
            # Check if already marked as complete (to prevent duplicate cleanup)
            if tunnel_info.get("download_complete"):
                return
            
            file_path = tunnel_info.get("file_path")
            if file_path:
                nas_mount = os.getenv("NAS_MOUNT_PATH", "/data")
                full_path = os.path.join(nas_mount, file_path.lstrip('/'))
                
                if os.path.exists(full_path):
                    file_size = os.path.getsize(full_path)
                    bytes_served = int(tunnel_info.get("bytes_served", 0))
                    
                    # Multiple completion detection methods:
                    
                    # Method 1: File size comparison (only for larger files)
                    size_complete = False
                    if file_size >= 10240:  # Only use size-based detection for files 10KB or larger
                        completion_threshold = file_size * 0.95
                        size_complete = bytes_served >= completion_threshold
                    
                    # Method 2: Connection lifecycle - no active connections for 30+ seconds after serving bytes
                    last_activity = tunnel_info.get("last_activity")
                    active_connections = int(tunnel_info.get("active_connections", 0))
                    connection_complete = False
                    
                    if bytes_served > 0 and active_connections == 0 and last_activity:
                        try:
                            last_time = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                            idle_seconds = (datetime.utcnow() - last_time).total_seconds()
                            connection_complete = idle_seconds >= 30  # 30 second idle after bytes served
                        except:
                            pass
                    
                    # Method 3: For small files (<10KB), require idle time after download
                    small_file_complete = False
                    if file_size < 10240 and bytes_served > 0 and active_connections == 0 and last_activity:
                        try:
                            last_time = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                            idle_seconds = (datetime.utcnow() - last_time).total_seconds()
                            small_file_complete = idle_seconds >= 60  # 60 second idle for small files
                        except:
                            pass
                    
                    # Trigger completion if any method indicates download is done
                    if size_complete or connection_complete or small_file_complete:
                        # Mark as complete first to prevent duplicate processing
                        tunnel_key = f"tunnel:{tunnel_id}"
                        self.redis_client.hset(tunnel_key, "download_complete", "true")
                        
                        completion_reason = "size_threshold" if size_complete else \
                                          "connection_idle" if connection_complete else "small_file"
                        
                        logger.info(f"Download complete for tunnel {tunnel_id} ({bytes_served}/{file_size} bytes, reason: {completion_reason})")
                        await self._cleanup_tunnel(tunnel_id, f"download_complete_{completion_reason}")
                        
        except Exception as e:
            logger.error(f"Error checking download completion: {e}")
    
    async def _update_download_tracking(self, tunnel_connections: Dict[str, int], nginx_stats: Dict):
        """Update download tracking based on connection data"""
        try:
            current_time = datetime.utcnow()
            
            # Update activity for tunnels with active connections
            for tunnel_id, connection_count in tunnel_connections.items():
                tunnel_key = f"tunnel:{tunnel_id}"
                
                if self.redis_client.exists(tunnel_key):
                    # Update last seen and connection info
                    self.redis_client.hset(tunnel_key, mapping={
                        "last_seen": current_time.isoformat(),
                        "active_connections": connection_count
                    })
                    
                    # Track connection changes
                    last_count = self.last_connection_counts.get(tunnel_id, 0)
                    if connection_count != last_count:
                        logger.info(f"Tunnel {tunnel_id}: {connection_count} active connections")
                        self.last_connection_counts[tunnel_id] = connection_count
                        
        except Exception as e:
            logger.error(f"Error updating download tracking: {e}")
    
    async def _monitor_tunnel_health(self):
        """Monitor tunnel health and detect stalls"""
        logger.info("Starting tunnel health monitoring")
        
        while True:
            try:
                current_time = datetime.utcnow()
                stalled_tunnels = []
                
                # Get all active tunnels
                active_tunnels = self.tunnel_manager.list_active_tunnels()
                
                for tunnel in active_tunnels:
                    tunnel_id = tunnel.get("tunnel_id")
                    
                    # A tunnel is only stalled if it has started transferring data
                    bytes_served = int(tunnel.get("bytes_served", 0))
                    if bytes_served == 0:
                        continue # Not started, not stalled. Let it expire naturally.

                    last_activity = tunnel.get("last_activity")
                    stall_time = None
                    if last_activity:
                        try:
                            stall_time = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                        except:
                            pass # Should not happen if last_activity is valid
                    
                    if stall_time and (current_time - stall_time).seconds > self.stall_timeout:
                        logger.info(f"Tunnel {tunnel_id} stalled after {bytes_served} bytes, cleaning up.")
                        stalled_tunnels.append(tunnel_id)
                
                # Clean up stalled tunnels
                for tunnel_id in stalled_tunnels:
                    await self._cleanup_tunnel(tunnel_id, "stalled")
                
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error monitoring tunnel health: {e}")
                await asyncio.sleep(30)
    
    async def _cleanup_expired_tunnels(self):
        """Clean up expired tunnels based on TTL"""
        logger.info("Starting expired tunnel cleanup")
        
        while True:
            try:
                # Clean up expired tunnels
                cleaned_tunnels = self.tunnel_manager.cleanup_expired_tunnels()
                
                # Clean up expired tokens  
                from token_service import TokenService
                token_service = TokenService(self.redis_client)
                cleaned_tokens = token_service.cleanup_expired_tokens()
                
                if cleaned_tunnels > 0 or cleaned_tokens > 0:
                    logger.info(f"Cleanup: {cleaned_tunnels} tunnels, {cleaned_tokens} tokens")
                
                await asyncio.sleep(60)  # Run cleanup every 1 minute
                
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_tunnel(self, tunnel_id: str, reason: str):
        """Clean up a specific tunnel"""
        try:
            # Pass reason to tunnel manager for consistent logging
            success = self.tunnel_manager.destroy_tunnel(tunnel_id, reason=reason)
            if success:
                # Update tunnel status with reason
                tunnel_key = f"tunnel:{tunnel_id}"
                self.redis_client.hset(tunnel_key, mapping={
                    "cleanup_reason": reason,
                    "cleanup_time": datetime.utcnow().isoformat()
                })
                
                logger.info(f"Cleaned up tunnel {tunnel_id}: {reason}")
            
        except Exception as e:
            logger.error(f"Error cleaning up tunnel {tunnel_id}: {e}")

    def get_download_stats(self, tunnel_id: str) -> Optional[Dict]:
        """Get download statistics for a tunnel"""
        try:
            tunnel_key = f"tunnel:{tunnel_id}"
            tunnel_data = self.redis_client.hgetall(tunnel_key)
            
            if not tunnel_data:
                return None
            
            return {
                "tunnel_id": tunnel_id,
                "last_activity": tunnel_data.get("last_activity"),
                "last_seen": tunnel_data.get("last_seen"),
                "bytes_served": int(tunnel_data.get("bytes_served", 0)),
                "active_connections": int(tunnel_data.get("active_connections", 0)),
                "is_active": tunnel_data.get("status") == "active"
            }
            
        except Exception as e:
            logger.error(f"Error getting download stats: {e}")
            return None
    
    async def _monitor_funnel_state(self):
        """Monitor funnel state and ensure it matches tunnel activity"""
        logger.info("Starting funnel state monitoring")
        
        while True:
            try:
                # Check every 2 minutes
                await asyncio.sleep(120)
                
                active_tunnels = self.tunnel_manager.list_active_tunnels()
                funnel_active = self.tunnel_manager.is_funnel_active()
                
                # Funnel should be active if and only if there are active tunnels
                if len(active_tunnels) > 0 and not funnel_active:
                    logger.warning(f"Funnel inactive but {len(active_tunnels)} tunnels active - activating funnel")
                    self.tunnel_manager._ensure_persistent_funnel()
                elif len(active_tunnels) == 0 and funnel_active:
                    logger.warning("Funnel active but no tunnels - deactivating funnel")
                    self.tunnel_manager._reset_funnel()
                else:
                    logger.debug(f"Funnel state correct: {len(active_tunnels)} tunnels, funnel {'on' if funnel_active else 'off'}")
                
            except Exception as e:
                logger.error(f"Error monitoring funnel state: {e}")
                await asyncio.sleep(60) 