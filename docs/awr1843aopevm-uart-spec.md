# AWR1843AOPEVM: UART-over-USB interface spec

Status: written 2026-11-03 from TI documentation and web sources, **before any hardware was available**.
Everything marked ✅ was checked against a source listed in [Sources](#13-sources). Items marked ⚠️ could
not be confirmed and must be checked on the first real board.

> **Test data notice:** the sample data in `tests/awr1843aopevm/` is **synthetic**. It follows the format
> in this document, but no sensor produced it, so it **may be slightly inaccurate compared with real
> sensor output**. Point counts, SNR/noise values, range-profile levels, timing/stats values, TLV order,
> the platform field, axis orientation and Doppler sign are estimates. Use it to build and test parsing
> and pipeline logic. Do not use it to tune detection thresholds or judge sensor performance. Replace it
> with real captures as soon as boards arrive.

---

## 1. Scope

This spec covers how a host (PC or the project's Raspberry Pi) talks to the **TI AWR1843AOPEVM**
(AWR1843 radar with antenna-on-package) through the board's single micro-USB connector. The board must
run TI's **out-of-box mmWave demo** firmware from mmWave SDK 3.5.x. Custom firmware, LVDS raw-ADC
capture (DCA1000) and CAN are out of scope.

## 2. Board summary ✅

| Item               | Value                                                                                                                                 |
|--------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| Radar              | AWR1843AOP, 3 TX / 4 RX antennas on package (12 virtual antennas in TDM-MIMO)                                                         |
| Band               | 77–81 GHz (4 GHz sweep bandwidth)                                                                                                     |
| Antenna gain       | ~5 dBi                                                                                                                                |
| USB-to-UART bridge | Silicon Labs **CP2105** (dual UART). The schematic labels it "SICP2105".                                                              |
| USB connector      | J1, micro-USB. It carries both UARTs and can power the board once the breakaway section is removed.                                   |
| Barrel power       | J5, 5 V, center positive, 2.1 mm, \> 2.5 A supply (not in the kit). Use it in modular mode with the breakaway section still attached. |
| Max duty cycle     | **50 %** (active chirp time ≤ 50 % of the frame period), or the junction can exceed 125 °C                                            |
| Thermal            | The surface gets hot. Use the supplied heat sink. Keep at least 5 cm from people during operation.                                    |
| Reset              | SW2 (NRST). TI recommends pressing it once after applying 5 V.                                                                        |
| LEDs               | LD1 = 5 V present, LD4 = USB-UART enumerated, LD5 = NRST held low                                                                     |

If you remove the breakaway section, the 60-pin connectors (DCA1000, MMWAVEICBOOST, JTAG) are lost for
good and the board cannot be put back together.

## 3. USB / serial interface

### 3.1 The two ports ✅

The CP2105 enumerates as **two serial ports** on one USB device:

| CP2105 port        | Role                              | Baud       | Direction     | Content                         |
|--------------------|-----------------------------------|------------|---------------|---------------------------------|
| **Enhanced** (ECI) | **CLI / "Application/User UART"** | **115200** | bidirectional | ASCII text commands and replies |
| **Standard** (SCI) | **Data port**                     | **921600** | device → host | Binary TLV frames (section 6)   |

The EVM guide states the roles directly: "The enhanced COM port is the application/user UART and the
standard COM port is the data port." The SDK user guide gives the baud rates (CLI 115200, data 921600).

Line settings: 8 data bits, no parity, 1 stop bit, no flow control. ⚠️ TI does not state this
explicitly. These are the pyserial defaults that working community parsers use.

### 3.2 Linux device names ⚠️

- The kernel's `cp210x` driver handles the CP2105, and both interfaces have worked since kernel 3.4. The ports appear as **`/dev/ttyUSB*`**. Ignore guides that say `/dev/ttyACM0/1`: those are for TI boards with an XDS110 bridge, not this one.
- Which port becomes `ttyUSB0` and which `ttyUSB1` depends on enumeration order. Bind by USB interface number with a udev rule instead of relying on the number. Interface 0 is *expected* to be the Enhanced (CLI) port and interface 1 the Standard (data) port. This matches the CP2105 driver's ECI/SCI handling but has not been checked on this board.
- Check on first use: the CLI port answers a bare newline with the `mmwDemo:/>` prompt. The data port stays silent until `sensorStart`.
- ⚠️ Not verified: whether the Alpine RPi kernel image used in `rpi/` ships the `cp210x` module.

### 3.3 Baud-rate limit on this EVM ✅ (derived)

The SDK's `configDataPort` command can raise the data-port baud rate up to 3,125,000. On this EVM,
however, the data port is the CP2105 **Standard** interface, whose maximum is **921600**. Only the
Enhanced interface goes to about 2 Mbps. **Keep the data port at 921600.** Higher rates require
swapping the port roles in firmware, which TI forum users report doing.

### 3.4 Board switch settings ✅

Switch positions for the USB modes (from the EVM guide, tables 2-1, 2-8 and 2-9):

| Mode                                          | S1.1 | S1.3 (SOP0) | S1.4 (SOP1) | S2.1 | S3 (SOP2) |
|-----------------------------------------------|------|-------------|-------------|------|-----------|
| **Functional**: run the demo over USB         | OFF  | OFF         | OFF         | OFF  | **OFF**   |
| **Flashing**: program the QSPI flash over USB | OFF  | OFF         | OFF         | OFF  | **ON**    |

S1.1 OFF routes the UART to the CP2105, which you need for any USB use. Press **SW2 (reset)** after
every switch change. The board reads its boot mode only at reset.

## 4. Firmware

- Out-of-box demo binary: **`xwr18xxAOP_mmw_demo`** from mmWave SDK **3.5.0.4**. AWR1843AOP support was added in SDK 3.5. TI forum posts also call the flashed file `xwr18xx_mmw_aop_demo.bin`. Use whichever `.bin` your SDK ships for the AOP platform. **Do not** flash the plain `xwr18xx_mmw_demo` (the BOOST build), because it has the wrong antenna geometry.
- Flashing steps: set the switches to flashing mode, press reset, then use TI **UniFlash** on the **Enhanced** COM port to load the image. Afterwards, set the switches back to functional mode and press reset.
- The demo source and full doxygen docs are in the SDK at `packages/ti/demo/xwr18xx/mmw/`.
- TI's mmWave Demo Visualizer calls this platform **`xwr18xx_AOP`**.
- ⚠️ A TI forum answer says the SDK demo does not support enabling all 3 TX on the AWR1843AOP, even though TI's AWR1843 profiles use `channelCfg 15 7 0`. Verify on hardware. If it fails, use 2 TX.

## 5. CLI protocol (Enhanced port, 115200)

### 5.1 Framing ✅

- Plain ASCII and line-based. The host sends one command per line, terminated with `\n`.
- The device echoes the command, then replies on its own line with:
  - `Done` on success,
  - `Error <negative code>` on failure (decode the code with the demo doxygen), or
  - `Ignored: Sensor is already stopped` or `Ignored: Sensor is already started`, followed by `Done`.
- After every reply the device prints the prompt **`mmwDemo:/>`** with no newline after it.
- Lines starting with `%` are comments, and the CLI skips them.
- ⚠️ The exact line endings the device sends (CR vs CRLF) are not documented. Split on either.

Recommended host behaviour: send a line, then read until the prompt appears. Treat `Done` as success
and anything containing `Error` as failure. Use a timeout of about 1 s for normal commands and about
5 s for `sensorStart`. If `sensorStart` gets no reply, the firmware has probably asserted. Log it and
reset the board. Community parsers that skip prompt detection wait 10 ms between lines, but waiting for
the prompt is more robust.

### 5.2 Session sequence ✅

1. Open both ports. The CLI port should give a prompt after a bare newline.
2. Send `sensorStop`, then `flushCfg`. Both are needed before any reconfiguration.
3. Send every mandatory configuration command (5.3). The order follows TI's sample profiles.
4. Send `sensorStart`. Binary frames start on the data port.
5. To change config: `sensorStop` → `flushCfg` → full config → `sensorStart`.
   - `sensorStart 0` restarts with the previous config and skips reconfiguration.
   - Some commands (`cfarCfg`, `cfarFovCfg`, `aoaFovCfg`, `clutterRemoval`, `multiObjBeamForming`, `calibDcRangeSig`, `extendedMaxVelocity`, `compRangeBiasAndRxChanPhase`, `measureRangeBiasAndRxChanPhase`) can be changed **while running**.
   - `dfeDataOutputMode`, `channelCfg`, `adcCfg`, `lowPower` and `calibData` need a **board reboot** to change.

The frame number in the data header resets only on power-cycle or reset. It does **not** reset on
sensorStop or sensorStart.

### 5.3 Command reference (SDK 3.5 mmW demo, xwr18xx) ✅

M = mandatory. Parameters are listed in order. `subFrameIdx` is always `-1` in legacy frame mode.

| Command                          | M   | Parameters                                                                                                                                  | Notes                                                                                                                                             |
|----------------------------------|-----|---------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| `sensorStop`                     |     | none                                                                                                                                        | Required before reconfiguring                                                                                                                     |
| `flushCfg`                       |     | none                                                                                                                                        | Clears the old config                                                                                                                             |
| `dfeDataOutputMode`              | M   | modeType                                                                                                                                    | `1` = frame-based chirps (use this), `3` = advanced frame                                                                                         |
| `channelCfg`                     | M   | rxMask txMask cascading                                                                                                                     | 4 RX = `15`, 3 TX = `7`, cascading = `0`                                                                                                          |
| `adcCfg`                         | M   | numADCBits adcOutputFmt                                                                                                                     | Only `2 1` (16-bit, complex 1x) is supported                                                                                                      |
| `adcbufCfg`                      | M   | subFrameIdx outFmt iqSwap chanInterleave chirpThreshold                                                                                     | 18xx demo: `-1 0 1 1 1` (chirpThreshold must be 1 because the HWA does the 1D FFT)                                                                |
| `profileCfg`                     | M   | id startFreqGHz idleUs adcStartUs rampEndUs txOutPower txPhaseShifter slopeMHzPerUs txStartUs numAdcSamples sampleRateKsps hpf1 hpf2 rxGain | One profile only. Buffer sizes depend on samples × loops × antennas, and an oversized config is rejected.                                         |
| `chirpCfg`                       | M   | startIdx endIdx profileId startFreqVar slopeVar idleVar adcStartVar txMask                                                                  | One chirp per TX for TDM-MIMO (txMask 1, 2 or 4)                                                                                                  |
| `frameCfg`                       | M   | chirpStart chirpEnd numLoops numFrames periodMs triggerSel triggerDelayMs                                                                   | numLoops ≥ 4. numFrames `0` = infinite. triggerSel `1` = software. The period must allow ≤ 50 % duty **and** enough time to send the UART output. |
| `lowPower`                       | M   | 0 adcMode                                                                                                                                   | `0 0`                                                                                                                                             |
| `guiMonitor`                     | M   | subFrameIdx detectedObjects logMagRange noiseProfile rangeAzimuth(Elev)HeatMap rangeDopplerHeatMap statsInfo                                | Selects which TLVs are sent (section 6.4). detectedObjects: `1` = points + side info, `2` = points only.                                          |
| `cfarCfg`                        | M   | subFrameIdx procDirection mode noiseWin guardLen divShift cyclicMode thresholdDb peakGrouping                                               | Send twice: once for range (0), once for Doppler (1)                                                                                              |
| `multiObjBeamForming`            | M   | subFrameIdx enabled threshold                                                                                                               |                                                                                                                                                   |
| `calibDcRangeSig`                | M   | subFrameIdx enabled negBinIdx posBinIdx numAvg                                                                                              |                                                                                                                                                   |
| `clutterRemoval`                 | M   | subFrameIdx enabled                                                                                                                         | Static clutter removal. When enabled, static objects disappear.                                                                                   |
| `aoaFovCfg`                      | M   | subFrameIdx minAz maxAz minElev maxElev                                                                                                     | Degrees                                                                                                                                           |
| `cfarFovCfg`                     | M   | subFrameIdx procDirection min max                                                                                                           | Send twice: range (m), Doppler (m/s)                                                                                                              |
| `compRangeBiasAndRxChanPhase`    | M   | rangeBias then 12 (Re, Im) pairs                                                                                                            | Q15. Use identity (`1 0` × 12) until calibrated.                                                                                                  |
| `measureRangeBiasAndRxChanPhase` | M   | enabled targetDistM searchWinM                                                                                                              | `0 …` except during calibration                                                                                                                   |
| `extendedMaxVelocity`            | M   | subFrameIdx enabled                                                                                                                         | Velocity disambiguation up to 2 × vmax                                                                                                            |
| `CQRxSatMonitor`                 | M   | profile satMonSel priSliceDuration numSlices rxChanMask                                                                                     |                                                                                                                                                   |
| `CQSigImgMonitor`                | M   | profile numSlices numSamplePerSlice                                                                                                         |                                                                                                                                                   |
| `analogMonitor`                  | M   | rxSaturation sigImgBand                                                                                                                     | `0 0` disables both monitors                                                                                                                      |
| `lvdsStreamCfg`                  | M   | subFrameIdx enableHeader dataFmt enableSW                                                                                                   | `-1 0 0 0` (no LVDS)                                                                                                                              |
| `calibData`                      | M   | saveEnable restoreEnable flashOffset                                                                                                        | TI profiles use `0 0 0`. **Required since SDK 3.4**: it is missing from older profiles, and without it `sensorStart` fails.                       |
| `sensorStart`                    | M   | \[doReconfig\]                                                                                                                              | Starts streaming                                                                                                                                  |
| `configDataPort`                 |     | baudrate ackPing                                                                                                                            | Optional. **Keep 921600 on this EVM** (section 3.3). With ackPing = 1 the device sends 16 × `0xFF` on the data port after the change.             |
| `queryDemoStatus`                |     | none                                                                                                                                        | Optional. Returns the sensor state (0 init, 1 opened, 2 started, 3 stopped) and the data-port baud rate.                                          |

The SDK user guide (section 3.4) has the full parameter semantics. The command names above match TI's
SDK 3.x profile files. In particular, profiles use `calibData` with a capital D, while the guide's
table writes `calibdata`.

A working example config is in `tests/awr1843aopevm/profile_test.cfg`, and the expected CLI exchange
for it is in `tests/awr1843aopevm/cli_session_ok.txt`.

## 6. Data port protocol (Standard port, 921600)

### 6.1 General ✅

- Binary and **little-endian**. One packet per radar frame. Floats are IEEE-754 float32.
- Each packet is a 40-byte header, then `numTLVs` TLV blocks, then zero padding so that the **total length is a multiple of 32 bytes**.
- `totalPacketLen` includes the header and the padding.

### 6.2 Frame header (40 bytes) ✅

| Offset | Size | Type        | Field          | Notes                                                                                                                                        |
|--------|------|-------------|----------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| 0      | 8    | uint16\[4\] | magicWord      | `0x0102 0x0304 0x0506 0x0708`. On the wire: `02 01 04 03 06 05 08 07`.                                                                       |
| 8      | 4    | uint32      | version        | SDK version: major\<\<24 \| minor\<\<16 \| bugfix\<\<8 \| build. For example, SDK 3.5.0.4 = `0x03050004`.                                    |
| 12     | 4    | uint32      | totalPacketLen | Bytes, including the header and padding                                                                                                      |
| 16     | 4    | uint32      | platform       | Device ID. TI documents `0xA6843` for IWR6843. ⚠️ For AWR1843 it is *presumably* `0xA1843`, unconfirmed. Log it rather than rejecting on it. |
| 20     | 4    | uint32      | frameNumber    | Resets only on reset or power-cycle                                                                                                          |
| 24     | 4    | uint32      | timeCpuCycles  | Free-running CPU cycle counter. Wraps.                                                                                                       |
| 28     | 4    | uint32      | numDetectedObj | Number of points in TLV 1                                                                                                                    |
| 32     | 4    | uint32      | numTLVs        |                                                                                                                                              |
| 36     | 4    | uint32      | subFrameNumber | 0 in legacy frame mode                                                                                                                       |

Example (frame 1 of `data_clean.bin`):

    02 01 04 03 06 05 08 07   magic
    04 00 05 03               version  0x03050004
    00 01 00 00               totalPacketLen 256
    43 18 0a 00               platform 0x000A1843 (synthetic guess)
    01 00 00 00               frameNumber 1
    15 fa 8c 08               timeCpuCycles
    06 00 00 00               numDetectedObj 6
    04 00 00 00               numTLVs 4
    00 00 00 00               subFrameNumber 0
    01 00 00 00 60 00 00 00   first TLV: type 1, length 96 (6 points × 16)

### 6.3 TLV header (8 bytes) ✅

| Offset | Type   | Field                                                        |
|--------|--------|--------------------------------------------------------------|
| 0      | uint32 | type                                                         |
| 4      | uint32 | length: payload bytes only, **excluding** this 8-byte header |

### 6.4 TLV types sent by the SDK mmW demo ✅

| Type | Name                             | Enabled by `guiMonitor`                                | Payload                                                                                                                                                                                    |
|------|----------------------------------|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1    | Detected points                  | detectedObjects = 1 or 2                               | numDetectedObj × 16 B: `x, y, z` (m), `doppler` (m/s), each float32                                                                                                                        |
| 2    | Range profile                    | logMagRange = 1                                        | rangeFFTSize × uint16. Sum of log2 magnitudes over the receive antennas at zero Doppler, **Q9** (divide by 512 to get log2 units; multiply log2 units by 6.02 to get dB).                  |
| 3    | Noise profile                    | noiseProfile = 1                                       | Same format as type 2, taken at the max Doppler bin (the noise floor)                                                                                                                      |
| 4    | Azimuth static heatmap           | rangeAzimuthHeatMap = 1 (legacy AoA DPU only)          | rangeFFTSize × numAzimuthVirtAnt × 4 B. Complex int16 pairs **imaginary first, then real**. Ordered by range bin, then antenna.                                                            |
| 5    | Range-Doppler heatmap            | rangeDopplerHeatMap = 1                                | rangeFFTSize × dopplerFFTSize × uint16, row-major by range bin                                                                                                                             |
| 6    | Stats                            | statsInfo = 1                                          | 24 B: interFrameProcessingTime (µs), transmitOutputTime (µs), interFrameProcessingMargin (µs), interChirpProcessingMargin (µs), activeFrameCPULoad (%), interFrameCPULoad (%), each uint32 |
| 7    | Detected points side info        | detectedObjects = 1                                    | numDetectedObj × 4 B: `snr`, `noise`, each uint16 in **0.1 dB** units, in the same order as TLV 1                                                                                          |
| 8    | Azimuth/elevation static heatmap | heatmap flag = 1 (AoA2D DPU, which the AOP builds use) | rangeFFTSize × **all** virtual antennas × 4 B. Same complex layout as type 4. Sent **instead of** type 4.                                                                                  |
| 9    | Temperature stats                | statsInfo = 1                                          | 28 B: tempReportValid (int32, 0 = valid), time (uint32, ms), then uint16 °C readings for Rx0–3, Tx0–2, PM, Dig0, Dig1                                                                      |

For the AWR1843AOP, expect **type 8, not type 4**, when the heatmap is enabled. The AOP demo uses the
AoA2D DPU, the same as the IWR6843AOP. ⚠️ This is confirmed for AOP builds in general by TI docs, but
not yet on this specific board.

Things a parser must tolerate:

- **TLV order** is not specified. Dispatch on type. Do not rely on position.
- **Unknown TLV types**: skip them using `length`. Never abort on them.
- ⚠️ With **zero detections**, the demo is expected to omit TLVs 1 and 7, so `numTLVs` is smaller. Handle both cases: TLV present with length 0, or TLV absent.
- ⚠️ **Coordinates**: x = lateral, y = boresight (forward), z = up. This is the usual TI convention. The EVM guide notes that the AOP package sits rotated on the PCB, so azimuth and elevation can come out swapped depending on how the board is mounted. Confirm with a corner reflector before trusting x and z.
- ⚠️ **Doppler sign**: not documented. Assume negative = approaching and confirm with a moving target.

### 6.5 Framing and resync (recommended host logic)

1. Search the byte stream for the 8-byte magic word.
2. Read the 40-byte header and sanity-check it:
   - `totalPacketLen` is a multiple of 32, at least 40 and below a sane upper bound for your config;
   - `numTLVs` is small (≤ 10 for the standard demo);
   - `version` matches the expected SDK.
3. Wait until `totalPacketLen` bytes are buffered. If another magic word turns up inside that span, the
   frame was truncated. Drop it and resync from the new magic word.
4. Walk the TLVs. If any `8 + length` runs past `totalPacketLen`, drop the frame.
5. If any check fails, advance **one byte** past the false magic word and search again.
6. If `frameNumber` falls back to a small value, the board was reset. If it skips values, frames were lost.

`tests/awr1843aopevm/data_faults.bin` exercises every one of these cases.

### 6.6 Bandwidth budget

At 921600 baud with 8N1 framing, the data port carries 92,160 bytes/s. Per frame, approximately:

- Header: 40 bytes.
- Points: 8 + 16·N bytes for TLV 1, plus 8 + 4·N bytes for TLV 7.
- Range and noise profiles: 8 + 2·rangeBins bytes each.
- Stats and temperature: 32 + 36 bytes.
- Heatmaps are large. For example, a 256 × 32 range-Doppler map is 16 KB, which takes about 178 ms per frame.

Round the total up to a multiple of 32. The transmit time must fit within the frame period alongside
processing. Otherwise **the demo asserts and stops**. Check `transmitOutputTime` and
`interFrameProcessingMargin` in TLV 6. TI recommends ≤ 4 fps whenever heatmaps are enabled.

## 7. Calibration

Every board needs its own range bias and RX-channel phase compensation:

1. Place a strong reflector (a corner reflector) at a known distance in a clutter-free area.
2. Run TI's `profile_calibration.cfg` with `measureRangeBiasAndRxChanPhase 1 <dist> <window>`.
3. Copy the resulting values into each production config's `compRangeBiasAndRxChanPhase` line.

Until calibration is done, use the identity values shown in the example config. Angle accuracy will be
reduced until then.

## 8. Derived quantities (for the example config)

Standard FMCW relations, applied to `profileCfg 0 77 7 3 39 0 0 100 1 256 7200 0 0 30` with
3 TX TDM and 32 loops:

| Quantity                  | Formula                                                                      | Value                                               |
|---------------------------|------------------------------------------------------------------------------|-----------------------------------------------------|
| Range bin step            | c · fs / (2 · S · Nrange), where fs = ADC rate, S = slope, Nrange = FFT size | 0.0422 m                                            |
| Max range (IF limit)      | Nrange · step                                                                | 10.8 m                                              |
| Chirp time Tc (per TX)    | idleTime + rampEndTime                                                       | 46 µs                                               |
| Max unambiguous velocity  | λ / (4 · Tc · numTX)                                                         | ±7.06 m/s                                           |
| Velocity step             | 2 · vmax / numLoops                                                          | 0.441 m/s                                           |
| Active chirp time / frame | numLoops · numTX · Tc                                                        | 4.4 ms (4.4 % of 100 ms, well under the 50 % limit) |

This profile is a **placeholder** for format testing. Its 10.8 m range and ±7 m/s velocity are
probably too short for the final application. Design the real profile with TI's mmWave Sensing
Estimator or the Demo Visualizer, then recompute these values.

## 9. Raspberry Pi notes

- One USB cable carries both UARTs. With the breakaway section attached, still use the 5 V barrel jack (J5). USB power alone is meant for a split board.
- Use udev rules to give the ports stable names, for example `/dev/radar-cli` and `/dev/radar-data`, bound by USB interface number (section 3.2).
- At 921600 baud the Pi's USB serial path is not a bottleneck, but the reader thread must drain the port continuously. A full OS buffer causes dropped bytes, which shows up as truncated frames.

## 10. Open items to verify on first hardware

1. Which CP2105 interface number becomes CLI and which becomes data on Linux (3.2).
2. Whether the Alpine kernel in `rpi/` includes `cp210x` (3.2).
3. The exact flash file name in the SDK install (4).
4. Whether 3 TX (`channelCfg 15 7 0`) works on the AOP demo, and the correct `chirpCfg` TX order (4, 5.3).
5. The `platform` header value (6.2).
6. Whether TLVs 1 and 7 are omitted with zero detections, and the actual TLV order (6.4).
7. Axis orientation and Doppler sign for our mounting (6.4).
8. CLI line endings (5.1).
9. Real noise and SNR levels, so detection thresholds can be tuned instead of using the synthetic values.

When these are checked, update this doc, remove the ⚠️ markers, and replace the synthetic test data
with real captures.

## 11. Test data

See `tests/awr1843aopevm/README.md`. Summary: `data_clean.bin` (100 frames, 10 s) and
`data_faults.bin` (resync torture test). Each has a JSON ground-truth file, plus the matching config
and CLI transcript. **Synthetic, and may be slightly inaccurate compared with real sensor data** (see
the notice at the top).

## 12. Glossary

| Term      | Meaning                                                                |
|-----------|------------------------------------------------------------------------|
| AOP       | Antenna-on-package                                                     |
| CLI       | Command-line interface (text config port)                              |
| ECI / SCI | CP2105 Enhanced / Standard Communication Interface                     |
| SOP       | Sense-on-power pins that select the boot mode                          |
| TDM-MIMO  | TX antennas take turns per chirp, which gives TX × RX virtual antennas |
| TLV       | Type-Length-Value block                                                |
| Q9        | Fixed point with 9 fractional bits (value / 512)                       |

## 13. Sources

- TI, *AWR1843AoP EVM User's Guide* (SPRUIX8, March 2021): https://www.ti.com/lit/ug/spruix8/spruix8.pdf. Source for board features, switches, SOP table, ports and flashing.
- TI, *mmWave SDK 3.5.0.4 User Guide*: https://downloads.ti.com/ra-processors/esd/MMWAVE-SDK/03_05_00_04/exports/mmwave_sdk_user_guide.pdf. Source for demo binaries, baud rates and the CLI command table.
- TI, *mmWave SDK 3.5 Release Notes*: https://downloads.ti.com/ra-processors/esd/MMWAVE-SDK/03_05_00_04/exports/mmwave_sdk_release_notes.pdf. Confirms AWR1843AOP support in the demo and the AoA2D DPU.
- TI Radar Toolbox, *Understanding UART Data Output Format*: https://dev.ti.com/tirex/content/radar_toolbox_3_00_00_05/software_docs/Understanding_UART_Data_Output_Format.html. Source for the header, TLVs, padding and TLV 8 for AOP.
- TI Industrial Toolbox, *Understanding OOB UART data*: https://dev.ti.com/tirex/explore/content/mmwave_industrial_toolbox_4_10_0/labs/Out_Of_Box_Demo/docs/understanding_oob_uart_data.html
- TI E2E, CLI session log (echo / Done / prompt format, `calibData 0 0 0`): https://e2e.ti.com/cfs-filesystemfile/__key/communityserver-discussions-components-files/1023/puttyCom27output.txt
- TI E2E, AWR1843AOP COM ports / 921600 discussions: https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/1356231/awr1843aopevm-uart-communication-via-com-ports and https://e2echina.ti.com/support/machine-translation/mt-sensors/f/mt-sensors-forum/927101/awr1843aop-awr1843aop-921600bps-uart
- Linux kernel `cp210x` patch, CP2105 ECI max 2 Mbaud / SCI max 921600: https://patchwork.kernel.org/comment/22467163
- Linux kernel bug 42811, CP2105 second-interface support: https://bugzilla.kernel.org/show_bug.cgi?id=42811
- Community AWR1843 parser (baud rates, header offsets, 10 ms line pacing): https://github.com/ibaiGorordo/AWR1843-Read-Data-Python-MMWAVE-SDK-3-
- TI, *Programming Chirp Parameters in TI Radar Devices* (SWRA553): https://www.ti.com/lit/SWRA553. Source for the range and velocity formulas.
