"""Строгая проверка submission перед загрузкой на платформу."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd


EXPECTED_COLUMNS = ['anon_polygon_id', 'date', 'primary_ndvi_true']
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def parse_args() -> argparse.Namespace:
    """Разбирает пути и необязательную ожидаемую контрольную сумму."""
    parser = argparse.ArgumentParser(description='Проверка NDVI submission')
    parser.add_argument('--test', type=Path, required=True)
    parser.add_argument('--submission', type=Path, required=True)
    parser.add_argument('--expected-sha256')
    return parser.parse_args()


def main() -> None:
    """Завершает работу ошибкой при любом нарушении формата платформы."""
    args = parse_args()
    raw_header = args.submission.read_text(encoding='utf-8').splitlines()[0]
    if raw_header != ','.join(EXPECTED_COLUMNS):
        raise ValueError(f'Неверный заголовок: {raw_header!r}')

    test = pd.read_csv(args.test, parse_dates=['date'])
    submission = pd.read_csv(args.submission, dtype={'anon_polygon_id': str, 'date': str})
    if submission.columns.tolist() != EXPECTED_COLUMNS:
        raise ValueError(f'Неверные колонки: {submission.columns.tolist()}')
    if submission.isna().any().any():
        raise ValueError('В submission есть пустые значения или NaN')
    if submission.duplicated(['anon_polygon_id', 'date']).any():
        raise ValueError('В submission есть повторяющиеся ключи')
    if not submission['date'].map(lambda value: bool(DATE_PATTERN.fullmatch(value))).all():
        raise ValueError('Дата должна иметь формат YYYY-MM-DD')
    values = pd.to_numeric(submission['primary_ndvi_true'], errors='coerce').to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError('Предсказания должны быть конечными числами')

    expected = test.loc[test['is_synthetic_gap'].astype(bool), ['anon_polygon_id', 'date']].copy()
    expected['date'] = expected['date'].dt.strftime('%Y-%m-%d')
    expected = expected.reset_index(drop=True)
    actual = submission[['anon_polygon_id', 'date']].reset_index(drop=True)
    if not actual.equals(expected):
        raise ValueError('Состав или порядок ключей не совпадает с hidden-строками test')

    digest = hashlib.sha256(args.submission.read_bytes()).hexdigest().upper()
    if args.expected_sha256 and digest != args.expected_sha256.upper():
        raise ValueError(f'SHA-256 не совпал: {digest}')
    print(
        f'OK: rows={len(submission)}, columns={EXPECTED_COLUMNS}, '
        f'min={values.min():.10f}, max={values.max():.10f}, SHA256={digest}'
    )


if __name__ == '__main__':
    main()

