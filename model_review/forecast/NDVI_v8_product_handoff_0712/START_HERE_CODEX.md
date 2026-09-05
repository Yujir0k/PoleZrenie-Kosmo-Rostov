# Инструкция следующему Codex-агенту

Рабочая модель — **v8**, публичный результат на replacement test — **0.0712**.
Не заменяй её на v9: увеличение числа деревьев улучшило старую analog-валидацию,
но ухудшило фактический leaderboard.

Сначала прочитай `README.md` и `docs/MODEL_CARD.md`. Для проверки готового файла
запусти:

```powershell
python validate_submission.py --test data/New_test.csv --submission submission.csv --expected-sha256 BE4F94BECFCED157665E345C4FF811868185CA702ADA61EF701AA76ACD0D618A
```

Для интеграции используй `run_v8.py` как batch entry point. Не меняй финальную
формулу `0.20 * prior + 0.80 * source_gated`, temperature `0.30`, число деревьев
source-expert `3500` и classifier `1500`, если нет новой независимой валидации.

Фактический заголовок платформы — `primary_ndvi_true`. Упоминание
`primary_ndvi_pred` в старом PDF устарело.

Пакет относится только к технической части интерполяции. Не утверждай, что он сам
реализует карту, сбор спутниковых данных, аномалии или весь веб-сервис.

