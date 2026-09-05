import { Satellite } from 'lucide-react';

import type { LayerId, LiveLayerState, SatelliteId } from '@/lib/types';

const content: Record<
  string,
  {
    title: string;
    description: string;
    scale?: [string, string, string];
    range?: [string, string];
  }
> = {
  base: {
    title: 'Обычная карта',
    description: 'Дороги и населённые пункты OpenStreetMap.',
  },
  rgb: {
    title: 'Спутниковый RGB',
    description: 'Натуральные цвета поверхности на выбранную дату.',
  },
  ndvi: {
    title: 'NDVI · состояние растительности',
    description:
      'Зелёный — активная растительность, жёлтый и красный — низкие значения.',
    scale: ['#b66835', '#e4c653', '#347348'],
    range: ['0,0', '1,0'],
  },
  evi: {
    title: 'EVI · плотность покрова',
    description: 'Индекс устойчивее на участках с плотной растительностью.',
    scale: ['#b8824d', '#b6c66e', '#2f7d63'],
    range: ['0,0', '1,0'],
  },
  ndwi: {
    title: 'NDWI · обеспеченность влагой',
    description: 'Синий — больше влаги, коричневый — вероятный дефицит.',
    scale: ['#d7a85e', '#8ec7bb', '#247395'],
    range: ['−1,0', '1,0'],
  },
};

const statusLabel: Record<LiveLayerState, string> = {
  idle: 'Нет рассчитанного слоя',
  loading: 'Загружаем спутниковый слой…',
  live: 'Живой тайл Google Earth Engine',
  error: 'Спутниковый слой недоступен',
};

const satelliteLabel: Record<SatelliteId, string> = {
  sentinel2: 'Sentinel‑2 · 10 м',
  landsat: 'Landsat 8/9 · 30 м',
  modis: 'MODIS · 250 м',
};

export default function LayerLegend({
  layer,
  state,
  satellite,
}: {
  layer: LayerId;
  state: LiveLayerState;
  satellite: SatelliteId;
}) {
  const item = content[layer] ?? content.base;
  return (
    <aside className="layer-legend" aria-live="polite">
      <header>
        <Satellite size={15} />
        <span>
          <strong>{item.title}</strong>
          <small>
            {layer === 'base' ? 'OpenStreetMap' : statusLabel[state]}
          </small>
        </span>
      </header>
      {item.scale ? (
        <div className="legend-scale">
          <i
            style={{
              background: `linear-gradient(90deg,${item.scale.join(',')})`,
            }}
          />
          <span>
            <small>{item.range?.[0]}</small>
            <small>{item.range?.[1]}</small>
          </span>
        </div>
      ) : null}
      <p>{item.description}</p>
      {layer !== 'base' ? (
        <div className="legend-note">
          {state === 'live'
            ? `Точная выбранная сцена ${satelliteLabel[satellite]}.`
            : state === 'loading'
              ? `Загружаем выбранную сцену ${satelliteLabel[satellite]}.`
              : state === 'error'
                ? 'Источник не ответил; данные не подменяются.'
                : 'Выберите фактическую сцену, чтобы получить слой.'}
        </div>
      ) : null}
    </aside>
  );
}
