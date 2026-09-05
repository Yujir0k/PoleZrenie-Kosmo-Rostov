import type {
  AlertLifecycleState,
  AlertValidation,
  AIResponse,
  AIStatus,
  AttentionItem,
  AnomalyEvent,
  FieldRecord,
  FieldSource,
  InspectionPoint,
  MapNote,
  ProviderStatus,
  RegionResult,
  RiskSignal,
  SatelliteId,
  SceneRecord,
  SpatialRiskResult,
  TimeseriesPoint,
} from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

type ApiField = {
  id: string;
  name: string;
  crop: string;
  region: string;
  area_ha: number;
  ndvi: number | null;
  delta: number | null;
  status: FieldRecord['status'];
  source: FieldSource;
  geometry: FieldRecord['geometry'];
  valid_pixels: number | null;
  updated_at: string;
  temperature_c: number | null;
  precipitation_7d_mm: number | null;
  data_provider: string | null;
  scene_date: string | null;
  weather_date: string | null;
  cloud_cover: number | null;
  worldcover_cropland_percent: number | null;
  is_verified_cropland: boolean | null;
  dataset_rows: number | null;
};

type ApiRegion = {
  id: string;
  name: string;
  display_name: string;
  lat: number;
  lon: number;
  bounding_box: [number, number, number, number];
};
type ApiProvider = {
  id: ProviderStatus['id'];
  name: string;
  status: ProviderStatus['status'];
  role: string;
  datasets: string[];
  detail: string;
};
type CandidateFeature = {
  id?: string;
  properties?: { name?: string; area_ha?: number };
  geometry: FieldRecord['geometry'];
};
type ApiMapNote = {
  id: string;
  title: string;
  text: string | null;
  longitude: number;
  latitude: number;
  field_id: string | null;
  created_at: string;
};
const optionalString = (value: unknown): string | null =>
  typeof value === 'string' ? value : null;

function fromApi(field: ApiField): FieldRecord {
  return {
    id: field.id,
    name: field.name,
    crop: field.crop,
    region: field.region,
    areaHa: field.area_ha,
    ndvi: field.ndvi,
    delta: field.delta,
    status: field.status,
    source: field.source,
    geometry: field.geometry,
    validPixels: field.valid_pixels,
    temperatureC: field.temperature_c,
    precipitation7dMm: field.precipitation_7d_mm,
    dataProvider: field.data_provider,
    sceneDate: field.scene_date,
    weatherDate: field.weather_date,
    cloudCover: field.cloud_cover,
    worldcoverCroplandPercent: field.worldcover_cropland_percent,
    isVerifiedCropland: field.is_verified_cropland,
    datasetRows: field.dataset_rows,
    updatedAt: new Intl.DateTimeFormat('ru-RU', {
      day: 'numeric',
      month: 'long',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(field.updated_at)),
  };
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeout = 6000,
): Promise<T> {
  const controller = new AbortController();
  const upstreamSignal = init?.signal;
  const abortFromUpstream = () => controller.abort(upstreamSignal?.reason);
  if (upstreamSignal?.aborted) abortFromUpstream();
  else
    upstreamSignal?.addEventListener('abort', abortFromUpstream, {
      once: true,
    });
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const headers = new Headers(init?.headers);
    if (!headers.has('Content-Type'))
      headers.set('Content-Type', 'application/json');
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers,
    });
    if (!response.ok) {
      const payload = (await response
        .json()
        .catch(() => ({ detail: `API ${response.status}` }))) as {
        detail?: string;
      };
      throw new Error(payload.detail ?? `API ${response.status}`);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timer);
    upstreamSignal?.removeEventListener('abort', abortFromUpstream);
  }
}

export async function loadApiFields(): Promise<FieldRecord[]> {
  return (await request<ApiField[]>('/api/v1/fields')).map(fromApi);
}

type ApiAIResponse = {
  field_id: string;
  message: string;
  model: string;
  used_tools: string[];
  visualizations: AIResponse['visualizations'];
};

const fromApiAI = (payload: ApiAIResponse): AIResponse => ({
  fieldId: payload.field_id,
  message: payload.message,
  model: payload.model,
  usedTools: payload.used_tools,
  visualizations: payload.visualizations,
});

export async function loadAIStatus(): Promise<AIStatus> {
  const value = await request<{
    configured: boolean;
    provider: string;
    models: AIStatus['models'];
    data_logging: boolean;
  }>('/api/v1/ai/status');
  return {
    configured: value.configured,
    provider: value.provider,
    models: value.models,
    dataLogging: value.data_logging,
  };
}

export async function sendAIChat(
  fieldId: string,
  message: string,
  history: Array<{ role: 'user' | 'assistant'; content: string }>,
): Promise<AIResponse> {
  return fromApiAI(
    await request<ApiAIResponse>(
      '/api/v1/ai/chat',
      {
        method: 'POST',
        body: JSON.stringify({ field_id: fieldId, message, history }),
      },
      65_000,
    ),
  );
}

export async function createAIReport(
  fieldId: string,
  reportRequest: string,
): Promise<AIResponse> {
  return fromApiAI(
    await request<ApiAIResponse>(
      '/api/v1/ai/report',
      {
        method: 'POST',
        body: JSON.stringify({ field_id: fieldId, request: reportRequest }),
      },
      65_000,
    ),
  );
}

export async function sendAIVision(
  fieldId: string,
  question: string,
  imageDataUrl: string,
): Promise<AIResponse> {
  return fromApiAI(
    await request<ApiAIResponse>(
      '/api/v1/ai/vision',
      {
        method: 'POST',
        body: JSON.stringify({
          field_id: fieldId,
          question,
          image_data_url: imageDataUrl,
        }),
      },
      65_000,
    ),
  );
}
export async function createApiField(field: FieldRecord): Promise<FieldRecord> {
  return fromApi(
    await request<ApiField>('/api/v1/fields', {
      method: 'POST',
      body: JSON.stringify({
        name: field.name,
        crop: field.crop,
        region: field.region,
        source: field.source,
        geometry: field.geometry,
      }),
    }),
  );
}
export async function patchApiField(
  id: string,
  patch: { name?: string; crop?: string },
): Promise<FieldRecord> {
  return fromApi(
    await request<ApiField>(`/api/v1/fields/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  );
}
export async function deleteApiField(id: string): Promise<void> {
  return request<void>(`/api/v1/fields/${id}`, { method: 'DELETE' });
}
export async function loadApiMapNotes(): Promise<MapNote[]> {
  const rows = await request<ApiMapNote[]>('/api/v1/map-notes');
  return rows.map((row) => ({
    id: row.id,
    title: row.title,
    text: row.text,
    longitude: row.longitude,
    latitude: row.latitude,
    fieldId: row.field_id,
    createdAt: row.created_at,
  }));
}
export async function createApiMapNote(note: {
  title: string;
  text?: string | null;
  longitude: number;
  latitude: number;
  fieldId?: string | null;
}): Promise<MapNote> {
  const row = await request<ApiMapNote>('/api/v1/map-notes', {
    method: 'POST',
    body: JSON.stringify({
      title: note.title,
      text: note.text || null,
      longitude: note.longitude,
      latitude: note.latitude,
      field_id: note.fieldId ?? null,
    }),
  });
  return {
    id: row.id,
    title: row.title,
    text: row.text,
    longitude: row.longitude,
    latitude: row.latitude,
    fieldId: row.field_id,
    createdAt: row.created_at,
  };
}
export async function deleteApiMapNote(id: string): Promise<void> {
  return request<void>(`/api/v1/map-notes/${id}`, { method: 'DELETE' });
}
export async function startApiAnalysis(
  fieldId: string,
): Promise<{ id: string }> {
  return request<{ id: string }>('/api/v1/analysis-jobs', {
    method: 'POST',
    body: JSON.stringify({ field_id: fieldId }),
  });
}
export async function searchApiRegions(query: string): Promise<RegionResult[]> {
  const rows = await request<ApiRegion[]>(
    `/api/v1/regions/search?q=${encodeURIComponent(query)}`,
    undefined,
    8_000,
  );
  return rows.map((item) => ({
    id: item.id,
    name: item.name,
    displayName: item.display_name,
    lat: item.lat,
    lon: item.lon,
    boundingBox: item.bounding_box,
  }));
}
export async function loadApiFieldCandidates(
  region: RegionResult,
): Promise<FieldRecord[]> {
  const [regionSouth, regionNorth, regionWest, regionEast] = region.boundingBox;
  const halfLat = Math.min((regionNorth - regionSouth) / 2, 0.275);
  const halfLon = Math.min((regionEast - regionWest) / 2, 0.425);
  const south = Math.max(regionSouth, region.lat - halfLat);
  const north = Math.min(regionNorth, region.lat + halfLat);
  const west = Math.max(regionWest, region.lon - halfLon);
  const east = Math.min(regionEast, region.lon + halfLon);
  const query = new URLSearchParams({
    west: String(west),
    south: String(south),
    east: String(east),
    north: String(north),
  });
  const collection = await request<{ features: CandidateFeature[] }>(
    `/api/v1/field-candidates?${query.toString()}`,
    undefined,
    18_000,
  );
  return collection.features.map((item, index) => ({
    id: item.id ?? `osm-${index}`,
    name: item.properties?.name ?? `Контур ${index + 1}`,
    crop: 'Культура не указана',
    region: 'Найденный регион',
    areaHa: item.properties?.area_ha ?? 0,
    ndvi: null,
    delta: null,
    status: 'normal',
    source: 'osm',
    updatedAt: 'не анализировалось',
    validPixels: null,
    geometry: item.geometry,
  }));
}
export async function loadApiProviders(): Promise<ProviderStatus[]> {
  const rows = await request<ApiProvider[]>(
    '/api/v1/system/providers',
    undefined,
    15_000,
  );
  return rows.map((item) => ({
    id: item.id,
    name: item.name,
    description: item.detail,
    status: item.status,
    latency: item.status === 'connected' ? 'API отвечает' : 'не подключён',
    updatedAt: 'только что',
    datasets: item.datasets,
  }));
}
export async function loadApiTimeseries(
  fieldId: string,
  year: number,
): Promise<TimeseriesPoint[]> {
  const payload = await request<{ points: Array<Record<string, unknown>> }>(
    `/api/v1/fields/${fieldId}/timeseries?year=${year}`,
    undefined,
    12_000,
  );
  return payload.points.map((row) => ({
    date: String(row.date),
    observed: row.observed == null ? null : Number(row.observed),
    restored: Number(row.restored),
    climateMean: row.climate_mean == null ? null : Number(row.climate_mean),
    climateLow: row.climate_low == null ? null : Number(row.climate_low),
    climateHigh: row.climate_high == null ? null : Number(row.climate_high),
    confidenceLow: Number(row.confidence_low),
    confidenceHigh: Number(row.confidence_high),
    s2: row.s2 == null ? null : Number(row.s2),
    landsat: row.landsat == null ? null : Number(row.landsat),
    modis: row.modis == null ? null : Number(row.modis),
    temperature: row.temperature == null ? null : Number(row.temperature),
    precipitation: row.precipitation == null ? null : Number(row.precipitation),
    isImputed: Boolean(row.is_imputed),
    validPixels: row.valid_pixels == null ? null : Number(row.valid_pixels),
    cloudCover: row.cloud_cover == null ? null : Number(row.cloud_cover),
    robustMedian: row.robust_median == null ? null : Number(row.robust_median),
    robustQ10: row.robust_q10 == null ? null : Number(row.robust_q10),
    robustQ90: row.robust_q90 == null ? null : Number(row.robust_q90),
    robustZ: row.robust_z == null ? null : Number(row.robust_z),
    normSampleCount: Number(row.norm_sample_count ?? 0),
    observationSource: optionalString(row.observation_source),
  }));
}

function fromApiRisk(row: Record<string, unknown>): RiskSignal {
  const quality = (row.quality ?? {}) as Record<string, unknown>;
  const workflow = (row.workflow ?? {}) as Record<string, unknown>;
  return {
    id: String(row.id),
    asOf: String(row.as_of),
    riskState: row.risk_state as RiskSignal['riskState'],
    riskScore: Number(row.risk_score),
    confidence: Number(row.confidence),
    confidenceLevel: row.confidence_level as RiskSignal['confidenceLevel'],
    robustZ: row.robust_z == null ? null : Number(row.robust_z),
    slope14d: row.slope_14d == null ? null : Number(row.slope_14d),
    projectedRobustZ14d:
      row.projected_robust_z_14d == null
        ? null
        : Number(row.projected_robust_z_14d),
    leadWindowDays: Number(row.lead_window_days ?? 14),
    projectionDisclaimer: optionalString(row.projection_disclaimer) ?? '',
    referenceSeasons: Number(row.reference_seasons),
    observationSource: optionalString(row.observation_source),
    observation: String(row.observation),
    context: Array.isArray(row.context) ? row.context.map(String) : [],
    hypothesis: String(row.hypothesis),
    recommendation: String(row.recommendation),
    affectedAreaHa:
      row.affected_area_ha == null ? null : Number(row.affected_area_ha),
    affectedAreaPercent:
      row.affected_area_percent == null
        ? null
        : Number(row.affected_area_percent),
    quality: {
      validPixels:
        quality.valid_pixels == null ? null : Number(quality.valid_pixels),
      cloudCover:
        quality.cloud_cover == null ? null : Number(quality.cloud_cover),
      normMethod: optionalString(quality.norm_method) ?? '',
      causal: Boolean(quality.causal),
    },
    workflow: {
      state: (workflow.state ?? 'detected') as AlertLifecycleState,
      assignee: optionalString(workflow.assignee),
      note: optionalString(workflow.note),
    },
  };
}

export async function loadApiRiskProfile(
  fieldId: string,
  asOf?: string,
): Promise<RiskSignal | null> {
  const suffix = asOf ? `?as_of=${encodeURIComponent(asOf)}` : '';
  const payload = await request<{ signal: Record<string, unknown> | null }>(
    `/api/v1/fields/${fieldId}/risk-profile${suffix}`,
    undefined,
    12_000,
  );
  return payload.signal ? fromApiRisk(payload.signal) : null;
}

export async function loadApiAttention(): Promise<AttentionItem[]> {
  const payload = await request<{ items: Array<Record<string, unknown>> }>(
    '/api/v1/attention',
    undefined,
    20_000,
  );
  return payload.items.map((item) => ({
    fieldId: String(item.field_id),
    fieldName: String(item.field_name),
    riskState: item.risk_state as AttentionItem['riskState'],
    signal: item.signal
      ? fromApiRisk(item.signal as Record<string, unknown>)
      : null,
  }));
}
export async function loadApiAlertValidation(): Promise<AlertValidation> {
  const row = await request<Record<string, unknown>>(
    '/api/v1/alert-validation',
  );
  return {
    reviewedAlerts: Number(row.reviewed_alerts),
    confirmedAlerts: Number(row.confirmed_alerts),
    rejectedAlerts: Number(row.rejected_alerts),
    precision: row.precision == null ? null : Number(row.precision),
    falseAlarmRate:
      row.false_alarm_rate == null ? null : Number(row.false_alarm_rate),
    recall: row.recall == null ? null : Number(row.recall),
    medianLeadTimeDays:
      row.median_lead_time_days == null
        ? null
        : Number(row.median_lead_time_days),
    state: row.state as AlertValidation['state'],
    limitations: Array.isArray(row.limitations)
      ? row.limitations.filter(
          (item): item is string => typeof item === 'string',
        )
      : [],
  };
}

export async function patchApiAlert(
  alertId: string,
  fieldId: string,
  patch: {
    state: AlertLifecycleState;
    assignee?: string | null;
    note?: string | null;
  },
): Promise<void> {
  const query = new URLSearchParams({ field_id: fieldId });
  await request(
    `/api/v1/alerts/${encodeURIComponent(alertId)}?${query.toString()}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  );
}

type ApiInspectionPoint = {
  id: string;
  field_id: string;
  alert_id: string | null;
  title: string;
  note: string | null;
  longitude: number;
  latitude: number;
  status: InspectionPoint['status'];
  created_at: string;
  updated_at: string;
};
const fromApiInspection = (row: ApiInspectionPoint): InspectionPoint => ({
  id: row.id,
  fieldId: row.field_id,
  alertId: row.alert_id,
  title: row.title,
  note: row.note,
  longitude: row.longitude,
  latitude: row.latitude,
  status: row.status,
  createdAt: row.created_at,
  updatedAt: row.updated_at,
});
export async function loadApiInspectionPoints(
  fieldId?: string,
): Promise<InspectionPoint[]> {
  const suffix = fieldId ? `?field_id=${encodeURIComponent(fieldId)}` : '';
  return (
    await request<ApiInspectionPoint[]>(`/api/v1/inspection-points${suffix}`)
  ).map(fromApiInspection);
}
export async function createApiInspectionPoint(point: {
  fieldId: string;
  alertId?: string | null;
  title: string;
  note?: string | null;
  longitude: number;
  latitude: number;
}): Promise<InspectionPoint> {
  return fromApiInspection(
    await request<ApiInspectionPoint>('/api/v1/inspection-points', {
      method: 'POST',
      body: JSON.stringify({
        field_id: point.fieldId,
        alert_id: point.alertId ?? null,
        title: point.title,
        note: point.note ?? null,
        longitude: point.longitude,
        latitude: point.latitude,
      }),
    }),
  );
}
export async function patchApiInspectionPoint(
  id: string,
  patch: {
    title?: string;
    status?: InspectionPoint['status'];
    note?: string | null;
  },
): Promise<InspectionPoint> {
  return fromApiInspection(
    await request<ApiInspectionPoint>(`/api/v1/inspection-points/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  );
}
export async function deleteApiInspectionPoint(id: string): Promise<void> {
  await request(`/api/v1/inspection-points/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}
export async function loadApiSpatialRisk(
  fieldId: string,
  sceneDate: string,
): Promise<SpatialRiskResult> {
  const row = await request<Record<string, unknown>>(
    `/api/v1/fields/${fieldId}/spatial-risk?scene_date=${encodeURIComponent(sceneDate)}`,
    undefined,
    95_000,
  );
  const candidates = Array.isArray(row.inspection_candidates)
    ? (row.inspection_candidates as Array<Record<string, unknown>>)
    : [];
  return {
    provider: 'gee',
    satellite: 'Sentinel‑2',
    sceneDate: String(row.scene_date),
    threshold: Number(row.threshold),
    nativeResolutionM: Number(row.native_resolution_m),
    affectedAreaHa: Number(row.affected_area_ha),
    affectedAreaPercent:
      row.affected_area_percent == null
        ? null
        : Number(row.affected_area_percent),
    validAreaHa: Number(row.valid_area_ha),
    inspectionCandidates: candidates
      .filter(
        (item) =>
          typeof item.longitude === 'number' &&
          typeof item.latitude === 'number',
      )
      .map((item) => ({
        title: typeof item.title === 'string' ? item.title : 'Зона осмотра',
        longitude: Number(item.longitude),
        latitude: Number(item.latitude),
      })),
    url: String(row.url),
  };
}
export async function loadApiAnomalies(
  fieldId: string,
): Promise<AnomalyEvent[]> {
  const payload = await request<{ events: Array<Record<string, unknown>> }>(
    `/api/v1/fields/${fieldId}/anomalies`,
    undefined,
    12_000,
  );
  return payload.events.map((row) => ({
    id: String(row.id),
    fieldId: String(row.field_id),
    start: String(row.start),
    end: String(row.end),
    severity: row.severity as AnomalyEvent['severity'],
    title: String(row.title),
    durationDays: Number(row.duration_days),
    minZScore: Number(row.min_zscore),
    deviation: row.deviation == null ? null : Number(row.deviation),
    affectedArea: row.affected_area == null ? null : Number(row.affected_area),
    probableCause: String(row.probable_cause),
    evidence: Array.isArray(row.evidence) ? row.evidence.map(String) : [],
    confidence: Number(row.confidence),
  }));
}
export async function loadApiScenes(
  fieldId: string,
  year?: number,
): Promise<SceneRecord[]> {
  const suffix = year ? `?year=${year}` : '';
  const payload = await request<{ scenes: Array<Record<string, unknown>> }>(
    `/api/v1/fields/${fieldId}/scenes${suffix}`,
    undefined,
    12_000,
  );
  return payload.scenes.map((row) => ({
    id:
      typeof row.scene_id === 'string'
        ? row.scene_id
        : `${String(row.satellite)}-${String(row.date)}`,
    date: String(row.date),
    satellite: row.satellite as SceneRecord['satellite'],
    cloudCover: row.cloud_cover == null ? null : Number(row.cloud_cover),
    validPixels: row.valid_pixels == null ? null : Number(row.valid_pixels),
    provider: row.provider as SceneRecord['provider'],
    ndvi: row.ndvi == null ? null : Number(row.ndvi),
    evi: row.evi == null ? null : Number(row.evi),
    ndwi: row.ndwi == null ? null : Number(row.ndwi),
    temperatureC: row.temperature_c == null ? null : Number(row.temperature_c),
    precipitation7dMm:
      row.precipitation_7d_mm == null ? null : Number(row.precipitation_7d_mm),
  }));
}
export function fieldDatasetUrl(fieldId: string): string {
  return `${API_URL}/api/v1/fields/${fieldId}/dataset.csv`;
}
export async function loadTileDescriptor(
  fieldId: string,
  layer: 'rgb' | 'ndvi' | 'evi' | 'ndwi',
  sceneDate: string,
  satellite: SatelliteId,
  signal?: AbortSignal,
): Promise<{
  provider: string;
  satellite: string;
  native_resolution_m: number;
  url: string;
  expires_in: number;
  requested_date: string;
  scene_date: string;
  cloud_cover: number | null;
}> {
  const query = new URLSearchParams({
    layer,
    scene_date: sceneDate,
    satellite,
  });
  return request(
    `/api/v1/fields/${fieldId}/tile-descriptor?${query.toString()}`,
    { signal },
    30_000,
  );
}
export function watchApiAnalysis(
  jobId: string,
  onProgress: (value: {
    status: string;
    progress: number;
    stage: string;
    error?: string | null;
  }) => void,
  onDone: (value: {
    status: string;
    progress: number;
    stage: string;
    error?: string | null;
  }) => void,
): () => void {
  const stream = new EventSource(
    `${API_URL}/api/v1/analysis-jobs/${jobId}/events`,
  );
  stream.onmessage = (event) => {
    const payload = JSON.parse(event.data) as {
      status: string;
      progress: number;
      stage: string;
      error?: string | null;
    };
    onProgress(payload);
    if (payload.status === 'completed' || payload.status === 'failed') {
      stream.close();
      onDone(payload);
    }
  };
  stream.onerror = () => {
    stream.close();
    onDone({
      status: 'failed',
      progress: 0,
      stage: 'Соединение с анализом потеряно',
      error: 'Не удалось получить состояние фоновой задачи',
    });
  };
  return () => stream.close();
}
