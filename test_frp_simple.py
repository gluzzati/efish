#!/usr/bin/env python3
"""
Simplified test script for FRP tunnel manager implementation (no Redis required)
"""

import os
import sys
import time
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent / "app"))

def test_frp_core_functionality():
    """Test core FRP functionality without Redis"""
    
    print("🧪 Testing FRP Core Functionality (No Redis)")
    print("=" * 50)
    
    # Set up test environment variables
    os.environ.update({
        "FRP_SERVER_ADDR": "test.vps.com",
        "FRP_SERVER_PORT": "45413",
        "FRP_TOKEN": "test_token_123",
        "DYNAMIC_PORT_SECRET": "JBSWY3DPEHPK3PXP",  # Base32 encoded secret
        "DYNAMIC_BASE_PORT": "30000",
        "DYNAMIC_PORT_RANGE": "1000",
        "DYNAMIC_PORT_INTERVAL": "300"
    })
    
    # Import tunnel manager
    try:
        from tunnel_manager import TunnelManager
        print("✅ Tunnel manager imported successfully")
    except Exception as e:
        print(f"❌ Failed to import tunnel manager: {e}")
        return False
    
    # Test dynamic port calculation
    print("\n🔢 Testing Dynamic Port Calculation")
    print("-" * 30)
    
    try:
        # Create a mock Redis client
        class MockRedis:
            def ping(self): return True
            def hset(self, *args, **kwargs): return True
            def expire(self, *args, **kwargs): return True
            def sadd(self, *args, **kwargs): return True
            def smembers(self): return set()
            def scard(self): return 0
            def ttl(self, *args): return 3600
            def hgetall(self, *args): return {}
            def srem(self, *args, **kwargs): return True
        
        tunnel_manager = TunnelManager(MockRedis())
        print("✅ Tunnel manager initialized with mock Redis")
        
        # Test port calculation
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
        if "test.vps.com" in config and "45413" in config and "test_token_123" in config:
            print("✅ Config contains expected values")
        else:
            print("❌ Config missing expected values")
            return False
            
        print("Config preview:")
        print(config[:200] + "..." if len(config) > 200 else config)
            
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
    
    # Test tunnel creation logic (without actual FRP process)
    print("\n🔗 Testing Tunnel Creation Logic")
    print("-" * 30)
    
    try:
        # Mock the FRP start method to avoid actual subprocess calls
        original_start_frpc = tunnel_manager._start_frpc
        original_ensure_frp_tunnel = tunnel_manager._ensure_frp_tunnel
        
        def mock_start_frpc():
            tunnel_manager.current_port = tunnel_manager._calculate_dynamic_port()
            return True
            
        def mock_ensure_frp_tunnel():
            if not tunnel_manager.current_port:
                tunnel_manager.current_port = tunnel_manager._calculate_dynamic_port()
            return True
        
        tunnel_manager._start_frpc = mock_start_frpc
        tunnel_manager._ensure_frp_tunnel = mock_ensure_frp_tunnel
        
        tunnel_data = tunnel_manager.create_tunnel("test_file.txt", "test_token_123", 3600)
        
        if tunnel_data:
            print("✅ Tunnel creation logic works")
            print(f"   Tunnel ID: {tunnel_data.get('tunnel_id')}")
            print(f"   Public URL: {tunnel_data.get('public_url')}")
            print(f"   FRP Port: {tunnel_data.get('frp_port')}")
        else:
            print("❌ Tunnel creation failed")
            return False
            
        # Restore original methods
        tunnel_manager._start_frpc = original_start_frpc
        tunnel_manager._ensure_frp_tunnel = original_ensure_frp_tunnel
        
    except Exception as e:
        print(f"❌ Tunnel creation test failed: {e}")
        return False
    
    print("\n🎉 All core tests passed!")
    print("=" * 50)
    print("The FRP tunnel manager core functionality is working correctly.")
    print("\nNext steps:")
    print("1. Deploy FRP server on VPS")
    print("2. Test with real Redis connection")
    print("3. Test end-to-end functionality")
    
    return True

if __name__ == "__main__":
    success = test_frp_core_functionality()
    sys.exit(0 if success else 1) 