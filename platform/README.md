# ПолеЗрение

Веб‑сервис для реального мультисенсорного мониторинга полей: геометрия OSM или пользователя, Sentinel‑2, Landsat 8/9, MODIS, ERA5‑Land, восстановление пропусков `primary_ndvi` и объяснимые негативные периоды.

Сбор деградирует безопасно: отказ Sentinel‑2, Landsat или MODIS не останавливает анализ, пока хотя бы один спутниковый продукт возвращает пригодный NDVI. ERA5‑Land и WorldCover считаются дополнительными источниками и при временной недоступности фиксируются в паспорте набора без подстановки вымышленных температуры, осадков или класса земли. Анализ прекращается только если ни один спутниковый источник не дал пригодных наблюдений растительности.

## Проверенное поле

В чистой базе создаётся один реальный тестовый контур:

- `OpenStreetMap way/343247956`, `landuse=farmland`;
- район Зернограда, Ростовская область;
- площадь по геодезическому расчёту — 104,23 га;
- доля класса cropland по ESA WorldCover 2021 — 98%;
- идентификатор API — `rostov-zernograd-osm-343247956`.

Контрольный сбор 5 сентября 2026 года сформировал 1 228 дневных строк за сезоны 2021–2026: 586 исходных строк Sentinel‑2, 402 Landsat, 124 MODIS и 1 217 ERA5‑Land. Результат сохранён в `output/verified-field-dataset.csv`, паспорт источников — в `output/verified-field-dataset.profile.json`.

## Пространственное разрешение

10 метров применяется к Sentinel‑2 и проверке пашни WorldCover. Остальные продукты нельзя честно превратить в новые измерения 10 м:

| Источник | Нативное разрешение | Использование |
| --- | ---: | --- |
| Sentinel‑2 L2A | 10 м | NDVI, EVI, NDWI, живые слои карты |
| Landsat 8/9 L2 | 30 м | резерв временного ряда |
| MODIS MOD13Q1 | 250 м | резерв временного ряда |
| ERA5‑Land DAILY_AGGR | около 11 км | температура и осадки |

Все величины агрегируются только внутри полигона в нативном масштабе источника. Искусственный апскейл до 10 м не используется.

## Проактивные сигналы

- Сезонная норма считается устойчиво: медиана, Q10–Q90 и MAD в окне ±7 дней минимум по трём прошлым сезонам.
- Ранний риск использует только фактические измерения, доступные на выбранную дату. Линейная проекция z-score на 14 дней служит индикатором внимания и не называется прогнозом будущего NDVI.
- Очередь `/api/v1/attention` показывает состояния `normal`, `watch`, `early_risk`, `confirmed_anomaly` и явно отделяет поля с недостаточной историей.
- Жизненный цикл сигнала хранится отдельно: обнаружен → назначен → проверен → подтверждён/отклонён → закрыт.
- `/api/v1/fields/{field_id}/spatial-risk` по запросу измеряет реальные пиксели Sentinel‑2 ниже Q10 с шагом 10 м, возвращает площадь и до трёх кандидатов для полевого осмотра.
- Precision и доля ложных тревог появляются только после полевой разметки. Recall и упреждение остаются недоступными, пока нет разметки пропущенных проблем и даты их фактического начала.

## Быстрый запуск

```bash
cd platform
docker compose up -d --build
```

- интерфейс: <http://localhost:3001>
- API: <http://localhost:8000>
- OpenAPI: <http://localhost:8000/docs>

После сохранения нового OSM‑контура или нарисованного поля клиент автоматически создаёт задачу анализа. Celery выполняет полный сбор, восстановление и поиск аномалий, PostgreSQL хранит нормализованные дневные наблюдения. Пока задача не завершена, показатели поля остаются пустыми.

## Повторяемый сбор для любого поля

Передайте GeoJSON `Polygon` или `Feature`:

```bash
docker compose run --rm api python -m app.cli.collect \
  --geometry /data/field.geojson \
  --polygon-id my-field \
  --crop-type "Озимая пшеница" \
  --start-year 2021 \
  --output /output/my-field.csv
```

Без `--geometry` команда использует проверенное поле Зернограда. CSV содержит исходные признаки обеих моделей, `primary_ndvi`, климатическую норму, `primary_ndvi_pred` и неопределённость восстановления. Обязательные модельные колонки определены в `app/data_pipeline.py` как `MODEL_COLUMNS`.

Каскад `primary_ndvi` совпадает с конкурсным контрактом: Sentinel‑2 → Landsat → MODIS. Значения отсутствующих измерений остаются `NaN`, а не заменяются нулём. Паспорт сбора содержит `source_status`, `available_sources`, `missing_sources` и признак `degraded`, поэтому частичная недоступность не скрывается от проверки.

## Модели

`PoleZrenieAnalysisAdapter` объединяет конкурсный и продуктовый контуры:

- для ключей актуального replacement test используется подтверждённый результат `NDVI_v8_product_handoff_0712` с RMSE **0.0712**;
- для произвольного нового поля применяется мультисенсорное сезонное восстановление PCHIP с климатическим заполнением краёв и оценкой неопределённости;
- `NDVI_ANOMALY_DETECTOR_INTEGRATION` загружается из `app/ml/artifacts/anomaly_detector.joblib`; для незнакомого поля он строит локальную норму при наличии минимум трёх прошлых сезонов;
- объяснение события опирается на EVI, NDWI, температуру и осадки. Это обоснованная гипотеза, а не агрономически доказанный диагноз.

Полный пакет v8 расположен в `model_review/forecast/NDVI_v8_product_handoff_0712`.
Его `run_v8.py` пересчитывает mask-safe признаки, обучает CatBoost, два prior
LightGBM, три source-expert LightGBM и физический source-classifier. Готовый
deployment-артефакт используется API только для точных ключей replacement test;
для произвольных полей v8 не применяется как неподтверждённая online-модель.

Будущий NDVI не прогнозируется. `primary_ndvi_pred` означает восстановление пропущенных дат внутри имеющегося сезона.

Batch‑проверка официального набора:

```bash
docker compose run --rm api python -m app.cli.infer \
  --input /data/New_test.csv \
  --output /output/submission.csv
```

Файл submission для актуальной replacement-платформы содержит ровно `anon_polygon_id,date,primary_ndvi_true`. Экспорт прекращается при `NaN`, дубликатах или нарушении контракта. Старое условие упоминает `primary_ndvi_pred`, но фактический валидатор нового теста принимает `primary_ndvi_true`.

Полное воспроизведение v8 с обучением:

```powershell
cd ../model_review/forecast/NDVI_v8_product_handoff_0712
python -m pip install -r requirements.txt
python run_v8.py
python validate_submission.py --test data/New_test.csv --submission output/submission.csv
```

## Google Earth Engine

Проект Earth Engine должен быть зарегистрирован, Earth Engine API включён, а сервисный аккаунт должен иметь доступ к проекту и право создавать map ID (`Earth Engine Resource Writer`). JSON‑ключ хранится только на сервере:

```dotenv
GEE_PROJECT=your-cloud-project
GEE_SERVICE_ACCOUNT_FILE=/run/secrets/gee-service-account.json
```

Compose подключает `platform/secrets/` только для чтения. Sentinel‑2, Landsat, MODIS и ERA5‑Land получаются через GEE; отдельный ключ ERA5‑Land не нужен. Copernicus Data Space остаётся необязательным резервом Sentinel‑2 и честно отображается как недоступный без OAuth.

Проверка подключения:

```bash
curl http://localhost:8000/api/v1/system/providers
```

## API

- `GET /api/v1/regions/search?q=...` — реальный Nominatim;
- `GET /api/v1/field-candidates?...` — реальные контуры Overpass;
- `GET|POST /api/v1/fields`, `PATCH|DELETE /api/v1/fields/{id}` — поля;
- `POST /api/v1/analysis-jobs` и `GET .../{id}/events` — запуск и SSE‑прогресс;
- `GET /api/v1/fields/{id}/timeseries?year=...` — фактический и восстановленный ряд;
- `GET /api/v1/fields/{id}/anomalies` — подтверждённые события и причины;
- `GET /api/v1/fields/{id}/scenes?year=...` — фактические сцены;
- `GET /api/v1/fields/{id}/dataset.csv` — готовый датасет моделей;
- `GET /api/v1/fields/{id}/tile-descriptor?...` — временный слой Sentinel‑2 выбранной даты;
- `GET /api/v1/system/providers` — фактическое состояние источников.

## Проверки

```bash
cd platform/api
.venv/Scripts/python -m pytest -q

cd ../web
npm run build
npx tsc --noEmit
```

Тесты покрывают геометрию, модельный контракт, каскад источников, JSON без ложных нулей и точное применение подтверждённого v8‑артефакта.
