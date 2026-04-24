import requests
import subprocess
import urllib3
import datetime
import json

urllib3.disable_warnings()

SLACK_WEBHOOK = "https://hooks.slack.com/services/xxxxxxxxx"
OPNSENSE_URL  = "https://192.168.10.1"
API_KEY       = "xxxxxxxxxxxx"
API_SECRET    = "xxxxxxxxxxxx"

CRITICAL_RULES = ["Block Guest to LAN", "Block Guest to DMZ", "Allow LAN to DMZ SSH"]
WAN_GATEWAY    = "8.8.8.8"

results = []
failures = []

def api_get(endpoint):
    return requests.get(
        f"{OPNSENSE_URL}{endpoint}",
        auth=(API_KEY, API_SECRET),
        verify=False,
        timeout=5
    )

def check(name, passed, detail=""):
    status = "PASS!!" if passed else "FAIL!!"
    line = f"{status} | {name} | {detail}"
    results.append(line)
    if not passed:
        failures.append(line)
    print(line)

def send_slack(message):
    requests.post(SLACK_WEBHOOK, json={"text": message})

# Check 1: Interface status
try:
    r = api_get("/api/diagnostics/interface/getInterfaceStatistics")
    data = r.json()
    stats = data.get("statistics", {})
    all_keys = " ".join(stats.keys()).upper()
    check("Interface WAN present", "WAN" in all_keys, "up" if "WAN" in all_keys else "missing")
    check("Interface LAN present", "LAN" in all_keys, "up" if "LAN" in all_keys else "missing")
    check("Interface Guest present", "OPT1" in all_keys or "GUEST" in all_keys,
          "up" if "OPT1" in all_keys or "GUEST" in all_keys else "missing")
    check("Interface DMZ present", "OPT2" in all_keys or "DMZ" in all_keys,
          "up" if "OPT2" in all_keys or "DMZ" in all_keys else "missing")
except Exception as e:
    check("Interface status", False, str(e)[:80])

# Check 2: Critical firewall rules
try:
    r = api_get("/api/firewall/filter/searchRule")
    data = r.json()
    rows = data.get("rows", [])
    all_descriptions = [row.get("description", "") for row in rows]
    for rule_name in CRITICAL_RULES:
        exists = any(rule_name in desc for desc in all_descriptions)
        check(f"Rule: {rule_name}", exists,
              "found" if exists else "MISSING - security risk")
except Exception as e:
    check("Firewall rules", False, str(e)[:80])

# Check 3: WAN reachability
result = subprocess.run(
    ["ping", "-c", "2", "-W", "3", WAN_GATEWAY],
    capture_output=True
)
check("WAN internet reachability", result.returncode == 0,
      f"ping to {WAN_GATEWAY}")

# Check 4: CPU and memory
try:
    r = api_get("/api/core/system/status")
    data = r.json()
    cpu = float(data.get("cpu", {}).get("used", 0))
    mem = float(data.get("memory", {}).get("used_fraq", 0))
    check("CPU usage", cpu < 80, f"{cpu}% used")
    check("Memory usage", mem < 85, f"{mem}% used")
except Exception as e:
    check("CPU/Memory", False, str(e)[:80])

# Check 5: DHCP leases
try:
    hour = datetime.datetime.now().hour
    is_business_hours = 8 <= hour <= 20
    r = api_get("/api/dhcpv4/leases/searchLease")
    data = r.json()
    total_leases = len(data.get("rows", []))
    if is_business_hours:
        check("DHCP leases", total_leases > 0,
              f"{total_leases} active leases")
    else:
        check("DHCP leases", True,
              f"{total_leases} leases - off hours")
except Exception as e:
    check("DHCP leases", False, str(e)[:80])

# Check 6: State table
try:
    r = api_get("/api/diagnostics/firewall/pfStates")
    data = r.json()
    current = int(data.get("current", 0))
    maximum = int(data.get("maximum", 0))
    if maximum > 100:
        pct = round((current / maximum) * 100, 1)
        check("State table", pct < 80,
              f"{pct}% full ({current}/{maximum})")
    else:
        check("State table", True,
              f"{current} active states")
except Exception as e:
    check("State table", False, str(e)[:80])

# Check 7: DMZ nginx
try:
    r = requests.get("http://192.168.30.10", timeout=5)
    check("DMZ nginx", r.status_code == 200, "responding on port 80")
except Exception as e:
    check("DMZ nginx", False, "DMZ-Server powered off or nginx down")

# Send Slack report
timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
report = f"*OPNsense Health Report — {timestamp}*\n\n"
report += "\n".join(results)

if failures:
    report += f"\n\n*{len(failures)} FAILURE(S) DETECTED — ACTION REQUIRED!!*"
else:
    report += "\n\n*All systems operational!!*"

send_slack(report)
print("\nReport sent to Slack.")
