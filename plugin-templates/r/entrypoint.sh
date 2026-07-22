#!/bin/sh
# fd-dup stdout isolation (CIVEX-133): duplicate the real stdout fd to fd 3,
# then point the public fd 1 at /dev/null -- before Rscript, or any package
# it loads, gets a chance to run. plugin.R writes protocol frames to fd 3 via
# /dev/fd/3, relying on the Linux-specific /proc behaviour that reopening a
# pipe fd through /proc/self/fd (of which /dev/fd is a symlink) refers to the
# same pipe -- always true here since this only ever runs inside a Linux
# container spawned with `docker run -i` (stdout captured as a pipe).
set -eu

exec 3>&1 1>/dev/null
exec Rscript plugin.R "$@"
