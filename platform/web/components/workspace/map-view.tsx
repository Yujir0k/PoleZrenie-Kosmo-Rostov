'use client';
/* oxlint-disable react-hooks/exhaustive-deps -- MapLibre is initialized once; dedicated effects synchronize mutable inputs. */

import 'maplibre-gl/dist/maplibre-gl.css';

import { area, bbox, feature, featureCollection } from '@turf/turf';
import {
  Check,
  Crosshair,
  Layers3,
  LocateFixed,
  Redo2,
  Trash2,
  Undo2,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import * as maplibregl from 'maplibre-gl';
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { useEffect, useRef, useState } from 'react';
import {
  TerraDraw,
  TerraDrawModeUndoRedo,
  TerraDrawPolygonMode,
  TerraDrawSelectMode,
  TerraDrawSessionUndoRedo,
  ValidateMaxAreaSquareMeters,
  ValidateNotSelfIntersecting,
} from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';

import { loadTileDescriptor } from '@/lib/api';
import type {
  FieldGeometry,
  FieldRecord,
  InspectionPoint,
  LayerId,
  LiveLayerState,
  MapNote,
  Position,
  RegionResult,
  SatelliteId,
} from '@/lib/types';

maplibregl.setWorkerUrl(workerUrl);

interface MapViewProps {
  fields: FieldRecord[];
  candidates: FieldRecord[];
  selectedFieldId: string;
  layer: LayerId;
  date: string;
  satellite: SatelliteId;
  drawing: boolean;
  choosingCandidate: boolean;
  selectedCandidateId?: string;
  notes: MapNote[];
  inspectionPoints: InspectionPoint[];
  focusedInspectionId: string;
  spatialRiskUrl: string | null;
  comparisonDate: string | null;
  comparisonBlend: number;
  placingNote: boolean;
  selectedNoteId: string;
  liveTilesEnabled: boolean;
  onLiveLayerStateChange: (state: LiveLayerState) => void;
  focusRegion: RegionResult | null;
  onSelectField: (id: string) => void;
  onSelectCandidate: (id: string) => void;
  onPlaceNote: (position: Position) => void;
  onSelectNote: (id: string) => void;
  onSelectInspection: (id: string) => void;
  onDraftGeometry: (geometry: FieldGeometry, areaHa: number) => void;
  onFinishDrawing: () => void;
  onCancelDrawing: () => void;
}

function fillExpression(
  layer: LayerId,
): maplibregl.ExpressionSpecification | string {
  if (layer === 'ndvi')
    return [
      'interpolate',
      ['linear'],
      ['get', 'ndvi'],
      0.15,
      '#b66835',
      0.35,
      '#e4c653',
      0.55,
      '#8fbd58',
      0.75,
      '#347348',
    ];
  if (layer === 'evi')
    return [
      'interpolate',
      ['linear'],
      ['get', 'ndvi'],
      0.15,
      '#b8824d',
      0.45,
      '#b6c66e',
      0.75,
      '#2f7d63',
    ];
  if (layer === 'ndwi')
    return [
      'interpolate',
      ['linear'],
      ['get', 'ndvi'],
      0.15,
      '#d7a85e',
      0.45,
      '#8ec7bb',
      0.75,
      '#247395',
    ];
  if (layer === 'rgb')
    return [
      'match',
      ['get', 'status'],
      'critical',
      '#ad8551',
      'warning',
      '#8fa465',
      '#6d9c62',
    ];
  return [
    'match',
    ['get', 'status'],
    'critical',
    '#d94b45',
    'warning',
    '#f3a83b',
    '#4f9561',
  ];
}

function fillOpacity(
  layer: LayerId,
): maplibregl.ExpressionSpecification | number {
  if (
    layer === 'rgb' ||
    layer === 'ndvi' ||
    layer === 'evi' ||
    layer === 'ndwi'
  )
    return 0;
  const available = layer === 'base' ? 0.18 : layer === 'clouds' ? 0.14 : 0;
  return [
    'case',
    ['boolean', ['get', 'dataAvailable'], false],
    available,
    0.04,
  ];
}

function asFeatureCollection(fields: FieldRecord[]) {
  return featureCollection(
    fields.map((field) =>
      feature(field.geometry, {
        id: field.id,
        name: field.name,
        ndvi:
          field.dataProvider === 'gee' && field.ndvi != null
            ? field.ndvi
            : null,
        status: field.status,
        dataAvailable: field.dataProvider === 'gee',
      }),
    ),
  );
}

function asNoteFeatureCollection(notes: MapNote[]) {
  return featureCollection(
    notes.map((note) =>
      feature(
        { type: 'Point', coordinates: [note.longitude, note.latitude] },
        { id: note.id, title: note.title },
      ),
    ),
  );
}

function asInspectionFeatureCollection(points: InspectionPoint[]) {
  return featureCollection(
    points.map((point, index) =>
      feature(
        { type: 'Point', coordinates: [point.longitude, point.latitude] },
        {
          id: point.id,
          title: point.title,
          status: point.status,
          number: index + 1,
        },
      ),
    ),
  );
}

const inspectionStatusLabel: Record<InspectionPoint['status'], string> = {
  planned: 'Запланирована',
  visited: 'Посещена',
  confirmed: 'Проблема подтверждена',
  rejected: 'Проблема не найдена',
};

export default function MapView({
  fields,
  candidates,
  selectedFieldId,
  layer,
  date,
  satellite,
  drawing,
  choosingCandidate,
  selectedCandidateId,
  notes,
  inspectionPoints,
  focusedInspectionId,
  spatialRiskUrl,
  comparisonDate,
  comparisonBlend,
  placingNote,
  selectedNoteId,
  liveTilesEnabled,
  focusRegion,
  onLiveLayerStateChange,
  onSelectField,
  onSelectCandidate,
  onPlaceNote,
  onSelectNote,
  onSelectInspection,
  onDraftGeometry,
  onFinishDrawing,
  onCancelDrawing,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const latestGeometryRef = useRef<FieldGeometry | null>(null);
  const modeRef = useRef({ drawing, choosingCandidate, placingNote });
  const mapActionsRef = useRef({
    onPlaceNote,
    onSelectNote,
    onSelectInspection,
  });
  const inspectionPointsRef = useRef(inspectionPoints);
  const comparisonBlendRef = useRef(comparisonBlend);
  const [ready, setReady] = useState(false);
  const [drawReady, setDrawReady] = useState(false);

  useEffect(() => {
    modeRef.current = { drawing, choosingCandidate, placingNote };
  }, [drawing, choosingCandidate, placingNote]);
  useEffect(() => {
    mapActionsRef.current = { onPlaceNote, onSelectNote, onSelectInspection };
  }, [onPlaceNote, onSelectInspection, onSelectNote]);
  useEffect(() => {
    inspectionPointsRef.current = inspectionPoints;
  }, [inspectionPoints]);
  useEffect(() => {
    comparisonBlendRef.current = comparisonBlend;
  }, [comparisonBlend]);

  // MapLibre owns one imperative lifecycle; later effects synchronize changing data and styles.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [39.79, 47.27],
      zoom: 10.7,
      minZoom: 3,
      maxZoom: 18,
      attributionControl: false,
      style: {
        version: 8,
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap',
          },
          imagery: {
            type: 'raster',
            tiles: [
              'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            ],
            tileSize: 256,
            attribution: 'Imagery © Esri',
          },
        },
        layers: [
          {
            id: 'basemap',
            type: 'raster',
            source: 'osm',
            layout: { visibility: layer === 'base' ? 'visible' : 'none' },
            paint: {
              'raster-saturation': -0.46,
              'raster-contrast': -0.08,
              'raster-brightness-max': 0.9,
            },
          },
          {
            id: 'imagery-basemap',
            type: 'raster',
            source: 'imagery',
            layout: { visibility: layer === 'base' ? 'none' : 'visible' },
            paint: {
              'raster-saturation': -0.16,
              'raster-contrast': 0.05,
              'raster-brightness-max': 0.82,
            },
          },
        ],
      },
    });
    map.on('error', () => {
      // Отдельный недоступный растровый тайл не должен ломать карту или засорять консоль;
      // MapLibre продолжит показывать уже загруженные соседние тайлы.
    });
    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      'bottom-left',
    );
    map.once('style.load', () => {
      map.addSource('fields', {
        type: 'geojson',
        data: asFeatureCollection(fields),
      });
      map.addLayer({
        id: 'field-fill',
        type: 'fill',
        source: 'fields',
        paint: {
          'fill-color': fillExpression(layer),
          'fill-opacity': fillOpacity(layer),
        },
      });
      map.addLayer({
        id: 'field-selected-glow',
        type: 'line',
        source: 'fields',
        paint: {
          'line-color': '#b9e36c',
          'line-width': 9,
          'line-blur': 6,
          'line-opacity': [
            'case',
            ['==', ['get', 'id'], selectedFieldId],
            0.52,
            0,
          ],
        },
      });
      map.addLayer({
        id: 'field-outline',
        type: 'line',
        source: 'fields',
        paint: {
          'line-color': [
            'case',
            ['==', ['get', 'id'], selectedFieldId],
            '#c9ef79',
            '#fffef8',
          ],
          'line-width': ['case', ['==', ['get', 'id'], selectedFieldId], 4, 2],
          'line-opacity': 0.98,
        },
      });
      map.addSource('candidates', {
        type: 'geojson',
        data: asFeatureCollection(candidates),
      });
      map.addLayer({
        id: 'candidate-fill',
        type: 'fill',
        source: 'candidates',
        layout: { visibility: 'none' },
        paint: {
          'fill-color': '#b9e36c',
          'fill-opacity': [
            'case',
            ['==', ['get', 'id'], selectedCandidateId ?? ''],
            0.55,
            0.2,
          ],
        },
      });
      map.addLayer({
        id: 'candidate-outline',
        type: 'line',
        source: 'candidates',
        layout: { visibility: 'none' },
        paint: {
          'line-color': '#173f35',
          'line-width': [
            'case',
            ['==', ['get', 'id'], selectedCandidateId ?? ''],
            4,
            2,
          ],
          'line-dasharray': [2, 1],
        },
      });
      map.addSource('notes', {
        type: 'geojson',
        data: asNoteFeatureCollection(notes),
      });
      map.addLayer({
        id: 'note-halo',
        type: 'circle',
        source: 'notes',
        paint: {
          'circle-radius': 11,
          'circle-color': 'rgba(185,227,108,.34)',
          'circle-blur': 0.18,
        },
      });
      map.addLayer({
        id: 'note-point',
        type: 'circle',
        source: 'notes',
        paint: {
          'circle-radius': [
            'case',
            ['==', ['get', 'id'], selectedNoteId],
            8,
            6,
          ],
          'circle-color': '#173f35',
          'circle-stroke-color': '#fffef8',
          'circle-stroke-width': 3,
        },
      });
      map.addSource('inspection-points', {
        type: 'geojson',
        data: asInspectionFeatureCollection(inspectionPoints),
      });
      map.addLayer({
        id: 'inspection-halo',
        type: 'circle',
        source: 'inspection-points',
        paint: {
          'circle-radius': 14,
          'circle-color': 'rgba(238,163,58,.25)',
          'circle-blur': 0.15,
        },
      });
      map.addLayer({
        id: 'inspection-point',
        type: 'circle',
        source: 'inspection-points',
        paint: {
          'circle-radius': [
            'case',
            ['==', ['get', 'id'], focusedInspectionId],
            10,
            7,
          ],
          'circle-color': [
            'match',
            ['get', 'status'],
            'confirmed',
            '#c84f45',
            'rejected',
            '#7c8982',
            'visited',
            '#3f8760',
            '#eea33a',
          ],
          'circle-stroke-color': '#fffef8',
          'circle-stroke-width': [
            'case',
            ['==', ['get', 'id'], focusedInspectionId],
            4,
            3,
          ],
        },
      });
      map.addLayer({
        id: 'inspection-label',
        type: 'symbol',
        source: 'inspection-points',
        layout: {
          'text-field': ['to-string', ['get', 'number']],
          'text-font': ['Open Sans Regular'],
          'text-size': 10,
          'text-offset': [0, 0],
          'text-anchor': 'center',
          'text-allow-overlap': true,
        },
        paint: {
          'text-color': '#fffef8',
          'text-halo-color': 'rgba(23,63,53,.35)',
          'text-halo-width': 1,
        },
      });
      map.on('mouseenter', 'field-fill', () => {
        if (!modeRef.current.placingNote)
          map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', 'field-fill', () => {
        map.getCanvas().style.cursor = modeRef.current.placingNote
          ? 'crosshair'
          : '';
      });
      map.on('click', 'field-fill', (event) => {
        if (
          modeRef.current.drawing ||
          modeRef.current.choosingCandidate ||
          modeRef.current.placingNote
        )
          return;
        const id = event.features?.[0]?.properties?.id;
        if (typeof id === 'string') onSelectField(id);
      });
      map.on('click', 'candidate-fill', (event) => {
        if (!modeRef.current.choosingCandidate) return;
        const id = event.features?.[0]?.properties?.id;
        if (typeof id === 'string') onSelectCandidate(id);
      });
      map.on('mouseenter', 'note-point', () => {
        if (!modeRef.current.placingNote)
          map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', 'note-point', () => {
        map.getCanvas().style.cursor = modeRef.current.placingNote
          ? 'crosshair'
          : '';
      });
      map.on('click', 'note-point', (event) => {
        if (modeRef.current.placingNote) return;
        const id = event.features?.[0]?.properties?.id;
        if (typeof id === 'string') mapActionsRef.current.onSelectNote(id);
      });
      map.on('mouseenter', 'inspection-point', () => {
        if (!modeRef.current.placingNote)
          map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', 'inspection-point', () => {
        map.getCanvas().style.cursor = modeRef.current.placingNote
          ? 'crosshair'
          : '';
      });
      map.on('click', 'inspection-point', (event) => {
        if (modeRef.current.placingNote) return;
        const id = event.features?.[0]?.properties?.id;
        if (typeof id !== 'string') return;
        const point = inspectionPointsRef.current.find(
          (item) => item.id === id,
        );
        if (!point) return;

        const content = document.createElement('div');
        content.className = 'inspection-popup-content';
        const eyebrow = document.createElement('span');
        eyebrow.textContent = inspectionStatusLabel[point.status];
        const title = document.createElement('strong');
        title.textContent = point.title;
        const description = document.createElement('p');
        description.textContent =
          point.note ||
          'Откройте карточку осмотра, чтобы увидеть задачу и зафиксировать результат.';
        const action = document.createElement('small');
        action.textContent = 'Карточка точки открыта справа';
        content.appendChild(eyebrow);
        content.appendChild(title);
        content.appendChild(description);
        content.appendChild(action);
        new maplibregl.Popup({
          offset: 16,
          closeButton: true,
          className: 'inspection-map-popup',
        })
          .setLngLat([point.longitude, point.latitude])
          .setDOMContent(content)
          .addTo(map);
        mapActionsRef.current.onSelectInspection(id);
      });
      map.on('click', (event) => {
        if (!modeRef.current.placingNote) return;
        mapActionsRef.current.onPlaceNote([event.lngLat.lng, event.lngLat.lat]);
      });

      const draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map }),
        modes: [
          new TerraDrawPolygonMode({
            editable: true,
            showCoordinatePoints: true,
            validation: (featureToValidate) => {
              const selfIntersection =
                ValidateNotSelfIntersecting(featureToValidate);
              if (!selfIntersection.valid) return selfIntersection;
              return ValidateMaxAreaSquareMeters(featureToValidate, 50_000_000);
            },
            styles: {
              fillColor: '#b9e36c',
              fillOpacity: 0.28,
              outlineColor: '#173f35',
              outlineWidth: 3,
              closingPointColor: '#b9e36c',
              closingPointOutlineColor: '#173f35',
              closingPointWidth: 8,
              coordinatePointColor: '#fffef8',
              coordinatePointOutlineColor: '#173f35',
              coordinatePointWidth: 6,
            },
          }),
          new TerraDrawSelectMode({
            flags: {
              polygon: {
                feature: {
                  draggable: true,
                  selfIntersectable: false,
                  coordinates: {
                    midpoints: true,
                    draggable: true,
                    deletable: true,
                  },
                },
              },
            },
            styles: {
              selectedPolygonColor: '#b9e36c',
              selectedPolygonFillOpacity: 0.35,
              selectedPolygonOutlineColor: '#173f35',
              selectedPolygonOutlineWidth: 3,
              selectionPointColor: '#fffef8',
              selectionPointOutlineColor: '#173f35',
              midPointColor: '#b9e36c',
              midPointOutlineColor: '#173f35',
            },
          }),
        ],
        undoRedo: {
          modeLevel: new TerraDrawModeUndoRedo(),
          sessionLevel: new TerraDrawSessionUndoRedo(),
        },
      });
      draw.start();
      const publishGeometry = () => {
        const polygon = draw
          .getSnapshot()
          .find((item) => item.geometry.type === 'Polygon');
        if (!polygon || polygon.geometry.type !== 'Polygon') {
          latestGeometryRef.current = null;
          setDrawReady(false);
          return;
        }
        const geometry = polygon.geometry as FieldGeometry;
        const areaHa = area(polygon) / 10_000;
        const coordinateCount = geometry.coordinates[0]?.length ?? 0;
        const validShape =
          coordinateCount >= 4 &&
          areaHa > 0 &&
          areaHa <= 5_000 &&
          ValidateNotSelfIntersecting(polygon).valid;
        latestGeometryRef.current = geometry;
        onDraftGeometry(geometry, areaHa);
        setDrawReady(validShape);
      };
      draw.on('finish', () => {
        publishGeometry();
        draw.setMode('select');
        setDrawReady(true);
      });
      draw.on('change', publishGeometry);
      drawRef.current = draw;
      setReady(true);
    });

    const observer = new ResizeObserver(() => map.resize());
    observer.observe(containerRef.current);
    mapRef.current = map;
    return () => {
      observer.disconnect();
      drawRef.current?.stop();
      map.remove();
      mapRef.current = null;
      drawRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    const source = mapRef.current.getSource('fields') as
      | GeoJSONSource
      | undefined;
    void source?.setData(asFeatureCollection(fields));
  }, [fields, ready]);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    const source = mapRef.current.getSource('candidates') as
      | GeoJSONSource
      | undefined;
    void source?.setData(asFeatureCollection(candidates));
  }, [candidates, ready]);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    const source = mapRef.current.getSource('notes') as
      | GeoJSONSource
      | undefined;
    void source?.setData(asNoteFeatureCollection(notes));
  }, [notes, ready]);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    const source = mapRef.current.getSource('inspection-points') as
      | GeoJSONSource
      | undefined;
    void source?.setData(asInspectionFeatureCollection(inspectionPoints));
  }, [inspectionPoints, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (map.getLayer('spatial-risk-tile')) map.removeLayer('spatial-risk-tile');
    if (map.getSource('spatial-risk-tile'))
      map.removeSource('spatial-risk-tile');
    if (!spatialRiskUrl) return;
    map.addSource('spatial-risk-tile', {
      type: 'raster',
      tiles: [spatialRiskUrl],
      tileSize: 256,
    });
    map.addLayer(
      {
        id: 'spatial-risk-tile',
        type: 'raster',
        source: 'spatial-risk-tile',
        paint: { 'raster-opacity': 0.52, 'raster-fade-duration': 0 },
      },
      map.getLayer('field-outline') ? 'field-outline' : undefined,
    );
    return () => {
      if (map.getLayer('spatial-risk-tile'))
        map.removeLayer('spatial-risk-tile');
      if (map.getSource('spatial-risk-tile'))
        map.removeSource('spatial-risk-tile');
    };
  }, [ready, spatialRiskUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map?.getLayer('note-point')) return;
    map.setPaintProperty('note-point', 'circle-radius', [
      'case',
      ['==', ['get', 'id'], selectedNoteId],
      8,
      6,
    ]);
    const note = notes.find((item) => item.id === selectedNoteId);
    if (note)
      map.easeTo({ center: [note.longitude, note.latitude], duration: 480 });
  }, [notes, ready, selectedNoteId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map?.getLayer('inspection-point')) return;
    map.setPaintProperty('inspection-point', 'circle-radius', [
      'case',
      ['==', ['get', 'id'], focusedInspectionId],
      10,
      7,
    ]);
    map.setPaintProperty('inspection-point', 'circle-stroke-width', [
      'case',
      ['==', ['get', 'id'], focusedInspectionId],
      4,
      3,
    ]);
    const point = inspectionPoints.find(
      (item) => item.id === focusedInspectionId,
    );
    if (point)
      map.easeTo({
        center: [point.longitude, point.latitude],
        zoom: 15.4,
        duration: 650,
      });
  }, [focusedInspectionId, inspectionPoints, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.getCanvas().style.cursor = placingNote ? 'crosshair' : '';
  }, [placingNote, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    let cancelled = false;
    const controller = new AbortController();
    const removeRaster = () => {
      if (map.getLayer('live-satellite')) map.removeLayer('live-satellite');
      if (map.getSource('live-satellite')) map.removeSource('live-satellite');
    };
    const selected = fields.find((field) => field.id === selectedFieldId);
    if (
      !liveTilesEnabled ||
      layer === 'base' ||
      layer === 'clouds' ||
      layer === 'crops' ||
      !selectedFieldId ||
      selected?.dataProvider !== 'gee' ||
      !date
    ) {
      removeRaster();
      onLiveLayerStateChange('idle');
      return;
    }
    onLiveLayerStateChange('loading');
    const requestTimer = window.setTimeout(
      () =>
        void loadTileDescriptor(
          selectedFieldId,
          layer,
          date,
          satellite,
          controller.signal,
        )
          .then((descriptor) => {
            if (cancelled) return;
            removeRaster();
            map.addSource('live-satellite', {
              type: 'raster',
              tiles: [descriptor.url],
              tileSize: 256,
            });
            map.addLayer(
              {
                id: 'live-satellite',
                type: 'raster',
                source: 'live-satellite',
                paint: {
                  'raster-opacity': comparisonDate ? comparisonBlend : 0.94,
                  'raster-fade-duration': 180,
                },
              },
              map.getLayer('field-fill') ? 'field-fill' : undefined,
            );
            onLiveLayerStateChange('live');
          })
          .catch(() => {
            if (!cancelled) onLiveLayerStateChange('error');
          }),
      180,
    );
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(requestTimer);
    };
  }, [
    comparisonDate,
    date,
    fields,
    layer,
    liveTilesEnabled,
    ready,
    satellite,
    selectedFieldId,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    let cancelled = false;
    const controller = new AbortController();
    const remove = () => {
      if (map.getLayer('compare-satellite'))
        map.removeLayer('compare-satellite');
      if (map.getSource('compare-satellite'))
        map.removeSource('compare-satellite');
    };
    if (
      !comparisonDate ||
      !selectedFieldId ||
      layer === 'base' ||
      layer === 'clouds' ||
      layer === 'crops'
    ) {
      remove();
      return;
    }
    void loadTileDescriptor(
      selectedFieldId,
      layer,
      comparisonDate,
      satellite,
      controller.signal,
    )
      .then((descriptor) => {
        if (cancelled) return;
        remove();
        map.addSource('compare-satellite', {
          type: 'raster',
          tiles: [descriptor.url],
          tileSize: 256,
        });
        map.addLayer(
          {
            id: 'compare-satellite',
            type: 'raster',
            source: 'compare-satellite',
            paint: {
              'raster-opacity': 1 - comparisonBlendRef.current,
              'raster-fade-duration': 0,
            },
          },
          map.getLayer('live-satellite') ? 'live-satellite' : undefined,
        );
      })
      .catch(() => remove());
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [comparisonDate, layer, ready, satellite, selectedFieldId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (map.getLayer('live-satellite'))
      map.setPaintProperty(
        'live-satellite',
        'raster-opacity',
        comparisonDate ? comparisonBlend : 0.94,
      );
    if (map.getLayer('compare-satellite'))
      map.setPaintProperty(
        'compare-satellite',
        'raster-opacity',
        1 - comparisonBlend,
      );
  }, [comparisonBlend, comparisonDate, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map?.getLayer('field-fill')) return;
    if (map.getLayer('basemap'))
      map.setLayoutProperty(
        'basemap',
        'visibility',
        layer === 'base' ? 'visible' : 'none',
      );
    if (map.getLayer('imagery-basemap'))
      map.setLayoutProperty(
        'imagery-basemap',
        'visibility',
        layer === 'base' ? 'none' : 'visible',
      );
    map.setPaintProperty('field-fill', 'fill-color', fillExpression(layer));
    map.setPaintProperty('field-fill', 'fill-opacity', fillOpacity(layer));
  }, [layer, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focusRegion) return;
    const [south, north, west, east] = focusRegion.boundingBox;
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      {
        padding: { top: 125, right: 80, bottom: 120, left: 80 },
        duration: 850,
        maxZoom: 12.5,
      },
    );
  }, [focusRegion, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map?.getLayer('field-outline')) return;
    map.setPaintProperty('field-selected-glow', 'line-opacity', [
      'case',
      ['==', ['get', 'id'], selectedFieldId],
      0.52,
      0,
    ]);
    map.setPaintProperty('field-outline', 'line-color', [
      'case',
      ['==', ['get', 'id'], selectedFieldId],
      '#c9ef79',
      '#fffef8',
    ]);
    map.setPaintProperty('field-outline', 'line-width', [
      'case',
      ['==', ['get', 'id'], selectedFieldId],
      4,
      2,
    ]);
    const selected = fields.find((field) => field.id === selectedFieldId);
    if (selected && !drawing && !choosingCandidate) {
      const bounds = bbox(feature(selected.geometry));
      map.fitBounds(
        [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[3]],
        ],
        {
          padding: { top: 130, right: 360, bottom: 155, left: 80 },
          duration: 700,
          maxZoom: 13.2,
        },
      );
    }
  }, [selectedFieldId, fields, drawing, choosingCandidate, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map?.getLayer('candidate-fill')) return;
    const visibility = choosingCandidate ? 'visible' : 'none';
    map.setLayoutProperty('candidate-fill', 'visibility', visibility);
    map.setLayoutProperty('candidate-outline', 'visibility', visibility);
    map.setPaintProperty('candidate-fill', 'fill-opacity', [
      'case',
      ['==', ['get', 'id'], selectedCandidateId ?? ''],
      0.55,
      0.2,
    ]);
    map.setPaintProperty('candidate-outline', 'line-width', [
      'case',
      ['==', ['get', 'id'], selectedCandidateId ?? ''],
      4,
      2,
    ]);
    if (choosingCandidate) {
      if (!candidates.length) return;
      const collection = asFeatureCollection(candidates);
      const bounds = bbox(collection);
      map.fitBounds(
        [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[3]],
        ],
        { padding: 80, duration: 650, maxZoom: 13 },
      );
    }
  }, [candidates, choosingCandidate, selectedCandidateId, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !choosingCandidate || !selectedCandidateId) return;
    const selected = candidates.find((item) => item.id === selectedCandidateId);
    if (!selected) return;
    const bounds = bbox(feature(selected.geometry));
    map.fitBounds(
      [
        [bounds[0], bounds[1]],
        [bounds[2], bounds[3]],
      ],
      {
        padding: { top: 90, right: 90, bottom: 90, left: 390 },
        duration: 520,
        maxZoom: 14,
      },
    );
  }, [candidates, choosingCandidate, ready, selectedCandidateId]);

  useEffect(() => {
    const draw = drawRef.current;
    if (!ready || !draw) return;
    if (drawing) {
      draw.clear();
      latestGeometryRef.current = null;
      queueMicrotask(() => setDrawReady(false));
      draw.setMode('polygon');
      mapRef.current?.getCanvas().focus();
    } else if (draw.enabled) {
      draw.clear();
      queueMicrotask(() => setDrawReady(false));
    }
  }, [drawing, ready]);

  const zoom = (delta: number) =>
    mapRef.current?.easeTo({
      zoom: (mapRef.current?.getZoom() ?? 10) + delta,
      duration: 280,
    });
  const locate = () =>
    navigator.geolocation?.getCurrentPosition(({ coords }) =>
      mapRef.current?.flyTo({
        center: [coords.longitude, coords.latitude],
        zoom: 13,
      }),
    );

  return (
    <div className="real-map-wrap">
      <div ref={containerRef} className="real-map" />
      {!ready && (
        <div className="map-loading">
          <span />
          Загружаем карту…
        </div>
      )}
      <div className="map-controls actual-map-controls">
        <button onClick={() => zoom(1)} aria-label="Приблизить">
          <ZoomIn size={19} />
        </button>
        <button onClick={() => zoom(-1)} aria-label="Отдалить">
          <ZoomOut size={19} />
        </button>
        <button aria-label="Слои карты">
          <Layers3 size={19} />
        </button>
        <button onClick={locate} aria-label="Моё местоположение">
          <LocateFixed size={19} />
        </button>
      </div>
      {drawing && (
        <div
          className="draw-toolbar"
          role="toolbar"
          aria-label="Редактор контура"
        >
          <div className="draw-instruction">
            <Crosshair size={18} />
            <span>
              <strong>
                {drawReady
                  ? 'Контур готов к сохранению'
                  : 'Рисуйте по границе поля'}
              </strong>
              <small>
                {drawReady
                  ? 'Перетаскивайте вершины для уточнения'
                  : 'Кликайте по карте, замкните контур первой точкой'}
              </small>
            </span>
          </div>
          <div className="draw-actions">
            <button
              onClick={() => drawRef.current?.undo()}
              aria-label="Отменить"
            >
              <Undo2 size={18} />
            </button>
            <button
              onClick={() => drawRef.current?.redo()}
              aria-label="Повторить"
            >
              <Redo2 size={18} />
            </button>
            <button
              onClick={() => {
                drawRef.current?.clear();
                latestGeometryRef.current = null;
                setDrawReady(false);
                drawRef.current?.setMode('polygon');
              }}
              aria-label="Очистить"
            >
              <Trash2 size={18} />
            </button>
            <button className="draw-cancel" onClick={onCancelDrawing}>
              <X size={18} /> Отмена
            </button>
            <button
              className="draw-save"
              disabled={!drawReady}
              onClick={onFinishDrawing}
            >
              <Check size={18} /> Готово
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
