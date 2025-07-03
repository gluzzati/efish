import jwt
import time
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import redis
import logging

logger = logging.getLogger(__name__)

class TokenService:
    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        self.jwt_secret = os.getenv("JWT_SECRET")
        if not self.jwt_secret:
            raise ValueError("JWT_SECRET environment variable is required")
        
    def generate_token(self, file_path: str, expires_in_seconds: int = 3600) -> str:
        """Generate a signed JWT token for file download"""
        token_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        payload = {
            "token_id": token_id,
            "file_path": file_path,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in_seconds),
            "single_use": True,
            "version": "1.0"
        }
        
        # Store token metadata in Redis
        token_key = f"token:{token_id}"
        token_data = {
            "file_path": file_path,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=expires_in_seconds)).isoformat(),
            "used": "false",
            "tunnel_id": "",  # Will be set when tunnel is created
        }
        
        # Set expiration in Redis to match JWT expiration
        self.redis_client.hset(token_key, mapping=token_data)
        self.redis_client.expire(token_key, expires_in_seconds)
        
        # Generate JWT
        token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")
        logger.info(f"Generated token {token_id} for file {file_path} (expires in: {expires_in_seconds}s)")
        
        return token
    
    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate JWT token and check single-use status"""
        try:
            # Decode JWT
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            token_id = payload.get("token_id")
            
            if not token_id:
                logger.warning("Token missing token_id")
                return None
            
            # Check Redis for token status
            token_key = f"token:{token_id}"
            token_data = self.redis_client.hgetall(token_key)
            
            if not token_data:
                logger.warning(f"Token {token_id} not found in Redis")
                return None
            
            # Check if already used
            if token_data.get("used") == "true":
                logger.warning(f"Token {token_id} already used")
                return None
            
            return {
                "token_id": token_id,
                "file_path": payload.get("file_path"),
                "expires_at": payload.get("exp"),
                "redis_data": token_data
            }
            
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None
    
    def mark_token_used(self, token_id: str, tunnel_id: str = "") -> bool:
        """Mark token as used and optionally store tunnel ID"""
        token_key = f"token:{token_id}"
        
        # Check if token exists
        if not self.redis_client.exists(token_key):
            return False
        
        # Update token status
        updates = {
            "used": "true",
            "used_at": datetime.utcnow().isoformat()
        }
        
        if tunnel_id:
            updates["tunnel_id"] = tunnel_id
        
        self.redis_client.hset(token_key, mapping=updates)
        logger.info(f"Marked token {token_id} as used")
        return True
    
    def get_token_info(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get token information from Redis"""
        token_key = f"token:{token_id}"
        token_data = self.redis_client.hgetall(token_key)
        
        if not token_data:
            return None
        
        return {
            "token_id": token_id,
            **token_data
        }
    
    def cleanup_expired_tokens(self) -> int:
        """Clean up expired tokens from Redis (called by background task)"""
        # Redis TTL handles this automatically, but we can scan for cleanup
        pattern = "token:*"
        keys = self.redis_client.keys(pattern)
        
        cleaned = 0
        for key in keys:
            ttl = self.redis_client.ttl(key)
            if ttl == -2:  # Key doesn't exist (expired)
                cleaned += 1
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired tokens")
        
        return cleaned 