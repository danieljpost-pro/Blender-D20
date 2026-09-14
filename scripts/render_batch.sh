#!/bin/bash
# Render a set of outcomes, one Blender process per outcome.
#
# Why per-outcome processes: FFmpeg buffers the whole video and only writes the
# container at the end, so a killed render leaves a 48-byte stub, not a partial
# video. One process per outcome means an OOM kill costs one video instead of
# the batch, and the render cache skips completed outcomes on retry.
#
# Every invocation is logged verbatim — to the batch log, to the per-outcome
# log, and to a .cmd sidecar next to the rendered file — so any output can be
# traced back to the exact command that produced it.
#
# Usage:
#   scripts/render_batch.sh --config CFG --out DIR --log DIR [--] OUTCOME...
#   scripts/render_batch.sh --config config_bluestudio_full_base.json \
#       --out ./renders/bluestudio_sharp --log /tmp/batch 1 2 4 8 12 18 20
#
# Extra flags for every render: set EXTRA_FLAGS="--samples 32 --resolution-percent 50"

set -u
BLENDER="${BLENDER:-blender}"
CONFIG=""; OUT=""; LOGDIR=""; PER_TIMEOUT="${PER_TIMEOUT:-21600}"

while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --out)    OUT="$2";    shift 2 ;;
    --log)    LOGDIR="$2"; shift 2 ;;
    --)       shift; break ;;
    *)        break ;;
  esac
done

if [ -z "$CONFIG" ] || [ -z "$OUT" ] || [ -z "$LOGDIR" ] || [ $# -eq 0 ]; then
  echo "usage: $0 --config CFG --out DIR --log DIR [--] OUTCOME..." >&2
  exit 2
fi

mkdir -p "$LOGDIR" "$OUT"
BATCH_LOG="$LOGDIR/batch.log"

# Resolve the filename pattern from the config so we can name the sidecar.
pattern=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['render']['output_filename_pattern'])" "$CONFIG")

{
  echo "=== BATCH START $(date '+%F %T') ==="
  echo "    config   : $CONFIG"
  echo "    outcomes : $*"
  echo "    output   : $OUT"
  echo "    extra    : ${EXTRA_FLAGS:-(none)}"
  echo "    blender  : $($BLENDER --version 2>/dev/null | head -1)"
} | tee -a "$BATCH_LOG"

for o in "$@"; do
  name=$(python3 -c "print('$pattern'.format(outcome=$o))")
  target="$OUT/$name.mp4"

  # Build the argv explicitly so the logged command is the one actually run.
  # No --no-simulate: that flag skips loading the baked .d20_cache/physics.blend
  # and renders an unbaked live sim with different motion. The default path
  # loads the bake on a physics cache HIT without re-simulating.
  set -- "$BLENDER" --background --python d20_renderer/run.py -- \
        --config "$CONFIG" --outcomes "$o" --output-dir "$OUT"
  # shellcheck disable=SC2086
  [ -n "${EXTRA_FLAGS:-}" ] && set -- "$@" ${EXTRA_FLAGS}

  printf -v cmd '%q ' "$@"

  {
    echo "=== outcome $o START $(date '+%F %T') ==="
    echo "    target : $target"
    echo "    cmd    : $cmd"
  } | tee -a "$BATCH_LOG"

  # Sidecar: the exact command, next to the file it produces.
  { echo "# rendered $(date '+%F %T')"; echo "# cwd: $(pwd)"; echo "$cmd"; } > "$target.cmd"

  timeout "$PER_TIMEOUT" "$@" > "$LOGDIR/o$o.log" 2>&1
  rc=$?
  sz=$(stat -c%s "$target" 2>/dev/null || echo 0)

  # 48 bytes == FFmpeg stub from a killed render, not a real video.
  if   [ "$rc" -ne 0 ];      then verdict="FAILED (rc=$rc)"
  elif [ "$sz" -le 1000 ];   then verdict="STUB — render was killed"
  else                            verdict="ok"
  fi

  echo "=== outcome $o DONE rc=$rc bytes=$sz $verdict $(date '+%F %T') ===" | tee -a "$BATCH_LOG"
done

echo "=== BATCH COMPLETE $(date '+%F %T') ===" | tee -a "$BATCH_LOG"
