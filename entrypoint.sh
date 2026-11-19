#!/bin/sh
set -e
alembic upgrade head

# Browser-Terminal (ttyd) im selben Container, Port 7681. Abschalten: TERMINAL=aus.
# Optionaler Login: TERMINAL_PASS (Benutzer TERMINAL_USER, Standard admin).
case "$(printf '%s' "${TERMINAL:-an}" | tr 'A-Z' 'a-z')" in
  aus|0|false|nein|off) ;;
  *)
    if command -v ttyd > /dev/null; then
      set -- ttyd --port 7681 --writable --cwd /app -t titleFixed=vfm-pipeline
      if [ -n "${TERMINAL_PASS:-}" ]; then
        set -- "$@" --credential "${TERMINAL_USER:-admin}:${TERMINAL_PASS}"
      fi
      "$@" bash &
    fi
    ;;
esac

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
