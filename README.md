# ПолеЗрение

Веб-сервис мониторинга сельскохозяйственных полей и воспроизводимое решение задачи восстановления NDVI.

## Структура

- `platform/` — FastAPI, Celery, PostgreSQL/PostGIS, Next.js и автоматический сбор Sentinel-2, Landsat, MODIS, ERA5-Land и WorldCover;
- `model_review/forecast/NDVI_v8_product_handoff_0712/` — актуальная конкурсная модель v8, данные и полный batch-пайплайн;
- `model_review/anomaly/ndvi_anomaly_detector/` — модель детекции и интерпретации аномалий;
- `критерии оценки.md` и `условие задачи.md` — требования соревнования.

## Запуск веб-сервиса

```powershell
cd platform
docker compose up -d --build
```

- интерфейс: <http://localhost:3001>
- API: <http://localhost:8000>
- OpenAPI: <http://localhost:8000/docs>

Параметры внешних API описаны в `platform/.env.example` и `platform/README.md`.

## Актуальный batch-инференс v8

Быстрый deployment-инференс по проверенному артефакту:

```powershell
cd platform
docker compose run --rm api python -m app.cli.infer --input /data/New_test.csv --output /output/submission.csv
```

Полное воспроизведение с построением признаков и обучением ансамбля:

```powershell
cd model_review/forecast/NDVI_v8_product_handoff_0712
python -m pip install -r requirements.txt
python run_v8.py
python validate_submission.py --test data/New_test.csv --submission output/submission.csv
```

Подтверждённый replacement leaderboard RMSE v8 — `0.0712`, GapScore — `8.64/30`. Submission содержит 2323 строки и фактически требуемый replacement-платформой столбец `primary_ndvi_true`.

Конкурсная v8 применяется только к ключам replacement test. Для произвольных новых полей веб-сервис использует универсальное мультисенсорное сезонное восстановление; детекция аномалий выполняется отдельной моделью.

## Проверки

```powershell
cd platform
docker compose run --rm --build api pytest -q

cd web
npm run build
npx tsc --noEmit
```

Подробная архитектура, источники данных, API и ограничения описаны в `platform/README.md` и карточке v8 `model_review/forecast/NDVI_v8_product_handoff_0712/docs/MODEL_CARD.md`.
