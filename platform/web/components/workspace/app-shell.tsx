'use client';

import {
  Activity,
  Check,
  ChevronDown,
  CloudSun,
  Database,
  Layers3,
  LoaderCircle,
  Map as MapIcon,
  MapPin,
  Menu,
  Satellite,
  Settings2,
  Sparkles,
  X,
} from 'lucide-react';
import dynamic from 'next/dynamic';
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react';

import AddFieldDialog from './add-field-dialog';
import AIAssistant from './ai-assistant';
import AnomaliesView from './anomalies-view';
import FieldDetails from './field-details';
import FieldSidebar, { BrandMark } from './field-sidebar';
import LayerLegend from './layer-legend';
import MapNotesPanel from './map-notes-panel';
import RegionSearch from './region-search';
import SeasonMenu from './season-menu';
import SourcesView from './sources-view';
import {
  createApiField,
  createApiMapNote,
  deleteApiField,
  deleteApiMapNote,
  loadApiAttention,
  loadApiFieldCandidates,
  loadApiFields,
  loadApiInspectionPoints,
  loadApiMapNotes,
  loadApiProviders,
  loadApiScenes,
  patchApiField,
  startApiAnalysis,
  watchApiAnalysis,
} from '@/lib/api';
import type {
  AttentionItem,
  FieldGeometry,
  FieldRecord,
  FieldSource,
  InspectionPoint,
  LayerId,
  LiveLayerState,
  MapNote,
  Position,
  RegionResult,
  SatelliteId,
  SceneRecord,
  SpatialRiskResult,
  WorkspaceView,
} from '@/lib/types';
import { useVegetationWebMcp } from '@/hooks/use-vegetation-webmcp';
import { BRAND_NAME } from '@/lib/brand';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select';

const MapView = dynamic(() => import('./map-view'), {
  ssr: false,
  loading: () => (
    <div className="map-loading">
      <span />
      Загружаем карту…
    </div>
  ),
});
const AnalysisChart = dynamic(() => import('./analysis-chart'), { ssr: false });

const layers: Array<{ id: LayerId; label: string }> = [
  { id: 'base', label: 'Карта' },
  { id: 'rgb', label: 'RGB' },
  { id: 'ndvi', label: 'NDVI' },
  { id: 'evi', label: 'EVI' },
  { id: 'ndwi', label: 'NDWI' },
];
const satellites: Array<{ id: SatelliteId; label: string; short: string }> = [
  { id: 'sentinel2', label: 'Sentinel‑2', short: 'S2' },
  { id: 'landsat', label: 'Landsat 8/9', short: 'L8/9' },
  { id: 'modis', label: 'MODIS', short: 'MODIS' },
];
const sceneSatelliteId = (scene: SceneRecord): SatelliteId =>
  scene.satellite === 'Landsat 8/9'
    ? 'landsat'
    : scene.satellite === 'MODIS'
      ? 'modis'
      : 'sentinel2';

function scrollSceneTimeline(event: ReactWheelEvent<HTMLDivElement>) {
  const timeline = event.currentTarget;
  const distance =
    Math.abs(event.deltaX) > Math.abs(event.deltaY)
      ? event.deltaX
      : event.deltaY;
  const maxScroll = timeline.scrollWidth - timeline.clientWidth;

  if (!distance || maxScroll <= 0) return;

  const nextPosition = Math.min(
    maxScroll,
    Math.max(0, timeline.scrollLeft + distance),
  );
  if (nextPosition === timeline.scrollLeft) return;

  event.preventDefault();
  timeline.scrollLeft = nextPosition;
}

function navigateSceneTimeline(event: ReactKeyboardEvent<HTMLDivElement>) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;

  event.preventDefault();
  event.currentTarget.scrollBy({
    left: event.key === 'ArrowLeft' ? -240 : 240,
    behavior: 'smooth',
  });
}

function NavRail({
  view,
  onChange,
  onHome,
  attentionCount,
  onAssistant,
}: {
  view: WorkspaceView;
  onChange: (value: WorkspaceView) => void;
  onHome: () => void;
  attentionCount: number;
  onAssistant: () => void;
}) {
  const items = [
    { id: 'fields' as const, label: 'Поля', icon: MapIcon },
    { id: 'anomalies' as const, label: 'Сигналы', icon: Activity },
    { id: 'sources' as const, label: 'Источники', icon: Database },
  ];
  return (
    <TooltipProvider delay={180}>
      <aside className="nav-rail" aria-label="Основная навигация">
        <button
          className="rail-home"
          onClick={onHome}
          aria-label="На титульную страницу"
        >
          <BrandMark />
        </button>
        <nav className="rail-links">
          {items.map(({ id, label, icon: Icon }) => (
            <Tooltip key={id}>
              <TooltipTrigger
                render={
                  <button
                    className={`rail-button ${view === id ? 'is-active' : ''}`}
                    onClick={() => onChange(id)}
                    aria-label={label}
                  />
                }
              >
                <Icon size={20} />
                {id === 'anomalies' && attentionCount ? (
                  <span className="rail-count">{attentionCount}</span>
                ) : null}
              </TooltipTrigger>
              <RailTooltipContent label={label} />
            </Tooltip>
          ))}
        </nav>
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                className="rail-button rail-ai"
                onClick={onAssistant}
                aria-label="AI-помощник"
              />
            }
          >
            <Sparkles size={20} />
          </TooltipTrigger>
          <RailTooltipContent label="AI‑помощник" />
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                className="rail-button rail-bottom"
                aria-label="Настройки"
              />
            }
          >
            <Settings2 size={20} />
          </TooltipTrigger>
          <RailTooltipContent label="Настройки" />
        </Tooltip>
      </aside>
    </TooltipProvider>
  );
}

function RailTooltipContent({ label }: { label: string }) {
  return (
    <TooltipContent side="right" sideOffset={12} className="rail-tooltip">
      <span className="rail-tooltip-dot" aria-hidden="true" />
      {label}
    </TooltipContent>
  );
}

export default function AppShell({
  onHome = () => undefined,
}: {
  onHome?: () => void;
}) {
  const [view, setView] = useState<WorkspaceView>('fields');
  const [fields, setFields] = useState<FieldRecord[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [detailsOpen, setDetailsOpen] = useState(true);
  const [layer, setLayer] = useState<LayerId>('ndvi');
  const [date, setDate] = useState('');
  const [season, setSeason] = useState(() => new Date().getFullYear());
  const [satellite, setSatellite] = useState<SatelliteId>('sentinel2');
  const [focusRegion, setFocusRegion] = useState<RegionResult | null>(null);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const [choosingCandidate, setChoosingCandidate] = useState(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>();
  const [draftGeometry, setDraftGeometry] = useState<FieldGeometry | null>(
    null,
  );
  const [draftArea, setDraftArea] = useState(0);
  const [draftSource, setDraftSource] = useState<FieldSource>('drawn');
  const [analysing, setAnalysing] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState<{
    progress: number;
    stage: string;
  } | null>(null);
  const [apiConnected, setApiConnected] = useState(false);
  const [liveTilesAvailable, setLiveTilesAvailable] = useState(false);
  const [liveLayerState, setLiveLayerState] = useState<LiveLayerState>('idle');
  const [candidates, setCandidates] = useState<FieldRecord[]>([]);
  const [scenes, setScenes] = useState<SceneRecord[]>([]);
  const [workspaceError, setWorkspaceError] = useState('');
  const [candidateLoadState, setCandidateLoadState] = useState<
    'idle' | 'loading' | 'ready' | 'error'
  >('idle');
  const [candidateRegion, setCandidateRegion] = useState<RegionResult | null>(
    null,
  );
  const [notes, setNotes] = useState<MapNote[]>([]);
  const [inspectionPoints, setInspectionPoints] = useState<InspectionPoint[]>(
    [],
  );
  const [focusedInspectionId, setFocusedInspectionId] = useState('');
  const [spatialRisk, setSpatialRisk] = useState<SpatialRiskResult | null>(
    null,
  );
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [comparisonDate, setComparisonDate] = useState('');
  const [comparisonBlend, setComparisonBlend] = useState(0.5);
  const [notesOpen, setNotesOpen] = useState(false);
  const [placingNote, setPlacingNote] = useState(false);
  const [draftNotePosition, setDraftNotePosition] = useState<Position | null>(
    null,
  );
  const [selectedNoteId, setSelectedNoteId] = useState('');
  const [detailTab, setDetailTab] = useState('summary');
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [fieldsPanelWidth, setFieldsPanelWidth] = useState(320);
  const [detailPanelWidth, setDetailPanelWidth] = useState(() =>
    typeof window === 'undefined'
      ? 540
      : Math.min(720, Math.max(540, window.innerWidth * 0.3)),
  );
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);
  const selected = fields.find((field) => field.id === selectedId) ?? fields[0];
  const selectedCandidate = candidates.find(
    (item) => item.id === selectedCandidateId,
  );
  const visibleInspectionPoints = useMemo(() => {
    const seen = new Set<string>();
    return inspectionPoints.filter((point) => {
      const key = `${point.fieldId}:${point.latitude.toFixed(5)}:${point.longitude.toFixed(5)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [inspectionPoints]);

  useEffect(() => {
    let active = true;
    void loadApiProviders()
      .then((providers) => {
        if (active)
          setLiveTilesAvailable(
            providers.some(
              (provider) =>
                provider.id === 'gee' && provider.status === 'connected',
            ),
          );
      })
      .catch(() => setLiveTilesAvailable(false));
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    loadApiFields()
      .then((remote) => {
        if (active) {
          setFields(remote);
          setSelectedId((current) =>
            remote.some((field) => field.id === current)
              ? current
              : (remote[0]?.id ?? ''),
          );
          setApiConnected(true);
          setWorkspaceError('');
        }
      })
      .catch(() => {
        if (active) {
          setApiConnected(false);
          setWorkspaceError(
            'API недоступен. Поля и показатели не подменяются локальными данными.',
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    loadApiMapNotes()
      .then((items) => {
        if (active) setNotes(items);
      })
      .catch(() => {
        if (active) setNotes([]);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    loadApiInspectionPoints()
      .then((items) => {
        if (active) setInspectionPoints(items);
      })
      .catch(() => {
        if (active) setInspectionPoints([]);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    loadApiAttention()
      .then((items) => {
        if (active) setAttentionItems(items);
      })
      .catch(() => {
        if (active) setAttentionItems([]);
      });
    return () => {
      active = false;
    };
  }, [fields]);
  useEffect(() => {
    queueMicrotask(() => setSpatialRisk(null));
  }, [selectedId, date]);
  useEffect(() => {
    let active = true;
    if (!selectedId) {
      queueMicrotask(() => {
        if (active) {
          setScenes([]);
          setDate('');
        }
      });
      return () => {
        active = false;
      };
    }
    loadApiScenes(selectedId, season)
      .then((items) => {
        if (active) {
          setScenes(items);
          const matching = items.filter(
            (item) => sceneSatelliteId(item) === satellite,
          );
          setDate((current) =>
            matching.some((item) => item.date === current)
              ? current
              : (matching[0]?.date ?? ''),
          );
        }
      })
      .catch(() => {
        if (active) {
          setScenes([]);
          setDate('');
        }
      });
    return () => {
      active = false;
    };
  }, [season, selectedId, fields, satellite]);

  const openField = useCallback((id: string) => {
    setSelectedId(id);
    setView('fields');
    setDetailsOpen(true);
    setDetailTab('summary');
    setAnalysisOpen(false);
  }, []);
  const openAttentionField = useCallback(
    (id: string) => {
      setSatellite('sentinel2');
      setLayer('ndvi');
      setComparisonOpen(false);
      openField(id);
    },
    [openField],
  );
  const beginAdd = useCallback(() => {
    setDraftGeometry(null);
    setDraftArea(0);
    setSelectedCandidateId(undefined);
    setDraftSource('drawn');
    setAddOpen(true);
  }, []);
  const startCandidates = (region: RegionResult) => {
    setAddOpen(false);
    setChoosingCandidate(true);
    setDrawing(false);
    setSelectedCandidateId(undefined);
    setCandidateRegion(region);
    if (!apiConnected) {
      setCandidates([]);
      setCandidateLoadState('error');
      return;
    }
    setCandidates([]);
    setCandidateLoadState('loading');
    void loadApiFieldCandidates(region)
      .then((items) => {
        setCandidates(items);
        setCandidateLoadState('ready');
      })
      .catch(() => {
        setCandidates([]);
        setCandidateLoadState('error');
      });
  };
  const startDrawing = () => {
    setAddOpen(false);
    setChoosingCandidate(false);
    setDraftGeometry(null);
    setDraftArea(0);
    setDraftSource('drawn');
    setDrawing(true);
  };
  const acceptCandidate = () => {
    if (!selectedCandidate) return;
    setDraftGeometry(selectedCandidate.geometry);
    setDraftArea(selectedCandidate.areaHa);
    setDraftSource('osm');
    setChoosingCandidate(false);
    setAddOpen(true);
  };
  const saveField = (name: string, crop: string, region: string) => {
    if (!draftGeometry) return;
    if (!apiConnected) {
      setWorkspaceError('Невозможно сохранить поле: API недоступен.');
      return;
    }
    const field: FieldRecord = {
      id: 'pending',
      name,
      crop,
      region,
      areaHa: draftArea,
      ndvi: null,
      delta: null,
      status: 'normal',
      source: draftSource,
      geometry: draftGeometry,
      updatedAt: 'не анализировалось',
      validPixels: null,
      dataProvider: null,
      temperatureC: null,
      precipitation7dMm: null,
    };
    setAddOpen(false);
    setDetailsOpen(true);
    setAnalysisOpen(false);
    setAnalysing(true);
    setAnalysisProgress({ progress: 0, stage: 'Создаём поле' });
    setWorkspaceError('');
    createApiField(field)
      .then(async (remote) => {
        setFields((current) => [remote, ...current]);
        setSelectedId(remote.id);
        const job = await startApiAnalysis(remote.id);
        watchApiAnalysis(
          job.id,
          (value) => {
            setAnalysing(
              value.status === 'queued' || value.status === 'running',
            );
            setAnalysisProgress({
              progress: value.progress,
              stage: value.stage,
            });
          },
          (value) => {
            setAnalysing(false);
            setAnalysisProgress(null);
            if (value.status === 'failed')
              setWorkspaceError(value.error ?? 'Анализ не выполнен');
            loadApiFields()
              .then(setFields)
              .catch(() => undefined);
          },
        );
      })
      .catch((reason: unknown) => {
        setAnalysing(false);
        setAnalysisProgress(null);
        setWorkspaceError(
          reason instanceof Error ? reason.message : 'Не удалось создать поле',
        );
      });
  };
  const deleteField = (fieldId: string) => {
    if (!apiConnected) return;
    void deleteApiField(fieldId)
      .then(() => {
        setFields((current) => {
          const next = current.filter((item) => item.id !== fieldId);
          if (selectedId === fieldId) setSelectedId(next[0]?.id ?? '');
          return next;
        });
        if (selectedId === fieldId) {
          setDetailsOpen(false);
          setAnalysisOpen(false);
        }
        setDeleteTargetId(null);
      })
      .catch((reason: unknown) =>
        setWorkspaceError(
          reason instanceof Error ? reason.message : 'Не удалось удалить поле',
        ),
      );
  };
  const renameField = (name: string) => {
    if (!selected || !apiConnected) return;
    void patchApiField(selected.id, { name })
      .then((updated) =>
        setFields((current) =>
          current.map((item) => (item.id === updated.id ? updated : item)),
        ),
      )
      .catch((reason: unknown) =>
        setWorkspaceError(
          reason instanceof Error
            ? reason.message
            : 'Не удалось переименовать поле',
        ),
      );
  };
  const refresh = () => {
    if (!selected || !apiConnected) {
      setWorkspaceError('Невозможно запустить анализ: API недоступен.');
      return;
    }
    setAnalysing(true);
    setWorkspaceError('');
    setAnalysisProgress({ progress: 0, stage: 'Задача поставлена в очередь' });
    startApiAnalysis(selectedId)
      .then((job) =>
        watchApiAnalysis(
          job.id,
          (value) => {
            setAnalysing(
              value.status === 'queued' || value.status === 'running',
            );
            setAnalysisProgress({
              progress: value.progress,
              stage: value.stage,
            });
          },
          (value) => {
            setAnalysing(false);
            setAnalysisProgress(null);
            if (value.status === 'failed')
              setWorkspaceError(value.error ?? 'Анализ не выполнен');
            loadApiFields()
              .then(setFields)
              .catch(() => undefined);
          },
        ),
      )
      .catch((reason: unknown) => {
        setAnalysing(false);
        setAnalysisProgress(null);
        setWorkspaceError(
          reason instanceof Error
            ? reason.message
            : 'Не удалось запустить анализ',
        );
      });
  };

  useVegetationWebMcp({
    fields,
    selectedId,
    onSelectField: openField,
    onStartAdd: beginAdd,
  });

  const availableScenes = useMemo(
    () => scenes.filter((scene) => sceneSatelliteId(scene) === satellite),
    [satellite, scenes],
  );
  useEffect(() => {
    if (!comparisonOpen) return;
    const alternatives = availableScenes.filter((scene) => scene.date !== date);
    queueMicrotask(() =>
      setComparisonDate((current) =>
        alternatives.some((scene) => scene.date === current)
          ? current
          : (alternatives[0]?.date ?? ''),
      ),
    );
  }, [availableScenes, comparisonOpen, date]);
  const selectedScene =
    availableScenes.find((scene) => scene.date === date) ?? null;
  const activeRiskIds = useMemo(
    () =>
      new Set(
        attentionItems
          .filter(
            (item) =>
              item.signal &&
              item.riskState !== 'normal' &&
              item.riskState !== 'insufficient_data' &&
              item.signal.workflow.state !== 'closed' &&
              item.signal.workflow.state !== 'rejected',
          )
          .map((item) => item.fieldId),
      ),
    [attentionItems],
  );
  const changeSeason = (year: number) => {
    setSeason(year);
    setDate('');
  };
  const changeSatellite = (next: SatelliteId) => {
    setSatellite(next);
    if (next === 'modis' && (layer === 'rgb' || layer === 'ndwi'))
      setLayer('ndvi');
    const matching = scenes.filter((scene) => sceneSatelliteId(scene) === next);
    setDate(matching[0]?.date ?? '');
  };
  const chooseRegion = (region: RegionResult) => {
    setFocusRegion(region);
    setDetailsOpen(false);
    setAnalysisOpen(false);
  };
  const beginNote = () => {
    setNotesOpen(true);
    setDraftNotePosition(null);
    setPlacingNote(true);
    setSelectedNoteId('');
  };
  const cancelNote = () => {
    setPlacingNote(false);
    setDraftNotePosition(null);
  };
  const placeNote = (position: Position) => {
    setDraftNotePosition(position);
    setPlacingNote(false);
    setNotesOpen(true);
  };
  const saveNote = async (title: string, text: string) => {
    if (!draftNotePosition) return;
    try {
      const note = await createApiMapNote({
        title,
        text: text || null,
        longitude: draftNotePosition[0],
        latitude: draftNotePosition[1],
        fieldId: selected?.id ?? null,
      });
      setNotes((current) => [note, ...current]);
      setSelectedNoteId(note.id);
      setDraftNotePosition(null);
    } catch (reason: unknown) {
      setWorkspaceError(
        reason instanceof Error ? reason.message : 'Не удалось сохранить метку',
      );
    }
  };
  const removeNote = async (id: string) => {
    try {
      await deleteApiMapNote(id);
      setNotes((current) => current.filter((item) => item.id !== id));
      if (selectedNoteId === id) setSelectedNoteId('');
    } catch (reason: unknown) {
      setWorkspaceError(
        reason instanceof Error ? reason.message : 'Не удалось удалить метку',
      );
    }
  };
  const beginHorizontalResize = (
    event: ReactPointerEvent<HTMLElement>,
    current: number,
    setValue: (value: number) => void,
    direction: 1 | -1,
    min: number,
    max: number,
  ) => {
    event.preventDefault();
    const startX = event.clientX;
    const move = (nextEvent: PointerEvent) =>
      setValue(
        Math.min(
          max,
          Math.max(min, current + (nextEvent.clientX - startX) * direction),
        ),
      );
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      document.body.classList.remove('is-resizing-panel');
    };
    document.body.classList.add('is-resizing-panel');
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop, { once: true });
  };
  return (
    <main
      className={`workspace-shell ${view !== 'fields' ? 'wide-mode' : ''} ${analysisOpen ? 'chart-open' : ''}`}
      style={
        {
          '--fields-width': `${fieldsPanelWidth}px`,
          '--detail-width': `${detailPanelWidth}px`,
        } as CSSProperties
      }
    >
      <NavRail
        view={view}
        onChange={setView}
        onHome={onHome}
        attentionCount={activeRiskIds.size}
        onAssistant={() => setAssistantOpen(true)}
      />
      {workspaceError ? (
        <div className="workspace-error" role="alert">
          <span>{workspaceError}</span>
          <button
            onClick={() => setWorkspaceError('')}
            aria-label="Закрыть ошибку"
          >
            <X size={15} />
          </button>
        </div>
      ) : null}
      {view === 'fields' ? (
        <>
          {notesOpen ? (
            <aside className="fields-panel notes-sidebar">
              <MapNotesPanel
                notes={notes}
                placing={placingNote}
                draftPosition={draftNotePosition}
                selectedNoteId={selectedNoteId}
                onBeginPlace={beginNote}
                onCancelPlace={cancelNote}
                onSelect={setSelectedNoteId}
                onSave={saveNote}
                onDelete={removeNote}
                onClose={() => {
                  setNotesOpen(false);
                  cancelNote();
                }}
              />
              <hr
                className="sidebar-resize-handle"
                aria-label="Изменить ширину панели меток"
                onPointerDown={(event) =>
                  beginHorizontalResize(
                    event,
                    fieldsPanelWidth,
                    setFieldsPanelWidth,
                    1,
                    280,
                    520,
                  )
                }
              />
            </aside>
          ) : (
            <FieldSidebar
              fields={fields}
              selectedFieldId={selectedId}
              onSelect={openField}
              onAdd={beginAdd}
              onDelete={setDeleteTargetId}
              onOpenAttention={() => setView('anomalies')}
              riskFieldIds={activeRiskIds}
              onResizeStart={(event) =>
                beginHorizontalResize(
                  event,
                  fieldsPanelWidth,
                  setFieldsPanelWidth,
                  1,
                  280,
                  520,
                )
              }
            />
          )}
          <section className="map-workspace" aria-label="Карта полей">
            <MapView
              fields={fields}
              candidates={candidates}
              selectedFieldId={selectedId}
              layer={layer}
              date={date}
              satellite={satellite}
              drawing={drawing}
              choosingCandidate={choosingCandidate}
              selectedCandidateId={selectedCandidateId}
              notes={notes}
              inspectionPoints={visibleInspectionPoints}
              focusedInspectionId={focusedInspectionId}
              spatialRiskUrl={spatialRisk?.url ?? null}
              comparisonDate={comparisonOpen ? comparisonDate : null}
              comparisonBlend={comparisonBlend}
              placingNote={placingNote}
              selectedNoteId={selectedNoteId}
              liveTilesEnabled={liveTilesAvailable}
              focusRegion={focusRegion}
              onLiveLayerStateChange={setLiveLayerState}
              onSelectField={openField}
              onSelectCandidate={setSelectedCandidateId}
              onPlaceNote={placeNote}
              onSelectNote={(id) => {
                setSelectedNoteId(id);
                setNotesOpen(true);
              }}
              onSelectInspection={(id) => {
                const point = visibleInspectionPoints.find(
                  (item) => item.id === id,
                );
                if (!point) return;
                openField(point.fieldId);
                setFocusedInspectionId(point.id);
                setDetailTab('inspection');
                setComparisonOpen(false);
              }}
              onDraftGeometry={(geometry, areaHa) => {
                setDraftGeometry(geometry);
                setDraftArea(areaHa);
              }}
              onFinishDrawing={() => {
                if (draftGeometry) {
                  setDrawing(false);
                  setDraftSource('drawn');
                  setAddOpen(true);
                }
              }}
              onCancelDrawing={() => {
                setDrawing(false);
                setDraftGeometry(null);
              }}
            />

            {!drawing && !choosingCandidate ? (
              <header className="map-topbar">
                <button className="mobile-menu" aria-label="Открыть меню">
                  <Menu size={20} />
                </button>
                <RegionSearch
                  key={focusRegion?.id ?? 'default-region'}
                  initialValue={focusRegion?.name ?? 'Ростовская область'}
                  onSelect={chooseRegion}
                />
                <SeasonMenu value={season} onChange={changeSeason} />
                <button
                  className={`notes-map-toggle ${notesOpen ? 'is-active' : ''}`}
                  onClick={() => {
                    setNotesOpen((value) => !value);
                    cancelNote();
                  }}
                >
                  <MapPin size={16} />
                  Метки{notes.length ? <span>{notes.length}</span> : null}
                </button>
                <span className="demo-mode">
                  <Satellite size={14} />
                  {selected?.dataProvider === 'gee'
                    ? 'Реальные данные GEE'
                    : 'Нет анализа'}
                </span>
              </header>
            ) : null}
            {!drawing && !choosingCandidate ? (
              <div className="map-layer-toolbar">
                <div className="layer-switcher">
                  <span className="layer-label">
                    <Layers3 size={16} />
                    Слой
                  </span>
                  {layers.map((item) => {
                    const unavailable =
                      satellite === 'modis' &&
                      (item.id === 'rgb' || item.id === 'ndwi');
                    return (
                      <button
                        key={item.id}
                        className={layer === item.id ? 'is-active' : ''}
                        disabled={unavailable}
                        title={
                          unavailable
                            ? 'Недоступно в продукте MOD13Q1'
                            : undefined
                        }
                        onClick={() => setLayer(item.id)}
                      >
                        {item.label}
                      </button>
                    );
                  })}
                </div>
                {layer !== 'base' && availableScenes.length > 1 ? (
                  <button
                    className={`map-compare-launch ${comparisonOpen ? 'is-active' : ''}`}
                    aria-expanded={comparisonOpen}
                    onClick={() =>
                      setComparisonOpen((value) => {
                        const next = !value;
                        if (next) setDetailsOpen(false);
                        return next;
                      })
                    }
                  >
                    {comparisonOpen ? 'Закрыть сравнение' : 'Сравнить даты'}
                  </button>
                ) : null}
              </div>
            ) : null}
            {!drawing &&
            !choosingCandidate &&
            comparisonOpen &&
            layer !== 'base' &&
            availableScenes.length > 1 ? (
              <div className="map-compare-control is-open">
                <div className="compare-date">
                  <span>Было</span>
                  <Select
                    value={comparisonDate}
                    onValueChange={(value) => value && setComparisonDate(value)}
                  >
                    <SelectTrigger aria-label="Дата до">
                      <strong>
                        {comparisonDate
                          ? new Intl.DateTimeFormat('ru-RU', {
                              day: '2-digit',
                              month: 'short',
                            }).format(new Date(`${comparisonDate}T12:00:00`))
                          : 'Выберите'}
                      </strong>
                    </SelectTrigger>
                    <SelectContent
                      className="compare-date-menu"
                      align="start"
                      sideOffset={7}
                      alignItemWithTrigger={false}
                    >
                      {availableScenes
                        .filter((scene) => scene.date !== date)
                        .map((scene) => (
                          <SelectItem key={scene.id} value={scene.date}>
                            {new Intl.DateTimeFormat('ru-RU', {
                              day: 'numeric',
                              month: 'long',
                              year: 'numeric',
                            }).format(new Date(`${scene.date}T12:00:00`))}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="compare-blend">
                  <span>
                    Показываем: {Math.round((1 - comparisonBlend) * 100)}% было
                    · {Math.round(comparisonBlend * 100)}% стало
                  </span>
                  <input
                    aria-label="Баланс снимков до и после"
                    type="range"
                    min="0"
                    max="100"
                    value={Math.round(comparisonBlend * 100)}
                    onChange={(event) =>
                      setComparisonBlend(Number(event.target.value) / 100)
                    }
                  />
                </div>
                <div className="compare-date is-after">
                  <span>Стало</span>
                  <strong>
                    {date
                      ? new Intl.DateTimeFormat('ru-RU', {
                          day: '2-digit',
                          month: 'short',
                        }).format(new Date(`${date}T12:00:00`))
                      : '—'}
                  </strong>
                </div>
              </div>
            ) : null}
            {!drawing && !choosingCandidate && !comparisonOpen ? (
              <LayerLegend
                layer={layer}
                state={liveLayerState}
                satellite={satellite}
              />
            ) : null}
            {spatialRisk ? (
              <aside className="risk-map-key">
                <span>
                  <i />
                  Локальные зоны для проверки
                </span>
                <strong>
                  {spatialRisk.affectedAreaHa.toFixed(1)} га ·{' '}
                  {spatialRisk.affectedAreaPercent?.toFixed(1) ?? '—'}%
                </strong>
                <small>
                  Показаны худшие пиксели ниже нормы, а не поражение всего поля.
                </small>
                <button onClick={() => setSpatialRisk(null)}>
                  Скрыть слой
                </button>
              </aside>
            ) : null}
            {choosingCandidate ? (
              <section className="candidate-panel">
                <header>
                  <div>
                    <span>Шаг 2 из 3</span>
                    <strong>Выберите готовый контур</strong>
                  </div>
                  <button
                    onClick={() => setChoosingCandidate(false)}
                    aria-label="Закрыть"
                  >
                    <X size={18} />
                  </button>
                </header>
                <p>
                  Контуры выделены лаймовым. Нажмите на поле на карте или на
                  строку ниже.
                </p>
                {candidateLoadState === 'loading' ? (
                  <div className="candidate-load-state">
                    <LoaderCircle size={18} />
                    <span>
                      <strong>Ищем поля рядом с регионом</strong>
                      <small>Обычно это занимает 2–8 секунд</small>
                    </span>
                  </div>
                ) : null}
                {candidateLoadState === 'error' ? (
                  <div className="candidate-load-state is-error">
                    <span>
                      <strong>Контуры не загрузились</strong>
                      <small>Публичный Overpass временно не ответил.</small>
                    </span>
                    <button
                      onClick={() =>
                        candidateRegion && startCandidates(candidateRegion)
                      }
                    >
                      Повторить
                    </button>
                  </div>
                ) : null}
                {candidateLoadState === 'ready' ? (
                  <div className="candidate-count">
                    Найдено контуров: <strong>{candidates.length}</strong>
                  </div>
                ) : null}
                <div className="candidate-list">
                  {candidates.map((item, index) => (
                    <button
                      key={item.id}
                      className={
                        selectedCandidateId === item.id ? 'is-active' : ''
                      }
                      onClick={() => setSelectedCandidateId(item.id)}
                    >
                      <b className="candidate-index">{index + 1}</b>
                      <span>
                        <strong>{item.name}</strong>
                        <small>
                          OSM ·{' '}
                          {item.areaHa
                            ? `${item.areaHa.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} га`
                            : 'площадь уточняется'}
                        </small>
                      </span>
                      {selectedCandidateId === item.id ? (
                        <Check size={17} />
                      ) : null}
                    </button>
                  ))}
                </div>
                {candidateLoadState === 'ready' && !candidates.length ? (
                  <div className="candidate-empty">
                    В этом окне поля не найдены. Выберите другой населённый
                    пункт или нарисуйте контур.
                  </div>
                ) : null}
                {selectedCandidate ? (
                  <div className="candidate-selected">
                    <Check size={15} />
                    <span>
                      <strong>{selectedCandidate.name} выбрано</strong>
                      <small>Теперь подтвердите добавление поля</small>
                    </span>
                  </div>
                ) : null}
                <footer>
                  <button onClick={() => setChoosingCandidate(false)}>
                    Отмена
                  </button>
                  <button
                    className="candidate-accept"
                    disabled={!selectedCandidate}
                    onClick={acceptCandidate}
                  >
                    {selectedCandidate
                      ? 'Добавить выбранное поле'
                      : 'Сначала выберите поле'}
                  </button>
                </footer>
              </section>
            ) : null}

            {!drawing && !choosingCandidate && selected && detailsOpen && (
              <FieldDetails
                field={selected}
                season={season}
                selectedDate={date}
                selectedScene={selectedScene}
                scenes={scenes}
                inspectionPoints={visibleInspectionPoints.filter(
                  (point) => point.fieldId === selected.id,
                )}
                focusedInspectionId={focusedInspectionId}
                activeTab={detailTab}
                onActiveTabChange={setDetailTab}
                spatialRisk={spatialRisk}
                onSpatialRisk={setSpatialRisk}
                onInspectionCreated={(point) =>
                  setInspectionPoints((current) => [point, ...current])
                }
                onInspectionUpdated={(point) =>
                  setInspectionPoints((current) =>
                    current.map((item) =>
                      item.id === point.id ? point : item,
                    ),
                  )
                }
                onInspectionDeleted={(id) => {
                  setInspectionPoints((current) =>
                    current.filter((item) => item.id !== id),
                  );
                  setFocusedInspectionId((current) =>
                    current === id ? '' : current,
                  );
                }}
                onFocusInspection={(point) => setFocusedInspectionId(point.id)}
                onSceneSelect={(scene) => {
                  setSatellite(sceneSatelliteId(scene));
                  setDate(scene.date);
                }}
                onAnalysis={() => setAnalysisOpen(true)}
                onRename={renameField}
                onClose={() => setDetailsOpen(false)}
                onRefresh={refresh}
                analysing={analysing}
                analysisProgress={analysisProgress}
                width={detailPanelWidth}
                onResizeStart={(event) =>
                  beginHorizontalResize(
                    event,
                    detailPanelWidth,
                    setDetailPanelWidth,
                    -1,
                    390,
                    760,
                  )
                }
              />
            )}
            {!drawing && !choosingCandidate && selected && !detailsOpen && (
              <button
                className="open-detail-chip"
                onClick={() => setDetailsOpen(true)}
              >
                <span className={`field-swatch ${selected.status}`} />
                {selected.name}
                <ChevronDown size={15} />
              </button>
            )}

            {!drawing && !choosingCandidate && selected && (
              <div className="date-timeline">
                <span className="timeline-caption">
                  <CloudSun size={16} />
                  <span>
                    <strong>Сцены · {availableScenes.length}</strong>
                    <small>выберите снимок</small>
                  </span>
                </span>
                <div
                  className="timeline-satellites"
                  aria-label="Спутниковый источник"
                >
                  {satellites.map((item) => (
                    <button
                      key={item.id}
                      aria-pressed={satellite === item.id}
                      className={satellite === item.id ? 'is-active' : ''}
                      onClick={() => changeSatellite(item.id)}
                    >
                      <span>{item.short}</span>
                    </button>
                  ))}
                </div>
                <div
                  className="timeline-scroll"
                  role="toolbar"
                  aria-label="Даты спутниковых снимков"
                  tabIndex={0}
                  onWheel={scrollSceneTimeline}
                  onKeyDown={navigateSceneTimeline}
                >
                  {availableScenes.map((scene) => (
                    <button
                      key={scene.id}
                      className={date === scene.date ? 'is-active' : ''}
                      onClick={() => setDate(scene.date)}
                      title={`${scene.satellite} · ${scene.date}`}
                    >
                      <span>
                        {new Intl.DateTimeFormat('ru-RU', {
                          day: '2-digit',
                          month: 'short',
                        }).format(new Date(`${scene.date}T12:00:00`))}
                      </span>
                      <i
                        className={(scene.cloudCover ?? 0) > 65 ? 'cloudy' : ''}
                      />
                    </button>
                  ))}
                  {!availableScenes.length ? (
                    <span className="timeline-empty">
                      В этом году сцен источника нет
                    </span>
                  ) : null}
                </div>
                <span className="timeline-source">
                  {satellites.find((item) => item.id === satellite)?.short}
                </span>
              </div>
            )}
            {analysisOpen && selected && (
              <AnalysisChart
                field={selected}
                season={season}
                selectedDate={date}
                onClose={() => setAnalysisOpen(false)}
                onDateSelect={setDate}
              />
            )}
          </section>
        </>
      ) : (
        <section className="wide-shell">
          <header className="compact-product-header">
            <button
              className="compact-home"
              onClick={onHome}
              aria-label="На титульную страницу"
            >
              <BrandMark />
            </button>
            <div>
              <span>Спутниковая аналитика</span>
              <strong>{BRAND_NAME}</strong>
            </div>
            <span className="demo-mode">
              <Satellite size={14} />
              Только реальные источники
            </span>
          </header>
          {view === 'anomalies' ? (
            <AnomaliesView
              fields={fields}
              onOpenField={openAttentionField}
              onAttentionChange={setAttentionItems}
            />
          ) : (
            <SourcesView />
          )}
        </section>
      )}

      <nav className="mobile-nav" aria-label="Мобильная навигация">
        <button
          className={view === 'fields' ? 'is-active' : ''}
          onClick={() => setView('fields')}
        >
          <MapIcon size={19} />
          <span>Поля</span>
        </button>
        <button
          className={view === 'anomalies' ? 'is-active' : ''}
          onClick={() => setView('anomalies')}
        >
          <Activity size={19} />
          <span>Сигналы</span>
        </button>
        <button
          className={view === 'sources' ? 'is-active' : ''}
          onClick={() => setView('sources')}
        >
          <Database size={19} />
          <span>Источники</span>
        </button>
        <button onClick={() => setAssistantOpen(true)}>
          <Sparkles size={19} />
          <span>AI</span>
        </button>
      </nav>
      <AddFieldDialog
        open={addOpen}
        geometry={draftGeometry}
        areaHa={draftArea}
        source={draftSource}
        initialRegion={focusRegion}
        onOpenChange={setAddOpen}
        onStartCandidates={startCandidates}
        onStartDrawing={startDrawing}
        onSave={saveField}
      />
      <AIAssistant
        open={assistantOpen}
        field={selected ?? null}
        onClose={() => setAssistantOpen(false)}
      />
      {deleteTargetId && fields.find((item) => item.id === deleteTargetId) ? (
        <div className="confirm-overlay">
          <section
            className="confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-field-title"
            aria-describedby="delete-field-description"
          >
            <header>
              <h3 id="delete-field-title">
                Удалить «
                {fields.find((item) => item.id === deleteTargetId)?.name}»?
              </h3>
              <p id="delete-field-description">
                Поле, временной ряд и результаты анализа будут удалены из
                рабочего пространства.
              </p>
            </header>
            <footer>
              <button type="button" onClick={() => setDeleteTargetId(null)}>
                Отмена
              </button>
              <button
                type="button"
                className="danger-action"
                onClick={() => deleteField(deleteTargetId)}
              >
                Удалить
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </main>
  );
}
