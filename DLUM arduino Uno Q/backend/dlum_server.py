import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import serial
import serial.tools.list_ports
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dlum")

FRAME_COUNT_MAX = 8
SERIAL_BAUD = int(os.environ.get("DLUM_BAUD", "115200"))

# ── Colour-change announcement helpers ────────────────────────────────────────
# French names for each PALETTE entry in draft.js (index 0-15).
_PALETTE_NAMES = [
    "noir", "blanc", "rouge", "vert", "bleu", "orange",
    "violet", "turquoise", "brun", "gris", "rouge vif", "vert vif",
    "ciel", "jaune", "mauve", "cyan",
]
_SCROLL_MS_PX = 60    # Arduino textScrollSpeed (ms per pixel column)
_CHAR_PX = 6          # Font_5x7 column width per character
_DISPLAY_PX = 12      # LED matrix width


def _scroll_wait_ms(text: str) -> int:
    """Milliseconds for led_text(text) to finish scrolling on the Arduino.
    The firmware prepends and appends two spaces, so total chars = len+4."""
    total_px = _DISPLAY_PX + (len(text) + 4) * _CHAR_PX
    return int(total_px * _SCROLL_MS_PX * 1.1)   # +10 % timing buffer
# ──────────────────────────────────────────────────────────────────────────────
SERIAL_RECONNECT_DELAY = 2.0
HEARTBEAT_INTERVAL = 2.0
SERIAL_PORT_OVERRIDE = os.environ.get("DLUM_SERIAL_PORT")
HTTP_HOST = os.environ.get("DLUM_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("DLUM_PORT", "8000"))

STATIC_DIR = Path(__file__).parent / "static"
MOTOR_MAP_PATH = Path(__file__).parent / "motor_map.json"
SETTINGS_PATH = Path(__file__).parent / "settings.json"
LIBRARY_DIR = Path(__file__).parent / "library"

from motor_map import MotorMap
from settings_store import SettingsStore
from library import PatternLibrary
import wifi as wifi_mod

settings = SettingsStore(SETTINGS_PATH)
motor_map = MotorMap(MOTOR_MAP_PATH, frame_count=int(settings.get("frame_count") or 4))
library = PatternLibrary(LIBRARY_DIR)


def FRAME_COUNT() -> int:
    return int(settings.get("frame_count") or 4)


def find_unoq_port() -> str | None:
    if SERIAL_PORT_OVERRIDE:
        return SERIAL_PORT_OVERRIDE
    for p in serial.tools.list_ports.comports():
        if p.vid == 0x2341 and p.pid == 0x0078:
            return p.device
    return None


class MCUBridge:
    """Owns the serial connection to the MCU. Reads JSON lines, broadcasts to clients,
    and accepts outgoing commands. Reconnects automatically when the port disappears."""

    def __init__(self, hub: "Hub"):
        self.hub = hub
        self.port: str | None = None
        self.ser: serial.Serial | None = None
        self.write_lock = asyncio.Lock()
        self.last_state = {"step": 0, "frames": [0] * FRAME_COUNT_MAX, "connected": False, "rest": False}

    async def run(self):
        loop = asyncio.get_running_loop()
        buffer = b""
        while True:
            if self.ser is None:
                self.port = find_unoq_port()
                if self.port is None:
                    await self._set_connected(False)
                    await asyncio.sleep(SERIAL_RECONNECT_DELAY)
                    continue
                try:
                    self.ser = await loop.run_in_executor(
                        None,
                        lambda: serial.Serial(
                            self.port,
                            SERIAL_BAUD,
                            timeout=0.05,
                            write_timeout=0.5,
                            dsrdtr=False,
                            rtscts=False,
                            xonxoff=False,
                        ),
                    )
                    await self._set_connected(True)
                    log.info("Serial open on %s", self.port)
                    buffer = b""
                except (serial.SerialException, OSError) as e:
                    log.warning("Serial open failed (%s): %s", self.port, e)
                    self.ser = None
                    await asyncio.sleep(SERIAL_RECONNECT_DELAY)
                    continue
            try:
                chunk = await loop.run_in_executor(None, self.ser.read, 256)
            except (serial.SerialException, OSError) as e:
                log.warning("Serial read error: %s", e)
                await self._close()
                continue
            if not chunk:
                await asyncio.sleep(0.01)
                continue
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    log.debug("Non-JSON from MCU: %r", line)
                    continue
                await self._handle_mcu_event(msg)

    async def _handle_mcu_event(self, msg: dict):
        if msg.get("evt") == "state":
            frames = msg.get("frames", [0] * FRAME_COUNT())
            self.last_state["step"] = int(msg.get("step", self.last_state["step"]))
            self.last_state["frames"] = [int(x) for x in frames][:FRAME_COUNT()]
            if "rest" in msg:
                self.last_state["rest"] = bool(msg["rest"])
        elif msg.get("evt") == "button":
            # Backend-only handler. We do NOT broadcast button events to web
            # clients : an old cached JS could otherwise re-emit next_step
            # and double-advance the sequence.
            now = time.monotonic()
            last = getattr(self, "_last_button_t", 0.0)
            if now - last < 1.5:
                log.info("Button event IGNORED (backend debounce, %.0fms since last)",
                         (now - last) * 1000)
            else:
                self._last_button_t = now
                log.info("Physical button press → next_step / prep_next")
                try:
                    if prep.active:
                        await prep.next()
                    else:
                        await seq.next_step()
                except Exception as e:
                    log.warning("Button advance failed: %s", e)
            return  # <-- skip broadcast for button events
        await self.hub.broadcast({"type": "mcu_event", "data": msg})

    async def _set_connected(self, connected: bool):
        if self.last_state["connected"] != connected:
            self.last_state["connected"] = connected
            await self.hub.broadcast(
                {"type": "mcu_status", "connected": connected, "port": self.port}
            )
            if connected:
                # Push current frame count + persisted servo angles to the MCU.
                await asyncio.sleep(0.5)
                fc = FRAME_COUNT()
                await self.send({"cmd": "set_frame_count", "count": fc})
                await self.send({"cmd": "set_hold_ms", "value": max(0, int(settings.get("lift_hold_ms") or 0))})
                downs = settings.get("down_angles") or [30] * FRAME_COUNT_MAX
                ups = settings.get("up_angles") or [130] * FRAME_COUNT_MAX
                for i in range(fc):
                    await self.send({"cmd": "set_angle", "motor": i, "down": int(downs[i]), "up": int(ups[i])})

    async def _close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        await self._set_connected(False)
        await asyncio.sleep(SERIAL_RECONNECT_DELAY)

    async def send(self, cmd: dict) -> bool:
        if self.ser is None:
            return False
        line = (json.dumps(cmd) + "\n").encode("utf-8")
        async with self.write_lock:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self.ser.write, line
                )
                return True
            except (serial.SerialException, OSError) as e:
                log.warning("Serial write error: %s", e)
                await self._close()
                return False


class Hub:
    """Tracks connected websocket clients and broadcasts events to them."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()

    async def add(self, ws: WebSocket):
        async with self.lock:
            self.clients.add(ws)

    async def remove(self, ws: WebSocket):
        async with self.lock:
            self.clients.discard(ws)

    async def broadcast(self, payload: dict):
        text = json.dumps(payload)
        async with self.lock:
            dead = []
            for ws in self.clients:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.clients.discard(ws)


class Sequencer:
    """Plays a pattern step-by-step, advancing on physical button presses or
    on a Linux-side 'next' command."""

    # 3×5 pixel digit glyphs (each row = 3-bit mask, MSB = left column)
    _DIGIT_GLYPHS: dict[str, list[int]] = {
        "0": [0b111, 0b101, 0b101, 0b101, 0b111],
        "1": [0b010, 0b110, 0b010, 0b010, 0b111],
        "2": [0b111, 0b001, 0b111, 0b100, 0b111],
        "3": [0b111, 0b001, 0b011, 0b001, 0b111],
        "4": [0b101, 0b101, 0b111, 0b001, 0b001],
        "5": [0b111, 0b100, 0b111, 0b001, 0b111],
        "6": [0b111, 0b100, 0b111, 0b101, 0b111],
        "7": [0b111, 0b001, 0b001, 0b001, 0b001],
        "8": [0b111, 0b101, 0b111, 0b101, 0b111],
        "9": [0b111, 0b101, 0b111, 0b001, 0b111],
        "/": [0b001, 0b001, 0b010, 0b100, 0b100],
    }

    @staticmethod
    def _build_counter_bitmap(current_1indexed: int, total: int) -> list[int] | None:
        """Return 8-element list of 12-bit ints for led_set.
        Rows 1-5: 'current/total' in compact 3×5 font (no inter-char gap),
        centered horizontally. Row 7: progress bar.
        Returns None when the text is wider than 12 px — caller should use
        led_text (scrolling) as a fallback.
        """
        text = f"{current_1indexed}/{total}"
        char_w = 3  # each glyph is 3 columns wide; no gap for compactness
        total_w = len(text) * char_w
        if total_w > 12:
            return None  # too wide for static display → use led_text scroll
        start_col = max(0, (12 - total_w) // 2)

        rows = [0] * 8
        row_offset = 1  # glyphs in rows 1-5, row 0 and rows 6-7 free
        for ci, ch in enumerate(text):
            glyph = Sequencer._DIGIT_GLYPHS.get(ch, [0] * 5)
            col_offset = start_col + ci * char_w
            for gr in range(5):
                for gc in range(char_w):
                    if (glyph[gr] >> (char_w - 1 - gc)) & 1:
                        col = col_offset + gc
                        if col < 12:
                            rows[row_offset + gr] |= (1 << col)

        # Row 7: progress bar
        if total > 0:
            filled = round(12 * current_1indexed / total)
            rows[7] = (1 << min(filled, 12)) - 1
        return rows

    def __init__(self, mcu: MCUBridge, hub: Hub):
        self.mcu = mcu
        self.hub = hub
        self.pattern: list[list[int]] = []
        self.index = 0
        self.active = False
        # Optional rich draft data for LED preview rendering
        self.draft_threading: list[int] = []
        self.draft_logical_liftplan: list[list[int]] = []  # before mapping
        # Auto-play state
        self.auto_task: asyncio.Task | None = None
        self.auto_interval_ms: int = 5000
        self.auto_paused: bool = False
        self.next_allowed_at: float = 0.0
        # Weft colour data for colour-change announcements
        self.weft_colors: list[int] = []
        self._last_played_color: int = -1  # -1 = no previous pick yet

    def _remaining_hold_ms(self) -> int:
        return max(0, int((self.next_allowed_at - time.monotonic()) * 1000))

    async def load(self, pattern: list[list[int]], threading: list[int] | None = None,
                   logical_liftplan: list[list[int]] | None = None,
                   weft_colors: list[int] | None = None):
        fc = FRAME_COUNT()
        cleaned = []
        cleaned_weft: list[int] = []
        for i, row in enumerate(pattern):
            row = [int(x) for x in row][:fc]
            row += [0] * (fc - len(row))
            raised = sum(row)
            if 1 <= raised <= (fc - 1):
                cleaned.append(row)
                cleaned_weft.append(int((weft_colors or [])[i]) if weft_colors and i < len(weft_colors) else 0)
        self.pattern = cleaned
        self.weft_colors = cleaned_weft
        self._last_played_color = -1
        self.draft_threading = list(threading or [])
        self.draft_logical_liftplan = [list(r) for r in (logical_liftplan or [])]
        self.index = 0
        self.active = bool(cleaned)
        self.next_allowed_at = 0.0
        await self.stop_auto()
        # Push initial LED preview centered on the first pick so user sees the
        # upcoming motif on the matrix immediately, even before clicking
        # "Duite suivante".
        if self.active:
            # Réveil automatique des servos : on quitte le mode repos pour
            # pouvoir actionner les cadres
            await self.mcu.send({"cmd": "set_rest", "on": False})
            # Marque de fabrique au démarrage du tissage : "5426 DLUM" scrolle
            await self.mcu.send({"cmd": "led_brand"})
            # Le scroll "5426 DLUM" prend ~5s (60ms/pixel × ~85 pixels)
            await asyncio.sleep(5.0)
            await self._push_led_drawdown(0)
        else:
            await self.mcu.send({"cmd": "led_clear"})
        await self._announce()

    async def _do_color_change_pause(self, color_idx: int):
        """Announce a weft colour change on the LED matrix.
        Scrolls the colour name 3 times then shows a 3-2-1 countdown via
        the dedicated led_countdown MCU command (large digits, 1 s each)."""
        name = _PALETTE_NAMES[color_idx % len(_PALETTE_NAMES)]
        await self.hub.broadcast({"type": "color_change", "phase": "start",
                                  "color": name, "color_idx": color_idx})
        # Scroll "couleur <nom>  couleur <nom>  couleur <nom>"
        text_3x = f"couleur {name}  couleur {name}  couleur {name}"
        await self.mcu.send({"cmd": "led_text", "text": text_3x})
        await asyncio.sleep(_scroll_wait_ms(text_3x) / 1000.0)
        # Countdown 3-2-1 : large digits, 1 s each (handled entirely on MCU)
        await self.mcu.send({"cmd": "led_countdown"})
        await asyncio.sleep(3.2)   # 3 × 1 s + 200 ms margin
        await self.hub.broadcast({"type": "color_change", "phase": "done"})

    async def _step_with_tassage(self, target_index: int, force_lift: bool = False,
                                  check_color_change: bool = False):
        delay_ms = int(settings.get("tassage_delay_ms") or 0)
        await self.mcu.send({"cmd": "all_down"})
        await self.hub.broadcast({"type": "tassage", "phase": "down", "ms": delay_ms})
        # Pendant le tassage, la moitié haute de la LED s'éteint (tous
        # cadres bas) tandis que la moitié basse continue d'afficher la
        # dernière duite tissée — feedback visuel "tassage en cours".
        await self._push_led_drawdown_tassage(target_index)

        # ── Colour-change pause (if enabled and colour changed) ──────────────
        did_color_pause = False
        if check_color_change and bool(settings.get("use_color_changes")) and self.weft_colors:
            new_color = self.weft_colors[target_index] if target_index < len(self.weft_colors) else 0
            if self._last_played_color >= 0 and new_color != self._last_played_color:
                await self._do_color_change_pause(new_color)
                did_color_pause = True
        # ────────────────────────────────────────────────────────────────────

        if not did_color_pause and delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
        row = self.pattern[target_index]
        await self.mcu.send({"cmd": "lift", "step": target_index, "frames": row, "force": bool(force_lift)})
        await self.hub.broadcast({"type": "tassage", "phase": "lift"})
        hold_ms = max(0, int(settings.get("lift_hold_ms") or 0))
        self.next_allowed_at = time.monotonic() + (hold_ms / 1000.0)
        self.index = (target_index + 1) % len(self.pattern)
        # Track the colour of the pick that was just lifted for next comparison
        if self.weft_colors and target_index < len(self.weft_colors):
            self._last_played_color = self.weft_colors[target_index]
        await self._push_led_drawdown(target_index)
        await self._announce()

    async def _push_led_drawdown_tassage(self, upcoming_pick: int):
        """LED pendant le tassage : on affiche les 8 dernières duites
        DÉJÀ tissées (= avant la nouvelle qui arrive). Effet visuel : la
        duite courante (en bas) est figée, on attend le prochain tissage."""
        if str(settings.get("led_display_mode") or "pattern") == "counter":
            # En mode compteur : afficher la prochaine duite pendant le tassage
            total = len(self.pattern)
            rows = self._build_counter_bitmap(upcoming_pick + 1, total)
            if rows is not None:
                await self.mcu.send({"cmd": "led_set", "rows": rows})
            else:
                await self.mcu.send({"cmd": "led_text", "text": f"{upcoming_pick + 1}/{total}"})
            return
        if not self.draft_threading or not self.draft_logical_liftplan:
            return
        fc = FRAME_COUNT()
        rows = [0] * 8
        for r in range(8):
            pick = (upcoming_pick - 1) - (7 - r)  # r=7 → pick déjà tissée
            if pick < 0 or pick >= len(self.draft_logical_liftplan):
                continue
            liftrow = self.draft_logical_liftplan[pick]
            bits = 0
            for c in range(12):
                if c < len(self.draft_threading):
                    shaft = self.draft_threading[c]
                    if 0 <= shaft < fc and shaft < len(liftrow) and liftrow[shaft]:
                        bits |= (1 << c)
            rows[r] = bits
        await self.mcu.send({"cmd": "led_set", "rows": rows})

    async def _push_led_drawdown(self, current_pick: int):
        """Push 8 rows of drawdown to the MCU (pattern or counter mode)."""
        if str(settings.get("led_display_mode") or "pattern") == "counter":
            total = len(self.pattern)
            rows = self._build_counter_bitmap(current_pick + 1, total)
            log.info("LED counter pick=%d/%d", current_pick + 1, total)
            if rows is not None:
                await self.mcu.send({"cmd": "led_set", "rows": rows})
            else:
                await self.mcu.send({"cmd": "led_text", "text": f"{current_pick + 1}/{total}"})
            return
        if not self.draft_threading or not self.draft_logical_liftplan:
            return
        rows = [0] * 8
        fc = FRAME_COUNT()
        for r in range(8):
            pick = current_pick - (7 - r)  # r=0 → pick-7 (oldest), r=7 → current
            if pick < 0 or pick >= len(self.draft_logical_liftplan):
                continue
            liftrow = self.draft_logical_liftplan[pick]
            bits = 0
            for c in range(12):
                if c < len(self.draft_threading):
                    shaft = self.draft_threading[c]
                    if 0 <= shaft < fc and shaft < len(liftrow) and liftrow[shaft]:
                        bits |= (1 << c)
            rows[r] = bits
        log.info("LED draw pick=%d rows=[%s]", current_pick,
                 " ".join(f"{r:03X}" for r in rows))
        await self.mcu.send({"cmd": "led_set", "rows": rows})

    async def start_auto(self, interval_ms: int):
        await self.stop_auto()
        self.auto_interval_ms = max(500, int(interval_ms))
        self.auto_paused = False
        self.auto_task = asyncio.create_task(self._auto_loop())
        await self.hub.broadcast({"type": "auto_play", "active": True, "interval_ms": self.auto_interval_ms})
        await self._announce()

    async def stop_auto(self):
        if self.auto_task is not None:
            self.auto_task.cancel()
            try:
                await self.auto_task
            except (asyncio.CancelledError, Exception):
                pass
            self.auto_task = None
            self.auto_paused = False
            await self.hub.broadcast({"type": "auto_play", "active": False, "interval_ms": self.auto_interval_ms})
            await self._announce()

    async def pause_auto(self):
        if self.auto_task is None:
            return
        self.auto_paused = True
        await self.hub.broadcast({"type": "auto_play", "active": True, "paused": True, "interval_ms": self.auto_interval_ms})
        await self._announce()

    async def resume_auto(self):
        if self.auto_task is None:
            return
        self.auto_paused = False
        await self.hub.broadcast({"type": "auto_play", "active": True, "paused": False, "interval_ms": self.auto_interval_ms})
        await self._announce()

    async def _auto_loop(self):
        try:
            while self.active and self.pattern:
                if self.auto_paused:
                    await asyncio.sleep(0.1)
                    continue
                await self.next_step()
                # Keep frames up for at least lift_hold_ms, while preserving the
                # existing auto interval if it is longer.
                wait_ms = max(self.auto_interval_ms, self._remaining_hold_ms())
                await asyncio.sleep(wait_ms / 1000.0)
        except asyncio.CancelledError:
            return

    async def next_step(self):
        if not self.active or not self.pattern:
            return
        remaining_ms = self._remaining_hold_ms()
        if remaining_ms > 0 and not self.auto_paused:
            await self.hub.broadcast({"type": "hold", "remaining_ms": remaining_ms})
            return
        await self._step_with_tassage(self.index, force_lift=self.auto_paused,
                                       check_color_change=True)

    async def prev_step(self):
        if not self.active or not self.pattern:
            return
        remaining_ms = self._remaining_hold_ms()
        if remaining_ms > 0 and not self.auto_paused:
            await self.hub.broadcast({"type": "hold", "remaining_ms": remaining_ms})
            return
        target = (self.index - 2) % len(self.pattern)
        await self._step_with_tassage(target, force_lift=self.auto_paused)

    async def stop(self):
        await self.stop_auto()
        self.active = False
        self.next_allowed_at = 0.0
        await self.mcu.send({"cmd": "all_down"})
        await self.mcu.send({"cmd": "led_clear"})
        await self._announce()

    async def _announce(self):
        await self.hub.broadcast(
            {
                "type": "sequencer",
                "active": self.active,
                "index": self.index,
                "size": len(self.pattern),
                "preview": self.pattern[self.index] if self.active and self.pattern else None,
                "auto": self.auto_task is not None,
                "auto_paused": self.auto_paused,
                "auto_interval_ms": self.auto_interval_ms,
                "lift_hold_ms": max(0, int(settings.get("lift_hold_ms") or 0)),
                "hold_remaining_ms": self._remaining_hold_ms(),
            }
        )


hub = Hub()
mcu = MCUBridge(hub)
seq = Sequencer(mcu, hub)


class PrepManager:
    """Guides the weaver through threading each warp end into the correct shaft.

    The ``threading`` list maps warp-end index → shaft index (0-based).
    The physical D2 button advances to the next end when prep mode is active.
    """

    def __init__(self, mcu: MCUBridge, hub: Hub):
        self.mcu = mcu
        self.hub = hub
        self.threading: list[int] = []   # [shaft_index, ...] per warp end
        self.end_count: int = 0          # total warp ends
        self.index: int = 0              # current warp-end index (0-based)
        self.active: bool = False

    # 5×5 pixel font (cols 0-4) for large shaft number display
    _LARGE_GLYPHS: dict[str, list[int]] = {
        "0": [0b01110, 0b10001, 0b10001, 0b10001, 0b01110],
        "1": [0b00100, 0b01100, 0b00100, 0b00100, 0b01110],
        "2": [0b01110, 0b00001, 0b01110, 0b10000, 0b11111],
        "3": [0b01110, 0b00001, 0b00110, 0b00001, 0b01110],
        "4": [0b10001, 0b10001, 0b11111, 0b00001, 0b00001],
        "5": [0b11111, 0b10000, 0b11110, 0b00001, 0b11110],
        "6": [0b01110, 0b10000, 0b11110, 0b10001, 0b01110],
        "7": [0b11111, 0b00001, 0b00010, 0b00100, 0b00100],
        "8": [0b01110, 0b10001, 0b01110, 0b10001, 0b01110],
        "9": [0b01110, 0b10001, 0b01111, 0b00001, 0b01110],
    }

    def _build_shaft_bitmap(self, shaft_1indexed: int, end_1indexed: int, total: int) -> list[int]:
        """8×12 bitmap:
        - Rows 1-5 centre: large shaft number (5×5 font)
        - Row 7: warp-end progress bar
        """
        rows = [0] * 8
        # Draw large number centred on 12-column display
        text = str(shaft_1indexed)
        char_w, gap = 5, 1
        total_w = len(text) * char_w + max(0, len(text) - 1) * gap
        start_col = max(0, (12 - total_w) // 2)
        for ci, ch in enumerate(text):
            glyph = self._LARGE_GLYPHS.get(ch, [0] * 5)
            col_offset = start_col + ci * (char_w + gap)
            for gr in range(5):
                for gc in range(char_w):
                    if (glyph[gr] >> (char_w - 1 - gc)) & 1:
                        col = col_offset + gc
                        if col < 12:
                            rows[1 + gr] |= (1 << col)
        # Progress bar (row 7)
        if total > 0:
            filled = round(12 * end_1indexed / total)
            rows[7] = (1 << min(filled, 12)) - 1
        return rows

    async def load(self, threading: list[int], end_count: int):
        """Start preparation mode with the given threading plan."""
        self.threading = [int(s) for s in threading]
        self.end_count = int(end_count)
        self.index = 0
        self.active = True
        await self._push()

    async def _push(self):
        """Send current state to UI and LED."""
        if not self.active:
            return
        shaft_0 = self.threading[self.index] if self.index < len(self.threading) else 0
        shaft_1 = shaft_0 + 1   # display 1-based
        rows = self._build_shaft_bitmap(shaft_1, self.index + 1, self.end_count)
        await self.mcu.send({"cmd": "led_set", "rows": rows})
        await self.hub.broadcast({
            "type": "prep_state",
            "active": True,
            "index": self.index,          # 0-based
            "end": self.index + 1,        # 1-based for display
            "total": self.end_count,
            "shaft": shaft_1,             # 1-based
        })

    async def next(self):
        if not self.active:
            return
        if self.index < self.end_count - 1:
            self.index += 1
            await self._push()
        else:
            # All ends threaded — auto-stop
            await self.stop(finished=True)

    async def prev(self):
        if not self.active:
            return
        if self.index > 0:
            self.index -= 1
            await self._push()

    async def stop(self, finished: bool = False):
        self.active = False
        await self.mcu.send({"cmd": "led_clear"})
        await self.hub.broadcast({
            "type": "prep_state",
            "active": False,
            "finished": finished,
        })


prep = PrepManager(mcu, hub)


async def network_status_poller():
    """Poll WiFi connection state every 30s. When in DLUM-Hotspot mode, push
    a "HOTSPOT" scrolling text to the LED matrix to remind the user that
    the carte is in fallback mode (= no known WiFi available)."""
    last_mode = None
    last_station_display = None

    def format_station_text(ssid: str, ip4: str) -> str:
        ip_only = (ip4 or "").split("/", 1)[0]
        parts = [ssid, ip_only]
        return " ".join(parts * 3)

    while True:
        try:
            await asyncio.sleep(5)
            info = await wifi_mod.status()
            mode = info.get("mode", "off")
            if mode != last_mode:
                log.info("Network mode changed: %s -> %s", last_mode, mode)
                last_mode = mode
            if mode == "hotspot":
                # Indicate hotspot mode visually on the LED matrix
                await mcu.send({"cmd": "led_text", "text": "HOTSPOT 192.168.42.1"})
                last_station_display = None
            elif mode == "station":
                ssid = info.get("active_connection") or ""
                ip4 = info.get("ip4") or ""
                if ssid and ip4:
                    station_display = (ssid, ip4)
                    if station_display != last_station_display:
                        await mcu.send({"cmd": "led_text", "text": format_station_text(ssid, ip4)})
                        last_station_display = station_display
                else:
                    last_station_display = None
        except Exception as e:
            log.warning("network_status_poller: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(mcu.run())
    net_task = asyncio.create_task(network_status_poller())
    yield
    task.cancel()
    net_task.cancel()
    for t in (task, net_task):
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan, title="DLUM Server")


@app.middleware("http")
async def disable_cache_for_ui(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path or ""
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/api/state")
async def api_state():
    return {
        "mcu": mcu.last_state,
        "sequencer": {
            "active": seq.active,
            "index": seq.index,
            "size": len(seq.pattern),
        },
    }


# --- WiFi management ---


@app.get("/api/wifi/status")
async def api_wifi_status():
    return await wifi_mod.status()


@app.get("/api/wifi/scan")
async def api_wifi_scan():
    return await wifi_mod.scan()


@app.post("/api/wifi/connect")
async def api_wifi_connect(payload: dict):
    ssid = payload.get("ssid", "")
    password = payload.get("password")
    return await wifi_mod.connect(ssid, password)


@app.post("/api/wifi/forget")
async def api_wifi_forget(payload: dict):
    name = payload.get("name", "")
    return await wifi_mod.forget(name)


@app.post("/api/wifi/hotspot")
async def api_wifi_hotspot(payload: dict):
    return await wifi_mod.hotspot(bool(payload.get("on")))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await hub.add(ws)
    try:
        await ws.send_text(json.dumps({
            "type": "hello", "mcu": mcu.last_state,
            "mapping": motor_map.info(), "settings": settings.info(),
            "frame_count": FRAME_COUNT(), "frame_count_max": FRAME_COUNT_MAX,
        }))
        await seq._announce()
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await dispatch(msg, ws)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(ws)


async def dispatch(msg: dict, ws: WebSocket):
    t = msg.get("type")
    if t == "lift":
        fc = FRAME_COUNT()
        frames = msg.get("frames", [])
        if len(frames) != fc or not (1 <= sum(int(x) for x in frames) <= (fc - 1)):
            await ws.send_text(
                json.dumps({"type": "error", "code": "invalid_frames"})
            )
            return
        phys = motor_map.to_physical_frames([int(x) for x in frames])
        await mcu.send({"cmd": "lift", "step": int(msg.get("step", 0)), "frames": phys})
    elif t == "manual":
        # Logical cadre index from UI -> map to physical position
        logical_idx = int(msg["frame"])
        if not (0 <= logical_idx < FRAME_COUNT()):
            return
        phys_idx = motor_map.logical_to_physical[logical_idx]
        await mcu.send({"cmd": "manual", "frame": phys_idx, "state": int(msg["state"])})
    elif t == "all_down":
        await mcu.send({"cmd": "all_down"})
    elif t == "all_up":
        await mcu.send({"cmd": "all_up"})
    elif t == "pin_test":
        # Direct physical pin test, no mapping translation
        await mcu.send({"cmd": "pin_test", "pin": int(msg["pin"])})
    elif t == "get_mapping":
        await ws.send_text(json.dumps({"type": "mapping", "data": motor_map.info()}))
    elif t == "set_mapping":
        ok = motor_map.set(msg.get("logical_to_physical", []))
        await ws.send_text(json.dumps({"type": "mapping", "ok": ok, "data": motor_map.info()}))
    elif t == "reset_mapping":
        motor_map.reset()
        await ws.send_text(json.dumps({"type": "mapping", "ok": True, "data": motor_map.info()}))
    elif t == "get_settings":
        await ws.send_text(json.dumps({"type": "settings", "data": settings.info()}))
    elif t == "set_setting":
        key = msg.get("key")
        value = msg.get("value")
        if key in ("tassage_delay_ms", "lift_hold_ms"):
            value = max(0, int(value or 0))
        elif key == "frame_count":
            value = max(2, min(FRAME_COUNT_MAX, int(value)))
        elif key == "use_color_changes":
            value = bool(value)
        ok = settings.set(key, value)
        # Special handling : if frame_count changed, propagate to motor_map and MCU.
        if ok and key == "frame_count":
            new_fc = max(2, min(FRAME_COUNT_MAX, int(value)))
            motor_map.set_frame_count(new_fc)
            await mcu.send({"cmd": "set_frame_count", "count": new_fc})
            await ws.send_text(json.dumps({"type": "mapping", "ok": True, "data": motor_map.info()}))
        if ok and key == "lift_hold_ms":
            await mcu.send({"cmd": "set_hold_ms", "value": int(value)})
        await ws.send_text(json.dumps({"type": "settings", "ok": ok, "data": settings.info()}))
    elif t == "set_motor_angle":
        # Update one motor's down or up angle. Persists locally + pushes to MCU.
        # Logical motor index is translated through the mapping.
        motor_logical = int(msg["motor"])
        if not (0 <= motor_logical < FRAME_COUNT()):
            return
        motor_phys = motor_map.logical_to_physical[motor_logical]
        kind = msg.get("kind", "")
        value = int(msg["value"])
        if kind not in ("down", "up"):
            return
        key = f"{kind}_angles"
        arr = list(settings.get(key))
        # Stored arrays are indexed by PHYSICAL pin (matches firmware).
        arr[motor_phys] = value
        settings.set(key, arr)
        await mcu.send({"cmd": "set_angle", "motor": motor_phys, kind: value})
        await ws.send_text(json.dumps({"type": "settings", "ok": True, "data": settings.info()}))
    elif t == "live_servo":
        # Direct test position. Physical motor index used as-is (this is for calibration).
        await mcu.send({"cmd": "live_servo", "motor": int(msg["motor"]), "angle": int(msg["angle"])})
    elif t == "led_test":
        await mcu.send({"cmd": "led_test"})
    elif t == "led_debug":
        await mcu.send({"cmd": "led_debug"})
    elif t == "led_brand":
        await mcu.send({"cmd": "led_brand"})
    elif t == "set_rest":
        await mcu.send({"cmd": "set_rest", "on": bool(msg.get("on"))})
    elif t == "library_list":
        await ws.send_text(json.dumps({"type": "library_list", "data": library.list()}))
    elif t == "library_get":
        d = library.get(msg.get("id", ""))
        await ws.send_text(json.dumps({"type": "library_entry", "data": d}))
    elif t == "library_save":
        rec = library.save(msg.get("payload", {}))
        await ws.send_text(json.dumps({"type": "library_saved", "data": rec}))
    elif t == "library_delete":
        ok = library.delete(msg.get("id", ""))
        await ws.send_text(json.dumps({"type": "library_deleted", "ok": ok, "id": msg.get("id")}))
    elif t == "ping_mcu":
        await mcu.send({"cmd": "ping"})
    elif t == "load_pattern":
        # Translate each row to physical order before storing in sequencer
        raw_pattern = msg.get("pattern", [])
        threading = msg.get("threading") or []
        weft_colors = [int(x) for x in (msg.get("weftColors") or [])]
        phys_pattern = [motor_map.to_physical_frames([int(x) for x in row]) for row in raw_pattern]
        # Store the LOGICAL liftplan as well so the LED drawdown rendering
        # uses the user-visible cadre numbering (1-4) which matches the threading.
        await seq.load(
            phys_pattern,
            threading=[int(x) for x in threading],
            logical_liftplan=[[int(x) for x in row] for row in raw_pattern],
            weft_colors=weft_colors,
        )
    elif t == "next_step":
        await seq.next_step()
    elif t == "prev_step":
        await seq.prev_step()
    elif t == "stop_sequence":
        await seq.stop()
    elif t == "auto_play_start":
        await seq.start_auto(int(msg.get("interval_ms", 5000)))
    elif t == "auto_play_pause":
        await seq.pause_auto()
    elif t == "auto_play_resume":
        await seq.resume_auto()
    elif t == "auto_play_stop":
        await seq.stop_auto()
    elif t == "prep_load":
        threading = [int(x) for x in msg.get("threading", [])]
        end_count = int(msg.get("end_count", len(threading)))
        await prep.load(threading, end_count)
    elif t == "prep_next":
        await prep.next()
    elif t == "prep_prev":
        await prep.prev()
    elif t == "prep_stop":
        await prep.stop()
    else:
        await ws.send_text(json.dumps({"type": "error", "code": "unknown_type", "t": t}))


if __name__ == "__main__":
    import uvicorn

    log.info("Starting on %s:%d (serial=%s)", HTTP_HOST, HTTP_PORT, SERIAL_PORT_OVERRIDE or "auto-detect")
    uvicorn.run(app, host=HTTP_HOST, port=HTTP_PORT, log_level="info")
