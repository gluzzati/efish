# FRP Tunnel Setup

This directory contains the configuration for the FRP (Fast Reverse Proxy) tunnel system that replaces Tailscale.

## Architecture

- **Homelab (Client)**: Runs FRP client (`frpc`) that connects to the VPS
- **VPS (Server)**: Runs FRP server (`frps`) that accepts connections from homelab
- **Dynamic Ports**: Ports change periodically based on shared secret and time

## Setup Instructions

### 1. VPS Setup (Server Side)

1. Copy the `frp/` directory to your VPS
2. Update `frps.ini` with your desired configuration:
   ```ini
   [common]
   bind_port = 7000
   token = your_secure_token_here
   dashboard_user = admin
   dashboard_pwd = your_secure_password_here
   ```

3. Deploy on VPS:
   ```bash
   cd frp
   docker-compose -f docker-compose.vps.yml up -d
   ```

4. Configure firewall to allow ports 7000, 7001, and 7500

### 2. Homelab Setup (Client Side)

1. Update environment variables in `.env`:
   ```bash
   FRP_SERVER_ADDR=your_vps_ip_here
   FRP_SERVER_PORT=7000
   FRP_TOKEN=your_secure_token_here
   DYNAMIC_PORT_SECRET=your_shared_secret_here
   DYNAMIC_BASE_PORT=30000
   DYNAMIC_PORT_RANGE=1000
   DYNAMIC_PORT_INTERVAL=300
   ```

2. Start the homelab services:
   ```bash
   docker-compose up -d
   ```

## Configuration

### Dynamic Port Calculation

The system uses TOTP-like calculation to determine the current port:

- **Base Port**: Starting port number (default: 30000)
- **Port Range**: Number of ports to choose from (default: 1000)
- **Interval**: How often ports change in seconds (default: 300 = 5 minutes)
- **Secret**: Shared secret for port calculation

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FRP_SERVER_ADDR` | VPS IP address | `your_vps_ip_here` |
| `FRP_SERVER_PORT` | FRP server port | `7000` |
| `FRP_TOKEN` | Authentication token | `your_frp_token_here` |
| `DYNAMIC_PORT_SECRET` | Secret for port calculation | `your_shared_secret_here` |
| `DYNAMIC_BASE_PORT` | Starting port number | `30000` |
| `DYNAMIC_PORT_RANGE` | Number of ports in range | `1000` |
| `DYNAMIC_PORT_INTERVAL` | Port change interval (seconds) | `300` |

## Monitoring

- **FRP Dashboard**: Access at `http://your_vps_ip:7500`
- **Logs**: Check `/logs/frpc.log` and `/logs/frps.log`
- **Status API**: Use the FastAPI endpoints to check tunnel status

## Security Notes

1. Use strong, unique tokens for FRP authentication
2. Use a strong shared secret for dynamic port calculation
3. Configure firewall rules to only allow necessary ports
4. Consider restricting source IPs in firewall rules
5. Monitor logs for suspicious activity

## Troubleshooting

### Common Issues

1. **Connection refused**: Check VPS firewall and FRP server status
2. **Authentication failed**: Verify FRP token matches on client and server
3. **Port not accessible**: Check if dynamic port is open in firewall
4. **Tunnel not working**: Verify nginx is running and accessible

### Debug Commands

```bash
# Check FRP client status
docker logs frpc-client

# Check FRP server status  
docker logs frps-server

# Test port connectivity
telnet your_vps_ip current_dynamic_port

# Check tunnel status via API
curl http://localhost:8000/api/tunnels/status
``` 