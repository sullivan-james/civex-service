from __future__ import annotations

from pathlib import Path

import typer

from civex.console import console


def demo(
    path: Path = typer.Argument(Path("civex-demo"), help="Directory to create the demo project in"),
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
    ctx.schema_svc.create("Deployment", description="Field deployment site")
    ctx.schema_svc.add_field("Deployment", "site", "string", required=True)
    ctx.schema_svc.add_field("Deployment", "date", "date", required=True)
    ctx.schema_svc.add_field(
        "Deployment", "habitat", "enum",
        restrictions={"choices": ["forest", "grassland", "wetland", "coastal"]},
    )
    ctx.schema_svc.add_field("Deployment", "notes", "string")

    ctx.schema_svc.create("Detection", description="Species detection event", parent="Deployment")
    ctx.schema_svc.add_field("Detection", "species", "string", required=True)
    ctx.schema_svc.add_field("Detection", "count", "integer", required=True, restrictions={"min": 1})
    ctx.schema_svc.add_field("Detection", "confidence", "float", restrictions={"min": 0.0, "max": 1.0})
    ctx.schema_svc.add_field("Detection", "time", "string")

    # --- Collection ---
    ctx.dataset_svc.create("amazon-survey-2024", description="Amazon field survey 2024")

    # --- Deployment records ---
    dep1 = ctx.record_svc.add(
        "amazon-survey-2024", "Deployment",
        {"site": "Site Alpha", "date": "2024-03-15", "habitat": "forest",
         "notes": "Dense canopy, good visibility"},
    )
    dep2 = ctx.record_svc.add(
        "amazon-survey-2024", "Deployment",
        {"site": "Site Beta", "date": "2024-03-22", "habitat": "wetland",
         "notes": "Near river confluence"},
    )

    # --- Detection records for Site Alpha ---
    ctx.record_svc.add(
        "amazon-survey-2024", "Detection",
        {"species": "Jaguar", "count": 1, "confidence": 0.95, "time": "06:32"},
        parent_record_id=str(dep1.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024", "Detection",
        {"species": "Tapir", "count": 3, "confidence": 0.88, "time": "08:15"},
        parent_record_id=str(dep1.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024", "Detection",
        {"species": "Harpy Eagle", "count": 1, "confidence": 0.72, "time": "10:47"},
        parent_record_id=str(dep1.id),
    )

    # --- Detection records for Site Beta ---
    ctx.record_svc.add(
        "amazon-survey-2024", "Detection",
        {"species": "Giant Otter", "count": 2, "confidence": 0.91, "time": "07:05"},
        parent_record_id=str(dep2.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024", "Detection",
        {"species": "Anaconda", "count": 1, "confidence": 0.85, "time": "14:30"},
        parent_record_id=str(dep2.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024", "Detection",
        {"species": "Pink River Dolphin", "count": 4, "confidence": 0.97, "time": "16:12"},
        parent_record_id=str(dep2.id),
    )
    ctx.record_svc.add(
        "amazon-survey-2024", "Detection",
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
