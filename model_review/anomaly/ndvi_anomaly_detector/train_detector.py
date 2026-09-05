"""CLI обучения исторической нормы детектора."""
import argparse
import json
from pathlib import Path
import pandas as pd
from anomaly_core import DetectorConfig,fit_detector,save_artifact


def main():
    parser=argparse.ArgumentParser(description="Обучить историческую норму NDVI")
    parser.add_argument("--input",required=True,type=Path,help="CSV с историческими сезонами")
    parser.add_argument("--output",default=Path("model/anomaly_detector.joblib"),type=Path)
    parser.add_argument("--min-history-years",default=3,type=int)
    args=parser.parse_args();data=pd.read_csv(args.input,parse_dates=["date"])
    model=fit_detector(data,DetectorConfig(min_history_years=args.min_history_years));save_artifact(model,args.output)
    summary={"model":str(args.output),"trained_fields":len(model["fields"]),"skipped_fields":len(model["skipped"]),
             "training_rows":model["training_rows"],"training_period":[model["training_date_min"],model["training_date_max"]]}
    args.output.with_suffix(".json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
