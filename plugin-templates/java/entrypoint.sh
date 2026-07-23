#!/bin/sh
# Duplicates the real stdout fd to fd 3, then redirects the public stdout
# (fd 1) to /dev/null before the JVM ever starts -- so a stray
# System.out.println (or output from a library a plugin author pulls in)
# can never corrupt the protocol stream. Main.java writes protocol frames
# through /proc/self/fd/3, the still-live duplicate, instead of System.out.
#
# This is the same fd-dup stdout-isolation trick as
# civex_plugin_sdk.io.isolate_stdout() (CIVEX-133), just performed here in
# the entrypoint rather than in-process -- Java has no portable dup2(), but
# `exec N>&1` on the shell that execs into the JVM has the identical effect,
# and both the subprocess and container tiers spawn this process with
# stdout captured, so a plain fd-dup is invisible to the parent either way.
set -eu
exec 3>&1
exec 1>/dev/null
exec java -cp /app Main "$@"
