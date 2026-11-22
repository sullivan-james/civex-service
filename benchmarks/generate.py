"""Populate a civex project with a large, realistic bioacoustics dataset.

Everything goes through civex's own services (RecordService.add, FileService,
StoreService), so what gets written -- validation, reference checks, audit
rows, file placement and dedup -- is what a real user's data would cost. Run
from inside a project (`civex init --sqlite` first):

    .venv/bin/python benchmarks/generate.py --preset small --files

Shape (a three-level hierarchy plus shared reference data):

    reference-data  (global)   site, species, observer
    survey-<year>   (local)    encounter -> recording -> selection
                               encounter refs site/observer, lists species

With --files, recordings carry a .wav and some selections a table (.txt), whose
download names come from the records above and the site reference. Files go to
extra volumes in a folder beside the project, one deliberately small so files
spill over, and each survey has a home volume. A --file-budget-gb caps the
bytes written; past it, records are still made, without files.

Deterministic for a given --seed, so runs are comparable.
"""

from __future__ import annotations

import argparse
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from civex.config import load_config
from civex.context import build_local_context
from civex.domain.query import RecordQuery

REGIONS = ["North Sea", "Baltic", "Celtic Sea", "Moray Firth", "Hebrides", "Biscay"]
GROUPS = ["cetacean", "pinniped", "fish", "seabird", "invertebrate"]
QUALITY = ["poor", "fair", "good", "excellent"]
LABELS = ["whistle", "click", "burst pulse", "buzz", "call", "noise", "unknown"]
FIRST = ["Ada", "Grace", "Alan", "Mary", "Linus", "Rosalind", "Carl", "Jane"]
LAST = ["Smith", "Okafor", "Nguyen", "Garcia", "Kowalski", "MacLeod", "Rossi", "Haddad"]


def build_schemas(ctx) -> None:
    s = ctx.schema_svc

    def make(name, fields, parent=None, label=None):
        s.create(name, parent=parent, label=label)
        for fname, dtype, *rest in fields:
            s.add_field(name, fname, dtype, restrictions=(rest[0] if rest else None))
        ctx.commit()

    make(
        "site",
        [
            ("name", "string"),
            ("region", "string", {"choices": REGIONS}),
            ("latitude", "float"),
            ("longitude", "float"),
            ("depth_m", "integer"),
        ],
    )
    make(
        "species",
        [
            ("common_name", "string"),
            ("latin_name", "string"),
            ("taxon_group", "string", {"choices": GROUPS}),
        ],
    )
    make("observer", [("name", "string"), ("email", "string"), ("active", "boolean")])
    make(
        "encounter",
        [
            ("code", "string"),
            ("date", "date"),
            ("site", "reference", {"schema": "site"}),
            ("observer", "reference", {"schema": "observer"}),
            ("species_seen", "reference_list", {"schema": "species"}),
            ("group_size", "integer", {"min": 1}),
            ("notes", "string"),
        ],
    )
    make(
        "recording",
        [
            ("file_name", "string"),
            ("started_at", "datetime"),
            ("sample_rate", "integer"),
            ("duration_s", "float", {"min": 0}),
            ("quality", "string", {"choices": QUALITY}),
        ],
        parent="encounter",
    )
    make(
        "selection",
        [
            ("begin_s", "float"),
            ("end_s", "float"),
            ("low_freq_hz", "float"),
            ("high_freq_hz", "float"),
            ("label", "string", {"choices": LABELS}),
            ("confidence", "float", {"min": 0, "max": 1}),
            ("reviewed", "boolean"),
        ],
        parent="recording",
    )


PRESETS = {
    # collections, encounters, sites, species, observers, file budget (GB)
    "tiny": dict(
        collections=1,
        encounters=40,
        sites=20,
        species=20,
        observers=10,
        file_budget_gb=0.1,
    ),
    "small": dict(
        collections=2,
        encounters=300,
        sites=60,
        species=50,
        observers=20,
        file_budget_gb=1.0,
    ),
    "medium": dict(
        collections=4,
        encounters=1500,
        sites=300,
        species=200,
        observers=100,
        file_budget_gb=8.0,
    ),
    "large": dict(
        collections=6,
        encounters=2000,
        sites=500,
        species=300,
        observers=200,
        file_budget_gb=20.0,
    ),
}


def add_file_fields(ctx) -> None:
    """Download names built from the records above (`code`, `started_at`) and a
    reference held by one of them (`site.name`, two levels up for a selection)."""
    s = ctx.schema_svc
    s.add_field(
        "recording",
        "audio",
        "file",
        restrictions={
            "accept": ".wav",
            "filename_template": "{site.name:slug}_{code}_{started_at:YYYYMMDD_HHmm}",
        },
    )
    s.add_field(
        "selection",
        "table",
        "file",
        restrictions={
            "accept": ".txt,.csv",
            "filename_template": "{site.region:slug}_{code}_{label:slug}_{begin_s}",
        },
    )
    ctx.commit()


def setup_volumes(ctx, args, project: Path) -> list[str]:
    """`args.volumes` volumes beside the project (outside it, so taking one away
    looks like an unplugged drive), first in the write queue. The last is small
    so it fills and later writes spill to the others."""
    base = Path(args.volumes_dir or f"{project}-volumes").resolve()
    small = args.small_volume_gb
    if small is None:
        small = max(0.02, args.file_budget_gb / 4)
    names = []
    for i in range(args.volumes):
        name = f"vol-{chr(ord('a') + i)}"
        last = i == args.volumes - 1 and args.volumes > 1
        ctx.store_svc.add_volume(
            name,
            str(base / name),
            allocated_gb=small if last else None,
            add_to_queue=True,
        )
        names.append(name)
    ctx.store_svc.set_queue(names + ["default"])
    print(
        f"volumes in {base}: {', '.join(names)}"
        + (f" ({names[-1]} capped at {small:g} GB)" if len(names) > 1 else "")
    )
    return names


class FileMaker:
    """Random content (so it doesn't compress or dedup by accident), with a
    share deliberately repeated, up to a byte budget for new content."""

    def __init__(self, ctx, rnd: random.Random, args):
        self.ctx, self.rnd, self.args = ctx, rnd, args
        self.budget = int(args.file_budget_gb * 2**30)
        self.used = 0
        self.pool: list[tuple[int, int]] = []  # (seed, size) of content written
        self.made = self.repeats = self.skipped = 0

    def _content(self, size: int) -> bytes | None:
        if self.pool and self.rnd.random() < self.args.dup_share:
            seed, size = self.rnd.choice(self.pool)
            self.repeats += 1
        else:
            if self.used + size > self.budget:
                self.skipped += 1
                return None
            seed = self.rnd.getrandbits(63)
            self.pool.append((seed, size))
            if len(self.pool) > 500:
                self.pool.pop(0)
            self.used += size
        return random.Random(seed).randbytes(size)

    def audio(self, name: str, collection_id: str) -> dict | None:
        lo, hi = self.args.audio_kb
        data = self._content(self.rnd.randint(lo, hi) * 1024)
        return self._store(data, name, collection_id)

    def table(self, name: str, collection_id: str, rows: int) -> dict | None:
        if self.used + rows * 40 > self.budget:
            self.skipped += 1
            return None
        r = self.rnd
        text = "Selection\tBegin\tEnd\tLow\tHigh\n" + "".join(
            f"{i}\t{r.uniform(0, 600):.3f}\t{r.uniform(0, 600):.3f}\t"
            f"{r.uniform(100, 2e4):.1f}\t{r.uniform(2e4, 9e4):.1f}\n"
            for i in range(rows)
        )
        data = text.encode()
        self.used += len(data)
        return self._store(data, name, collection_id)

    def _store(self, data: bytes | None, name: str, collection_id: str):
        if data is None:
            return None
        self.made += 1
        return self.ctx.file_svc.store_bytes(data, name, collection_id).to_dict()


class Progress:
    def __init__(self, total: int | None = None):
        self.t0 = time.monotonic()
        self.n = 0

    def tick(self, every: int = 5000) -> None:
        self.n += 1
        if self.n % every == 0:
            rate = self.n / (time.monotonic() - self.t0)
            print(f"  {self.n:>10,} records  {rate:,.0f}/s", flush=True)


# -- one kind, many records (--flat) -------------------------------------------

# Twenty fields of the scalar types a list is sorted and filtered by.
FLAT_FIELDS = [
    ("code", "string"),
    ("site", "string"),
    ("region", "string"),
    ("observer", "string"),
    ("quality", "string"),
    ("label", "string"),
    ("notes", "string"),
    ("taken", "date"),
    ("seen_at", "datetime"),
    ("depth", "float"),
    ("temperature", "float"),
    ("salinity", "float"),
    ("latitude", "float"),
    ("longitude", "float"),
    ("score", "float"),
    ("count", "integer"),
    ("sample_rate", "integer"),
    ("group_size", "integer"),
    ("reviewed", "boolean"),
    ("flagged", "boolean"),
]
FLAT_SITES = [f"Site {i:03d}" for i in range(200)]


def flat_values(i: int, rnd: random.Random) -> dict:
    """One record of the flat kind, by field name. Some values are left out
    (about 1 in 10 depths, 1 in 5 notes), as real data has gaps."""
    when = datetime(2019, 1, 1, tzinfo=timezone.utc) + timedelta(
        minutes=rnd.randint(0, 6 * 365 * 1440)
    )
    data = {
        "code": f"R{i:07d}",
        "site": rnd.choice(FLAT_SITES),
        "region": rnd.choice(REGIONS),
        "observer": f"{rnd.choice(FIRST)} {rnd.choice(LAST)}",
        "quality": rnd.choice(QUALITY),
        "label": rnd.choice(LABELS),
        "taken": when.date().isoformat(),
        "seen_at": when.isoformat().replace("+00:00", "Z"),
        "temperature": round(rnd.uniform(-2, 25), 2),
        "salinity": round(rnd.uniform(28, 38), 3),
        "latitude": round(rnd.uniform(48, 62), 5),
        "longitude": round(rnd.uniform(-12, 12), 5),
        "score": round(rnd.random(), 4),
        "count": rnd.randint(0, 500),
        "sample_rate": rnd.choice([48000, 96000, 192000, 384000]),
        "group_size": rnd.randint(1, 60),
        "reviewed": rnd.random() < 0.3,
        "flagged": rnd.random() < 0.05,
    }
    if rnd.random() < 0.9:
        data["depth"] = round(rnd.uniform(0, 4000), 1)
    if rnd.random() < 0.8:
        data["notes"] = f"Sea state {rnd.randint(0, 6)}; {rnd.choice(LABELS)} heard"
    return data


def generate_flat(args) -> None:
    """`--flat N`: one collection `flat` holding N records of one kind
    `sample` (twenty fields), for timing lists at a million records.

    Through `RecordService.add` by default (validation, history, everything:
    ~200 records/s on SQLite, so a million takes over an hour). `--bulk`
    instead writes the rows straight into the records table, in the stored
    form (field-id keyed data, the timestamps `add` would give), a batch per
    statement: tens of thousands a second. It bypasses validation, history
    (no audit_log rows), triggers and the reference/file catalogs, none of
    which a list reads; the records are what `add` would have stored, so
    the queries see the same thing. Not for timing writes."""
    rnd = random.Random(args.seed)
    ctx = build_local_context(load_config())
    t_start = time.monotonic()
    if "sample" not in {s.name for s in ctx.schema_svc.list_all()}:
        ctx.schema_svc.create("sample")
        for name, dtype in FLAT_FIELDS:
            ctx.schema_svc.add_field("sample", name, dtype)
        ctx.dataset_svc.create("flat", timezone="UTC")
        ctx.commit()
    schema = ctx.schema_svc.get("sample")
    collection = ctx.dataset_svc.get("flat")
    have = ctx.record_svc.count_records(RecordQuery(dataset="flat", schema="sample"))
    prog = Progress(args.flat)
    if not args.bulk:
        for i in range(have, args.flat):
            ctx.record_svc.add("flat", "sample", flat_values(i, rnd), with_labels=False)
            if (i + 1) % args.batch == 0:
                ctx.commit()
            prog.tick()
    else:
        import uuid

        from sqlalchemy import insert

        from civex.db.models import Record

        ids = {f.name: str(f.id) for f in schema.fields}
        start = datetime.now(timezone.utc) - timedelta(seconds=args.flat)
        rows = []
        for i in range(have, args.flat):
            at = start + timedelta(seconds=i)
            data = {ids[k]: v for k, v in flat_values(i, rnd).items()}
            rows.append(
                dict(
                    id=uuid.uuid4(),
                    dataset_id=collection.id,
                    schema_id=schema.id,
                    data=data,
                    created_at=at,
                    updated_at=at,
                )
            )
            if len(rows) >= max(args.batch, 10_000):
                ctx._session.execute(insert(Record), rows)
                ctx.commit()
                prog.n += len(rows)
                if prog.n % 100_000 < len(rows):
                    rate = prog.n / (time.monotonic() - prog.t0)
                    print(f"  {prog.n:>10,} records  {rate:,.0f}/s", flush=True)
                rows = []
        if rows:
            ctx._session.execute(insert(Record), rows)
            prog.n += len(rows)
    ctx.commit()
    ctx.index_svc.after_bulk_write()
    ctx.commit()
    ctx.close()
    dt = time.monotonic() - t_start
    made = max(args.flat - have, 0)
    print(f"done: {made:,} records in {dt:,.0f}s ({made / max(dt, 1e-9):,.0f}/s)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collections", type=int, default=6, help="survey collections")
    ap.add_argument("--encounters", type=int, default=2000, help="per collection")
    ap.add_argument("--recordings", type=float, default=3, help="mean per encounter")
    ap.add_argument("--selections", type=float, default=8, help="mean per recording")
    ap.add_argument("--sites", type=int, default=500)
    ap.add_argument("--species", type=int, default=300)
    ap.add_argument("--observers", type=int, default=200)
    ap.add_argument("--first-year", type=int, default=2019)
    ap.add_argument("--batch", type=int, default=2000, help="records per commit")
    ap.add_argument("--seed", type=int, default=1)
    flat = ap.add_argument_group("one kind, many records")
    flat.add_argument(
        "--flat",
        type=int,
        metavar="N",
        help="instead of the study: N records of one 20-field kind in one collection",
    )
    flat.add_argument(
        "--bulk",
        action="store_true",
        help="with --flat: write rows straight into the table (fast; no history)",
    )
    ap.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        help="sizes for everything above (explicit options win)",
    )
    files = ap.add_argument_group("files")
    files.add_argument(
        "--files",
        action="store_true",
        help="attach .wav files to recordings and tables to selections",
    )
    files.add_argument(
        "--file-budget-gb",
        type=float,
        default=None,
        help="new bytes to write at most (default 2, or the preset's)",
    )
    files.add_argument(
        "--audio-kb",
        type=int,
        nargs=2,
        default=[256, 4096],
        metavar=("MIN", "MAX"),
        help="size range of each .wav",
    )
    files.add_argument(
        "--table-share",
        type=float,
        default=0.25,
        help="share of selections that get a table file",
    )
    files.add_argument(
        "--dup-share",
        type=float,
        default=0.1,
        help="share of .wav files repeating earlier content",
    )
    files.add_argument(
        "--volumes",
        type=int,
        default=2,
        help="extra volumes to spread files over (0: project only)",
    )
    files.add_argument(
        "--volumes-dir",
        default=None,
        help="where they go (default: <project>-volumes beside it)",
    )
    files.add_argument(
        "--small-volume-gb",
        type=float,
        default=None,
        help="cap of the last volume (default: a quarter of the budget)",
    )
    defaults = {a.dest: a.default for a in ap._actions}
    args = ap.parse_args()
    if args.preset:
        for key, value in PRESETS[args.preset].items():
            if getattr(args, key) == defaults.get(key):
                setattr(args, key, value)
    if args.file_budget_gb is None:
        args.file_budget_gb = 2.0
    if args.flat:
        generate_flat(args)
        return

    rnd = random.Random(args.seed)
    ctx = build_local_context(load_config())
    prog = Progress()
    pending = 0

    def add(*a, **kw):
        nonlocal pending
        rec = ctx.record_svc.add(*a, with_labels=False, **kw)
        pending += 1
        if pending >= args.batch:
            ctx.commit()
            pending = 0
        prog.tick()
        return rec

    t_start = time.monotonic()
    project = load_config().project_root
    build_schemas(ctx)
    maker = None
    volumes: list[str] = []
    if args.files:
        add_file_fields(ctx)
        if args.volumes:
            volumes = setup_volumes(ctx, args, project)
        maker = FileMaker(ctx, rnd, args)

    ctx.dataset_svc.create(
        "reference-data",
        scope="global",
        description="Shared sites, species and observers",
    )
    years = [args.first_year + i for i in range(args.collections)]
    for y in years:
        ctx.dataset_svc.create(
            f"survey-{y}",
            timezone="UTC",
            description=f"{y} field season",
        )
    ctx.commit()
    for i, y in enumerate(years):
        if volumes:
            ctx.store_svc.set_placement(
                str(ctx.dataset_svc.get(f"survey-{y}").id), volumes[i % len(volumes)]
            )

    print("reference data…", flush=True)
    sites = [
        add(
            "reference-data",
            "site",
            {
                "name": f"Site {i:04d}",
                "region": rnd.choice(REGIONS),
                "latitude": round(rnd.uniform(48, 62), 5),
                "longitude": round(rnd.uniform(-12, 12), 5),
                "depth_m": rnd.randint(5, 400),
            },
        ).id
        for i in range(args.sites)
    ]
    species = [
        add(
            "reference-data",
            "species",
            {
                "common_name": f"Species {i:04d}",
                "latin_name": f"Genus{i % 90} sp{i}",
                "taxon_group": rnd.choice(GROUPS),
            },
        ).id
        for i in range(args.species)
    ]
    observers = [
        add(
            "reference-data",
            "observer",
            {
                "name": f"{rnd.choice(FIRST)} {rnd.choice(LAST)} {i}",
                "email": f"observer{i}@example.org",
                "active": rnd.random() < 0.8,
            },
        ).id
        for i in range(args.observers)
    ]
    ctx.commit()
    pending = 0

    for y in years:
        coll = f"survey-{y}"
        coll_id = str(ctx.dataset_svc.get(coll).id)
        print(f"{coll}…", flush=True)
        day0 = datetime(y, 3, 1, tzinfo=timezone.utc)
        for e in range(args.encounters):
            when = day0 + timedelta(
                days=rnd.randint(0, 200), minutes=rnd.randint(0, 1439)
            )
            enc = add(
                coll,
                "encounter",
                {
                    "code": f"{y}-{e:05d}",
                    "date": when.date().isoformat(),
                    "site": str(rnd.choice(sites)),
                    "observer": str(rnd.choice(observers)),
                    "species_seen": [
                        str(x) for x in rnd.sample(species, rnd.randint(1, 4))
                    ],
                    "group_size": rnd.randint(1, 60),
                    "notes": f"Sea state {rnd.randint(0, 6)}; "
                    f"{rnd.choice(['calm', 'swell', 'rain', 'fog', 'clear'])}",
                },
            )
            for r in range(max(0, round(rnd.gauss(args.recordings, 1)))):
                start = when + timedelta(minutes=r * 15)
                dur = round(rnd.uniform(30, 900), 2)
                rec_data = {
                    "file_name": f"{y}-{e:05d}_{r:02d}.wav",
                    "started_at": start.isoformat(),
                    "sample_rate": rnd.choice([48000, 96000, 192000, 384000]),
                    "duration_s": dur,
                    "quality": rnd.choice(QUALITY),
                }
                if maker:
                    ref = maker.audio(rec_data["file_name"], coll_id)
                    if ref:
                        rec_data["audio"] = ref
                rec = add(coll, "recording", rec_data, parent_record_id=str(enc.id))
                for _ in range(max(0, round(rnd.gauss(args.selections, 3)))):
                    b = round(rnd.uniform(0, dur - 1), 3)
                    lo = round(rnd.uniform(100, 20000), 1)
                    sel_data = {
                        "begin_s": b,
                        "end_s": round(b + rnd.uniform(0.05, 1.5), 3),
                        "low_freq_hz": lo,
                        "high_freq_hz": round(lo + rnd.uniform(200, 40000), 1),
                        "label": rnd.choice(LABELS),
                        "confidence": round(rnd.random(), 3),
                        "reviewed": rnd.random() < 0.3,
                    }
                    if maker and rnd.random() < args.table_share:
                        ref = maker.table(
                            "selections.txt", coll_id, rnd.randint(5, 400)
                        )
                        if ref:
                            sel_data["table"] = ref
                    add(coll, "selection", sel_data, parent_record_id=str(rec.id))
    ctx.commit()
    ctx.close()
    dt = time.monotonic() - t_start
    print(f"done: {prog.n:,} records in {dt:,.0f}s ({prog.n / dt:,.0f}/s)")
    if maker:
        print(
            f"files: {maker.made:,} stored ({maker.repeats:,} repeating earlier "
            f"content), {maker.used / 2**30:.2f} GB new; {maker.skipped:,} left "
            "out once the budget was used"
        )


if __name__ == "__main__":
    main()
