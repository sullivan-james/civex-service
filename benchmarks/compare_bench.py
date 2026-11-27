"""Compare two files of benchmark results (one JSON object per line, as
bench_bulk_files.py prints) and fail when the second is clearly slower.

    python benchmarks/compare_bench.py before.jsonl after.jsonl --tolerance 0.7

Each (direction, shape, store) is the best of its runs on each side, so one
slow run on a shared CI machine does not decide it. The second must reach
`tolerance` x the first's MB/s: 0.7 lets ordinary noise through and catches a
real slowdown (a pack or a parallel path lost is a 2x to 5x loss)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def best(path: str) -> dict[tuple[str, str, str], float]:
    out: dict[tuple[str, str, str], float] = {}
    for line in Path(path).read_text().splitlines():
        if not line.startswith("{"):
            continue
        row = json.loads(line)
        key = (row["direction"], row["shape"], row["store"])
        out[key] = max(out.get(key, 0.0), float(row["MB_per_s"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--tolerance", type=float, default=0.7)
    args = ap.parse_args()
    before, after = best(args.before), best(args.after)
    failed = False
    if set(before) != set(after):  # a side that lost a shape (a crash) is a failure
        print(
            "FAILED: different runs on the two sides: "
            f"{sorted(set(before) ^ set(after))}"
        )
        failed = True
    print(f"{'direction shape store':<28}{'before':>10}{'after':>10}{'ratio':>8}")
    for key in sorted(before):
        b, a = before[key], after.get(key, 0.0)
        ratio = a / b if b else 1.0
        bad = ratio < args.tolerance
        failed |= bad
        print(
            f"{' '.join(key):<28}{b:>10.1f}{a:>10.1f}{ratio:>8.2f}"
            f"{'  SLOWER' if bad else ''}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
