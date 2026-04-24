-> firewall_rules.yml - Ansible playbook that deploys firewall rules to OPNsense via REST API. Blocks Guest-to-LAN, Guest-to-DMZ, and allows LAN-to-DMZ SSH — all in one command.


-> health_check.py — Python script that runs 13 checks across all network zones and sends a pass/fail report to Slack. Monitors interface status, rule integrity, CPU/memory, DHCP leases, and DMZ server availability.
