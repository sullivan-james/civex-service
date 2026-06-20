#!/bin/sh
set -e
ssh-keygen -A
/usr/sbin/sshd -D &
exec civexhub serve --host 0.0.0.0 --port 8001
