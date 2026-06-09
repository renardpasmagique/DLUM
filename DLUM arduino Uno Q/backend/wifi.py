"""WiFi management via nmcli — invokes the system NetworkManager CLI.

The arduino user on UNO Q is in netdev group, so nmcli works without sudo
thanks to the default polkit rules. All commands are run as subprocesses.
"""
import asyncio
import shlex
from typing import Any

HOTSPOT_CON = "DLUM-Hotspot"
WLAN_DEV = "wlan0"


async def _run(*args: str, timeout: float = 10.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


def _parse_nmcli_terse(text: str, fields: list[str]) -> list[dict]:
    """Parse `nmcli -t -f F1,F2,... ...` output (colon-separated, escaped \\ and :)."""
    rows = []
    for line in text.strip().splitlines():
        if not line:
            continue
        # nmcli -t escapes ':' as '\:' and '\' as '\\'
        parts: list[str] = []
        cur = ""
        i = 0
        while i < len(line):
            c = line[i]
            if c == "\\" and i + 1 < len(line):
                cur += line[i + 1]
                i += 2
            elif c == ":":
                parts.append(cur)
                cur = ""
                i += 1
            else:
                cur += c
                i += 1
        parts.append(cur)
        rows.append({fields[j]: parts[j] if j < len(parts) else "" for j in range(len(fields))})
    return rows


async def status() -> dict[str, Any]:
    """Current WiFi state: which connection is active, mode, IP, SSID."""
    rc, out, err = await _run("nmcli", "-t", "-f", "NAME,DEVICE,TYPE,STATE", "connection", "show", "--active")
    active = _parse_nmcli_terse(out, ["name", "device", "type", "state"])
    rc, out, _ = await _run("ip", "-brief", "addr", "show", WLAN_DEV)
    ip_line = out.strip()
    ip4 = ""
    for tok in ip_line.split():
        if "." in tok and "/" in tok:
            ip4 = tok
            break

    rc, out, _ = await _run("nmcli", "-t", "-f", "NAME,UUID,TYPE,AUTOCONNECT", "connection", "show")
    saved = _parse_nmcli_terse(out, ["name", "uuid", "type", "autoconnect"])
    saved_wifi = [
        {"name": s["name"], "autoconnect": s["autoconnect"] == "yes"}
        for s in saved
        if s["type"] in ("wifi", "802-11-wireless")
    ]

    wifi_active = next(
        (a for a in active if a["device"] == WLAN_DEV and a["type"] in ("wifi", "802-11-wireless")),
        None,
    )
    mode = "off"
    if wifi_active:
        if wifi_active["name"] == HOTSPOT_CON:
            mode = "hotspot"
        else:
            mode = "station"

    return {
        "mode": mode,
        "active_connection": wifi_active["name"] if wifi_active else None,
        "ip4": ip4,
        "saved": saved_wifi,
    }


async def scan() -> list[dict[str, Any]]:
    """Trigger a rescan and return visible APs."""
    await _run("nmcli", "device", "wifi", "rescan", timeout=8.0)
    await asyncio.sleep(2)
    rc, out, _ = await _run(
        "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE,BSSID", "device", "wifi", "list",
    )
    rows = _parse_nmcli_terse(out, ["ssid", "signal", "security", "in_use", "bssid"])
    seen = {}
    for r in rows:
        s = r["ssid"]
        if not s:
            continue
        sig = int(r["signal"] or 0)
        if s not in seen or sig > seen[s]["signal"]:
            seen[s] = {
                "ssid": s,
                "signal": sig,
                "security": r["security"] or "open",
                "in_use": r["in_use"] == "*",
            }
    return sorted(seen.values(), key=lambda x: -x["signal"])


async def connect(ssid: str, password: str | None = None) -> dict[str, Any]:
    """Save & activate a WiFi connection. Returns success status."""
    if not ssid:
        return {"ok": False, "error": "ssid required"}
    args = ["nmcli", "device", "wifi", "connect", ssid, "ifname", WLAN_DEV]
    if password:
        args += ["password", password]
    rc, out, err = await _run(*args, timeout=30.0)
    return {"ok": rc == 0, "stdout": out.strip(), "stderr": err.strip()}


async def forget(name: str) -> dict[str, Any]:
    """Delete a saved connection profile."""
    if name == HOTSPOT_CON:
        return {"ok": False, "error": "cannot delete hotspot profile"}
    rc, out, err = await _run("nmcli", "connection", "delete", name)
    return {"ok": rc == 0, "stdout": out.strip(), "stderr": err.strip()}


async def hotspot(on: bool) -> dict[str, Any]:
    """Activate or deactivate the hotspot connection."""
    if on:
        rc, out, err = await _run("nmcli", "connection", "up", HOTSPOT_CON, timeout=20.0)
    else:
        rc, out, err = await _run("nmcli", "connection", "down", HOTSPOT_CON, timeout=15.0)
    return {"ok": rc == 0, "stdout": out.strip(), "stderr": err.strip()}
