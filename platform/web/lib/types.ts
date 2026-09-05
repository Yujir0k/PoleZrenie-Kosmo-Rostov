export type WorkspaceView = 'fields' | 'anomalies' | 'sources';
export type LayerId =
  | 'base'
  | 'rgb'
  | 'ndvi'
  | 'evi'
  | 'ndwi'
  | 'clouds'
  | 'crops';
export type LiveLayerState = 'idle' | 'loading' | 'live' | 'error';
export type FieldStatus = 'normal' | 'warning' | 'critical';
export type RiskState =
  | 'normal'
  | 'watch'
  | 'early_risk'
  | 'confirmed_anomaly'
  | 'insufficient_data';
export type AlertLifecycleState =
  | 'detected'
  | 'assigned'
  | 'verified'
  | 'confirmed'
  | 'rejected'
  | 'closed';
export type FieldSource = 'osm' | 'drawn';
export type SatelliteId = 'sentinel2' | 'landsat' | 'modis';

export type Position = [number, number];

export interface FieldGeometry {
  type: 'Polygon';
  coordinates: Position[][];
}

export interface FieldRecord {
  id: string;
  name: string;
  crop: string;
  region: string;
  areaHa: number;
  ndvi: number | null;
  delta: number | null;
  status: FieldStatus;
  source: FieldSource;
  geometry: FieldGeometry;
  updatedAt: string;
  validPixels: number | null;
  temperatureC?: number | null;
  precipitation7dMm?: number | null;
  dataProvider?: string | null;
  sceneDate?: string | null;
  weatherDate?: string | null;
  cloudCover?: number | null;
  worldcoverCroplandPercent?: number | null;
  isVerifiedCropland?: boolean | null;
  datasetRows?: number | null;
}

export interface TimeseriesPoint {
  date: string;
  observed: number | null;
  restored: number;
  climateMean: number | null;
  climateLow: number | null;
  climateHigh: number | null;
  confidenceLow: number;
  confidenceHigh: number;
  s2: number | null;
  landsat: number | null;
  modis: number | null;
  temperature: number | null;
  precipitation: number | null;
  isImputed: boolean;
  validPixels: number | null;
  cloudCover: number | null;
  robustMedian: number | null;
  robustQ10: number | null;
  robustQ90: number | null;
  robustZ: number | null;
  normSampleCount: number;
  observationSource: string | null;
}

export interface RiskSignal {
  id: string;
  asOf: string;
  riskState: RiskState;
  riskScore: number;
  confidence: number;
  confidenceLevel: 'high' | 'medium' | 'low' | 'insufficient';
  robustZ: number | null;
  slope14d: number | null;
  projectedRobustZ14d: number | null;
  leadWindowDays: number;
  projectionDisclaimer: string;
  referenceSeasons: number;
  observationSource: string | null;
  observation: string;
  context: string[];
  hypothesis: string;
  recommendation: string;
  affectedAreaHa: number | null;
  affectedAreaPercent: number | null;
  quality: {
    validPixels: number | null;
    cloudCover: number | null;
    normMethod: string;
    causal: boolean;
  };
  workflow: {
    state: AlertLifecycleState;
    assignee: string | null;
    note: string | null;
  };
}

export interface AttentionItem {
  fieldId: string;
  fieldName: string;
  riskState: RiskState;
  signal: RiskSignal | null;
}

export interface AlertValidation {
  reviewedAlerts: number;
  confirmedAlerts: number;
  rejectedAlerts: number;
  precision: number | null;
  falseAlarmRate: number | null;
  recall: number | null;
  medianLeadTimeDays: number | null;
  state: 'measurable' | 'awaiting_field_labels';
  limitations: string[];
}

export interface AnomalyEvent {
  id: string;
  fieldId: string;
  start: string;
  end: string;
  severity: 'warning' | 'critical';
  title: string;
  durationDays: number;
  minZScore: number;
  deviation: number | null;
  affectedArea: number | null;
  probableCause: string;
  evidence: string[];
  confidence: number;
}

export interface SceneRecord {
  id: string;
  date: string;
  satellite: 'Sentinel‑2' | 'Landsat 8/9' | 'MODIS';
  cloudCover: number | null;
  validPixels: number | null;
  provider: 'GEE' | 'CDSE';
  ndvi: number | null;
  evi: number | null;
  ndwi: number | null;
  temperatureC: number | null;
  precipitation7dMm: number | null;
}

export interface ProviderStatus {
  id: 'gee' | 'cdse' | 'osm' | 'era5';
  name: string;
  description: string;
  status: 'connected' | 'unavailable';
  latency: string;
  updatedAt: string;
  datasets: string[];
}

export interface AnalysisJob {
  id: string;
  fieldId: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: string;
  progress: number;
  provider: string;
}

export interface RegionResult {
  id: string;
  name: string;
  displayName: string;
  lat: number;
  lon: number;
  boundingBox: [number, number, number, number];
}

export interface MapNote {
  id: string;
  title: string;
  text: string | null;
  longitude: number;
  latitude: number;
  fieldId: string | null;
  createdAt: string;
}

export interface InspectionPoint {
  id: string;
  fieldId: string;
  alertId: string | null;
  title: string;
  note: string | null;
  longitude: number;
  latitude: number;
  status: 'planned' | 'visited' | 'confirmed' | 'rejected';
  createdAt: string;
  updatedAt: string;
}

export interface SpatialRiskResult {
  provider: 'gee';
  satellite: 'Sentinel‑2';
  sceneDate: string;
  threshold: number;
  nativeResolutionM: number;
  affectedAreaHa: number;
  affectedAreaPercent: number | null;
  validAreaHa: number;
  inspectionCandidates: Array<{
    title: string;
    longitude: number;
    latitude: number;
  }>;
  url: string;
}

export interface AIVisualizationPoint {
  date: string;
  value: number | null;
  normal: number | null;
  restored: boolean;
}

export interface AIVisualization {
  kind: 'ndvi_chart' | 'field_contour';
  title: string;
  subtitle: string;
  data?: AIVisualizationPoint[];
  geometry?: FieldGeometry;
}

export interface AIResponse {
  fieldId: string;
  message: string;
  model: string;
  usedTools: string[];
  visualizations: AIVisualization[];
}

export interface AIStatus {
  configured: boolean;
  provider: string;
  models: {
    chat: string;
    report: string;
    vision: string;
  };
  dataLogging: boolean;
}
