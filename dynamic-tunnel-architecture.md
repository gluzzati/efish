# Dynamic Port, Self-Hosted Tunnel Architecture

## Overview

This system enables secure, ephemeral exposure of a homelab service (e.g., file server) to the public internet via a VPS relay, without requiring the VPS to join your private network. The public-facing port on the VPS changes periodically, based on a shared secret and the current time, providing a “second factor” for access. Firewall rules are managed programmatically via the VPS provider’s API (e.g., IONOS).

---

## Architecture Diagram

```mermaid
flowchart LR
    subgraph Internet
        User
    end
    subgraph VPS (Public)
        Relay["FRP/Inlets Server"]
        FW["Firewall (API-controlled)"]
    end
    subgraph HomeLab (Private)
        FileServer["File Server"]
        TunnelClient["FRP/Inlets Client"]
        PortCalc["Dynamic Port Calculator"]
    end

    User -- "HTTPS Request" --> FW
    FW -- "Allow traffic on dynamic port" --> Relay
    Relay -- "Tunnel" --> TunnelClient
    TunnelClient -- "Local Request" --> FileServer
    PortCalc -- "Current port" --> TunnelClient
    PortCalc -- "Current port" --> FW
```

---

## Components

1. **VPS (Relay)**
   - Runs FRP or Inlets server.
   - Public IP, open to the internet.
   - Firewall rules managed via provider API (e.g., IONOS FirewallRulesApi).

2. **Homelab (Client)**
   - Runs FRP or Inlets client, connects outbound to VPS.
   - Hosts the actual service (e.g., file server).
   - Runs a FastAPI (or similar) app to control tunnel and port logic.

3. **Dynamic Port Calculation**
   - Both VPS and homelab share a secret.
   - Port is derived from secret + current time interval (e.g., HMAC(secret, timestamp)).
   - Port changes at a fixed interval (e.g., every 5 minutes).

4. **Firewall Automation**
   - When port changes, the system:
     - Opens the new port on the VPS firewall.
     - Closes the previous port.
   - Uses provider’s API (e.g., IONOS Python SDK).

---

## Requirements

### Functional

- Expose a homelab service to the public internet via a VPS relay.
- The public-facing port changes periodically, based on a shared secret and time.
- Both client and server can calculate the current port independently.
- Firewall rules on the VPS are updated automatically to allow only the current port.
- Tunnel is established outbound from homelab to VPS (no inbound ports on homelab).
- No sensitive data or network access is exposed to the VPS.

### Security

- The VPS is not trusted and does not join the private network.
- Only the current dynamic port is open at any time.
- Optionally restrict allowed source IPs in firewall rules.
- All sensitive authentication and file access logic remains on the homelab.
- Use HTTPS and authentication for the REST API.

### Operational

- System can be started/stopped on demand.
- Handles clock drift (optionally allow previous/next interval ports).
- Logs all port changes and firewall rule updates.
- Recovers gracefully from failures (e.g., missed port change).

---

## Technology Choices

- **Tunnel:** FRP (https://github.com/fatedier/frp)
    - *Required: All tunnel management must use FRP. Inlets is not supported in this architecture.*
- **Firewall Automation:** IONOS Python SDK ([docs](https://docs.ionos.com/python-sdk/api/firewallrulesapi))
- **REST API & Control:** FastAPI (Python)
- **Port Calculation:** HMAC(secret, timestamp) or similar deterministic function
    - *Recommended Python library for TOTP/dynamic port calculation: [pyotp](https://pypi.org/project/pyotp/). Install with `pip install pyotp`.*

---

## Example Port Calculation (Python)

```python
import hmac, hashlib, time

def get_dynamic_port(secret, base_port=30000, port_range=1000, interval=300):
    now = int(time.time())
    epoch = now // interval
    msg = str(epoch).encode()
    key = secret.encode()
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    port_offset = int.from_bytes(digest[:2], 'big') % port_range
    return base_port + port_offset
```

---

## Next Steps

1. Prototype the port calculation and FastAPI control logic.
2. Script firewall rule management using the IONOS Python SDK.
3. Integrate FRP tunnel management.
4. Test end-to-end with dynamic port changes and firewall updates.

---

## Migration Guidance: What to Keep and What to Replace

When adapting an existing architecture or codebase to this dynamic tunnel system, consider the following:

### **What Can Be Kept**
- **Core Application Logic:** Your main service (e.g., file server, FastAPI app) and its business logic remain unchanged.
- **Authentication and Authorization:** Existing user authentication, JWT handling, and access control mechanisms can be reused.
- **Internal Networking:** Any logic or configuration related to serving files or handling requests within your homelab does not need to change.
- **Monitoring and Logging:** Existing logging, monitoring, and alerting systems can be retained and extended to include tunnel and firewall events.

### **What Needs to Be Replaced or Added**
- **Tunnel Management:**
  - Replace any Tailscale, ngrok, Inlets, or static port forwarding logic with FRP client/server setup.
  - Add automation for starting/stopping FRP tunnels and updating their configuration based on the dynamic port.
- **Dynamic Port Calculation:**
  - Implement the shared secret-based, time-dependent port calculation in both the client and any control scripts/services.
- **Firewall Automation:**
  - Integrate with your VPS provider's firewall API (e.g., IONOS Python SDK) to programmatically open/close the correct port at each interval.
  - Remove any static firewall rules for previous tunnel solutions.
- **Control API/Service:**
  - If not already present, add a FastAPI (or similar) REST API to orchestrate tunnel lifecycle, port calculation, and firewall updates.
- **Configuration:**
  - Add configuration for the shared secret, port range, interval, and any provider-specific credentials needed for firewall automation.
- **Security Enhancements:**
  - Review and update security policies to ensure only the current dynamic port is exposed, and restrict source IPs if possible.

By focusing changes on the networking, tunnel, and firewall management layers, you can preserve most of your existing application logic while gaining the security and flexibility of dynamic, ephemeral public access.

---

## Rough Draft Migration Plan

1. Remove Tailscale and any Inlets/other tunnel logic from the codebase.
2. Implement FRP server (on VPS) and FRP client (on homelab) subprocess management, assume fixed port for testing
3. Integrate dynamic port calculation (shared secret, time-based) for FRP.
4. Automate firewall rule updates for the dynamic port (IONOS API).
5. Expose control endpoints via FastAPI for tunnel lifecycle and status.
6. Test end-to-end: dynamic port, FRP tunnel, firewall automation, and FastAPI control.