# Migrate from Tailscale to FRP for Dynamic Tunnel Management

## Overview
Replace the current Tailscale-based tunnel system with FRP (Fast Reverse Proxy) to enable dynamic port management, automated firewall rules, and improved security through ephemeral public access.

## Background
- Current system uses Tailscale funnels for public access
- Need to eliminate dependency on Tailscale
- Want to implement dynamic port calculation for security
- Require automated firewall management via IONOS API

## Requirements

### Functional
- [ ] Remove all Tailscale logic from `tunnel_manager.py`
- [ ] Implement FRP server (VPS) and client (homelab) subprocess management
- [ ] Add dynamic port calculation using shared secret + time (pyotp library)
- [ ] Integrate IONOS Python SDK for firewall automation
- [ ] Expose FastAPI endpoints for tunnel lifecycle control
- [ ] Maintain existing Redis-based tunnel state management

### Technical
- [ ] Use FRP for tunnel management (not Inlets)
- [ ] Implement HMAC-based port calculation (see architecture doc)
- [ ] Support configurable port ranges and intervals
- [ ] Handle clock drift gracefully
- [ ] Log all port changes and firewall updates
- [ ] Maintain backward compatibility with existing API endpoints

### Security
- [ ] Only current dynamic port is open at any time
- [ ] Shared secret stored securely (environment variable)
- [ ] HTTPS and authentication for REST API
- [ ] No sensitive data exposed to VPS
- [ ] Optionally restrict allowed source IPs

## Implementation Plan

### Phase 1: Core FRP Integration
1. [ ] Install and configure FRP server on VPS
2. [ ] Install and configure FRP client on homelab
3. [ ] Update `tunnel_manager.py` to use FRP subprocess calls
4. [ ] Test basic tunnel creation/destruction

### Phase 2: Dynamic Port Logic
1. [ ] Implement port calculation using pyotp
2. [ ] Add configuration for shared secret, port range, interval
3. [ ] Integrate port calculation into tunnel management
4. [ ] Test port changes at specified intervals

### Phase 3: Firewall Automation
1. [ ] Integrate IONOS Python SDK
2. [ ] Implement firewall rule management
3. [ ] Add automatic port opening/closing
4. [ ] Test firewall automation end-to-end

### Phase 4: FastAPI Control
1. [ ] Add endpoints for tunnel status
2. [ ] Add endpoints for manual port management
3. [ ] Add endpoints for firewall rule status
4. [ ] Update documentation and examples

## Dependencies
- [pyotp](https://pypi.org/project/pyotp/) for TOTP/dynamic port calculation
- [IONOS Python SDK](https://docs.ionos.com/python-sdk/api/firewallrulesapi) for firewall automation
- FRP binary installation on both VPS and homelab

## Configuration Changes
- Add environment variables for shared secret, port range, interval
- Add IONOS API credentials
- Update Docker configuration for FRP containers
- Update nginx configuration if needed

## Testing Checklist
- [ ] Basic FRP tunnel creation works
- [ ] Dynamic port calculation is consistent between client/server
- [ ] Firewall rules update correctly
- [ ] FastAPI endpoints return correct status
- [ ] Tunnel expiration works as expected
- [ ] System recovers from failures gracefully
- [ ] Performance is acceptable

## Acceptance Criteria
- [ ] All Tailscale logic removed from codebase
- [ ] FRP tunnels work reliably with dynamic ports
- [ ] Firewall automation functions correctly
- [ ] FastAPI provides full tunnel control
- [ ] No regression in existing functionality
- [ ] Documentation updated

## References
- [Dynamic Tunnel Architecture Doc](dynamic-tunnel-architecture.md)
- [FRP Documentation](https://github.com/fatedier/frp)
- [IONOS Python SDK](https://docs.ionos.com/python-sdk/api/firewallrulesapi)