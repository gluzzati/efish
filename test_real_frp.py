#!/usr/bin/env python3
"""
Test real FRP connectivity with actual VPS
"""

import os
import sys
import socket
import time
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent / "app"))

def test_vps_connectivity(vps_ip):
    """Test basic connectivity to VPS FRP ports"""
    
    print(f"🔍 Testing connectivity to VPS: {vps_ip}")
    print("=" * 50)
    
    ports_to_test = [45413, 45414, 45415]
    
    for port in ports_to_test:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((vps_ip, port))
            sock.close()
            
            if result == 0:
                print(f"✅ Port {port} is open and accessible")
            else:
                print(f"❌ Port {port} is not accessible")
                
        except Exception as e:
            print(f"❌ Error testing port {port}: {e}")
    
    print()

def test_frp_config_generation(vps_ip, frp_token, shared_secret):
    """Test FRP config generation with real values"""
    
    print("📝 Testing FRP Config Generation with Real Values")
    print("=" * 50)
    
    # Set up environment variables
    os.environ.update({
        "FRP_SERVER_ADDR": vps_ip,
        "FRP_SERVER_PORT": "45413",
        "FRP_TOKEN": frp_token,
        "DYNAMIC_PORT_SECRET": shared_secret,
        "DYNAMIC_BASE_PORT": "30000",
        "DYNAMIC_PORT_RANGE": "1000",
        "DYNAMIC_PORT_INTERVAL": "300"
    })
    
    try:
        from tunnel_manager import TunnelManager
        
        # Create mock Redis for testing
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
        
        # Test port calculation
        current_port = tunnel_manager._calculate_dynamic_port()
        print(f"✅ Calculated current dynamic port: {current_port}")
        
        # Test config generation
        config = tunnel_manager._generate_frpc_config(current_port)
        print("✅ FRP config generated successfully")
        
        # Show config (with sensitive data masked)
        config_lines = config.split('\n')
        for line in config_lines:
            if 'token' in line:
                print(f"   {line.split('=')[0]}=***MASKED***")
            else:
                print(f"   {line}")
        
        print(f"\n📊 Current dynamic port: {current_port}")
        print(f"🌐 Public URL would be: http://{vps_ip}:{current_port}/files/TUNNEL_ID/file")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing FRP config: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Real FRP Connectivity Test")
    print("=" * 50)
    
    # Hardcoded VPS details
    vps_ip = "194.164.22.177"
    frp_token = "your_frp_token_here"  # Replace with your actual token
    shared_secret = "JBSWY3DPEHPK3PXP"  # Replace with your actual base32 secret
    
    print(f"Testing VPS: {vps_ip}")
    print()
    
    # Test connectivity
    test_vps_connectivity(vps_ip)
    
    # Test config generation
    if test_frp_config_generation(vps_ip, frp_token, shared_secret):
        print("\n🎉 Configuration test passed!")
        print("\nNext steps:")
        print("1. Update your .env file with these values")
        print("2. Start the full docker-compose stack")
        print("3. Test actual file sharing")
    else:
        print("\n❌ Configuration test failed!")
        sys.exit(1) 