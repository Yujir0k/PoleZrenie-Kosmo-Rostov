"""Портативная точка запуска подтверждённой модели v8."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'src'
sys.path.insert(0, str(SRC))

import released_context_core_benchmark as pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Разбирает пути к данным и каталогу результатов."""
    parser = argparse.ArgumentParser(description='NDVI v8 batch-инференс')
    parser.add_argument('--train-zip', type=Path, default=ROOT / 'data' / 'train_dataset.zip')
    parser.add_argument('--test', type=Path, default=ROOT / 'data' / 'New_test.csv')
    parser.add_argument(
        '--old-test', type=Path, default=ROOT / 'data' / 'old_private_features.csv'
    )
    parser.add_argument(
        '--old-ground-truth', type=Path, default=ROOT / 'data' / 'old_ground_truth.zip'
    )
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'work')
    parser.add_argument('--output', type=Path, default=ROOT / 'output' / 'submission.csv')
    parser.add_argument(
        '--rebuild-features',
        action='store_true',
        help='Пересчитать признаки, даже если кэш уже существует.',
    )
    return parser.parse_args()


def main() -> None:
    """Подставляет пользовательские пути и запускает исходный конвейер v8."""
    args = parse_args()
    for path in (args.train_zip, args.test, args.old_test, args.old_ground_truth):
        if not path.is_file():
            raise FileNotFoundError(f'Не найден обязательный файл: {path}')

    pipeline.TRAIN_ZIP = args.train_zip.resolve()
    pipeline.NEW_TEST = args.test.resolve()
    pipeline.OLD_TEST = args.old_test.resolve()
    pipeline.GROUND_TRUTH = args.old_ground_truth.resolve()

    pipeline_args = [
        'released_context_core_benchmark.py',
        '--private',
        str(args.test.resolve()),
        '--work-dir',
        str(args.work_dir.resolve()),
        '--output',
        str(args.output.resolve()),
        '--fixed-gated-weight',
        '0.80',
    ]
    if args.rebuild_features:
        pipeline_args.append('--rebuild-features')
    original_argv = sys.argv
    try:
        sys.argv = pipeline_args
        pipeline.main()
    finally:
        sys.argv = original_argv


if __name__ == '__main__':
    main()
