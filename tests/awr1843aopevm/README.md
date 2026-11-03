# AWR1843AOPEVM synthetic test data

Stand-in data for building and testing the host side (serial reader, frame parser, tracking) before
the real sensors arrive. Interface details are in `docs/awr1843aopevm-uart-spec.md`.

> **Warning:** everything here is **synthetic**. It follows the documented mmWave SDK 3.5 output format,
> but no board produced it. Real data **will differ slightly or more**: noise levels, point counts, SNR
> values, TLV order, timing, the platform field, axis orientation and Doppler sign are all estimates.
> Treat these files as a format test, not as a model of the sensor's performance.

## Files

| File                   | What it is                                                                                                                                                           |
|------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `profile_test.cfg`   | CLI config these captures assume (3 TX / 4 RX, 256 range bins, 32 Doppler bins, 10 fps, range/noise profiles off).                                                   |
| `cli_session_ok.txt` | Expected exchange on the CLI port when sending `profile_test.cfg`, plus known failure replies.                                                                     |
| `data_clean.bin`     | 100 frames (10 s) of the raw data-port byte stream, frame numbers 1–100, no faults. 19,616 bytes.                                                                    |
| `data_clean.json`    | Ground truth for `data_clean.bin`: every header field, point, side-info value, stats and temperature for each frame, plus the byte offset where each frame starts. |
| `data_faults.bin`    | 7,823 bytes of stream with deliberate faults, for testing resynchronisation.                                                                                         |
| `data_faults.json`   | Ground truth for `data_faults.bin`. Each frame has `expectValid`. Invalid frames have a `fault` description.                                                   |

## Scene in the captures

The sensor is stationary. Positions use the TI demo convention (x = lateral, y = boresight/range,
z = height, metres).

- **car**: starts at y ≈ 10.5 m, x ≈ 0.9 m and approaches at 4 m/s, giving about 3 points per frame. It drops out once it leaves the configured range.
- **pole**: static at (-1.6, 6.0, 0), 1 point per frame, Doppler 0 (clutter removal is off).
- **pedestrian**: crosses from x = -2.5 to +2.5 m at y = 4 m and 1.2 m/s, about 2 points per frame.
- **clutter**: about 15 % of frames contain one low-SNR false alarm.

Point counts in `data_clean`: pole 100, pedestrian 84, car 72, clutter 23, with 1–7 points per frame.
Ranges are quantised to the 0.0422 m range bin and velocities to the 0.441 m/s Doppler bin, the way the
demo does it. The `truthLabel` per point exists **only in the JSON**. The real sensor gives no labels.

Each frame contains these TLVs, in this order: 1 (points), 7 (side info), 6 (stats), 9 (temperature).
The range and noise profiles (TLVs 2 and 3) are switched off in `guiMonitor`, because this project does not use them.
When a frame has no detections, TLVs 1 and 7 are left out and `numTLVs` drops to 2. A parser must not rely on TLV order or count.

Fixed header values: version `0x03050004` (SDK 3.5.0.4), platform `0x000A1843` (**unverified guess**,
see the spec), subFrameNumber 0. `timeCpuCycles` advances 20,000,000 per frame, assuming a 200 MHz R4F.

## Faults in `data_faults.bin`

| Byte offset | Fault                                                                                | Correct parser behaviour                                                 |
|-------------|--------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| 0–36        | Random garbage: the port was opened mid-stream.                                      | Skip forward to the first magic word.                                    |
| 1349        | Frame 506 truncated after 150 bytes. The next frame's magic word follows right away. | Drop 506 and resync on frame 507.                                        |
| 2619        | A stray magic word followed by 12 junk bytes (20 bytes in all), before frame 511.    | Reject it, because the header fails sanity checks, and find frame 511.   |
| 3951        | Frame 516 has `totalPacketLen` = 0x7FFFFFFF.                                       | Reject it (not a multiple of 32, larger than any sane frame) and resync. |
| 5231        | Frame 521: the first TLV length is 0xFFFF, which runs past the packet end.           | Drop the frame and resync.                                               |
| 6511        | Board reset: frame numbers restart at 1 (frames 1–5).                                | Accept them and treat the drop in frame number as a sensor restart.      |

A correct parser recovers **27** frames (501–505, 507–515, 517–520, 522–525, 1–5) and nothing else.
These counts and offsets were checked with an independent decoder against the JSON ground truth.
