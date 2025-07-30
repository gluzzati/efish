#!/usr/bin/env python3
"""
Test script for FRP tunnel manager implementation
"""

import os
import sys
import time
import redis
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent / "app"))

from tunnel_manager import TunnelManager

def test_frp_tunnel_manager():
    """Test the FRP tunnel manager implementation"""
    
    print("🧪 Testing FRP Tunnel Manager Implementation")
    print("=" * 50)
    
    # Set up test environment variables
    os.environ.update({
        "FRP_SERVER_ADDR": "test.vps.com",
        "FRP_SERVER_PORT": "7000",
        "FRP_TOKEN": "test_token_123",
        "DYNAMIC_PORT_SECRET": "test_secret_456",
        "DYNAMIC_BASE_PORT": "30000",
        "DYNAMIC_PORT_RANGE": "1000",
        "DYNAMIC_PORT_INTERVAL": "300"
    })
    
    # Initialize Redis client (use a test database)
    try:
        redis_client = redis.from_url("redis://localhost:6379/1", decode_responses=True)
        redis_client.ping()
        print("✅ Redis connection successful")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("Make sure Redis is running on localhost:6379")
        return False
    
    # Initialize tunnel manager
    try:
        tunnel_manager = TunnelManager(redis_client)
        print("✅ Tunnel manager initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize tunnel manager: {e}")
        return False
    
    # Test dynamic port calculation
    print("\n🔢 Testing Dynamic Port Calculation")
    print("-" * 30)
    
    try:
        port1 = tunnel_manager._calculate_dynamic_port()
        print(f"Current port: {port1}")
        
        # Test that port calculation is deterministic
        port2 = tunnel_manager._calculate_dynamic_port()
        if port1 == port2:
            print("✅ Port calculation is deterministic")
        else:
            print("❌ Port calculation is not deterministic")
            return False
            
        # Test port range
        if 30000 <= port1 <= 30999:
            print("✅ Port is within expected range (30000-30999)")
        else:
            print(f"❌ Port {port1} is outside expected range")
            return False
            
    except Exception as e:
        print(f"❌ Port calculation failed: {e}")
        return False
    
    # Test FRP config generation
    print("\n📝 Testing FRP Config Generation")
    print("-" * 30)
    
    try:
        config = tunnel_manager._generate_frpc_config(port1)
        print("✅ FRP config generated successfully")
        
        # Check that config contains expected values
        if "test.vps.com" in config and "7000" in config and "test_token_123" in config:
            print("✅ Config contains expected values")
        else:
            print("❌ Config missing expected values")
            return False
            
    except Exception as e:
        print(f"❌ FRP config generation failed: {e}")
        return False
    
    # Test FRP status
    print("\n📊 Testing FRP Status")
    print("-" * 30)
    
    try:
        status = tunnel_manager.get_frp_status()
        print(f"✅ FRP status retrieved: {status}")
        
        expected_keys = ["frp_running", "current_port", "server_addr", "server_port"]
        for key in expected_keys:
            if key in status:
                print(f"✅ Status contains {key}")
            else:
                print(f"❌ Status missing {key}")
                return False
                
    except Exception as e:
        print(f"❌ FRP status failed: {e}")
        return False
    
    # Test tunnel creation (without actually starting FRP)
    print("\n🔗 Testing Tunnel Creation Logic")
    print("-" * 30)
    
    try:
        # Mock the FRP start method to avoid actual subprocess calls
        original_start_frpc = tunnel_manager._start_frpc
        tunnel_manager._start_frpc = lambda: True
        
        tunnel_data = tunnel_manager.create_tunnel("test_file.txt", "test_token_123", 3600)
        
        if tunnel_data:
            print("✅ Tunnel creation logic works")
            print(f"   Tunnel ID: {tunnel_data.get('tunnel_id')}")
            print(f"   Public URL: {tunnel_data.get('public_url')}")
            print(f"   FRP Port: {tunnel_data.get('frp_port')}")
        else:
            print("❌ Tunnel creation failed")
            return False
            
        # Restore original method
        tunnel_manager._start_frpc = original_start_frpc
        
    except Exception as e:
        print(f"❌ Tunnel creation test failed: {e}")
        return False
    
    # Test tunnel cleanup
    print("\n🧹 Testing Tunnel Cleanup")
    print("-" * 30)
    
    try:
        # Get list of active tunnels
        active_tunnels = tunnel_manager.list_active_tunnels()
        print(f"Active tunnels before cleanup: {len(active_tunnels)}")
        
        # Clean up expired tunnels
        cleaned = tunnel_manager.cleanup_expired_tunnels()
        print(f"Cleaned up {cleaned} expired tunnels")
        
        active_tunnels_after = tunnel_manager.list_active_tunnels()
        print(f"Active tunnels after cleanup: {len(active_tunnels_after)}")
        
        print("✅ Tunnel cleanup works")
        
    except Exception as e:
        print(f"❌ Tunnel cleanup failed: {e}")
        return False
    
    print("\n🎉 All tests passed!")
    print("=" * 50)
    print("The FRP tunnel manager implementation is working correctly.")
    print("\nNext steps:")
    print("1. Configure your VPS with the FRP server")
    print("2. Update environment variables with real values")
    print("3. Deploy the updated docker-compose.yml")
    print("4. Test end-to-end functionality")
    
    return True

if __name__ == "__main__":
    success = test_frp_tunnel_manager()
    sys.exit(0 if success else 1) 