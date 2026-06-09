"""DLUM network watchdog.

If wlan0 has no IPv4 address (no station connection up) for STARTUP_GRACE
seconds after boot, OR drops for FALLBACK_DELAY consecutive seconds, the
DLUM-Hotspot connection is activated so users can still reach the loom UI.

When in hotspot mode, periodically scan for known WiFi networks; if any
saved profile becomes visible, switch back to station.

Runs as a long-lived process (systemd unit). Logs to journal.
"""
import logging
import os
import subprocess
import time

WLAN = "wlan0"
HOTSPOT = "DLUM-Hotspot"
STARTUP_GRACE = 45  # seconds after boot before first decision
FALLBACK_DELAY = 30  # seconds without IP before fallback
RESCAN_PERIOD = 60   # while in hotspot, rescan for known WiFi every Ns

logging.basicConfig(level=logging.INFO, format="%(asctime)s netwatch %(message)s")
log = logging.getLogger()


def run(*args, timeout=10):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def has_ipv4():
    rc, out, _ = run("ip", "-brief", "addr", "show", WLAN)
    if rc != 0:
        return False
    for tok in out.split():
        if "." in tok and "/" in tok:
            return True
    return False


def active_wifi_connection():
    rc, out, _ = run("nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show", "--active")
    if rc != 0:
        return None
    for line in out.strip().splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == WLAN and parts[2] in ("wifi", "802-11-wireless"):
            return parts[0]
    return None


def saved_wifi_names():
    rc, out, _ = run("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show")
    if rc != 0:
        return []
    names = []
    for line in out.strip().splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] in ("wifi", "802-11-wireless") and parts[0] != HOTSPOT:
            names.append(parts[0])
    return names


def visible_ssids():
    run("nmcli", "device", "wifi", "rescan", timeout=8)
    time.sleep(2)
    rc, out, _ = run("nmcli", "-t", "-f", "SSID", "device", "wifi", "list")
    if rc != 0:
        return set()
    return {line for line in out.strip().splitlines() if line}


def activate_hotspot():
    log.info("activating hotspot %s", HOTSPOT)
    rc, out, err = run("nmcli", "connection", "up", HOTSPOT, timeout=20)
    log.info("hotspot up rc=%d %s %s", rc, out.strip(), err.strip())
    return rc == 0


def deactivate_hotspot():
    log.info("deactivating hotspot")
    rc, out, err = run("nmcli", "connection", "down", HOTSPOT, timeout=15)
    log.info("hotspot down rc=%d", rc)
    return rc == 0


def main():
    boot = time.time()
    fail_since = None
    last_scan = 0
    in_hotspot = active_wifi_connection() == HOTSPOT
    log.info("started, in_hotspot=%s", in_hotspot)

    while True:
        now = time.time()
        active = active_wifi_connection()
        ip_ok = has_ipv4() and active and active != HOTSPOT

        if in_hotspot:
            # In hotspot: scan periodically for known WiFi to switch back
            if now - last_scan > RESCAN_PERIOD:
                last_scan = now
                visible = visible_ssids()
                wanted = set(saved_wifi_names())
                match = visible & wanted
                if match:
                    log.info("known network appeared: %s — switching back to station", match)
                    deactivate_hotspot()
                    time.sleep(3)
                    in_hotspot = False
                    fail_since = None
        else:
            if ip_ok:
                fail_since = None
            else:
                # No IP. Wait grace period before action.
                if now - boot < STARTUP_GRACE:
                    pass  # still booting
                else:
                    if fail_since is None:
                        fail_since = now
                        log.info("no station IP, starting fallback timer")
                    elif now - fail_since > FALLBACK_DELAY:
                        if activate_hotspot():
                            in_hotspot = True
                            fail_since = None
                            last_scan = now

        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
