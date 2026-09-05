'use client';

import {
  BadgeCheck,
  CalendarDays,
  CloudSun,
  Info,
  Move,
  RotateCcw,
  Sprout,
  SlidersHorizontal,
  TriangleAlert,
  X,
} from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select';
import { loadApiTimeseries } from '@/lib/api';
import type { FieldRecord, TimeseriesPoint } from '@/lib/types';

interface AnalysisChartProps {
  field: FieldRecord;
  season: number;
  selectedDate: string;
  onClose: () => void;
  onDateSelect: (date: string) => void;
}
type Range = 'all' | '30' | '60' | '90';
type ChartMode = 'vegetation' | 'risk' | 'weather' | 'quality';
type Visibility = {
  observed: boolean;
  restored: boolean;
  norm: boolean;
  sensors: boolean;
  compare: boolean;
  zScore: boolean;
  weather: boolean;
};
const shortDate = (value: string) =>
  new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short' }).format(
    new Date(`${value}T12:00:00`),
  );
const rangeLabel: Record<Range, string> = {
  all: 'Весь сезон',
  90: 'Последние 90 дней',
  60: 'Последние 60 дней',
  30: 'Последние 30 дней',
};
const chartModeLabel: Record<ChartMode, string> = {
  vegetation: 'Динамика NDVI',
  risk: 'Ранние риски',
  weather: 'Погода и отклик',
  quality: 'Надёжность данных',
};

const valueOrDash = (value: number | null, digits = 2) =>
  value == null ? '—' : value.toFixed(digits).replace('.', ',');

const mean = (values: Array<number | null>) => {
  const valid = values.filter((value): value is number => value != null);
  return valid.length
    ? valid.reduce((total, value) => total + value, 0) / valid.length
    : null;
};

const sum = (values: Array<number | null>) => {
  const valid = values.filter((value): value is number => value != null);
  return valid.length
    ? valid.reduce((total, value) => total + value, 0)
    : null;
};

function modeTooltip(mode: ChartMode, point: TimeseriesPoint) {
  const date = new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date(`${point.date}T12:00:00`));
  const uncertainty = (point.confidenceHigh - point.confidenceLow) / 2;
  const rows =
    mode === 'risk'
      ? [
          ['Индекс отклонения', valueOrDash(point.robustZ)],
          [
            'Оценка',
            point.robustZ == null
              ? 'недостаточно данных'
              : point.robustZ <= -2
                ? 'аномалия'
                : point.robustZ <= -1.2
                  ? 'ранний риск'
                  : 'в пределах нормы',
          ],
          ['NDVI / медиана', `${valueOrDash(point.restored)} / ${valueOrDash(point.robustMedian)}`],
          ['Исторических сезонов', String(point.normSampleCount)],
        ]
      : mode === 'weather'
        ? [
            ['NDVI', valueOrDash(point.observed ?? point.restored)],
            ['Температура', `${valueOrDash(point.temperature, 1)} °C`],
            ['Осадки', `${valueOrDash(point.precipitation, 1)} мм`],
            ['Источник снимка', point.observationSource ?? 'нет фактической сцены'],
          ]
        : [
            ['Источник', point.observationSource ?? 'нет фактической сцены'],
            ['Факт / модель', `${valueOrDash(point.observed)} / ${valueOrDash(point.restored)}`],
            ['Неопределённость', `±${uncertainty.toFixed(3).replace('.', ',')}`],
            ['Облачность', point.cloudCover == null ? '—' : `${valueOrDash(point.cloudCover, 1)}%`],
            ['Валидные пиксели', point.validPixels == null ? '—' : String(Math.round(point.validPixels))],
          ];
  return `<b>${date}</b><div class="chart-tooltip-grid">${rows
    .map(([label, value]) => `<span>${label}</span><b>${value}</b>`)
    .join('')}</div>`;
}

function buildFocusedOption(
  mode: Exclude<ChartMode, 'vegetation'>,
  points: TimeseriesPoint[],
  selectedPoint: TimeseriesPoint | null,
  labelInterval: number,
) {
  const dates = points.map((point) => point.date);
  const commonXAxis = (gridIndex: number, showLabels: boolean) => ({
    type: 'category',
    gridIndex,
    data: dates,
    boundaryGap: false,
    axisLine: { lineStyle: { color: '#dce2d7' } },
    axisTick: { show: false },
    axisLabel: {
      show: showLabels,
      color: '#738078',
      fontSize: 10,
      formatter: shortDate,
      interval: labelInterval,
      hideOverlap: true,
    },
  });
  const selectedMarker = selectedPoint
    ? {
        name: 'Выбранная дата',
        type: 'line',
        data: points.map(() => null),
        symbol: 'none',
        silent: true,
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            {
              xAxis: selectedPoint.date,
              lineStyle: { color: '#e09b32', width: 1.5, type: 'dashed' },
              label: { show: false },
            },
          ],
        },
      }
    : null;
  const shared = {
    animationDuration: 350,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#173f35',
      borderWidth: 0,
      padding: [11, 13],
      textStyle: { color: '#fff', fontSize: 11 },
      formatter: (items: Array<{ dataIndex: number }>) => {
        const point = points[items[0]?.dataIndex];
        return point ? modeTooltip(mode, point) : '';
      },
    },
  };

  if (mode === 'risk') {
    return {
      ...shared,
      title: {
        text: 'Отклонение от сезонной нормы · модель раннего риска',
        subtext:
          'Ниже −1,2 — ранний сигнал, ниже −2 — аномалия. Чем ниже линия, тем сильнее отклонение.',
        left: 58,
        top: 4,
        textStyle: { color: '#21382e', fontSize: 13, fontWeight: 700 },
        subtextStyle: { color: '#75827b', fontSize: 10 },
      },
      grid: [{ left: 58, right: 38, top: 48, bottom: 56 }],
      xAxis: [commonXAxis(0, true)],
      yAxis: [
        {
          type: 'value',
          min: -4,
          max: 2,
          interval: 1,
          name: 'устойчивый z-score',
          nameTextStyle: { color: '#738078', fontSize: 10 },
          axisLabel: { color: '#738078', fontSize: 10 },
          splitLine: { lineStyle: { color: '#e8ece5', type: 'dashed' } },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0], filterMode: 'none' },
        {
          type: 'slider',
          xAxisIndex: [0],
          filterMode: 'none',
          height: 17,
          bottom: 8,
          borderColor: '#dce2d7',
          backgroundColor: '#f3f5ef',
          fillerColor: 'rgba(139,88,116,.14)',
          handleStyle: { color: '#8b5874' },
          brushSelect: false,
        },
      ],
      series: [
        {
          name: 'Индекс отклонения',
          type: 'line',
          data: points.map((point) => point.robustZ),
          connectNulls: false,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { color: '#8b5874', width: 2.5 },
          itemStyle: { color: '#8b5874', borderColor: '#fffef8', borderWidth: 1 },
          markArea: {
            silent: true,
            data: [
              [
                { yAxis: -4, itemStyle: { color: 'rgba(198,78,69,.11)' } },
                { yAxis: -2 },
              ],
              [
                { yAxis: -2, itemStyle: { color: 'rgba(224,160,57,.10)' } },
                { yAxis: -1.2 },
              ],
            ],
          },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [
              {
                yAxis: -1.2,
                lineStyle: { color: '#d89d38', type: 'dashed' },
                label: { formatter: 'ранний риск', position: 'insideEndTop' },
              },
              {
                yAxis: -2,
                lineStyle: { color: '#c64e45', type: 'dashed' },
                label: { formatter: 'аномалия', position: 'insideEndBottom' },
              },
            ],
          },
        },
        ...(selectedMarker ? [selectedMarker] : []),
      ],
    };
  }

  const isWeather = mode === 'weather';
  const grids = [
    { left: 58, right: 48, top: 48, height: '43%' },
    { left: 58, right: 48, top: '62%', bottom: 56 },
  ];
  const xAxis = [commonXAxis(0, false), commonXAxis(1, true)];
  const dataZoom = [
    { type: 'inside', xAxisIndex: [0, 1], filterMode: 'none' },
    {
      type: 'slider',
      xAxisIndex: [0, 1],
      filterMode: 'none',
      height: 17,
      bottom: 8,
      borderColor: '#dce2d7',
      backgroundColor: '#f3f5ef',
      fillerColor: 'rgba(47,125,74,.14)',
      handleStyle: { color: '#2f7d4a' },
      brushSelect: false,
    },
  ];

  if (isWeather) {
    return {
      ...shared,
      title: [
        {
          text: 'Отклик растительности на погодные условия',
          subtext:
            'Верхний график — NDVI и сезонная норма. Нижний — температура и осадки ERA5-Land.',
          left: 58,
          top: 4,
          textStyle: { color: '#21382e', fontSize: 13, fontWeight: 700 },
          subtextStyle: { color: '#75827b', fontSize: 10 },
        },
      ],
      grid: grids,
      xAxis,
      yAxis: [
        {
          type: 'value',
          min: 0,
          max: 1,
          interval: 0.25,
          axisLabel: { color: '#738078', fontSize: 10 },
          splitLine: { lineStyle: { color: '#e8ece5', type: 'dashed' } },
        },
        {
          type: 'value',
          gridIndex: 1,
          scale: true,
          name: '°C',
          axisLabel: { color: '#9a653b', fontSize: 10, formatter: '{value}°' },
          splitLine: { lineStyle: { color: '#edf0ea', type: 'dashed' } },
        },
        {
          type: 'value',
          gridIndex: 1,
          min: 0,
          name: 'мм',
          axisLabel: { color: '#4e817c', fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      dataZoom,
      series: [
        {
          name: 'NDVI',
          type: 'line',
          data: points.map((point) => point.restored),
          symbol: 'none',
          lineStyle: { color: '#2f7d4a', width: 2.7 },
        },
        {
          name: 'Медиана нормы',
          type: 'line',
          data: points.map((point) => point.robustMedian),
          symbol: 'none',
          lineStyle: { color: '#7c9f55', width: 1.7, type: 'dashed' },
        },
        {
          name: 'Температура',
          type: 'line',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: points.map((point) => point.temperature),
          symbol: 'none',
          smooth: 0.25,
          lineStyle: { color: '#d78043', width: 2 },
          areaStyle: { color: 'rgba(215,128,67,.07)' },
        },
        {
          name: 'Осадки',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 2,
          data: points.map((point) => point.precipitation),
          itemStyle: { color: '#67a49f' },
          barMaxWidth: 9,
        },
        ...(selectedMarker ? [selectedMarker] : []),
      ],
    };
  }

  return {
    ...shared,
    title: [
      {
        text: 'Надёжность наблюдений и работа восстановления',
        subtext:
          'Верхний график — факт, модель и её неопределённость. Нижний — облачность и валидные пиксели.',
        left: 58,
        top: 4,
        textStyle: { color: '#21382e', fontSize: 13, fontWeight: 700 },
        subtextStyle: { color: '#75827b', fontSize: 10 },
      },
    ],
    grid: grids,
    xAxis,
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: 1,
        interval: 0.25,
        axisLabel: { color: '#738078', fontSize: 10 },
        splitLine: { lineStyle: { color: '#e8ece5', type: 'dashed' } },
      },
      {
        type: 'value',
        gridIndex: 1,
        min: 0,
        max: 100,
        name: 'облачность, %',
        axisLabel: { color: '#728397', fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#edf0ea', type: 'dashed' } },
      },
      {
        type: 'value',
        gridIndex: 1,
        min: 0,
        name: 'пиксели',
        axisLabel: { color: '#4e817c', fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    dataZoom,
    series: [
      {
        name: 'Нижняя граница',
        type: 'line',
        data: points.map((point) => point.confidenceLow),
        symbol: 'none',
        lineStyle: { width: 0 },
        stack: 'quality-band',
        areaStyle: { opacity: 0 },
        silent: true,
      },
      {
        name: 'Диапазон неопределённости',
        type: 'line',
        data: points.map((point) => point.confidenceHigh - point.confidenceLow),
        symbol: 'none',
        lineStyle: { width: 0 },
        stack: 'quality-band',
        areaStyle: { color: '#7eb68d', opacity: 0.2 },
        silent: true,
      },
      {
        name: 'Модель',
        type: 'line',
        data: points.map((point) => point.restored),
        symbol: 'none',
        lineStyle: { color: '#2f7d4a', width: 2.4 },
      },
      {
        name: 'Фактический снимок',
        type: 'scatter',
        data: points.map((point) => point.observed),
        symbolSize: 7,
        itemStyle: { color: '#173f35', borderColor: '#fffef8', borderWidth: 1.5 },
        z: 8,
      },
      {
        name: 'Восстановленная дата',
        type: 'scatter',
        data: points.map((point) => (point.isImputed ? point.restored : null)),
        symbol: 'diamond',
        symbolSize: 7,
        itemStyle: { color: '#eea33a' },
      },
      {
        name: 'Облачность',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: points.map((point) => point.cloudCover),
        symbol: 'none',
        lineStyle: { color: '#75859a', width: 1.8 },
        areaStyle: { color: 'rgba(117,133,154,.08)' },
      },
      {
        name: 'Валидные пиксели',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 2,
        data: points.map((point) => point.validPixels),
        itemStyle: { color: '#67a49f' },
        barMaxWidth: 9,
      },
      ...(selectedMarker ? [selectedMarker] : []),
    ],
  };
}

function anomalyAreas(
  points: TimeseriesPoint[],
): Array<Array<{ xAxis: string }>> {
  const areas: Array<Array<{ xAxis: string }>> = [];
  let start = '';
  let end = '';
  points.forEach((point, index) => {
    const risk = point.robustZ != null && point.robustZ <= -1.2;
    if (risk) {
      start = start || point.date;
      end = point.date;
    }
    if ((!risk || index === points.length - 1) && start) {
      areas.push([{ xAxis: start }, { xAxis: end }]);
      start = '';
      end = '';
    }
  });
  return areas;
}

export default function AnalysisChart({
  field,
  season,
  selectedDate,
  onClose,
  onDateSelect,
}: AnalysisChartProps) {
  const [points, setPoints] = useState<TimeseriesPoint[]>([]);
  const [previous, setPrevious] = useState<TimeseriesPoint[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>(
    'loading',
  );
  const [error, setError] = useState('');
  const [range, setRange] = useState<Range>('all');
  const [chartMode, setChartMode] = useState<ChartMode>('vegetation');
  const [visibility, setVisibility] = useState<Visibility>({
    observed: true,
    restored: true,
    norm: true,
    sensors: false,
    compare: false,
    zScore: false,
    weather: false,
  });
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [analysisParametersOpen, setAnalysisParametersOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const chartRef = useRef<ReactECharts>(null);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) {
        setState('loading');
        setError('');
      }
    });
    Promise.all([
      loadApiTimeseries(field.id, season),
      loadApiTimeseries(field.id, season - 1),
    ])
      .then(([next, prior]) => {
        if (!active) return;
        setPoints(next);
        setPrevious(prior);
        setState(next.length ? 'ready' : 'empty');
      })
      .catch((reason: unknown) => {
        if (active) {
          setPoints([]);
          setPrevious([]);
          setError(
            reason instanceof Error
              ? reason.message
              : 'Не удалось получить временной ряд',
          );
          setState('error');
        }
      });
    return () => {
      active = false;
    };
  }, [field.id, season]);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const observer = new ResizeObserver(() =>
      chartRef.current?.getEchartsInstance().resize(),
    );
    observer.observe(dialog);
    return () => observer.disconnect();
  }, [state]);
  const visiblePoints = useMemo(
    () => (range === 'all' ? points : points.slice(-Number(range))),
    [points, range],
  );
  const selectedPoint = useMemo(
    () =>
      visiblePoints.find((point) => point.date === selectedDate) ??
      visiblePoints.at(-1) ??
      null,
    [selectedDate, visiblePoints],
  );
  const previousByDay = useMemo(
    () =>
      new Map(previous.map((point) => [point.date.slice(5), point.restored])),
    [previous],
  );
  const labelInterval = Math.max(0, Math.ceil(visiblePoints.length / 8) - 1);
  const insightCards = useMemo(() => {
    const current = selectedPoint ?? visiblePoints.at(-1) ?? null;
    const riskPoints = visiblePoints.filter(
      (point) => point.robustZ != null && point.robustZ <= -1.2,
    );
    const anomalyPoints = visiblePoints.filter(
      (point) => point.robustZ != null && point.robustZ <= -2,
    );
    const recent = visiblePoints.slice(-14);
    const observedCount = visiblePoints.filter(
      (point) => point.observed != null,
    ).length;
    const restoredCount = visiblePoints.filter((point) => point.isImputed).length;
    const averageUncertainty = mean(
      visiblePoints.map(
        (point) => (point.confidenceHigh - point.confidenceLow) / 2,
      ),
    );
    const deviation =
      current?.robustMedian != null
        ? current.restored - current.robustMedian
        : null;
    if (chartMode === 'risk') {
      const selectedZ = current?.robustZ ?? null;
      return [
        {
          label: 'Сигнал на выбранную дату',
          value:
            selectedZ == null
              ? 'Нет оценки'
              : selectedZ <= -2
                ? 'Аномалия'
                : selectedZ <= -1.2
                  ? 'Ранний риск'
                  : 'В норме',
          hint: selectedZ == null ? 'недостаточно истории' : `z = ${valueOrDash(selectedZ)}`,
          tone: selectedZ != null && selectedZ <= -1.2 ? 'risk' : 'good',
        },
        {
          label: 'Ранних сигналов',
          value: String(riskPoints.length),
          hint: `за выбранный период из ${visiblePoints.length} дат`,
          tone: riskPoints.length ? 'warn' : 'good',
        },
        {
          label: 'Подтверждённых аномалий',
          value: String(anomalyPoints.length),
          hint: 'ниже порога z = −2',
          tone: anomalyPoints.length ? 'risk' : 'good',
        },
        {
          label: 'Историческая база',
          value: `${current?.normSampleCount ?? 0} сезонов`,
          hint: 'использовано для сезонной нормы',
          tone: 'neutral',
        },
      ];
    }
    if (chartMode === 'weather') {
      const precipitation14d = sum(recent.map((point) => point.precipitation));
      const temperature14d = mean(recent.map((point) => point.temperature));
      return [
        {
          label: 'NDVI на выбранную дату',
          value: valueOrDash(current ? current.observed ?? current.restored : null),
          hint:
            deviation == null
              ? 'сезонная норма недоступна'
              : `${deviation >= 0 ? '+' : ''}${valueOrDash(deviation)} к медиане`,
          tone: deviation != null && deviation < -0.08 ? 'risk' : 'good',
        },
        {
          label: 'Осадки · последние 14 дней',
          value: precipitation14d == null ? '—' : `${valueOrDash(precipitation14d, 1)} мм`,
          hint: 'сумма по ERA5-Land',
          tone: precipitation14d != null && precipitation14d < 5 ? 'warn' : 'neutral',
        },
        {
          label: 'Средняя температура · 14 дней',
          value: temperature14d == null ? '—' : `${valueOrDash(temperature14d, 1)} °C`,
          hint: 'по доступным погодным данным',
          tone: 'neutral',
        },
        {
          label: 'Погодное объяснение',
          value:
            precipitation14d == null
              ? 'Нет данных'
              : precipitation14d < 5 && deviation != null && deviation < 0
                ? 'Возможен дефицит влаги'
                : 'Явной связи нет',
          hint: 'гипотеза, не подтверждение причины',
          tone:
            precipitation14d != null && precipitation14d < 5 && deviation != null && deviation < 0
              ? 'warn'
              : 'neutral',
        },
      ];
    }
    if (chartMode === 'quality') {
      const observedShare = visiblePoints.length
        ? (observedCount / visiblePoints.length) * 100
        : 0;
      const restoredShare = visiblePoints.length
        ? (restoredCount / visiblePoints.length) * 100
        : 0;
      const cloudAverage = mean(
        visiblePoints.map((point) => point.cloudCover),
      );
      return [
        {
          label: 'Фактических снимков',
          value: `${observedCount} · ${Math.round(observedShare)}%`,
          hint: 'остальные даты оценены моделью',
          tone: observedShare < 25 ? 'warn' : 'good',
        },
        {
          label: 'Восстановлено моделью',
          value: `${restoredCount} · ${Math.round(restoredShare)}%`,
          hint: 'обозначено оранжевыми ромбами',
          tone: restoredShare > 75 ? 'warn' : 'neutral',
        },
        {
          label: 'Средняя неопределённость',
          value: averageUncertainty == null ? '—' : `±${valueOrDash(averageUncertainty, 3)}`,
          hint: 'уже — надёжнее оценка модели',
          tone: averageUncertainty != null && averageUncertainty > 0.05 ? 'warn' : 'good',
        },
        {
          label: 'Средняя облачность',
          value: cloudAverage == null ? '—' : `${valueOrDash(cloudAverage, 0)}%`,
          hint: 'для фактических спутниковых сцен',
          tone: cloudAverage != null && cloudAverage > 50 ? 'warn' : 'neutral',
        },
      ];
    }
    return [
      {
        label: 'NDVI на выбранную дату',
        value: valueOrDash(current ? current.observed ?? current.restored : null),
        hint: current?.observed != null ? 'фактический снимок' : 'восстановлено моделью',
        tone: 'neutral',
      },
      {
        label: 'Отклонение от медианы',
        value:
          deviation == null
            ? '—'
            : `${deviation >= 0 ? '+' : ''}${valueOrDash(deviation)}`,
        hint: 'относительно прошлых сезонов',
        tone: deviation != null && deviation < -0.08 ? 'risk' : 'good',
      },
      {
        label: 'Коридор сезонной нормы',
        value:
          current?.robustQ10 == null || current.robustQ90 == null
            ? '—'
            : `${valueOrDash(current.robustQ10)}–${valueOrDash(current.robustQ90)}`,
        hint: `${current?.normSampleCount ?? 0} исторических сезонов`,
        tone: 'neutral',
      },
      {
        label: 'Источник значения',
        value: current?.observationSource ?? 'Модель восстановления',
        hint: current?.date ? shortDate(current.date) : 'нет выбранной даты',
        tone: current?.observed != null ? 'good' : 'neutral',
      },
    ];
  }, [chartMode, selectedPoint, visiblePoints]);
  const beginDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest('button,[role=combobox]')) return;
    event.preventDefault();
    const startX = event.clientX,
      startY = event.clientY,
      startPosition = position;
    const move = (next: PointerEvent) =>
      setPosition({
        x: startPosition.x + next.clientX - startX,
        y: startPosition.y + next.clientY - startY,
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
  const toggle = (key: keyof Visibility) =>
    setVisibility((current) => ({ ...current, [key]: !current[key] }));
  const grids = useMemo(
    () =>
      visibility.zScore && visibility.weather
        ? [
            { left: 58, right: 38, top: 34, height: '41%' },
            { left: 58, right: 38, top: '52%', height: '16%' },
            { left: 58, right: 38, top: '73%', bottom: 56 },
          ]
        : visibility.zScore
          ? [
              { left: 58, right: 38, top: 34, height: '59%' },
              { left: 58, right: 38, top: '68%', bottom: 56 },
            ]
          : visibility.weather
            ? [
                { left: 58, right: 38, top: 34, height: '55%' },
                { left: 58, right: 38, top: '64%', bottom: 56 },
              ]
            : [{ left: 58, right: 38, top: 34, bottom: 56 }],
    [visibility.weather, visibility.zScore],
  );
  const technicalGrid = visibility.zScore ? 1 : -1;
  const weatherGrid = visibility.weather ? (visibility.zScore ? 2 : 1) : -1;
  const riskAreas = useMemo(() => anomalyAreas(visiblePoints), [visiblePoints]);
  const option = useMemo(() => {
    if (chartMode !== 'vegetation') {
      return buildFocusedOption(
        chartMode,
        visiblePoints,
        selectedPoint,
        labelInterval,
      );
    }
    const dates = visiblePoints.map((point) => point.date);
    const gridIndexes = [
      0,
      ...(visibility.zScore ? [technicalGrid] : []),
      ...(visibility.weather ? [weatherGrid] : []),
    ];
    const lastGrid = gridIndexes.at(-1) ?? 0;
    const xAxis = gridIndexes.map((gridIndex) => ({
      type: 'category',
      gridIndex,
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#dce2d7' } },
      axisTick: { show: false },
      axisLabel: {
        show: gridIndex === lastGrid,
        color: '#738078',
        fontSize: 10,
        formatter: shortDate,
        interval: labelInterval,
        hideOverlap: true,
      },
    }));
    const series: Array<Record<string, unknown>> = [];
    if (visibility.norm) {
      series.push(
        {
          name: 'Q10 нормы',
          type: 'line',
          data: visiblePoints.map((point) => point.robustQ10),
          symbol: 'none',
          lineStyle: { width: 0 },
          stack: 'robust-band',
          areaStyle: { opacity: 0 },
          silent: true,
        },
        {
          name: 'Q10–Q90 нормы',
          type: 'line',
          data: visiblePoints.map((point) =>
            point.robustQ90 != null && point.robustQ10 != null
              ? point.robustQ90 - point.robustQ10
              : null,
          ),
          symbol: 'none',
          lineStyle: { width: 0 },
          stack: 'robust-band',
          areaStyle: { color: '#bfd09b', opacity: 0.34 },
          silent: true,
        },
        {
          name: 'Медиана нормы',
          type: 'line',
          data: visiblePoints.map((point) => point.robustMedian),
          symbol: 'none',
          lineStyle: { color: '#7c9f55', width: 1.7, type: 'dashed' },
        },
      );
    }
    if (visibility.compare && previous.length) {
      series.push({
        name: `Сезон ${season - 1}`,
        type: 'line',
        data: visiblePoints.map(
          (point) => previousByDay.get(point.date.slice(5)) ?? null,
        ),
        symbol: 'none',
        lineStyle: { color: '#6f7d94', width: 1.6, type: 'dotted' },
      });
    }
    if (visibility.restored) {
      series.push(
        {
          name: 'Нижняя граница восстановления',
          type: 'line',
          data: visiblePoints.map((point) => point.confidenceLow),
          symbol: 'none',
          lineStyle: { width: 0 },
          stack: 'restoration-band',
          areaStyle: { opacity: 0 },
          silent: true,
        },
        {
          name: 'Неопределённость восстановления',
          type: 'line',
          data: visiblePoints.map(
            (point) => point.confidenceHigh - point.confidenceLow,
          ),
          symbol: 'none',
          lineStyle: { width: 0 },
          stack: 'restoration-band',
          areaStyle: { color: '#7eb68d', opacity: 0.14 },
          silent: true,
        },
        {
          name: 'Восстановленный ряд',
          type: 'line',
          data: visiblePoints.map((point) => point.restored),
          symbol: 'none',
          connectNulls: false,
          lineStyle: { color: '#2f7d4a', width: 2.7 },
          markArea: {
            silent: true,
            itemStyle: { color: 'rgba(210,75,62,.10)' },
            data: riskAreas,
          },
        },
      );
      series.push({
        name: 'Восстановлено',
        type: 'scatter',
        data: visiblePoints.map((point) =>
          point.isImputed ? point.restored : null,
        ),
        symbol: 'diamond',
        symbolSize: 8,
        itemStyle: { color: '#eea33a' },
      });
    }
    if (visibility.observed)
      series.push({
        name: 'Фактический primary_ndvi',
        type: 'scatter',
        data: visiblePoints.map((point) => point.observed),
        symbolSize: 7,
        itemStyle: {
          color: '#173f35',
          borderColor: '#fffef8',
          borderWidth: 1.5,
        },
        z: 8,
      });
    if (selectedPoint)
      series.push({
        name: 'Выбранная дата',
        type: 'scatter',
        data: visiblePoints.map((point) =>
          point.date === selectedPoint.date
            ? (point.observed ?? point.restored)
            : null,
        ),
        symbolSize: 15,
        itemStyle: { color: '#fffef8', borderColor: '#e09b32', borderWidth: 4 },
        z: 20,
        tooltip: { show: false },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            {
              xAxis: selectedPoint.date,
              lineStyle: { color: '#e09b32', width: 1.4, type: 'dashed' },
              label: { show: false },
            },
          ],
        },
      });
    if (visibility.sensors) {
      series.push(
        {
          name: 'Sentinel-2',
          type: 'scatter',
          data: visiblePoints.map((point) => point.s2),
          symbolSize: 6,
          itemStyle: { color: '#2787b7' },
        },
        {
          name: 'Landsat 8/9',
          type: 'scatter',
          data: visiblePoints.map((point) => point.landsat),
          symbolSize: 6,
          itemStyle: { color: '#7059ad' },
        },
        {
          name: 'MODIS',
          type: 'scatter',
          data: visiblePoints.map((point) => point.modis),
          symbolSize: 6,
          itemStyle: { color: '#bd6f35' },
        },
      );
    }
    if (visibility.zScore)
      series.push({
        name: 'Индекс отклонения',
        type: 'line',
        xAxisIndex: technicalGrid,
        yAxisIndex: technicalGrid,
        data: visiblePoints.map((point) => point.robustZ),
        symbol: 'none',
        connectNulls: false,
        lineStyle: { color: '#8b5874', width: 1.8 },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            {
              yAxis: -1.2,
              lineStyle: { color: '#e0a039', type: 'dashed' },
              label: { formatter: 'ранний риск', position: 'insideEndTop' },
            },
            {
              yAxis: -2,
              lineStyle: { color: '#c64e45', type: 'dashed' },
              label: { formatter: 'аномалия', position: 'insideEndBottom' },
            },
          ],
        },
      });
    if (visibility.weather) {
      series.push(
        {
          name: 'Температура ERA5-Land',
          type: 'line',
          xAxisIndex: weatherGrid,
          yAxisIndex: weatherGrid,
          data: visiblePoints.map((point) => point.temperature),
          symbol: 'none',
          smooth: 0.25,
          lineStyle: { color: '#d78043', width: 1.8 },
          areaStyle: { color: 'rgba(215,128,67,.07)' },
        },
        {
          name: 'Осадки ERA5-Land',
          type: 'bar',
          xAxisIndex: weatherGrid,
          yAxisIndex: weatherGrid + 1,
          data: visiblePoints.map((point) => point.precipitation),
          itemStyle: { color: '#67a49f' },
          barMaxWidth: 9,
        },
      );
    }
    const yAxis: Array<Record<string, unknown>> = [
      {
        type: 'value',
        min: 0,
        max: 1,
        interval: 0.25,
        axisLabel: { color: '#738078', fontSize: 10 },
        splitLine: { lineStyle: { color: '#e8ece5', type: 'dashed' } },
      },
    ];
    if (visibility.zScore)
      yAxis.push({
        type: 'value',
        gridIndex: technicalGrid,
        min: -4,
        max: 2,
        interval: 1,
        axisLabel: { color: '#738078', fontSize: 9, formatter: 'z {value}' },
        splitLine: { lineStyle: { color: '#edf0ea', type: 'dashed' } },
      });
    if (visibility.weather)
      yAxis.push(
        {
          type: 'value',
          gridIndex: weatherGrid,
          scale: true,
          axisLabel: { color: '#738078', fontSize: 9, formatter: '{value}°' },
          splitLine: { show: false },
        },
        {
          type: 'value',
          gridIndex: weatherGrid,
          min: 0,
          axisLabel: { show: false },
          splitLine: { show: false },
        },
      );
    return {
      animationDuration: 350,
      title: [
        {
          text: 'Состояние растительности · NDVI',
          subtext:
            'Выше — активнее растительность. Светлая полоса — обычный диапазон прошлых сезонов.',
          left: 58,
          top: 4,
          textStyle: { color: '#21382e', fontSize: 13, fontWeight: 700 },
          subtextStyle: { color: '#75827b', fontSize: 10, fontWeight: 400 },
        },
      ],
      grid: grids,
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#173f35',
        borderWidth: 0,
        padding: [11, 13],
        textStyle: { color: '#fff', fontSize: 11 },
        formatter: (items: Array<{ axisValue: string; dataIndex: number }>) => {
          const point = visiblePoints[items[0]?.dataIndex];
          if (!point) return '';
          const value = (number: number | null, digits = 2) =>
            number == null ? 'нет данных' : number.toFixed(digits);
          const uncertainty = (point.confidenceHigh - point.confidenceLow) / 2;
          return `<b>${new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(`${point.date}T12:00:00`))}</b><div class="chart-tooltip-grid"><span>Источник</span><b>${point.observationSource ?? 'нет фактической сцены'}</b><span>Факт / восстановлено</span><b>${value(point.observed)} / ${value(point.restored)}</b><span>Неопределённость</span><b>±${uncertainty.toFixed(3)}</b><span>Индекс отклонения</span><b>${value(point.robustZ)}</b><span>Коридор нормы</span><b>${value(point.robustQ10)} — ${value(point.robustQ90)}</b><span>Исторических сезонов</span><b>${point.normSampleCount}</b><span>Облачность</span><b>${point.cloudCover == null ? 'нет данных' : `${value(point.cloudCover, 1)}%`}</b><span>Валидные пиксели</span><b>${point.validPixels == null ? 'нет данных' : Math.round(point.validPixels)}</b><span>Температура / осадки</span><b>${value(point.temperature, 1)} °C / ${value(point.precipitation, 1)} мм</b></div>`;
        },
      },
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: gridIndexes,
          filterMode: 'none',
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
        },
        {
          type: 'slider',
          xAxisIndex: gridIndexes,
          filterMode: 'none',
          height: 17,
          bottom: 8,
          borderColor: '#dce2d7',
          backgroundColor: '#f3f5ef',
          fillerColor: 'rgba(47,125,74,.16)',
          handleStyle: { color: '#2f7d4a' },
          brushSelect: false,
        },
      ],
      xAxis,
      yAxis,
      series,
    };
  }, [
    chartMode,
    grids,
    labelInterval,
    previous.length,
    previousByDay,
    riskAreas,
    season,
    selectedPoint,
    technicalGrid,
    visibility,
    visiblePoints,
    weatherGrid,
  ]);
  return (
    <div className="analysis-overlay">
      <dialog
        ref={dialogRef}
        open
        className="analysis-drawer"
        aria-label="Аналитика поля"
        style={
          {
            transform: `translate(${position.x}px,${position.y}px)`,
          } as CSSProperties
        }
      >
        <header className="analysis-header" onPointerDown={beginDrag}>
          <div>
            <span className="analysis-kicker">Динамика и ранние сигналы</span>
            <h3>{field.name}</h3>
          </div>
          <span className="drag-hint">
            <Move size={13} />
            перетащите окно
          </span>
          <div className="analysis-actions">
            <button
              onClick={() => {
                setPosition({ x: 0, y: 0 });
                chartRef.current
                  ?.getEchartsInstance()
                  .dispatchAction({ type: 'dataZoom', start: 0, end: 100 });
              }}
              aria-label="Сбросить вид"
            >
              <RotateCcw size={16} />
            </button>
            <button onClick={onClose} aria-label="Закрыть аналитику">
              <X size={18} />
            </button>
          </div>
        </header>
        <div className="chart-control-row">
          <Select
            value={range}
            onValueChange={(value) => setRange(value as Range)}
          >
            <SelectTrigger className="chart-range" aria-label="Период графика">
              <CalendarDays size={15} />
              <span>
                {rangeLabel[range]} {range === 'all' ? season : ''}
              </span>
            </SelectTrigger>
            <SelectContent
              className="chart-range-menu"
              align="start"
              sideOffset={7}
              alignItemWithTrigger={false}
            >
              <SelectItem value="all">Весь сезон {season}</SelectItem>
              <SelectItem value="90">Последние 90 дней</SelectItem>
              <SelectItem value="60">Последние 60 дней</SelectItem>
              <SelectItem value="30">Последние 30 дней</SelectItem>
            </SelectContent>
          </Select>
          <div
            className="chart-view-tabs"
            role="tablist"
            aria-label="Вид аналитического графика"
          >
            {(
              [
                ['vegetation', Sprout],
                ['risk', TriangleAlert],
                ['weather', CloudSun],
                ['quality', BadgeCheck],
              ] as Array<[ChartMode, typeof Sprout]>
            ).map(([mode, Icon]) => (
              <button
                key={mode}
                role="tab"
                aria-selected={chartMode === mode}
                className={chartMode === mode ? 'is-active' : ''}
                onClick={() => {
                  setChartMode(mode);
                  setAnalysisParametersOpen(false);
                }}
              >
                <Icon size={14} />
                {chartModeLabel[mode]}
              </button>
            ))}
          </div>
          {chartMode === 'vegetation' ? (
            <div className="analysis-parameters">
              <button
                className={
                  visibility.sensors ||
                  visibility.compare ||
                  !visibility.observed ||
                  !visibility.restored ||
                  !visibility.norm
                    ? 'is-active'
                    : ''
                }
                onClick={() => setAnalysisParametersOpen((open) => !open)}
                aria-expanded={analysisParametersOpen}
              >
                <SlidersHorizontal size={14} />
                Параметры анализа
              </button>
              {analysisParametersOpen ? (
                <div className="analysis-parameters-menu">
                  {(
                    [
                      ['observed', 'Фактические снимки'],
                      ['restored', 'Сглаженный ряд модели'],
                      ['norm', 'Коридор сезонной нормы'],
                      ['compare', `Сравнить с ${season - 1}`],
                      ['sensors', 'Все спутники'],
                    ] as Array<[keyof Visibility, string]>
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      className={visibility[key] ? 'is-active' : ''}
                      onClick={() => toggle(key)}
                    >
                      <i />
                      {label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="chart-explainer">
          {chartMode === 'vegetation' || chartMode === 'quality' ? (
            <>
              <span>
                <i className="legend-dot" />
                Фактический снимок
              </span>
              <span>
                <i className="legend-dot imputed" />
                Восстановлено моделью
              </span>
            </>
          ) : null}
          {chartMode === 'vegetation' ? (
            <span>
              <i className="track-dot ndvi" />
              NDVI и коридор сезонной нормы
            </span>
          ) : null}
          {chartMode === 'risk' ? (
            <>
              <span>
                <i className="track-dot risk" />
                Устойчивый z-score модели
              </span>
              <span>
                <i className="risk-band early" />
                −1,2…−2 ранний риск
              </span>
              <span>
                <i className="risk-band anomaly" />
                ниже −2 аномалия
              </span>
            </>
          ) : null}
          {chartMode === 'weather' ? (
            <>
              <span>
                <i className="track-dot ndvi" />
                NDVI и сезонная норма
              </span>
              <span>
                <i className="track-dot weather" />
                Температура и осадки ERA5-Land
              </span>
            </>
          ) : null}
          {chartMode === 'quality' ? (
            <span>
              <i className="quality-band" />
              Светлая полоса — неопределённость модели
            </span>
          ) : null}
          <span>
            <Info size={13} />
            Нажмите точку, чтобы выбрать дату
          </span>
        </div>
        {selectedPoint ? (
          <div className="chart-selection-bar">
            <span>
              <i />
              Выбрано:{' '}
              <strong>
                {new Intl.DateTimeFormat('ru-RU', {
                  day: 'numeric',
                  month: 'long',
                  year: 'numeric',
                }).format(new Date(`${selectedPoint.date}T12:00:00`))}
              </strong>
            </span>
            <span>
              {chartMode === 'risk' ? 'Индекс отклонения' : 'NDVI'}{' '}
              <strong>
                {chartMode === 'risk'
                  ? valueOrDash(selectedPoint.robustZ)
                  : valueOrDash(selectedPoint.observed ?? selectedPoint.restored)}
              </strong>
            </span>
            <span>
              {chartMode === 'weather'
                ? `${valueOrDash(selectedPoint.temperature, 1)} °C · ${valueOrDash(selectedPoint.precipitation, 1)} мм осадков`
                : chartMode === 'quality'
                  ? `${selectedPoint.cloudCover == null ? '—' : `${valueOrDash(selectedPoint.cloudCover, 0)}% облачности`} · ${selectedPoint.validPixels == null ? '—' : Math.round(selectedPoint.validPixels)} пикс.`
                  : selectedPoint.observed != null
                    ? `Факт · ${selectedPoint.observationSource ?? 'спутник'}`
                    : 'Восстановленное значение'}
            </span>
            <span>
              {chartMode === 'risk'
                ? selectedPoint.robustZ == null
                  ? 'Оценка риска недоступна'
                  : selectedPoint.robustZ <= -2
                    ? 'Аномалия — нужен осмотр'
                    : selectedPoint.robustZ <= -1.2
                      ? 'Ранний риск — наблюдать'
                      : 'В пределах сезонной нормы'
                : selectedPoint.robustMedian == null
                  ? 'Норма недоступна'
                  : `Норма ${valueOrDash(selectedPoint.robustQ10)}–${valueOrDash(selectedPoint.robustQ90)}`}
            </span>
          </div>
        ) : null}
        {state === 'ready' ? (
          <div className="chart-insight-strip" aria-label="Ключевые выводы графика">
            {insightCards.map((card) => (
              <article key={card.label} data-tone={card.tone}>
                <span>{card.label}</span>
                <strong>{card.value}</strong>
                <small>{card.hint}</small>
              </article>
            ))}
          </div>
        ) : null}
        {state === 'loading' ? (
          <div className="analysis-state">Загружаем реальные наблюдения…</div>
        ) : null}
        {state === 'empty' ? (
          <div className="analysis-state">
            Для этого сезона данных нет. Запустите анализ поля.
          </div>
        ) : null}
        {state === 'error' ? (
          <div className="analysis-state is-error">{error}</div>
        ) : null}
        {state === 'ready' ? (
          <ReactECharts
            ref={chartRef}
            className="analysis-chart-canvas"
            option={option}
            notMerge
            style={{ flex: 1, minWidth: 0, minHeight: 0, width: '100%' }}
            opts={{ renderer: 'canvas' }}
            onEvents={{
              click: (params: { name?: string }) =>
                params.name && onDateSelect(params.name),
            }}
          />
        ) : null}
        <span className="analysis-resize-cue" aria-hidden="true" />
      </dialog>
    </div>
  );
}
