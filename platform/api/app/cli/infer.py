from pathlib import Path

import pandas as pd
import typer

from app.analysis import build_submission, load_analysis_adapter


app = typer.Typer(add_completion=False, help="Формирует submission.csv для контрольных пропусков.")


@app.command()
def main(input: Path = typer.Option(..., exists=True, readable=True), output: Path = typer.Option(...)) -> None:
    frame = pd.read_csv(input)
    adapter = load_analysis_adapter()
    submission = build_submission(frame, adapter)
    output.parent.mkdir(parents=True, exist_ok=True)
    submission.to_csv(output, index=False, encoding="utf-8")
    typer.echo(f"Готово: {len(submission)} строк сохранено в {output} (модель {adapter.version})")


if __name__ == "__main__":
    app()
