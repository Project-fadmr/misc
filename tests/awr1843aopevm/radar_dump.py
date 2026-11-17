#!/usr/bin/env python3
"""Record the raw, unparsed byte stream from the AWR1843AOPEVM data port to a .bin file.

The file is byte-identical to what the port delivered (same format as data_clean.bin),
so it can be shared and replayed with:
    python radar_live.py --file OUT.bin

Usage:
    python radar_dump.py OUT.bin                 # Ctrl+C to stop
    python radar_dump.py OUT.bin --port /dev/ttyUSB1

OUT.bin must not exist; it is never overwritten. Every chunk is flushed as it arrives,
so an unplug or crash keeps everything already received.
Python 3 standard library only. Port handling comes from radar_live.py.
"""
import argparse
import os
import subprocess
import sys

from radar_live import DEFAULT_PORT, open_port, read_port


def main(argv=None):
    ap = argparse.ArgumentParser(description="Record the raw data-port byte stream.")
    ap.add_argument("out", metavar="OUT.bin")
    ap.add_argument("--port", default=DEFAULT_PORT, help="data port (default: CP2105 port0 by-id)")
    args = ap.parse_args(argv)

    out = fd = None
    total = 0
    rc = 0
    try:
        fd = open_port(args.port)            # open the port first, so a failure leaves no file
        out = open(args.out, "xb")           # fails if the file exists; never overwrites
        for chunk in read_port(fd):
            if chunk is None:                # idle period, nothing to write
                continue
            out.write(chunk)
            out.flush()
            total += len(chunk)
            print(f"\r{total} bytes", end="", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        pass
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"\nradar_dump: {exc}", file=sys.stderr)
        rc = 1
    finally:
        if fd is not None:
            os.close(fd)
        if out is not None:
            out.close()
    if out is not None:                      # OUT was created by this run
        print(f"\nwrote {total} bytes to {args.out}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
