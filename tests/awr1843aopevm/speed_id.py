"""Track objects in data_clean.json, resolve their speed past the Doppler wrap, and identify them.

Usage: python speed_id.py --sensor-speed 0 [--wrap 14.8] [--cluster-radius 0.8] [--gate 1.5] [--env .env]
"""
import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

DATA_FILE = Path(__file__).with_name("data_clean.json")


@dataclass
class Point:
    x: float  # lateral
    y: float  # boresight / frontal distance
    doppler: float  # radial speed, negative = approaching
    # z ignored (distance hypothesis)


@dataclass
class Obj:
    """One object in one frame: the centroid of a cluster of points."""
    x: float
    y: float
    doppler: float
    track: int = -1

    @property
    def distance(self):
        return math.hypot(self.x, self.y)


@dataclass
class Frame:
    time_s: float
    points: list[Point]
    objects: list[Obj] = field(default_factory=list)


def load_frames(path=DATA_FILE):
    with open(path) as f:
        frames = json.load(f)["frames"]
    return [Frame(fr["time_s"], [Point(p["x"], p["y"], p["doppler"]) for p in fr["points"]]) for fr in frames]


def load_groups(path):
    """Parse `name: [low, high]` lines. File order matters: the first matching group wins."""
    groups = {}
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition(":")
        try:
            limits = json.loads(value)
        except json.JSONDecodeError:
            limits = None
        if not sep or not isinstance(limits, list) or len(limits) != 2 or not limits[0] <= limits[1]:
            raise SystemExit(f"{path}:{n}: expected `name: [low, high]` with low <= high, got {line!r}")
        groups[name.strip()] = (float(limits[0]), float(limits[1]))
    return groups


def cluster(points, radius):
    """Greedy single-link clustering: a point joins the first cluster that has a point within radius."""
    clusters = []
    for p in points:
        for c in clusters:
            if any(math.hypot(p.x - q.x, p.y - q.y) <= radius for q in c):
                c.append(p)
                break
        else:
            clusters.append([p])
    # shortcut: averaging doppler assumes points of one object share a Doppler bin; use the median if real data scatters
    return [Obj(*(sum(getattr(p, a) for p in c) / len(c) for a in ("x", "y", "doppler"))) for c in clusters]


def movement(prev, cur, dt):
    """Coarse radial speed from the change in range. Only used to pick the Doppler wrap chunk."""
    return (cur.distance - prev.distance) / dt


def doppler(coarse, measured, wrap):
    """Unwrap the measured Doppler into the chunk that the coarse speed points at."""
    return measured + round((coarse - measured) / wrap) * wrap


def actual_speed(relative, obj, sensor_speed):
    """Remove the sensor's own motion (along +y) from the relative radial speed."""
    return relative + sensor_speed * obj.y / obj.distance


def identify(speed, groups):
    return next((name for name, (lo, hi) in groups.items() if lo <= speed <= hi), "unidentified")


def track(frames, radius, gate):
    """Cluster each frame and give each object the track id of the nearest object in the previous frame."""
    next_id = 0
    prev = []
    for fr in frames:
        fr.objects = cluster(fr.points, radius)
        free = list(prev)
        for o in fr.objects:
            best = min(free, key=lambda p: math.hypot(o.x - p.x, o.y - p.y), default=None)
            if best and math.hypot(o.x - best.x, o.y - best.y) <= gate:
                o.track = best.track
                free.remove(best)
            else:
                o.track, next_id = next_id, next_id + 1
        prev = fr.objects


def run(args):
    groups = load_groups(args.env)
    frames = load_frames()
    track(frames, args.cluster_radius, args.gate)
    last = {}  # track id -> (time, Obj)
    for fr in frames:
        for o in fr.objects:
            if o.track in last:
                t0, p = last[o.track]
                relative = doppler(movement(p, o, fr.time_s - t0), o.doppler, args.wrap)
                speed = actual_speed(relative, o, args.sensor_speed)
                print(f"t={fr.time_s:5.1f}s track={o.track:<3} x={o.x:6.2f} y={o.y:6.2f} dist={o.distance:5.2f}m "
                      f"rel={relative:6.2f} actual={speed:6.2f} m/s -> {identify(abs(speed), groups)}")
            last[o.track] = (fr.time_s, o)


def selftest():
    assert doppler(-4.0, -3.97, 14.8) == -3.97
    assert math.isclose(doppler(12.0, -2.8, 14.8), 12.0)  # one chunk up
    assert math.isclose(doppler(-20.0, 9.0, 14.8), -20.6)  # two chunks down
    assert actual_speed(-5.0, Obj(0, 10, -5.0), 5.0) == 0  # static object dead ahead, sensor at 5 m/s
    assert identify(1.0, {"a": (0, 0.5), "b": (0.5, 2)}) == "b"
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sensor-speed", type=float, help="sensor's own speed along +y, m/s")
    ap.add_argument("--wrap", type=float, default=14.8, help="Doppler wrap span, m/s")
    ap.add_argument("--cluster-radius", type=float, default=0.8, help="max gap between points of one object, m")
    ap.add_argument("--gate", type=float, default=1.5, help="max centroid jump between frames for one track, m")
    ap.add_argument("--env", default=Path(__file__).with_name(".env"), help="identification groups file")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if not args.selftest and args.sensor_speed is None:
        ap.error("--sensor-speed is required")
    selftest() if args.selftest else run(args)
