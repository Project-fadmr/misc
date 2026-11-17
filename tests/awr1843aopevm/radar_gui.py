#!/usr/bin/env python3
"""Sector PPI radar view of the live points decoded by radar_live.py.

Usage:
    python radar_gui.py                      # default port
    python radar_gui.py --port /dev/ttyUSB1  # other port
"""
import argparse
import math
import os
import queue
import threading
import time
import tkinter as tk

from radar_live import DEFAULT_PORT, FrameClock, FrameParser, open_port, read_port

MAX_RANGE_M = 10.5               # cfarFovCfg -1 0 0.25 10.5 in profile_test.cfg
RING_STEP_M = 2.0
FADE_S = 2.0                     # afterglow lifetime of a point
SWEEP_PERIOD_S = 2.0             # one back-and-forth swing of the sweep line
STATIC_V = 0.3                   # |doppler| below this (m/s) counts as static
TICK_MS = 33                     # about 30 fps

W, H = 720, 400
CX, CY = W // 2, H - 40          # sensor at bottom centre
R = 340                          # sector radius in pixels

BG = (0x05, 0x0a, 0x05)
STATIC_COL = (0x33, 0xff, 0x66)
APPROACH_COL = (0xff, 0x99, 0x00)
RECEDE_COL = (0x00, 0xcc, 0xff)
GRID_COL = "#1d4d24"
SWEEP_COL = "#2a7a3a"


def to_canvas(x, y, cx, cy, radius):
    """Map sensor (x, y) metres to canvas pixels, or None outside the sector."""
    dist = math.hypot(x, y)
    if y < 0 or dist > MAX_RANGE_M:
        return None
    return polar_to_canvas(math.atan2(x, y), dist / MAX_RANGE_M * radius, cx, cy)


def polar_to_canvas(bearing, px_dist, cx, cy):
    """Bearing in radians from boresight (0 = straight up), distance in pixels."""
    return cx + px_dist * math.sin(bearing), cy - px_dist * math.cos(bearing)


def _mix(col, fade):
    fade = max(0.0, min(1.0, fade))
    return "#%02x%02x%02x" % tuple(round(b + (c - b) * fade) for c, b in zip(col, BG))


def point_colour(doppler, fade):
    """Colour for a point; fade 1 = full colour, fade 0 = background."""
    if abs(doppler) < STATIC_V:
        col = STATIC_COL
    elif doppler < 0:
        # Negative doppler = approaching: the car closes range in the synthetic data
        # (data_clean.json). Unverified on hardware.
        col = APPROACH_COL
    else:
        col = RECEDE_COL
    return _mix(col, fade)


def prune(points, now):
    """Keep only afterglow points younger than FADE_S. Points are (arrival, x, y, doppler)."""
    return [p for p in points if now - p[0] < FADE_S]


def sweep_bearing(now):
    """Sweep angle in radians, swinging from -90 to +90 degrees and back."""
    u = (now % SWEEP_PERIOD_S) / SWEEP_PERIOD_S
    frac = 1 - abs(2 * u - 1)
    return math.radians(-90 + 180 * frac)


class RadarApp:
    def __init__(self, root, port):
        self.root = root
        self.queue = queue.Queue()
        self.stop = threading.Event()
        self.points = []
        self.frame_no, self.t_s, self.n_pts = None, 0.0, 0
        self.link = "opening port"

        root.title("AWR1843 radar")
        root.configure(bg=_hex(BG))
        self.canvas = tk.Canvas(root, width=W, height=H, bg=_hex(BG), highlightthickness=0)
        self.canvas.pack()
        self._draw_grid()
        self.status_id = self.canvas.create_text(10, H - 10, anchor="sw", fill="#66cc77",
                                                 font=("Courier", 11))
        root.protocol("WM_DELETE_WINDOW", self._close)

        self.reader = threading.Thread(target=self._read, args=(port,), daemon=True)
        self.reader.start()
        root.after(TICK_MS, self._tick)

    def _draw_grid(self):
        c = self.canvas
        for k in range(1, int(MAX_RANGE_M // RING_STEP_M) + 1):
            rad = k * RING_STEP_M / MAX_RANGE_M * R
            c.create_arc(CX - rad, CY - rad, CX + rad, CY + rad, start=0, extent=180,
                         style="arc", outline=GRID_COL)
            c.create_text(CX + 4, CY - rad, anchor="sw", fill=GRID_COL, text=f"{k * RING_STEP_M:g} m")
        for deg in range(-90, 91, 30):
            ex, ey = polar_to_canvas(math.radians(deg), R, CX, CY)
            c.create_line(CX, CY, ex, ey, fill=GRID_COL)
            lx, ly = polar_to_canvas(math.radians(deg), R + 14, CX, CY)
            # the +-90 labels sit on the canvas edge, so anchor them inward to stay visible
            anchor = {-90: "w", 90: "e"}.get(deg, "center")
            c.create_text(lx, ly, anchor=anchor, fill=GRID_COL, text=f"{deg:+d}°" if deg else "0°")
        c.create_arc(CX - R, CY - R, CX + R, CY + R, start=0, extent=180, style="arc",
                     outline=GRID_COL)
        legend = [("static", STATIC_COL), ("approaching", APPROACH_COL), ("receding", RECEDE_COL)]
        for i, (label, col) in enumerate(legend):
            c.create_text(10, 14 + 18 * i, anchor="nw", fill=_hex(col), text=f"■ {label}")

    def _read(self, port):
        """Background thread: owns the port fd and reports errors through the queue."""
        fd = None
        try:
            fd = open_port(port)
            self.queue.put(("link", "port open"))
            parser, clock = FrameParser(), FrameClock()
            for chunk in read_port(fd):
                if self.stop.is_set():
                    break
                frames = parser.stall() if chunk is None else parser.feed(chunk)
                for frame in frames:
                    self.queue.put(("frame", (frame, clock.advance(frame.number, frame.cycles))))
            self.queue.put(("link", "port closed"))
        except Exception as exc:  # any reader failure goes to the status line, not a traceback
            self.queue.put(("link", f"error: {exc}"))
        finally:
            if fd is not None:
                os.close(fd)

    def _tick(self):
        now = time.monotonic()
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "frame":
                frame, t_s = payload
                self.frame_no, self.t_s, self.n_pts = frame.number, t_s, len(frame.points)
                self.points += [(now, p.x, p.y, p.doppler) for p in frame.points]
            else:
                self.link = payload
        self.points = prune(self.points, now)
        self._draw(now)
        self.root.after(TICK_MS, self._tick)

    def _draw(self, now):
        c = self.canvas
        c.delete("dyn")
        for arrival, x, y, dop in self.points:
            xy = to_canvas(x, y, CX, CY, R)
            if xy is None:
                continue
            px, py = xy
            col = point_colour(dop, 1 - (now - arrival) / FADE_S)
            c.create_oval(px - 2, py - 2, px + 2, py + 2, fill=col, outline=col, tags="dyn")
        ex, ey = polar_to_canvas(sweep_bearing(now), R, CX, CY)
        c.create_line(CX, CY, ex, ey, fill=SWEEP_COL, width=2, tags="dyn")
        frame = "-" if self.frame_no is None else self.frame_no
        c.itemconfigure(self.status_id, text=f"frame {frame}  t={self.t_s:.2f}s  "
                                             f"{self.n_pts} pts  |  {self.link}")

    def _close(self):
        self.stop.set()
        self.reader.join(2)              # the reader closes the fd within one idle timeout
        self.root.destroy()


def _hex(col):
    return "#%02x%02x%02x" % col


def main():
    ap = argparse.ArgumentParser(description="Sector PPI view of AWR1843AOPEVM points.")
    ap.add_argument("--port", default=DEFAULT_PORT, help="data port (default: CP2105 port0 by-id)")
    args = ap.parse_args()
    root = tk.Tk()
    RadarApp(root, args.port)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
