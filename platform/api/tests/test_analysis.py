import numpy as np
import pandas as pd

from app.analysis import BaselineAnalysisAdapter, build_submission


def test_submission_contains_only_control_gaps() -> None:
    frame = pd.DataFrame({
        "anon_polygon_id": ["A", "A", "A", "A"],
        "date": ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04"],
        "primary_ndvi": [0.2, np.nan, 0.4, 0.5],
        "is_synthetic_gap": [False, True, False, False],
    })
    result = build_submission(frame)
    assert list(result.columns) == ["anon_polygon_id", "date", "primary_ndvi_true"]
    assert len(result) == 1
    assert result.iloc[0]["primary_ndvi_true"] == 0.3


def test_baseline_does_not_depend_on_polygon_memorisation() -> None:
    frame = pd.DataFrame({
        "anon_polygon_id": ["new-region"] * 3,
        "date": ["2026-05-01", "2026-05-03", "2026-05-05"],
        "primary_ndvi": [0.25, np.nan, 0.65],
    })
    restored = BaselineAnalysisAdapter().restore(frame)
    assert restored["primary_ndvi_pred"].between(-1, 1).all()
    assert np.isfinite(restored.loc[1, "primary_ndvi_pred"])
