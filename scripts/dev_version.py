#!/usr/bin/env python3
"""The version of a dev build: `<next patch after the last v* tag>.dev<N>`.

Reads `git describe --tags --long --match 'v[0-9]*'` output (v2.2.0-12-gabc1234)
and prints `version=2.2.1.dev12` for $GITHUB_OUTPUT. Used only by
.github/workflows/dev-build.yml, as SETUPTOOLS_SCM_PRETEND_VERSION.
"""

from __future__ import annotations

import re
import sys

m = re.fullmatch(r"v(\d+(?:\.\d+)*)(?:[.-]?(?:a|b|rc|post|dev)\d+)*-(\d+)-g[0-9a-f]+", sys.argv[1])
if not m:
    sys.exit(f"can't read the git describe output {sys.argv[1]!r}")
parts = [int(p) for p in m.group(1).split(".")]
parts += [0] * (3 - len(parts))
parts[2] += 1
print(f"version={parts[0]}.{parts[1]}.{parts[2]}.dev{m.group(2)}")
