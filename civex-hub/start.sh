#!/bin/sh
set -e
ssh-keygen -A
/usr/sbin/sshd -D &
if [ "${CIVEXHUB_RELOAD}" = "true" ]; then
  exec uvicorn civexhub.server.app:app --host 0.0.0.0 --port 8001 --reload
else
  exec civexhub serve --host 0.0.0.0 --port 8001
fi
