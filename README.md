# Ephemeral File Sharing System

A secure, temporary file sharing system that creates public HTTPS tunnels for file downloads without exposing your network infrastructure. Files are shared through time-limited, single-use links that automatically clean up after download completion or timeout.

## 🚀 Features

- **Public Internet Access**: Files accessible via HTTPS from anywhere, no VPN required
- **Ephemeral Tunnels**: Temporary Tailscale Funnel endpoints that auto-destroy
- **Single-Use Tokens**: JWT-based links that can only be used once
- **Real-time Monitoring**: Track download progress, bytes served, completion status
- **Smart Cleanup**: Automatic tunnel termination on completion, timeout, or stall
- **Admin Dashboard**: Monitor active tunnels, view history, manual controls
- **Security**: Path validation, token expiration, no persistent exposure

## 📋 Prerequisites

- **Docker & Docker Compose** - Container orchestration
- **Tailscale Account** - For secure tunnel creation ([tailscale.com](https://tailscale.com))
- **Tailscale Auth Key** - Generate from Tailscale admin console
- **Tailscale Funnel Access** - Must be enabled on your tailnet
- **Traefik Proxy (Optional but Recommended)** - The default `docker-compose.yml` is configured to use [Traefik](https://traefik.io/traefik/) for network routing.

### Tailscale Setup Requirements

1. **Create Tailscale Account** at [tailscale.com](https://tailscale.com)
2. **Enable Funnel** in your tailnet settings (required for public internet access)
3. **Generate Auth Key**:
   - Go to Tailscale admin console → Settings → Keys
   - Create new auth key with "Ephemeral" and "Preauthorized" enabled
   - Copy the `tskey-auth-...` key

## 🛠 Installation

1. **Clone/Download** the filesharing directory
2. **Configure Environment**:
   ```bash
   cp env.example .env
   # Edit .env with your values:
   # - TAILSCALE_AUTH_KEY: Your tailscale auth key
   # - JWT_SECRET: Generate with `openssl rand -hex 32`
   ```

3. **Prepare File Storage**:
   ```bash
   # Create a directory for your files
   mkdir -p /path/to/your/data/
   # Put files to share in that directory
   echo "Hello World!" > /path/to/your/data/example.txt
   # Update docker-compose.yml to mount it:
   # volumes:
   #   - /path/to/your/data:/data:ro
   ```

4. **Configure Networking**:
    The system is designed to work behind a Traefik reverse proxy. Update the `Host` rule in `docker-compose.yml` to match your domain.
    ```yaml
    # In docker-compose.yml, under the file-sharer service:
    labels:
      - "traefik.http.routers.filesharer-http.rule=Host(`your-domain.com`)"
      - "traefik.http.routers.filesharer-https.rule=Host(`your-domain.com`)"
    ```

5. **Start Services**:
   ```bash
   docker compose up -d
   ```

6. **Verify Health**:
   ```bash
   curl http://your-domain.com/health
   ```

## 📁 Directory Structure

```
filesharing/
├── docker-compose.yml      # Service orchestration
├── .env                   # Environment configuration
├── app/                   # Python FastAPI application
│   ├── main.py           # Main application & API endpoints
│   ├── token_service.py  # JWT token management
│   ├── tunnel_manager.py # Tailscale tunnel operations
│   ├── monitor.py        # Download monitoring & cleanup
│   └── requirements.txt  # Python dependencies
├── web/                   # Web frontend (HTML, JS, CSS)
│   └── index.html       # Main user interface
├── nginx/                # File server configuration
│   └── nginx.conf       # Nginx config for logging
├── tunnels/               # Temporary tunnel symlinks
└── logs/                 # Application & access logs
```

## 🔄 Usage Workflow

This system provides a web interface for easy link generation and an API for automation.

### 1. Use the Web Interface
The interface will:
- List all available files from your shared data directory.
- Allow you to generate a secure, public download link with a single click.
- Copy the public URL to your clipboard.

### 2. Use the API
You can also generate links programmatically.

**Generate Download Link:**
```bash
curl -X POST https://your-domain.com/generate-link \
  -H "Content-Type: application/json" \
  -d '{"file_path": "example.txt", "expires_in_seconds": 3600}'
```

**Response:**
The API immediately creates a tunnel and returns the public download URL.

```json
{
  "download_url": "https://unique-id.your-tailnet.ts.net/tunnel123/files/tunnel123/example.txt",
  "tunnel_id": "tunnel123",
  "token": "eyJhbGci...",
  "file_path": "example.txt",
  "expires_in_seconds": 3600
}
```

### 3. Share the Download URL
Send the `download_url` from the web UI or API response to your recipient. The link is single-use and time-limited.

### 4. File Download
The recipient downloads the file directly from the secure Tailscale Funnel URL. The system monitors the download and automatically destroys the tunnel upon completion, timeout, or stall.

## 🔧 Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TAILSCALE_AUTH_KEY` | ✅ | - | Tailscale authentication key |
| `JWT_SECRET` | ✅ | - | Secret for JWT token signing (32+ chars) |
| `MAX_TUNNEL_SECONDS` | ❌ | 3600 | Maximum tunnel lifetime (seconds) |
| `STALL_TIMEOUT_SECONDS` | ❌ | 300 | Download stall detection timeout |
| `GRACE_PERIOD_SECONDS`| ❌ | 3600 | How long a tunnel persists after download completes |
| `NAS_MOUNT_PATH` | ❌ | `/data` | Internal container path for shared files |
| `REDIS_URL` | ❌ | redis://redis:6379 | Redis connection string |
| `BASE_URL` | ❌ | `http://localhost:8000` | Base URL for link generation (mostly for legacy/dev use) |

### File Storage

By default, files are served from the `./data` directory:

**Example:** Change this:
```yaml
```yaml
# In docker-compose.yml update the volume mount:
services:
  file-sharer:
    volumes:
      - /path/to/your/data:/data:ro
# ...
  nginx:
    volumes:
      - /path/to/your/data:/data:ro
```

## 📊 Admin API

The Admin API provides endpoints for monitoring and managing the system.

### List Available Files
```bash
curl https://your-domain.com/api/files
```

### Monitor Active Tunnels
```bash
curl https://your-domain.com/admin/tunnels
```

### Get Tunnel Details
```bash
curl https://your-domain.com/admin/tunnels/tunnel123/stats
```

### System Status
```bash
curl https://your-domain.com/admin/monitor/status
```

### Manual Cleanup
```bash
curl -X POST https://your-domain.com/admin/cleanup
```

### Terminate Tunnel
```bash
curl -X DELETE https://your-domain.com/admin/tunnels/tunnel123
```

### View History
```bash
curl https://your-domain.com/admin/history
```

## 🏗 Architecture

### Components

1. **Web Frontend**
   - A static HTML page (`index.html`) providing a user-friendly interface for listing files and generating links.

2. **FastAPI Application** (`file-sharer`)
   - Serves the web frontend.
   - JWT token generation/validation
   - File serving with security checks
   - Admin API endpoints
   - Download monitoring

3. **Tailscale Sidecar** (`tailscale-tunnel`)
   - Creates/destroys public tunnels
   - Handles HTTPS termination
   - Network namespace sharing

4. **Redis** (`redis-state`)
   - Token state tracking
   - Tunnel metadata storage
   - Download activity logs

5. **Nginx** (`file-server`)
   - Static file serving
   - Access logging for monitoring

### Security Model

The security model is designed around the principle of minimal exposure.

- **On-Demand Tunnels**: Tunnels are created for each download session and are never persistent. The system does not maintain a single, global public funnel.
- **Single-Use Tokens**: Access is granted via short-lived JWTs that are invalidated after their first use.
- **Path Validation**: The application validates file paths to prevent directory traversal attacks.
- **HTTPS Only**: All public traffic is served over HTTPS using Tailscale's built-in TLS termination.
- **Network Isolation**: The file server is not exposed to the internet; it is only accessible to the FastAPI application within the internal Docker network.

### Monitoring & Cleanup

The system includes intelligent monitoring to automate tunnel lifecycle management. This process is handled by a dedicated monitoring service that tails Nginx's access logs to track bytes transferred for each download.

It automatically destroys tunnels based on the following triggers:
- **Download Completion**: When 100% of the file has been served.
- **Stall Detection**: When no download activity is detected for a configured period (`STALL_TIMEOUT_SECONDS`).
- **Timeout Expiration**: When the tunnel's maximum lifetime (`MAX_TUNNEL_SECONDS`) is reached.
- **Manual Termination**: When triggered via the admin API.


### Expired Link Handling
- **Problem**: Expired or invalid tokens would return a standard `401 Unauthorized` or `404 Not Found` error.
- **Solution**: The system now returns a non-standard `HTTP 444` status (Connection Closed Without Response) for invalid tokens. This is a more secure practice as it simply drops the request without providing information to the client.

## 📝 License

This project is licensed under the MIT License - see the `LICENSE` file for details.

