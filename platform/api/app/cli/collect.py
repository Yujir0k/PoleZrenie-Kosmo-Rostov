from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from app.analysis import load_analysis_adapter
from app.providers import EarthEngineProvider
from app.services import VERIFIED_FIELD


def main(
    output: Path = typer.Option(Path("/output/verified-field-dataset.csv"), "--output"),
    geometry: Path | None = typer.Option(None, "--geometry", help="GeoJSON Polygon или Feature"),
    polygon_id: str = typer.Option(VERIFIED_FIELD["id"], "--polygon-id"),
    crop_type: str = typer.Option("Культура не указана", "--crop-type"),
    start_year: int | None = typer.Option(None, "--start-year"),
    end_date: str | None = typer.Option(None, "--end-date", help="YYYY-MM-DD"),
) -> None:
    """Собирает реальный мультисенсорный датасет для любого GeoJSON-полигона."""
    if geometry:
        payload = json.loads(geometry.read_text(encoding="utf-8"))
        selected_geometry = payload.get("geometry", payload)
    else:
        selected_geometry = VERIFIED_FIELD["geometry"]
    finish = date.fromisoformat(end_date) if end_date else None
    frame, profile = EarthEngineProvider().collect_model_dataset(
        selected_geometry,
        polygon_id,
        crop_type,
        start_year=start_year,
        end_date=finish,
    )
    restored = load_analysis_adapter().restore(frame)
    output.parent.mkdir(parents=True, exist_ok=True)
    restored.to_csv(output, index=False, date_format="%Y-%m-%d", encoding="utf-8")
    profile_path = output.with_suffix(".profile.json")
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(json.dumps({"rows": len(restored), "output": str(output), "profile": profile}, ensure_ascii=False))


if __name__ == "__main__":
    typer.run(main)
