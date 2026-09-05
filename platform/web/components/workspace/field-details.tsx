'use client';

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  CloudSun,
  Database,
  Image as ImageIcon,
  MapPinCheck,
  Pencil,
  RefreshCw,
  Satellite,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { pointOnFeature, polygon } from '@turf/turf';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  createApiInspectionPoint,
  deleteApiInspectionPoint,
  loadApiRiskProfile,
  loadApiSpatialRisk,
  loadApiTimeseries,
  patchApiAlert,
  patchApiInspectionPoint,
} from '@/lib/api';
import type {
  AlertLifecycleState,
  FieldRecord,
  InspectionPoint,
  RiskSignal,
  SceneRecord,
  SpatialRiskResult,
  TimeseriesPoint,
} from '@/lib/types';
import { AlertStatusSelect, InspectionStatusSelect } from './status-select';

interface FieldDetailsProps {
  field: FieldRecord;
  season: number;
  selectedDate: string;
  selectedScene: SceneRecord | null;
  scenes: SceneRecord[];
  inspectionPoints: InspectionPoint[];
  focusedInspectionId: string;
  activeTab: string;
  onActiveTabChange: (tab: string) => void;
  spatialRisk: SpatialRiskResult | null;
  onSpatialRisk: (result: SpatialRiskResult | null) => void;
  onInspectionCreated: (point: InspectionPoint) => void;
  onInspectionUpdated: (point: InspectionPoint) => void;
  onInspectionDeleted: (id: string) => void;
  onFocusInspection: (point: InspectionPoint) => void;
  onSceneSelect: (scene: SceneRecord) => void;
  onAnalysis: () => void;
  onRename: (name: string) => void;
  onClose: () => void;
  onRefresh: () => void;
  analysing: boolean;
  analysisProgress: { progress: number; stage: string } | null;
  width: number;
  onResizeStart: (event: ReactPointerEvent<HTMLElement>) => void;
}

const closeEnough = (left: [number, number], right: [number, number]) =>
  Math.abs(left[0] - right[0]) < 0.00003 &&
  Math.abs(left[1] - right[1]) < 0.00003;

const inspectionStatusLabel: Record<InspectionPoint['status'], string> = {
  planned: 'Запланирована',
  visited: 'Посещена',
  confirmed: 'Проблема подтверждена',
  rejected: 'Проблема не найдена',
};

export default function FieldDetails({
  field,
  season,
  selectedDate,
  selectedScene,
  scenes,
  inspectionPoints,
  focusedInspectionId,
  activeTab,
  onActiveTabChange,
  spatialRisk,
  onSpatialRisk,
  onInspectionCreated,
  onInspectionUpdated,
  onInspectionDeleted,
  onFocusInspection,
  onSceneSelect,
  onAnalysis,
  onRename,
  onClose,
  onRefresh,
  analysing,
  analysisProgress,
  width,
  onResizeStart,
}: FieldDetailsProps) {
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(field.name);
  const [history, setHistory] = useState<TimeseriesPoint[]>([]);
  const [relatedState, setRelatedState] = useState<
    'loading' | 'ready' | 'empty' | 'error'
  >('loading');
  const [risk, setRisk] = useState<RiskSignal | null>(null);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [spatialState, setSpatialState] = useState<
    'idle' | 'loading' | 'error'
  >('idle');
  const [spatialError, setSpatialError] = useState('');
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [editingInspectionId, setEditingInspectionId] = useState('');
  const [inspectionTitleDraft, setInspectionTitleDraft] = useState('');
  const [inspectionNoteDraft, setInspectionNoteDraft] = useState('');
  const [deleteInspectionId, setDeleteInspectionId] = useState('');
  const [inspectionBusy, setInspectionBusy] = useState(false);
  const hasLiveData = field.dataProvider === 'gee';
  const liveValue = (value: number | undefined | null, suffix = '') =>
    analysing || !hasLiveData || value == null
      ? '—'
      : `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}${suffix}`;
  const selectedPoint = history.find((point) => point.date === selectedDate);
  const selectedNdvi =
    selectedScene?.ndvi ??
    (selectedDate === field.sceneDate ? field.ndvi : null);
  const normValue = selectedPoint?.robustMedian ?? selectedPoint?.climateMean;
  const selectedDelta =
    selectedNdvi != null && normValue != null && Math.abs(normValue) >= 0.02
      ? (100 * (selectedNdvi - normValue)) / Math.abs(normValue)
      : null;
  const focusedInspection = inspectionPoints.find(
    (point) => point.id === focusedInspectionId,
  );
  const sceneDateLabel = selectedDate
    ? new Intl.DateTimeFormat('ru-RU', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      }).format(new Date(`${selectedDate}T12:00:00`))
    : 'дата не выбрана';
  const sparkline = useMemo(() => {
    const values = history
      .map((point) => point.restored)
      .filter(Number.isFinite);
    if (values.length < 2)
      return { path: '', selected: null as null | { x: number; y: number } };
    const min = Math.min(...values),
      max = Math.max(...values),
      span = Math.max(0.05, max - min);
    const coordinates = values.map((value, index) => ({
      x: 3 + (index * 124) / (values.length - 1),
      y: 48 - ((value - min) * 38) / span,
    }));
    const selectedIndex = history.findIndex(
      (point) => point.date === selectedDate,
    );
    return {
      path: coordinates
        .map(
          (point, index) =>
            `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`,
        )
        .join(' '),
      selected: selectedIndex >= 0 ? coordinates[selectedIndex] : null,
    };
  }, [history, selectedDate]);
  const fieldBounds = useMemo(() => {
    const ring = field.geometry.coordinates[0] ?? [];
    const xs = ring.map((coordinate) => coordinate[0]),
      ys = ring.map((coordinate) => coordinate[1]);
    return {
      west: Math.min(...xs),
      east: Math.max(...xs),
      south: Math.min(...ys),
      north: Math.max(...ys),
    };
  }, [field.geometry]);
  const describeLocation = (longitude: number, latitude: number) => {
    const centerX = (fieldBounds.west + fieldBounds.east) / 2,
      centerY = (fieldBounds.south + fieldBounds.north) / 2;
    const dx =
        (longitude - centerX) /
        Math.max(0.00001, fieldBounds.east - fieldBounds.west),
      dy =
        (latitude - centerY) /
        Math.max(0.00001, fieldBounds.north - fieldBounds.south);
    const horizontal = dx > 0.15 ? 'восточная' : dx < -0.15 ? 'западная' : '';
    const vertical = dy > 0.15 ? 'северная' : dy < -0.15 ? 'южная' : '';
    return vertical && horizontal
      ? `${vertical}-${horizontal} часть`
      : vertical
        ? `${vertical} часть`
        : horizontal
          ? `${horizontal} часть`
          : 'центр поля';
  };
  const trendCopy =
    risk?.projectedRobustZ14d == null
      ? 'Тренд пока не определён'
      : risk.projectedRobustZ14d <= -2
        ? 'Отрицательная динамика усиливается'
        : risk.projectedRobustZ14d <= -1.2
          ? 'Падение продолжается — нужен ранний контроль'
          : 'Динамика остаётся в нормальном диапазоне';

  const saveName = () => {
    if (draftName.trim()) onRename(draftName.trim());
    setEditing(false);
  };
  const beginDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest('button,input')) return;
    event.preventDefault();
    const startX = event.clientX,
      startY = event.clientY,
      startPosition = position;
    const move = (nextEvent: PointerEvent) =>
      setPosition({
        x: startPosition.x + nextEvent.clientX - startX,
        y: startPosition.y + nextEvent.clientY - startY,
      });
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      document.body.classList.remove('is-dragging-panel');
    };
    document.body.classList.add('is-dragging-panel');
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop, { once: true });
  };
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) setRelatedState('loading');
    });
    (hasLiveData ? loadApiTimeseries(field.id, season) : Promise.resolve([]))
      .then((next) => {
        if (active) {
          setHistory(next);
          setRelatedState(scenes.length || next.length ? 'ready' : 'empty');
        }
      })
      .catch(() => {
        if (active) {
          setHistory([]);
          setRelatedState('error');
        }
      });
    return () => {
      active = false;
    };
  }, [field.id, field.updatedAt, hasLiveData, season, scenes.length]);
  useEffect(() => {
    let active = true;
    if (!hasLiveData) {
      queueMicrotask(() => active && setRisk(null));
      return () => {
        active = false;
      };
    }
    loadApiRiskProfile(field.id, selectedDate || undefined)
      .then((signal) => {
        if (active) setRisk(signal);
      })
      .catch(() => {
        if (active) setRisk(null);
      });
    return () => {
      active = false;
    };
  }, [field.id, field.updatedAt, hasLiveData, selectedDate]);
  const setWorkflow = async (state: AlertLifecycleState) => {
    if (!risk) return;
    setWorkflowBusy(true);
    try {
      await patchApiAlert(risk.id, field.id, { state });
      setRisk({ ...risk, workflow: { ...risk.workflow, state } });
    } finally {
      setWorkflowBusy(false);
    }
  };
  const beginInspectionEdit = (point: InspectionPoint) => {
    setEditingInspectionId(point.id);
    setInspectionTitleDraft(point.title);
    setInspectionNoteDraft(point.note ?? '');
    onFocusInspection(point);
  };
  const saveInspectionEdit = async () => {
    if (!editingInspectionId || !inspectionTitleDraft.trim()) return;
    setInspectionBusy(true);
    try {
      const updated = await patchApiInspectionPoint(editingInspectionId, {
        title: inspectionTitleDraft.trim(),
        note: inspectionNoteDraft.trim() || null,
      });
      onInspectionUpdated(updated);
      setEditingInspectionId('');
    } finally {
      setInspectionBusy(false);
    }
  };
  const removeInspection = async () => {
    if (!deleteInspectionId) return;
    setInspectionBusy(true);
    try {
      await deleteApiInspectionPoint(deleteInspectionId);
      onInspectionDeleted(deleteInspectionId);
      setDeleteInspectionId('');
      if (editingInspectionId === deleteInspectionId)
        setEditingInspectionId('');
    } finally {
      setInspectionBusy(false);
    }
  };
  const createInspection = async () => {
    if (!risk) return null;
    const center = pointOnFeature(polygon(field.geometry.coordinates)).geometry
      .coordinates as [number, number];
    const existing = inspectionPoints.find((point) =>
      closeEnough([point.longitude, point.latitude], center),
    );
    if (existing) {
      onFocusInspection(existing);
      return existing;
    }
    const point = await createApiInspectionPoint({
      fieldId: field.id,
      alertId: risk.id,
      title: `Осмотр: ${field.name}`,
      note: 'Точка первичного осмотра рассчитана по геометрии поля; это не локализованный спутниковый очаг.',
      longitude: center[0],
      latitude: center[1],
    });
    onInspectionCreated(point);
    onFocusInspection(point);
    return point;
  };
  const createTask = async () => {
    if (inspectionPoints[0]) onFocusInspection(inspectionPoints[0]);
    else await createInspection();
    if (risk?.workflow.state === 'detected') await setWorkflow('assigned');
  };
  const calculateSpatialRisk = async () => {
    if (!selectedDate) return;
    setSpatialState('loading');
    setSpatialError('');
    try {
      onSpatialRisk(await loadApiSpatialRisk(field.id, selectedDate));
      setSpatialState('idle');
    } catch (reason: unknown) {
      setSpatialState('error');
      setSpatialError(
        reason instanceof Error
          ? reason.message
          : 'Пиксельный расчёт не выполнен',
      );
    }
  };
  const createCandidateInspection = async (
    candidate: SpatialRiskResult['inspectionCandidates'][number],
  ) => {
    if (!risk) return;
    const existing = inspectionPoints.find((point) =>
      closeEnough(
        [point.longitude, point.latitude],
        [candidate.longitude, candidate.latitude],
      ),
    );
    if (existing) {
      onFocusInspection(existing);
      return;
    }
    const point = await createApiInspectionPoint({
      fieldId: field.id,
      alertId: risk.id,
      title: candidate.title,
      note: `Кандидат получен из пикселей Sentinel-2 ниже исторической нижней границы ${spatialRisk?.threshold.toFixed(2)}.`,
      longitude: candidate.longitude,
      latitude: candidate.latitude,
    });
    onInspectionCreated(point);
    onFocusInspection(point);
  };

  return (
    <aside
      className="detail-panel"
      style={
        {
          '--detail-width': `${width}px`,
          transform: `translate(${position.x}px,${position.y}px)`,
        } as CSSProperties
      }
    >
      <hr
        className="detail-resize-handle"
        aria-label="Изменить ширину панели данных"
        aria-orientation="vertical"
        onPointerDown={onResizeStart}
      />
      <header className="detail-titlebar" onPointerDown={beginDrag}>
        <span
          className={`health-badge ${!hasLiveData ? 'pending' : risk?.riskState === 'confirmed_anomaly' ? 'critical' : risk?.riskState === 'early_risk' || risk?.riskState === 'watch' ? 'warning' : 'normal'}`}
        >
          <i />
          {!hasLiveData
            ? 'Нет анализа'
            : risk?.riskState === 'confirmed_anomaly'
              ? 'Подтверждённая аномалия'
              : risk?.riskState === 'early_risk'
                ? 'Ранний риск'
                : risk?.riskState === 'watch'
                  ? 'Наблюдать'
                  : risk?.riskState === 'insufficient_data'
                    ? 'Недостаточно истории'
                    : selectedDate
                      ? 'На выбранную дату риск не выявлен'
                      : 'Дата не выбрана'}
        </span>
        <div className="detail-header-actions">
          <button
            onClick={onRefresh}
            className={analysing ? 'is-spinning' : ''}
            aria-label="Обновить анализ"
          >
            <RefreshCw size={17} />
          </button>
          <button onClick={onClose} aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>
      </header>
      <div className="detail-heading">
        {editing ? (
          <div className="rename-row">
            <input
              aria-label="Новое название поля"
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && saveName()}
            />
            <button onClick={saveName} aria-label="Сохранить название">
              <Check size={17} />
            </button>
          </div>
        ) : (
          <div className="heading-with-action">
            <h2>{field.name}</h2>
            <button
              onClick={() => {
                setDraftName(field.name);
                setEditing(true);
              }}
              aria-label="Переименовать"
            >
              <Pencil size={14} />
            </button>
          </div>
        )}
        <p>
          {field.crop} ·{' '}
          {field.areaHa.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}{' '}
          га
        </p>
        <span
          className={`field-data-source ${hasLiveData ? 'is-live' : 'is-pending'}`}
          title={
            risk?.quality.causal
              ? 'Расчёт произведён строго по данным, доступным на дату события.'
              : ''
          }
        >
          {hasLiveData && selectedScene
            ? `GEE · ${selectedScene.satellite} · ${sceneDateLabel}`
            : hasLiveData
              ? 'Выберите спутниковую сцену'
              : 'Данные ещё не рассчитаны'}
        </span>
      </div>
      {analysing ? (
        <div className="analysis-progress">
          <span>
            <RefreshCw size={15} />
            {analysisProgress?.stage ?? 'Получаем свежие данные'}
          </span>
          <div>
            <i style={{ width: `${analysisProgress?.progress ?? 5}%` }} />
          </div>
          <small>{analysisProgress?.progress ?? 5}%</small>
        </div>
      ) : null}
      <nav className="field-journey" aria-label="Работа с полем">
        <button
          className={activeTab === 'summary' ? 'is-active' : ''}
          onClick={() => onActiveTabChange('summary')}
        >
          <b>1</b>
          <span>
            Понять<strong>Состояние</strong>
          </span>
        </button>
        <button
          className={activeTab === 'inspection' ? 'is-active' : ''}
          onClick={() => onActiveTabChange('inspection')}
        >
          <b>2</b>
          <span>
            Проверить<strong>Осмотр</strong>
          </span>
        </button>
        <button onClick={onAnalysis}>
          <b>3</b>
          <span>
            Сравнить<strong>Динамика</strong>
          </span>
        </button>
      </nav>
      <Tabs
        value={activeTab}
        onValueChange={onActiveTabChange}
        className="detail-tabs"
      >
        <TabsList className="detail-tabs-list">
          <TabsTrigger value="summary">Обзор</TabsTrigger>
          <TabsTrigger value="inspection">
            Осмотр
            {inspectionPoints.length ? <i>{inspectionPoints.length}</i> : null}
          </TabsTrigger>
          <TabsTrigger value="scenes">Снимки</TabsTrigger>
          <TabsTrigger value="data">Данные</TabsTrigger>
        </TabsList>
        <TabsContent value="summary" className="detail-tab-content">
          <section className="field-story-block diagnosis-block">
            <header>
              <span>1</span>
              <div>
                <small>Что происходит</small>
                <strong>Состояние поля</strong>
              </div>
            </header>
            <section className="ndvi-summary">
              <div>
                <span>NDVI · {sceneDateLabel}</span>
                <strong>
                  {analysing || !hasLiveData || selectedNdvi == null
                    ? '—'
                    : selectedNdvi.toFixed(2).replace('.', ',')}
                </strong>
                <small
                  className={(selectedDelta ?? 0) < 0 ? 'negative' : 'positive'}
                >
                  {selectedDelta == null
                    ? 'Недостаточно истории для сравнения'
                    : `${Math.abs(selectedDelta).toFixed(0)}% ${selectedDelta < 0 ? 'ниже' : 'выше'} сезонной нормы`}
                </small>
              </div>
              {sparkline.path ? (
                <button
                  className="mini-curve chart-entry"
                  onClick={onAnalysis}
                  aria-label="Открыть детальный график NDVI и погоды"
                >
                  <span className="mini-chart-title">Динамика NDVI</span>
                  <svg viewBox="0 0 130 54">
                    <path
                      d={sparkline.path}
                      fill="none"
                      stroke="#2f7d4a"
                      strokeWidth="3"
                      strokeLinecap="round"
                    />
                    {sparkline.selected ? (
                      <>
                        <line
                          x1={sparkline.selected.x}
                          x2={sparkline.selected.x}
                          y1="4"
                          y2="51"
                          stroke="#e09b32"
                          strokeDasharray="3 3"
                        />
                        <circle
                          cx={sparkline.selected.x}
                          cy={sparkline.selected.y}
                          r="4.5"
                          fill="#fffef8"
                          stroke="#e09b32"
                          strokeWidth="3"
                        />
                      </>
                    ) : null}
                  </svg>
                  <span>
                    Выбранная дата выделена <ArrowRight size={14} />
                  </span>
                </button>
              ) : (
                <div className="mini-curve-empty">Ряд не рассчитан</div>
              )}
            </section>
            <div className="metric-strip">
              <div>
                <CloudSun size={18} />
                <span>
                  <strong>
                    {liveValue(selectedScene?.temperatureC, ' °C')}
                  </strong>
                  <small>Температура</small>
                </span>
              </div>
              <div>
                <Database size={18} />
                <span>
                  <strong>
                    {liveValue(selectedScene?.precipitation7dMm, ' мм')}
                  </strong>
                  <small>Осадки, 7 дней</small>
                </span>
              </div>
              <div>
                <Satellite size={18} />
                <span>
                  <strong>{liveValue(selectedScene?.ndwi)}</strong>
                  <small>Влага NDWI</small>
                </span>
              </div>
            </div>
            {risk ? (
              <div className="plain-diagnosis">
                <div>
                  <span>Вывод</span>
                  <strong>{trendCopy}</strong>
                </div>
                <div>
                  <span>Возможная причина</span>
                  <strong>{risk.hypothesis}</strong>
                </div>
                <div>
                  <span>Следующий шаг</span>
                  <strong>{risk.recommendation}</strong>
                </div>
                <details>
                  <summary>
                    Почему система так решила · риск {risk.riskScore}/100
                  </summary>
                  <p>{risk.observation}</p>
                  {risk.context.map((line) => (
                    <p key={line}>{line}</p>
                  ))}
                </details>
                <div className="risk-trust">
                  <span>Доверие {risk.confidence}%</span>
                  <span>{risk.referenceSeasons} исторических сезона</span>
                </div>
                <div className="summary-actions">
                  <button onClick={onAnalysis}>
                    <Activity size={16} />
                    Открыть понятный график
                  </button>
                  <button onClick={() => onActiveTabChange('inspection')}>
                    Перейти к осмотру
                    <ArrowRight size={16} />
                  </button>
                </div>
              </div>
            ) : relatedState === 'error' ? (
              <div className="normal-callout">
                <span>
                  <AlertTriangle size={18} />
                </span>
                <div>
                  <strong>Проверка риска не завершилась</strong>
                  <p>Сервер не вернул результат. Повторите анализ поля.</p>
                </div>
              </div>
            ) : hasLiveData ? (
              <div className="normal-callout">
                <span>
                  <Sparkles size={18} />
                </span>
                <div>
                  <strong>Для этой даты оценка риска недоступна</strong>
                  <p>Нужна фактическая сцена и минимум три прошлых сезона.</p>
                </div>
              </div>
            ) : (
              <div className="normal-callout">
                <span>
                  <Database size={18} />
                </span>
                <div>
                  <strong>Анализ ещё не выполнен</strong>
                  <p>
                    Запустите сбор. До его завершения показатели и выводы не
                    отображаются.
                  </p>
                </div>
              </div>
            )}
          </section>
          {!risk ? (
            <button className="analysis-button large" onClick={onRefresh}>
              Запустить сбор данных <Activity size={17} />
            </button>
          ) : null}
        </TabsContent>
        <TabsContent
          value="inspection"
          className="detail-tab-content inspection-workspace"
        >
          <header className="inspection-intro">
            <div>
              <small>Рабочий маршрут</small>
              <h3>Полевой осмотр</h3>
              <p>
                Найдите локальные зоны, создайте точки обхода и после выезда
                отметьте результат.
              </p>
            </div>
            {risk ? (
              <span>
                {
                  inspectionPoints.filter((point) => point.status !== 'planned')
                    .length
                }
                /{inspectionPoints.length} проверено
              </span>
            ) : null}
          </header>
          <div
            className="inspection-path"
            aria-label="Как появляются точки осмотра"
          >
            <span>
              <b>1</b> Найти зоны
            </span>
            <ArrowRight size={14} />
            <span>
              <b>2</b> Добавить точки
            </span>
            <ArrowRight size={14} />
            <span>
              <b>3</b> Записать результат
            </span>
          </div>
          {risk ? (
            <>
              <section className="field-story-block inspection-section">
                <header>
                  <span>1</span>
                  <div>
                    <small>Где смотреть</small>
                    <strong>Зоны, отстающие от нормы</strong>
                  </div>
                </header>
                <div className="spatial-risk-actions">
                  <button
                    className="spatial-risk-action"
                    disabled={!selectedDate || spatialState === 'loading'}
                    onClick={() => void calculateSpatialRisk()}
                  >
                    {spatialState === 'loading'
                      ? 'Сравниваем пиксели Sentinel‑2…'
                      : spatialRisk
                        ? 'Пересчитать зоны'
                        : 'Найти локальные зоны для проверки'}
                  </button>
                  {spatialRisk ? (
                    <button
                      className="spatial-risk-reset"
                      onClick={() => onSpatialRisk(null)}
                    >
                      Вернуть обычную карту
                    </button>
                  ) : null}
                </div>
                <p className="spatial-explainer">
                  Оранжевым на карте будут показаны только худшие пиксели внутри
                  поля — не диагноз и не всё поле.
                </p>
                {spatialState === 'error' ? (
                  <p className="spatial-error">{spatialError}</p>
                ) : null}
                {spatialRisk ? (
                  <div className="spatial-result">
                    <strong>
                      Приоритетная зона: {spatialRisk.affectedAreaHa.toFixed(1)}{' '}
                      га
                    </strong>
                    <span>
                      {spatialRisk.affectedAreaPercent == null
                        ? 'Доля от валидной площади не рассчитана'
                        : `${spatialRisk.affectedAreaPercent.toFixed(1)}% валидной площади`}{' '}
                      · Sentinel‑2 · {spatialRisk.nativeResolutionM} м ·{' '}
                      {spatialRisk.sceneDate}
                    </span>
                    <small>
                      Порог локализован по худшему квартилю поля среди пикселей
                      ниже исторической нормы.
                    </small>
                    {spatialRisk.inspectionCandidates.map(
                      (candidate, index) => (
                        <button
                          key={`${candidate.longitude}-${candidate.latitude}`}
                          onClick={() =>
                            void createCandidateInspection(candidate)
                          }
                        >
                          <MapPinCheck size={15} />
                          <span>
                            <strong>
                              Кандидат {index + 1} ·{' '}
                              {describeLocation(
                                candidate.longitude,
                                candidate.latitude,
                              )}
                            </strong>
                            <small>Добавить точку и приблизить карту</small>
                          </span>
                        </button>
                      ),
                    )}
                  </div>
                ) : (
                  <p className="inspection-empty">
                    Сначала выполните расчёт — система предложит до трёх
                    конкретных мест внутри поля.
                  </p>
                )}
              </section>
              <section className="field-story-block action-block">
                <header>
                  <span>2</span>
                  <div>
                    <small>Кто и что делает</small>
                    <strong>Задача агроному</strong>
                  </div>
                </header>
                <p>
                  Статус сигнала показывает этап работы, а статусы точек —
                  результат каждого места осмотра.
                </p>
                <div className="field-action-row">
                  <AlertStatusSelect
                    value={risk.workflow.state}
                    disabled={workflowBusy}
                    onChange={(state) => void setWorkflow(state)}
                  />
                  <button onClick={() => void createTask()}>
                    <MapPinCheck size={16} />
                    {inspectionPoints.length
                      ? 'Показать первую точку'
                      : 'Создать точку в центре'}
                  </button>
                </div>
              </section>
              <section className="field-story-block inspection-section point-list-section">
                <header>
                  <span>3</span>
                  <div>
                    <small>Что найдено на месте</small>
                    <strong>Точки обхода · {inspectionPoints.length}</strong>
                  </div>
                </header>
                {focusedInspection ? (
                  <article className="inspection-point-card">
                    <header>
                      <b>
                        Точка{' '}
                        {inspectionPoints.findIndex(
                          (point) => point.id === focusedInspection.id,
                        ) + 1}
                      </b>
                      <span
                        className={`inspection-state ${focusedInspection.status}`}
                      >
                        {inspectionStatusLabel[focusedInspection.status]}
                      </span>
                    </header>
                    <strong>{focusedInspection.title}</strong>
                    <p>
                      {focusedInspection.note ||
                        'Проверьте состояние растений и почвы в этой точке, сделайте фото и укажите результат осмотра.'}
                    </p>
                    <dl>
                      <div>
                        <dt>Где</dt>
                        <dd>
                          {describeLocation(
                            focusedInspection.longitude,
                            focusedInspection.latitude,
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt>Координаты</dt>
                        <dd>
                          {focusedInspection.latitude.toFixed(5)},{' '}
                          {focusedInspection.longitude.toFixed(5)}
                        </dd>
                      </div>
                      <div>
                        <dt>Создана</dt>
                        <dd>
                          {new Intl.DateTimeFormat('ru-RU', {
                            day: 'numeric',
                            month: 'short',
                            hour: '2-digit',
                            minute: '2-digit',
                          }).format(new Date(focusedInspection.createdAt))}
                        </dd>
                      </div>
                    </dl>
                    {editingInspectionId === focusedInspection.id ? (
                      <form
                        className="inspection-edit-form"
                        onSubmit={(event) => {
                          event.preventDefault();
                          void saveInspectionEdit();
                        }}
                      >
                        <label>
                          Название
                          <input
                            value={inspectionTitleDraft}
                            maxLength={160}
                            onChange={(event) =>
                              setInspectionTitleDraft(event.target.value)
                            }
                          />
                        </label>
                        <label>
                          Что проверить
                          <textarea
                            value={inspectionNoteDraft}
                            maxLength={2000}
                            onChange={(event) =>
                              setInspectionNoteDraft(event.target.value)
                            }
                          />
                        </label>
                        <div>
                          <button
                            type="button"
                            onClick={() => setEditingInspectionId('')}
                          >
                            Отмена
                          </button>
                          <button
                            className="is-primary"
                            disabled={
                              inspectionBusy || !inspectionTitleDraft.trim()
                            }
                          >
                            <Check size={14} /> Сохранить
                          </button>
                        </div>
                      </form>
                    ) : (
                      <div className="inspection-card-actions">
                        <button
                          onClick={() => beginInspectionEdit(focusedInspection)}
                        >
                          <Pencil size={14} /> Изменить
                        </button>
                        <button
                          className="is-danger"
                          onClick={() =>
                            setDeleteInspectionId(focusedInspection.id)
                          }
                        >
                          <Trash2 size={14} /> Удалить
                        </button>
                      </div>
                    )}
                  </article>
                ) : null}
                {inspectionPoints.length ? (
                  <div className="inspection-list">
                    {inspectionPoints.map((point, index) => (
                      <div
                        className={`inspection-row ${point.id === focusedInspectionId ? 'is-focused' : ''}`}
                        key={point.id}
                      >
                        <button
                          className="inspection-focus"
                          onClick={() => onFocusInspection(point)}
                        >
                          <b>{index + 1}</b>
                          <MapPinCheck size={15} />
                          <span>
                            <strong>
                              Точка {index + 1} · {point.title}
                            </strong>
                            <small>
                              {inspectionStatusLabel[point.status]} ·{' '}
                              {describeLocation(
                                point.longitude,
                                point.latitude,
                              )}
                            </small>
                          </span>
                        </button>
                        <InspectionStatusSelect
                          value={point.status}
                          onChange={(status) =>
                            void patchApiInspectionPoint(point.id, {
                              status,
                            }).then(onInspectionUpdated)
                          }
                        />
                        <button
                          className="inspection-row-action"
                          aria-label={`Изменить точку ${index + 1}`}
                          onClick={() => beginInspectionEdit(point)}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          className="inspection-row-action is-danger"
                          aria-label={`Удалить точку ${index + 1}`}
                          onClick={() => setDeleteInspectionId(point.id)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="inspection-empty">
                    Точек ещё нет. Найдите локальные зоны или создайте первичную
                    точку в центре поля.
                  </p>
                )}
              </section>
            </>
          ) : (
            <div className="normal-callout">
              <span>
                <Database size={18} />
              </span>
              <div>
                <strong>Сначала нужен рассчитанный сигнал</strong>
                <p>
                  Откройте дату с фактической сценой или запустите сбор данных.
                </p>
              </div>
            </div>
          )}
        </TabsContent>
        <TabsContent value="scenes" className="detail-tab-content">
          <div className="scene-heading">
            <div>
              <strong>Доступные снимки · {scenes.length}</strong>
              <span>Все реальные сцены GEE за {season} год</span>
            </div>
          </div>
          <div className="scene-list">
            {scenes.map((scene) => (
              <button
                key={scene.id}
                className={scene.id === selectedScene?.id ? 'is-active' : ''}
                onClick={() => onSceneSelect(scene)}
              >
                <span className="scene-thumb">
                  <ImageIcon size={17} />
                </span>
                <span>
                  <strong>
                    {new Intl.DateTimeFormat('ru-RU', {
                      day: 'numeric',
                      month: 'short',
                    }).format(new Date(`${scene.date}T12:00:00`))}
                  </strong>
                  <small>
                    {scene.satellite} · {scene.provider}
                  </small>
                </span>
                <span>
                  <strong>
                    {scene.ndvi == null
                      ? '—'
                      : `NDVI ${scene.ndvi.toFixed(2).replace('.', ',')}`}
                  </strong>
                  <small>
                    {scene.cloudCover == null
                      ? 'облачность не указана'
                      : `${scene.cloudCover.toFixed(0)}% облаков`}
                  </small>
                </span>
              </button>
            ))}
          </div>
          {relatedState === 'loading' ? (
            <div className="panel-empty">Загружаем список снимков…</div>
          ) : null}
          {relatedState === 'error' ? (
            <div className="panel-empty">Не удалось получить снимки.</div>
          ) : null}
          {relatedState === 'empty' ? (
            <div className="panel-empty">
              Снимков пока нет. Запустите анализ поля.
            </div>
          ) : null}
        </TabsContent>
        <TabsContent value="data" className="detail-tab-content">
          <div className="data-passport">
            <header>
              <Database size={18} />
              <div>
                <strong>Паспорт и доверие к данным</strong>
                <span>Как сформирован текущий результат</span>
              </div>
            </header>
            <dl>
              <div>
                <dt>Источник контура</dt>
                <dd>
                  {field.source === 'osm'
                    ? 'OpenStreetMap'
                    : 'Пользовательский контур'}
                </dd>
              </div>
              <div>
                <dt>Пашня WorldCover</dt>
                <dd>
                  {field.worldcoverCroplandPercent == null
                    ? 'нет расчёта'
                    : `${field.worldcoverCroplandPercent.toFixed(1)}%`}
                </dd>
              </div>
              <div>
                <dt>Текущие показатели</dt>
                <dd>{hasLiveData ? 'Google Earth Engine' : 'Не рассчитаны'}</dd>
              </div>
              <div>
                <dt>Источники</dt>
                <dd>
                  {hasLiveData ? 'Sentinel‑2 · Landsat · MODIS' : 'нет данных'}
                </dd>
              </div>
              <div>
                <dt>Погодные данные</dt>
                <dd>{hasLiveData ? 'ERA5‑Land' : 'нет данных'}</dd>
              </div>
              <div>
                <dt>Строк временного ряда</dt>
                <dd>{field.datasetRows ?? 'нет данных'}</dd>
              </div>
              <div>
                <dt>Метод нормы</dt>
                <dd>{risk?.quality.normMethod ?? 'норма не рассчитана'}</dd>
              </div>
              <div>
                <dt>Исторические сезоны</dt>
                <dd>{risk?.referenceSeasons ?? 'нет данных'}</dd>
              </div>
              <div>
                <dt>Облачность сцены</dt>
                <dd>
                  {risk?.quality.cloudCover == null
                    ? 'нет данных'
                    : `${risk.quality.cloudCover.toFixed(1)}%`}
                </dd>
              </div>
              <div>
                <dt>Валидные пиксели</dt>
                <dd>
                  {risk?.quality.validPixels == null
                    ? 'нет данных'
                    : Math.round(risk.quality.validPixels)}
                </dd>
              </div>
              <div>
                <dt>Обновлено</dt>
                <dd>{field.updatedAt}</dd>
              </div>
            </dl>
          </div>
        </TabsContent>
      </Tabs>
      <AlertDialog
        open={Boolean(deleteInspectionId)}
        onOpenChange={(open) => !open && setDeleteInspectionId('')}
      >
        <AlertDialogContent className="inspection-delete-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить точку осмотра?</AlertDialogTitle>
            <AlertDialogDescription>
              Точка исчезнет с карты и из маршрута. Остальные точки и сам сигнал
              сохранятся.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={inspectionBusy}>
              Отмена
            </AlertDialogCancel>
            <AlertDialogAction
              className="inspection-delete-confirm"
              disabled={inspectionBusy}
              onClick={() => void removeInspection()}
            >
              {inspectionBusy ? 'Удаляем…' : 'Удалить точку'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
}
