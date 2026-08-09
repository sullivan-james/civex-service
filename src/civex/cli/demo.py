from __future__ import annotations

from pathlib import Path

import typer

from civex.console import console


def demo(
    path: Path = typer.Argument(
        Path("civex-demo"), help="Directory to create the demo project in"
    ),
) -> None:
    """Create a demo project pre-populated with example schemas and records."""
    from civex.config import Config, DBConfig
    from civex.context import build_local_context
    from civex.project import scaffold_project

    resolved = path.resolve()

    try:
        db_url = scaffold_project(resolved)
    except FileExistsError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1)

    config = Config(project_root=resolved, db=DBConfig(url=db_url), remote=None)
    ctx = build_local_context(config)

    # --- Schemas ---
    ctx.schema_svc.create(
        "deployment", label="Deployment", description="Field deployment site"
    )
    ctx.schema_svc.add_field(
        "deployment", "site", "string", required=True, label="Site"
    )
    ctx.schema_svc.add_field(
        "deployment", "date", "date", required=True, label="Deployment Date"
    )
    ctx.schema_svc.add_field(
        "deployment",
        "habitat",
        "enum",
        restrictions={"choices": ["forest", "grassland", "wetland", "coastal"]},
        label="Habitat Type",
    )
    ctx.schema_svc.add_field("deployment", "notes", "string")

    ctx.schema_svc.create(
        "detection",
        label="Detection",
        description="Species detection event",
        parent="deployment",
    )
    ctx.schema_svc.add_field("detection", "species", "string", required=True)
    ctx.schema_svc.add_field(
        "detection", "count", "integer", required=True, restrictions={"min": 1}
    )
    ctx.schema_svc.add_field(
        "detection",
        "confidence",
        "float",
        restrictions={"min": 0.0, "max": 1.0},
        label="Confidence Score",
    )
    ctx.schema_svc.add_field("detection", "time", "string")

    # --- Collection ---
    ctx.dataset_svc.create("amazon-survey-2024", description="Amazon field survey 2024")

    # --- Deployment records ---
    dep1 = ctx.record_svc.add(
        "amazon-survey-2024",
        "deployment",
        {
            "site": "Site Alpha",
            "date": "2024-03-15",
            "habitat": "forest",
            "notes": "Dense canopy, good visibility",
        },
    )
    dep2 = ctx.record_svc.add(
        "amazon-survey-2024",
        "deployment",
        {
            "site": "Site Beta",
            "date": "2024-03-22",
            "habitat": "wetland",
            "notes": "Near river confluence",
        },
    )

    # --- Detection records for Site Alpha ---
    ctx.record_svc.add(
        "amazon-survey-2024",
        "detection",
        {"species": "Jaguar", "count": 1, "confidence": 0.95, "time": "06:32"},
        parent_record_id=str(dep1.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024",
        "detection",
        {"species": "Tapir", "count": 3, "confidence": 0.88, "time": "08:15"},
        parent_record_id=str(dep1.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024",
        "detection",
        {"species": "Harpy Eagle", "count": 1, "confidence": 0.72, "time": "10:47"},
        parent_record_id=str(dep1.id),
    )

    # --- Detection records for Site Beta ---
    ctx.record_svc.add(
        "amazon-survey-2024",
        "detection",
        {"species": "Giant Otter", "count": 2, "confidence": 0.91, "time": "07:05"},
        parent_record_id=str(dep2.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024",
        "detection",
        {"species": "Anaconda", "count": 1, "confidence": 0.85, "time": "14:30"},
        parent_record_id=str(dep2.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024",
        "detection",
        {
            "species": "Pink River Dolphin",
            "count": 4,
            "confidence": 0.97,
            "time": "16:12",
        },
        parent_record_id=str(dep2.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024",
        "detection",
        {"species": "Scarlet Macaw", "count": 7, "confidence": 0.99, "time": "09:22"},
        parent_record_id=str(dep2.id),
    )

    ctx.commit()
    ctx.close()

    console.print(f"[success]Demo project created at {resolved}[/success]")
    console.print("  Schemas     Deployment, Detection")
    console.print("  Collection  amazon-survey-2024")
    console.print("  Records     2 deployments, 7 detections")
    console.print(f"\nTo explore: cd {resolved} && civex collection list")
