#!/bin/sh
# Conductor Python launcher: finds a working Python 3.8+ and runs it with the given args.
# Order: plugin option "python" (if set), python3, python, py. Never fails a hook.
for c in "$CLAUDE_PLUGIN_OPTION_PYTHON" python3 python py; do
  [ -n "$c" ] || continue
  command -v "$c" >/dev/null 2>&1 || continue
  if "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then
    exec "$c" "$@"
  fi
done
echo "conductor: Python 3.8+ not found (install it or set the plugin option 'python')" >&2
exit 0
