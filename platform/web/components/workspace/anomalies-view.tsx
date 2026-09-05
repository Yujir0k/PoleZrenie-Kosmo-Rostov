'use client';

import {
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Eye,
  Search,
  ShieldCheck,
  UserRoundCheck,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  loadApiAlertValidation,
  loadApiAttention,
  patchApiAlert,
} from '@/lib/api';
import type {
  AlertLifecycleState,
  AlertValidation,
  AttentionItem,
  FieldRecord,
  RiskState,
} from '@/lib/types';
import { AlertStatusSelect } from './status-select';

interface AnomaliesViewProps {
  fields: FieldRecord[];
  onOpenField: (fieldId: string) => void;
  onAttentionChange?: (items: AttentionItem[]) => void;
}

const riskCopy: Record<RiskState, { label: string; detail: string }> = {
  confirmed_anomaly: {
    label: 'Подтверждённая аномалия',
    detail: 'Устойчивое отклонение ниже нормы',
  },
  early_risk: {
    label: 'Ранний риск',
    detail: 'Есть признаки возможного выхода за норму',
  },
  watch: {
    label: 'Наблюдать',
    detail: 'Слабый сигнал — нужно следить за следующей сценой',
  },
  normal: { label: 'В норме', detail: 'Достоверного негативного сигнала нет' },
  insufficient_data: {
    label: 'Недостаточно данных',
    detail: 'Для оценки нужны измерения и минимум 3 прошлых сезона',
  },
};
export default function AnomaliesView({
  fields,
  onOpenField,
  onAttentionChange,
}: AnomaliesViewProps) {
  const [scope, setScope] = useState<'attention' | 'all' | 'closed'>(
    'attention',
  );
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<AttentionItem[]>([]);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>(
    'loading',
  );
  const [busy, setBusy] = useState('');
  const [validation, setValidation] = useState<AlertValidation | null>(null);
  const reload = useCallback(() => {
    setLoadState('loading');
    Promise.all([loadApiAttention(), loadApiAlertValidation()])
      .then(([rows, metrics]) => {
        setItems(rows);
        onAttentionChange?.(rows);
        setValidation(metrics);
        setLoadState('ready');
      })
      .catch(() => {
        setItems([]);
        setValidation(null);
        setLoadState('error');
      });
  }, [onAttentionChange]);
  useEffect(() => {
    queueMicrotask(reload);
  }, [fields, reload]);
  const visible = useMemo(
    () =>
      items.filter((item) => {
        const lifecycle = item.signal?.workflow.state;
        const matchesScope =
          scope === 'all' ||
          (scope === 'closed'
            ? lifecycle === 'closed' || lifecycle === 'rejected'
            : item.riskState !== 'normal' &&
              item.riskState !== 'insufficient_data' &&
              lifecycle !== 'closed' &&
              lifecycle !== 'rejected');
        return (
          matchesScope &&
          item.fieldName.toLowerCase().includes(query.toLowerCase())
        );
      }),
    [items, query, scope],
  );
  const counts = {
    critical: items.filter((item) => item.riskState === 'confirmed_anomaly')
      .length,
    early: items.filter((item) => item.riskState === 'early_risk').length,
    watch: items.filter((item) => item.riskState === 'watch').length,
    normal: items.filter((item) => item.riskState === 'normal').length,
  };
  const activeCount = counts.critical + counts.early;
  const signalWord =
    activeCount % 10 === 1 && activeCount % 100 !== 11
      ? 'сигнал'
      : activeCount % 10 >= 2 &&
          activeCount % 10 <= 4 &&
          (activeCount % 100 < 12 || activeCount % 100 > 14)
        ? 'сигнала'
        : 'сигналов';
  const setLifecycle = async (
    item: AttentionItem,
    state: AlertLifecycleState,
  ) => {
    if (!item.signal) return;
    setBusy(item.signal.id);
    try {
      await patchApiAlert(item.signal.id, item.fieldId, { state });
      const next = items.map((entry) =>
        entry.signal && entry.signal.id === item.signal?.id
          ? {
              ...entry,
              signal: {
                ...entry.signal,
                workflow: { ...entry.signal.workflow, state },
              },
            }
          : entry,
      );
      setItems(next);
      onAttentionChange?.(next);
    } finally {
      setBusy('');
    }
  };

  return (
    <section className="wide-view attention-view">
      <header className="wide-header">
        <div>
          <p className="eyebrow">Рабочий день агронома начинается здесь</p>
          <h1>Центр внимания</h1>
          <span>
            Поля уже отсортированы по приоритету. Откройте сигнал, проверьте
            зоны на карте и зафиксируйте результат выезда.
          </span>
        </div>
        <div className="period-button">
          <CalendarDays size={17} />
          На сегодня
        </div>
      </header>
      <div className="risk-overview">
        <div className="risk-main">
          <div className="risk-ring">
            <strong>{activeCount}</strong>
            <span>{signalWord}</span>
          </div>
          <div>
            <span>Требуют решения</span>
            <strong>
              {counts.critical
                ? 'Есть подтверждённые отклонения'
                : counts.early
                  ? 'Есть ранние риски'
                  : 'Критических сигналов нет'}
            </strong>
            <small>
              Площадь поражения показывается только после пиксельного расчёта
            </small>
          </div>
        </div>
        <div className="risk-stat critical">
          <CircleAlert size={19} />
          <div>
            <strong>{counts.critical}</strong>
            <span>Аномалия</span>
          </div>
        </div>
        <div className="risk-stat warning">
          <Clock3 size={19} />
          <div>
            <strong>{counts.early + counts.watch}</strong>
            <span>Ранний контроль</span>
          </div>
        </div>
        <div className="risk-stat normal">
          <ShieldCheck size={19} />
          <div>
            <strong>{counts.normal}</strong>
            <span>В норме</span>
          </div>
        </div>
      </div>
      <div className="attention-guide" aria-label="Как работать с сигналом">
        <div className="is-current">
          <b>1</b>
          <span>
            <strong>Выберите сигнал</strong>
            <small>Самый важный — первым</small>
          </span>
        </div>
        <ArrowRight size={17} />
        <div>
          <b>2</b>
          <span>
            <strong>Откройте поле</strong>
            <small>Проверьте дату и зону</small>
          </span>
        </div>
        <ArrowRight size={17} />
        <div>
          <b>3</b>
          <span>
            <strong>Закройте проверку</strong>
            <small>Отметьте результат осмотра</small>
          </span>
        </div>
      </div>
      <div className="validation-strip">
        <strong>Проверяемость сигналов</strong>
        {validation?.precision != null ? (
          <>
            <span>
              Подтверждено агрономом: {(validation.precision * 100).toFixed(0)}%
            </span>
            <span>
              Ложные тревоги:{' '}
              {((validation.falseAlarmRate ?? 0) * 100).toFixed(0)}%
            </span>
          </>
        ) : (
          <span>
            Метрики появятся после подтверждения или отклонения первых выездов
          </span>
        )}
        <small>
          Recall и упреждение не подменяются оценкой: для них пока нет полевой
          разметки.
        </small>
      </div>
      <div className="wide-toolbar">
        <label>
          <Search size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Найти поле"
          />
        </label>
        <div className="segmented">
          <button
            className={scope === 'attention' ? 'is-active' : ''}
            onClick={() => setScope('attention')}
          >
            Требуют внимания
          </button>
          <button
            className={scope === 'all' ? 'is-active' : ''}
            onClick={() => setScope('all')}
          >
            Все поля
          </button>
          <button
            className={scope === 'closed' ? 'is-active' : ''}
            onClick={() => setScope('closed')}
          >
            Закрытые
          </button>
        </div>
      </div>
      <div className="attention-list">
        {visible.map((item) => {
          const signal = item.signal;
          const copy = riskCopy[item.riskState];
          return (
            <article
              key={item.fieldId}
              className={`attention-card ${item.riskState}`}
            >
              <header>
                <span className="attention-state">
                  <i />
                  {copy.label}
                </span>
                <span>
                  {signal
                    ? new Intl.DateTimeFormat('ru-RU', {
                        day: 'numeric',
                        month: 'long',
                      }).format(new Date(`${signal.asOf}T12:00:00`))
                    : '—'}
                </span>
              </header>
              <div className="attention-main">
                <div>
                  <h3>{item.fieldName}</h3>
                  <p>{copy.detail}</p>
                </div>
                <div
                  className="risk-score"
                  title="Приоритет объединяет силу отклонения, устойчивость тренда, погоду и качество данных"
                >
                  <strong>{signal ? signal.riskScore : '—'}</strong>
                  <span>приоритет / 100</span>
                </div>
              </div>
              {signal ? (
                <div className="evidence-grid">
                  <div>
                    <span>Наблюдение</span>
                    <p>{signal.observation}</p>
                  </div>
                  <div>
                    <span>Тренд</span>
                    <p>
                      {signal.projectedRobustZ14d != null
                        ? signal.projectedRobustZ14d <= -2
                          ? 'Отрицательная динамика усиливается'
                          : signal.projectedRobustZ14d <= -1.2
                            ? 'Падение продолжается — нужен ранний контроль'
                            : 'Динамика остаётся в безопасном диапазоне'
                        : (signal.context[0] ??
                          'Подтверждающий контекст отсутствует')}
                    </p>
                  </div>
                  <div>
                    <span>Возможная причина</span>
                    <p>{signal.hypothesis}</p>
                  </div>
                  <div>
                    <span>Следующий шаг</span>
                    <p>{signal.recommendation}</p>
                  </div>
                </div>
              ) : (
                <div className="attention-no-data">
                  Анализ ещё не дал достаточной истории для честной оценки.
                </div>
              )}
              <footer>
                <div className="confidence-line">
                  <span>
                    Доверие {signal ? `${signal.confidence}%` : 'не рассчитано'}
                  </span>
                  {signal ? (
                    <span>
                      {signal.referenceSeasons} исторических сезона ·{' '}
                      {signal.observationSource}
                    </span>
                  ) : null}
                </div>
                <div className="attention-actions">
                  {signal ? (
                    <AlertStatusSelect
                      compact
                      value={signal.workflow.state}
                      disabled={busy === signal.id}
                      onChange={(state) => void setLifecycle(item, state)}
                    />
                  ) : null}
                  <button onClick={() => onOpenField(item.fieldId)}>
                    {signal?.workflow.state === 'verified' ? (
                      <CheckCircle2 size={16} />
                    ) : signal?.workflow.state === 'assigned' ? (
                      <UserRoundCheck size={16} />
                    ) : (
                      <Eye size={16} />
                    )}
                    Разобрать на карте
                    <ArrowRight size={16} />
                  </button>
                </div>
              </footer>
            </article>
          );
        })}
        {loadState === 'loading' ? (
          <div className="empty-wide">
            Считаем сигналы по реальным наблюдениям…
          </div>
        ) : null}
        {loadState === 'error' ? (
          <div className="empty-wide">
            <CircleAlert size={26} />
            <strong>Не удалось рассчитать очередь</strong>
            <button onClick={reload}>Повторить</button>
          </div>
        ) : null}
        {loadState === 'ready' && !visible.length ? (
          <div className="empty-wide">
            <ShieldCheck size={28} />
            <strong>В этой группе сигналов нет</strong>
            <span>
              Это не скрывает поля без данных — они доступны во вкладке «Все
              поля».
            </span>
          </div>
        ) : null}
      </div>
    </section>
  );
}
