# NDVI anomaly detector

Автономный интеграционный пакет поиска негативных периодов. Leaderboard-модель и восстановление скрытых контрольных точек сюда не входят.

## Что делает метод

`train_detector.py` не обучает ML-классификатор. Он строит для каждого полигона исторические ежедневные нормы NDVI, EVI, NDWI, температуры и осадков и сохраняет робастные масштабы отклонений.

`infer_anomalies.py` для последнего года каждого переданного полигона:

1. строит робастную ежедневную кривую по доступным наблюдениям;
2. выравнивает историческую норму по фазе в пределах ±21 дня;
3. находит устойчивый дефицит `z < -1` и `residual < -0.04`;
4. требует длительность 7 дней либо 3 дня при `min z < -2`;
5. требует минимум два подтверждения из EVI, NDWI, дефицита осадков и температуры;
6. требует минимум два фактически наблюдавшихся дня внутри периода;
7. возвращает даты, тяжесть, подтверждения и гипотезу причины.

Это строгий слой для автоматических уведомлений. Причина остаётся гипотезой, поскольку погодные и спутниковые признаки не доказывают причинность.

## Требования к данным

Обязательные колонки:

- `anon_polygon_id`, `date`, `primary_ndvi`;
- `primary_evi`, `primary_ndwi` либо соответствующие `s2_*`, `landsat_*`, `modis_*`;
- для погодного подтверждения: `era5_temp_c`, `era5_precip_mm`;
- необязательно: `crop_type`, `is_synthetic_gap`.

Обучающий CSV должен содержать минимум три исторических сезона для каждого поля. Инференс может содержать несколько полигонов; анализируется последний год каждого. Если поле отсутствует в артефакте, но во входном CSV есть минимум три предыдущих сезона, его индивидуальная норма рассчитывается на лету только по этим прошлым годам. Поля без достаточной истории попадают в `skipped_fields.csv`, а не получают ненадёжный диагноз.

## Запуск

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe train_detector.py `
  --input path\to\historical.csv `
  --output model\anomaly_detector.joblib

.\.venv\Scripts\python.exe infer_anomalies.py `
  --model model\anomaly_detector.joblib `
  --input path\to\current.csv `
  --output-dir output
```

Результаты:

- `anomaly_events.csv` — готовые карточки уведомлений;
- `anomaly_daily_points.csv` — ежедневная кривая, норма, z-score и флаг периода;
- `skipped_fields.csv` — поля без обученной нормы или достаточного NDVI;
- `quality_flags.csv` — физически некорректные значения NDVI;
- `summary.json` — краткая статистика запуска.

В архив уже включён `model/anomaly_detector.joblib`, обученный на предоставленном `train_dataset.csv`, и `example_output` контрольного инференса. При подключении других полей модель можно переобучить той же командой.

## Встраивание в Python-приложение

```python
import pandas as pd
from anomaly_core import load_artifact, detect_anomalies

model = load_artifact("model/anomaly_detector.joblib")
current = pd.read_csv("current.csv", parse_dates=["date"])
events, daily_points, skipped, quality = detect_anomalies(current, model)
```

`events` удобно отдавать API для списка уведомлений. `daily_points` содержит данные для графика: `ndvi_reconstructed`, `aligned_climatology`, `climatology_scale`, `z`, контекстные z-score, `origin`, `is_anomaly` и `event_id`. Поле `normal_source` принимает `trained_artifact` или `input_history` и показывает происхождение исторической нормы.

## Ограничения

- Реальная precision/recall неизвестна без независимой агрономической разметки.
- EVI и NDWI могут зависеть от тех же условий съёмки, что и NDVI.
- Для нового поля без истории нужен отдельный cold-start режим; строгий пакет сознательно его не смешивает с надёжными уведомлениями.
- При обновлении истории модель следует переобучить тем же `train_detector.py`.
