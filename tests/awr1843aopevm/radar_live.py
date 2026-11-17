#!/usr/bin/env python3
"""Live decoder for the AWR1843AOPEVM data port (mmWave SDK 3.x out-of-box demo).

Reads the binary TLV stream from the CP2105 Standard (data) port at 921600 8N1,
or a recorded .bin file, and prints each valid frame with its detected points.
Frame layout follows docs/awr1843aopevm-uart-spec.md, section 6.
Python 3 standard library only.

Usage:
    python radar_live.py                      # live port, Ctrl+C to stop
    python radar_live.py --port /dev/ttyUSB1  # other port
    python radar_live.py --file data_clean.bin
    python radar_live.py --quiet-empty        # hide frames with 0 points

On a terminal the live view redraws the latest frame in place; piped output and
--file keep printing every frame.
"""
import argparse
import collections
import math
import os
import select
import struct
import subprocess
import sys

DEFAULT_PORT = ("/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_"
                "019C69A2-if01-port0")
BAUD = 921600

MAGIC = bytes([0x02, 0x01, 0x04, 0x03, 0x06, 0x05, 0x08, 0x07])
HEADER_LEN = 40                  # magic (8) + eight little-endian uint32 fields
HEADER_FMT = "<8s8I"             # magic, version, totalPacketLen, platform, frameNumber,
                                 # timeCpuCycles, numDetectedObj, numTLVs, subFrameNumber
PACKET_ALIGN = 32                # totalPacketLen is a multiple of 32 (spec 6.1)
MAX_PACKET_LEN = 64 * 1024       # sanity bound; a real frame is a few KB
MAX_TLVS = 32                    # sanity bound; the standard demo sends about 4

TLV_POINTS = 1                   # numDetectedObj x (x, y, z, doppler) float32
TLV_SIDE_INFO = 7                # numDetectedObj x (snr, noise) uint16, 0.1 dB units

# timeCpuCycles is a free-running CPU cycle counter. The 200 MHz clock is an
# ASSUMPTION (the R4F clock used by the synthetic data); not confirmed on hardware.
CPU_HZ = 200e6
CYCLE_MASK = 0xFFFFFFFF          # the counter wraps at 2^32

IDLE_TIMEOUT_S = 1.0             # a partial frame with no new bytes for this long is dropped
READ_CHUNK = 65536
FILE_CHUNK = 4096                # small chunks so frames straddle reads, as on the live port

Point = collections.namedtuple("Point", "x y z doppler snr_db")
Frame = collections.namedtuple("Frame", "number cycles points")


def _decode_frame(pkt, num_tlvs, num_objs, frame_number, cycles):
    """Walk the TLVs of one complete packet. Returns a Frame, or None if it is inconsistent."""
    total = len(pkt)
    off = HEADER_LEN
    points = None
    side = None
    for _ in range(num_tlvs):
        if off + 8 > total:
            return None
        tlv_type, tlv_len = struct.unpack_from("<II", pkt, off)
        body = off + 8
        if body + tlv_len > total:
            return None          # TLV runs past the end of the packet
        if tlv_type == TLV_POINTS:
            if tlv_len % 16:
                return None
            points = [struct.unpack_from("<4f", pkt, body + 16 * i) for i in range(tlv_len // 16)]
        elif tlv_type == TLV_SIDE_INFO:
            if tlv_len % 4:
                return None
            side = [struct.unpack_from("<HH", pkt, body + 4 * i) for i in range(tlv_len // 4)]
        # other TLV types (stats, temperature, profiles, heatmaps) are skipped by length
        off = body + tlv_len

    count = len(points) if points else 0
    if count != num_objs:
        return None              # spec 6.2: numDetectedObj is the number of points in TLV 1
    if side is None or len(side) != count:
        side = None              # side info is optional; ignore it if it does not line up
    out = []
    for i, (x, y, z, dop) in enumerate(points or []):
        snr = side[i][0] * 0.1 if side else None
        out.append(Point(x, y, z, dop, snr))
    return Frame(frame_number, cycles, out)


class FrameParser:
    """Incremental byte-stream parser with resync on bad or truncated frames."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        return self._drain()

    def stall(self):
        """Called when the stream went quiet. Any partial frame is abandoned:
        drop one byte and resync, so a bogus length cannot hold the parser forever."""
        if self.buf:
            del self.buf[:1]
        return self._drain()

    def _drain(self):
        frames = []
        while True:
            start = self.buf.find(MAGIC)
            if start < 0:
                # keep a possible partial magic at the end of the buffer
                del self.buf[:max(0, len(self.buf) - (len(MAGIC) - 1))]
                return frames
            if start:
                del self.buf[:start]
            if len(self.buf) < HEADER_LEN:
                return frames

            _, version, total, platform, number, cycles, num_objs, num_tlvs, _sub = \
                struct.unpack_from(HEADER_FMT, self.buf, 0)
            # The platform and version fields are logged rather than checked (spec 6.2).
            if (total < HEADER_LEN or total > MAX_PACKET_LEN or total % PACKET_ALIGN
                    or num_tlvs > MAX_TLVS):
                del self.buf[:1]          # false magic: move on one byte
                continue

            # A second magic inside this frame's span means this frame was cut short.
            nxt = self.buf.find(MAGIC, 1, min(len(self.buf), total + len(MAGIC) - 1))
            if 0 < nxt < total:
                del self.buf[:nxt]
                continue

            if len(self.buf) < total:
                return frames            # wait for the rest of the packet

            frame = _decode_frame(bytes(self.buf[:total]), num_tlvs, num_objs, number, cycles)
            if frame is None:
                del self.buf[:1]         # bad TLV layout: move on one byte
                continue
            del self.buf[:total]
            frames.append(frame)


class FrameClock:
    """Seconds since the first frame, accumulated from timeCpuCycles deltas.
    Uses the ASSUMED CPU_HZ clock. Deltas are taken modulo 2^32 so the counter wrap is
    handled. A frame-number decrease means the board restarted, so no time is added."""

    def __init__(self):
        self.t = 0.0
        self.last_cycles = None
        self.last_number = None

    def advance(self, number, cycles):
        if self.last_cycles is not None and number >= self.last_number:
            self.t += ((cycles - self.last_cycles) & CYCLE_MASK) / CPU_HZ
        self.last_cycles = cycles
        self.last_number = number
        return self.t


def format_frame(frame, t_s):
    lines = [f"frame {frame.number}  t={t_s:+.3f}s  {len(frame.points)} pts"]
    for p in frame.points:
        r = math.sqrt(p.x * p.x + p.y * p.y + p.z * p.z)
        line = (f"   x={p.x:+.2f}  y={p.y:+.2f}  z={p.z:+.2f} m   "
                f"r={r:.2f} m   v={p.doppler:+.2f} m/s")
        if p.snr_db is not None:
            line += f"   snr={p.snr_db:.1f} dB"
        lines.append(line)
    return "\n".join(lines) + "\n"


def read_file(path):
    with open(path, "rb") as fh:
        while True:
            data = fh.read(FILE_CHUNK)
            if not data:
                return
            yield data


def open_port(path):
    subprocess.run(["stty", "-F", path, str(BAUD), "raw", "-echo",
                    "cs8", "-cstopb", "-parenb", "-crtscts"], check=True)
    return os.open(path, os.O_RDONLY | os.O_NOCTTY)


def read_port(fd):
    """Yields bytes as they arrive, or None after an idle period."""
    while True:
        ready, _, _ = select.select([fd], [], [], IDLE_TIMEOUT_S)
        if ready:
            data = os.read(fd, READ_CHUNK)
            if not data:
                return
            yield data
        else:
            yield None


CLEAR = "\x1b[H\x1b[J"            # cursor home + clear to end of screen


def run(chunks, quiet_empty, in_place=False):
    parser = FrameParser()
    clock = FrameClock()
    for chunk in chunks:
        frames = parser.stall() if chunk is None else parser.feed(chunk)
        for frame in frames:
            if quiet_empty and not frame.points:
                continue
            t_s = clock.advance(frame.number, frame.cycles)
            text = format_frame(frame, t_s)
            sys.stdout.write(CLEAR + text if in_place else text)
            sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="Decode AWR1843AOPEVM data-port frames.")
    ap.add_argument("--port", default=DEFAULT_PORT, help="data port (default: CP2105 port0 by-id)")
    ap.add_argument("--file", metavar="X.bin", help="decode a recorded stream instead of the port")
    ap.add_argument("--quiet-empty", action="store_true", help="hide frames with no points")
    args = ap.parse_args()

    fd = None
    try:
        if args.file:
            chunks = read_file(args.file)
        else:
            fd = open_port(args.port)
            chunks = read_port(fd)
        # redraw in place only for a live terminal; files and pipes keep the full log
        run(chunks, args.quiet_empty, in_place=fd is not None and sys.stdout.isatty())
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        # stdout closed (e.g. piped into head): avoid the error at interpreter exit
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"radar_live: {exc}", file=sys.stderr)
        return 1
    finally:
        if fd is not None:
            os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
