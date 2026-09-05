"""CLI инференса строгого объяснимого детектора."""
import argparse
import json
from pathlib import Path
import pandas as pd
from anomaly_core import load_artifact,detect_anomalies


def main():
    parser=argparse.ArgumentParser(description="Найти негативные периоды NDVI")
    parser.add_argument("--model",required=True,type=Path)
    parser.add_argument("--input",required=True,type=Path,help="CSV с текущими наблюдениями")
    parser.add_argument("--output-dir",default=Path("output"),type=Path)
    args=parser.parse_args();model=load_artifact(args.model);current=pd.read_csv(args.input,parse_dates=["date"])
    events,points,skipped,quality=detect_anomalies(current,model);args.output_dir.mkdir(parents=True,exist_ok=True)
    events.to_csv(args.output_dir/"anomaly_events.csv",index=False,date_format="%Y-%m-%d")
    points.to_csv(args.output_dir/"anomaly_daily_points.csv",index=False,date_format="%Y-%m-%d")
    skipped.to_csv(args.output_dir/"skipped_fields.csv",index=False)
    quality.to_csv(args.output_dir/"quality_flags.csv",index=False,date_format="%Y-%m-%d")
    summary={"events":len(events),"polygons_with_events":int(events.anon_polygon_id.nunique()) if len(events) else 0,
             "daily_points":len(points),"skipped_fields":len(skipped),"quality_flags":len(quality)}
    (args.output_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
