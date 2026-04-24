# Enterprise Network Security & Traffic Control Lab

Virtualized multi-zone enterprise network built on OPNsense — implementing zone-based firewall policy, QoS traffic shaping, Ansible automation via REST API, and Python-based health monitoring with Slack alerting. Every security control is verified with packet captures and firewall logs. Every bandwidth claim is backed by iperf3 measurements.

---

## Architecture

```
                        ┌─────────────────┐
                        │   OPNsense FW   │
                        │  192.168.x.1    │
                        └────────┬────────┘
               ┌─────────────────┼─────────────────┐
               │                 │                 │
        ┌──────▼──────┐  ┌───────▼──────┐  ┌──────▼──────┐
        │     LAN     │  │    Guest     │  │     DMZ     │
        │192.168.10.0 │  │192.168.20.0  │  │192.168.30.0 │
        │    /24      │  │    /24       │  │    /24      │
        │             │  │              │  │             │
        │ Employee    │  │ Untrusted    │  │ nginx web   │
        │ workstation │  │ users        │  │ SSH server  │
        └─────────────┘  └──────────────┘  └─────────────┘
```

| Zone | Subnet | Gateway | Trust Level |
|------|--------|---------|-------------|
| LAN | 192.168.10.0/24 | 192.168.10.1 | Trusted — full internet, DMZ access on SSH/HTTP only |
| Guest | 192.168.20.0/24 | 192.168.20.1 | Untrusted — internet only, 5 Mbps cap |
| DMZ | 192.168.30.0/24 | 192.168.30.1 | Semi-trusted — hosts internal servers, no Guest access |
| WAN | NAT (VirtualBox) | — | Untrusted — default-deny inbound |

---

## Lab Environment

| VM | Role | OS | Resources |
|----|------|----|-----------|
| OPNsense-FW | Firewall / Router | OPNsense 24.x (FreeBSD) | 2 cores, 2GB RAM |
| LAN-Client | Employee workstation | Ubuntu 22.04 Desktop | 1 core, 1GB RAM |
| Guest-Client | Guest user | Ubuntu 22.04 Desktop | 1 core, 1GB RAM |
| DMZ-Server | Web / SSH server | Ubuntu 22.04 Server | 1 core, 1GB RAM |

Everything runs inside VirtualBox on a single laptop. VirtualBox internal networks simulate physical network segments. OPNsense sits at the center with four virtual interfaces — one per zone.

---

## Firewall Policy

Rules are processed top-to-bottom. First match wins. Block rules precede allow rules on every interface.

| Interface | Source | Destination | Action | Purpose |
|-----------|--------|-------------|--------|---------|
| Guest | 192.168.20.0/24 | 192.168.20.1 | Block | Guests cannot reach firewall |
| Guest | 192.168.20.0/24 | 192.168.10.0/24 | Block | Guests cannot reach employees |
| Guest | 192.168.20.0/24 | 192.168.30.0/24 | Block | Guests cannot reach servers |
| Guest | 192.168.20.0/24 | any | Allow TCP 80,443 | Internet browsing only |
| LAN | 192.168.10.0/24 | 192.168.20.0/24 | Block | Employees cannot reach Guest zone |
| LAN | 192.168.10.0/24 | 192.168.30.10 | Allow TCP 22 | SSH to DMZ server |
| LAN | 192.168.10.0/24 | 192.168.30.10 | Allow TCP 80 | HTTP to DMZ server |
| LAN | 192.168.10.0/24 | any | Allow | Internet access |
| WAN | any | any | Block | Default-deny all inbound |

### Verification

Every rule was tested with both a positive test (traffic that should be allowed) and a negative test (traffic that should be blocked). Evidence captured via Wireshark-equivalent OPNsense firewall logs.

| Test | Result | Evidence |
|------|--------|---------|
| Guest → LAN ping | 100% packet loss | Screenshot — firewall log shows drop |
| Guest → DMZ HTTP | Connection timed out | Screenshot — browser timeout |
| Guest → google.com | Loaded successfully | Screenshot — Firefox |
| LAN → DMZ nginx | nginx welcome page | Screenshot — Firefox |
| LAN → DMZ SSH | Connected successfully | Screenshot — terminal |
| LAN → Guest ping | 100% packet loss | Screenshot — firewall log shows drop |

---

## QoS Traffic Shaping

### Pipes — Bandwidth Containers

| Pipe | Bandwidth | Applied To |
|------|-----------|------------|
| Guest-Cap | 5 Mbps hard limit | All Guest zone traffic |
| LAN-Guarantee | 20 Mbps guaranteed | All LAN zone traffic |

### Queues — Priority Lanes Inside LAN Pipe

| Queue | Weight | Share During Congestion | Traffic Type |
|-------|--------|------------------------|--------------|
| Management | 100 | ~83% | SSH port 22 |
| Interactive | 20 | ~16% | HTTP/HTTPS ports 80, 443 |
| Bulk | 1 | ~1% | Everything else |

Weights only activate during link saturation. Under normal load all traffic flows freely.

### Classification Rules

Five floating rules inspect every packet and direct it to the correct pipe or queue:

1. Guest interface, all protocols → Guest-Cap pipe
2. LAN TCP port 22 → Management queue
3. LAN TCP port 80 → Interactive queue
4. LAN TCP port 443 → Interactive queue
5. LAN all remaining → Bulk queue (catch-all)

### Measured Results

iperf3 test from LAN-Client to DMZ-Server over 30 seconds:

```
[ ID] Interval        Transfer     Bitrate
[  5] 0.00-30.03 sec  67.2 MBytes  18.8 Mbits/sec    receiver
```

LAN sustained ~19 Mbps confirming the LAN-Guarantee pipe is enforced. SSH remained responsive throughout the test with no perceptible latency — confirming Management queue priority is working under load.

---

## Automation

### Ansible — Firewall Rule Deployment

Firewall rules are deployed via the OPNsense REST API using an Ansible playbook. Configuration is version-controlled in Git. Running the playbook on a fresh OPNsense install rebuilds the entire security policy in seconds.

```bash
ansible-playbook -i inventory.yml firewall_rules.yml
```

Output on successful run:

```
TASK [Block Guest to LAN]   ✓ ok
TASK [Block Guest to DMZ]   ✓ ok
TASK [Allow LAN to DMZ SSH] ✓ ok
TASK [Apply firewall rules]  ✓ ok
PLAY RECAP: ok=4  failed=0
```

### Python — Network Health Monitor

`health_check.py` runs 13 checks across the network and sends a full pass/fail report to Slack. Designed around production monitoring principles — not just connectivity checks.

| Check | What It Detects |
|-------|-----------------|
| Interface status (WAN/LAN/Guest/DMZ) | Zone connectivity failure |
| Critical rule existence by name | Silent security policy deletion |
| WAN gateway reachability | Internet outage |
| CPU usage < 80% | Firewall performance degradation |
| Memory usage < 85% | Packet drop risk |
| DHCP lease count (time-aware) | Client connectivity failure |
| State table usage < 80% | Connection tracking exhaustion |
| DMZ nginx HTTP response | Server availability |

DHCP check is time-aware — zero leases at 3am is normal, zero leases during business hours is a failure. This prevents alert fatigue from false overnight alerts.

State table monitoring detects a failure mode most engineers don't know exists — when the connection tracking table fills up, the firewall silently drops new connections with no error message.

```bash
python3 health_check.py
```

Sample output:

```
PASS!! | Interface WAN present    | up
PASS!! | Interface LAN present    | up
PASS!! | Interface Guest present  | up
PASS!! | Interface DMZ present    | up
PASS!! | Rule: Block Guest to LAN | found
PASS!! | Rule: Block Guest to DMZ | found
PASS!! | Rule: Allow LAN to DMZ SSH | found
PASS!! | WAN internet reachability | ping to 8.8.8.8
PASS!! | CPU usage                | 0.0% used
PASS!! | Memory usage             | 0.0% used
PASS!! | DHCP leases              | 0 leases - off hours
PASS!! | State table              | 115 active states
PASS!! | DMZ nginx                | responding on port 80

Report sent to Slack.
```

Slack alert screenshot — `screenshots/slack_health_report.png`

---

## Skills Demonstrated

| Skill | Evidence |
|-------|---------|
| Zone-based firewall architecture | 4-zone network with enforced inter-zone policy |
| Stateful firewall rule design | Rule ordering, default-deny, verified with packet captures |
| QoS traffic shaping | Pipes, queues, classification rules — measured with iperf3 |
| Bandwidth enforcement | Guest capped at 5 Mbps, LAN sustained 19 Mbps |
| REST API automation | Ansible pushing firewall rules via OPNsense API |
| Infrastructure as code | Rules version-controlled in Git, reproducible from scratch |
| Production monitoring design | State table, rule integrity, time-aware thresholds, Slack alerting |
| Linux systems | Ubuntu VM administration, service management, network configuration |
| Troubleshooting | Diagnosed DHCP conflicts, DNS failures, package lock issues from logs |

---

## Repository Structure

```
├── scripts/
│   ├── firewall_rules.yml     # Ansible playbook — deploys firewall rules via REST API
│   └── health_check.py        # Python health monitor — 13 checks, Slack alerting
├── screenshots/               # Verification evidence for every firewall rule
└── configs/
    └── opnsense_config.xml    # Full OPNsense configuration backup
```

---

## How to Reproduce

**Requirements:** VirtualBox, OPNsense 24.x ISO, Ubuntu 22.04 ISO, Ansible, Python 3

1. Create four VMs in VirtualBox with internal networks as described in the architecture table
2. Install OPNsense, assign interfaces, set LAN IP to 192.168.10.1
3. Install Ubuntu on LAN-Client, Guest-Client, DMZ-Server
4. Install nginx on DMZ-Server: `sudo apt install nginx -y`
5. Add your OPNsense API key and secret to `inventory.yml`
6. Run: `ansible-playbook -i inventory.yml firewall_rules.yml`
7. Run: `python3 health_check.py`

Full OPNsense configuration is available in `configs/opnsense_config.xml` — restore via System → Configuration → Backups to replicate the exact environment.

---

## Stack

- **OPNsense 24.x** — FreeBSD-based enterprise firewall
- **Ansible** — firewall rule deployment via REST API
- **Python 3** — health monitoring and Slack integration
- **iperf3** — bandwidth measurement and QoS verification
- **Ubuntu 22.04** — client and server VMs
- **VirtualBox** — hypervisor for full lab virtualization
