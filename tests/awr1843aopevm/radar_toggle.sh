#!/usr/bin/env bash
# radar_toggle.sh - toggle the AWR1843AOPEVM mmWave demo between running and stopped.
#
# Usage: radar_toggle.sh [toggle|on|off|status]    (default: toggle)
# Env:   RADAR_CLI  serial CLI port (default: CP2105 port0 by-id path)
#        RADAR_CFG  config sent when the board is unconfigured
#                   (default: profile_test.cfg next to this script)
set -u

readonly DEFAULT_PORT=/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_019C69A2-if00-port0
readonly SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
PORT=${RADAR_CLI:-$DEFAULT_PORT}
CFG=${RADAR_CFG:-$SCRIPT_DIR/profile_test.cfg}
readonly TIMEOUT=3
readonly FD=3
readonly PROMPT='mmwDemo:/>'

die() {
  printf 'radar_toggle: %s\n' "$*" >&2
  exit 1
}

# fail_cmd <command> <reply> <reason>: report a failed command and exit.
fail_cmd() {
  printf 'radar_toggle: command "%s" failed: %s\n' "$1" "$3" >&2
  printf -- '--- reply ---\n%s\n-------------\n' "$(printf '%s' "$2" | tr -d '\r')" >&2
  exit 1
}

# drain: discard any stale output left on the port.
drain() {
  local junk
  while IFS= read -r -d '>' -t 0.2 junk <&$FD; do :; done
}

# send_cmd <command>: send one line, read until the prompt, check the reply.
# Sets REPLY_TXT to the raw reply.
send_cmd() {
  local cmd=$1 buf="" chunk
  printf '%s\n' "$cmd" >&$FD 2>/dev/null || fail_cmd "$cmd" "" "write to port failed"
  while :; do
    if ! IFS= read -r -d '>' -t "$TIMEOUT" chunk <&$FD; then
      fail_cmd "$cmd" "$buf$chunk" "timed out waiting for prompt"
    fi
    buf+="$chunk>"
    [[ $buf == *"$PROMPT" ]] && break
  done
  REPLY_TXT=$buf
  if [[ $buf == *Error* || $buf == *"not recognized"* ]]; then
    fail_cmd "$cmd" "$buf" "board reported an error"
  fi
}

# query_state: sets STATE to the numeric Sensor State.
query_state() {
  send_cmd queryDemoStatus
  STATE=$(sed -n 's/.*Sensor State: *\([0-9][0-9]*\).*/\1/p' <<<"$REPLY_TXT" | tail -n 1)
  [[ -n $STATE ]] || fail_cmd queryDemoStatus "$REPLY_TXT" "no 'Sensor State' line in reply"
}

# state_name <N>: sets NAME to running, stopped or unconfigured.
state_name() {
  case $1 in
    2) NAME=running ;;
    3) NAME=stopped ;;
    0|1) NAME=unconfigured ;;
    *) die "unexpected Sensor State: $1" ;;
  esac
}

# send_cfg: send every non-comment, non-blank line of CFG, one at a time.
send_cfg() {
  local line
  [[ -f $CFG ]] || die "config file not found: $CFG"
  [[ -r $CFG ]] || die "config file not readable: $CFG"
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%$'\r'}
    [[ $line =~ ^[[:space:]]*$ || $line =~ ^[[:space:]]*% ]] && continue
    send_cmd "$line"
  done < "$CFG"
}

mode=${1:-toggle}
case $mode in
  toggle|on|off|status) ;;
  *) die "usage: $(basename "$0") [toggle|on|off|status]" ;;
esac

[[ -e $PORT ]] || die "serial port $PORT does not exist (board unplugged?)"
[[ -c $PORT ]] || die "$PORT is not a character device"
[[ -r $PORT && -w $PORT ]] || die "no read/write access to $PORT"

exec 3<>"$PORT" || die "cannot open $PORT"
trap 'exec 3>&-' EXIT
stty -F "$PORT" 115200 raw -echo cs8 -cstopb -parenb -crtscts || die "stty failed on $PORT"
drain

query_state
state_name "$STATE"
CUR=$NAME

if [[ $mode == status ]]; then
  if [[ $CUR == unconfigured ]]; then
    echo "radar: unconfigured (state $STATE, never configured since power-up)"
  else
    echo "radar: $CUR"
  fi
  exit 0
fi

case $mode in
  toggle) if [[ $CUR == running ]]; then TARGET=stopped; else TARGET=running; fi ;;
  on) TARGET=running ;;
  off) TARGET=stopped ;;
esac

if [[ $CUR == "$TARGET" ]]; then
  echo "radar: $CUR"
  exit 0
fi

case $CUR/$TARGET in
  running/stopped) send_cmd sensorStop ;;
  stopped/running) send_cmd "sensorStart 0" ;;
  unconfigured/running) send_cfg ;;
  unconfigured/stopped) echo "radar: unconfigured (state $STATE, never configured since power-up)"; exit 0 ;;
esac

query_state
state_name "$STATE"
if [[ $NAME != "$TARGET" ]]; then
  die "after $mode the radar is $NAME (state $STATE), expected $TARGET"
fi
echo "radar: $NAME"
exit 0
