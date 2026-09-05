'use client';

import { Bell, Filter, Plus, Search, Trash2 } from 'lucide-react';
import {
  useMemo,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';

import type { FieldRecord } from '@/lib/types';
import { BRAND_NAME } from '@/lib/brand';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

interface FieldSidebarProps {
  fields: FieldRecord[];
  selectedFieldId: string;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onDelete: (id: string) => void;
  onOpenAttention: () => void;
  riskFieldIds: Set<string>;
  onResizeStart: (event: ReactPointerEvent<HTMLElement>) => void;
}

export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 36 36" aria-hidden="true">
      <path
        className="brand-field"
        d="M4.1 18.5c5.1-2.9 10-6 15.4-8.4 2.7-1.2 5.3-.3 8.1.4-2.1 2.7-5.2 4.8-8.5 6.4-5.6 2.7-10.5 5.4-14 9.1l-2.6-2.2c-1.7-1.6-.6-4 1.6-5.3Z"
      />
      <path
        className="brand-field"
        d="M6.8 27.2c3.4-4.4 8.3-6.7 13-9 3.7-1.8 6.8-3.8 8.9-6.5l2.1 2.5c-2.2 3.5-5.7 6-9.7 8-4.7 2.3-8.8 4.8-11.1 8.7l-3.2-3.7Z"
      />
      <path
        className="brand-field"
        d="M11.7 32.1c1.9-4.3 5.7-6.7 10-8.8 4.3-2.1 7.6-4.6 9.6-7.8 1.6 2 1.8 4.2.2 6.4l-8 9.7c-3.1 3.8-7.7 4.1-11.8.5Z"
      />
      <path className="brand-scan" d="M3.3 16.3C8.8 5.7 20.5 3.2 28.5 9.3" />
      <circle className="brand-point" cx="29.5" cy="11.1" r="2.65" />
    </svg>
  );
}

export default function FieldSidebar({
  fields,
  selectedFieldId,
  onSelect,
  onAdd,
  onDelete,
  onOpenAttention,
  riskFieldIds,
  onResizeStart,
}: FieldSidebarProps) {
  const [query, setQuery] = useState('');
  const [riskOnly, setRiskOnly] = useState(false);
  const [cropFilter, setCropFilter] = useState('all');
  const [regionFilter, setRegionFilter] = useState('all');
  const crops = useMemo(
    () =>
      Array.from(new Set(fields.map((field) => field.crop))).sort((a, b) =>
        a.localeCompare(b, 'ru'),
      ),
    [fields],
  );
  const regions = useMemo(
    () =>
      Array.from(new Set(fields.map((field) => field.region))).sort((a, b) =>
        a.localeCompare(b, 'ru'),
      ),
    [fields],
  );
  const advancedFilterActive = cropFilter !== 'all' || regionFilter !== 'all';
  const filtered = useMemo(
    () =>
      fields.filter((field) => {
        const matches = `${field.name} ${field.crop} ${field.region}`
          .toLowerCase()
          .includes(query.toLowerCase());
        return (
          matches &&
          (!riskOnly || riskFieldIds.has(field.id)) &&
          (cropFilter === 'all' || field.crop === cropFilter) &&
          (regionFilter === 'all' || field.region === regionFilter)
        );
      }),
    [fields, query, riskOnly, cropFilter, regionFilter, riskFieldIds],
  );
  const totalArea = fields.reduce((sum, field) => sum + field.areaHa, 0);
  const risks = riskFieldIds.size;
  const analysed = fields.filter((field) => field.dataProvider === 'gee');
  const latestScene = analysed
    .map((field) => field.sceneDate)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);

  return (
    <section className="fields-panel">
      <header className="product-header">
        <div>
          <p className="eyebrow">Спутниковая аналитика</p>
          <h1>{BRAND_NAME}</h1>
        </div>
        <button
          className="icon-plain"
          aria-label={`Открыть центр внимания: ${risks} активных сигналов`}
          title="Центр внимания"
          onClick={onOpenAttention}
        >
          <Bell size={19} />
          {risks ? <span className="notification-count">{risks}</span> : null}
        </button>
      </header>
      <div className="panel-toolbar">
        <div className="section-heading">
          <div>
            <h2>Поля</h2>
            <span>
              {fields.length} территории ·{' '}
              {totalArea.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}{' '}
              га
            </span>
          </div>
          <button className="add-button" onClick={onAdd}>
            <Plus size={18} />
            Добавить
          </button>
        </div>
        <label className="search-field">
          <Search size={18} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Поиск по полям"
            placeholder="Название или регион"
          />
        </label>
        <div className="filter-row">
          <button
            className={`filter-chip ${!riskOnly ? 'is-active' : ''}`}
            onClick={() => setRiskOnly(false)}
          >
            Все
          </button>
          <button
            className={`filter-chip ${riskOnly ? 'is-active' : ''}`}
            onClick={() => setRiskOnly(true)}
          >
            С риском <span>{risks}</span>
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <button
                  className={`filter-chip ${advancedFilterActive ? 'is-active' : ''}`}
                  aria-label="Фильтры по культуре и региону"
                />
              }
            >
              <Filter size={15} />
              {advancedFilterActive ? (
                <b>
                  {(cropFilter !== 'all' ? 1 : 0) +
                    (regionFilter !== 'all' ? 1 : 0)}
                </b>
              ) : null}
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              sideOffset={7}
              className="field-filter-menu"
            >
              <DropdownMenuRadioGroup
                value={cropFilter}
                onValueChange={setCropFilter}
              >
                <DropdownMenuLabel>Культура</DropdownMenuLabel>
                <DropdownMenuRadioItem value="all">
                  Все культуры
                </DropdownMenuRadioItem>
                {crops.map((crop) => (
                  <DropdownMenuRadioItem key={crop} value={crop}>
                    {crop}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuRadioGroup
                value={regionFilter}
                onValueChange={setRegionFilter}
              >
                <DropdownMenuLabel>Регион</DropdownMenuLabel>
                <DropdownMenuRadioItem value="all">
                  Все регионы
                </DropdownMenuRadioItem>
                {regions.map((region) => (
                  <DropdownMenuRadioItem key={region} value={region}>
                    {region}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
              {advancedFilterActive ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => {
                      setCropFilter('all');
                      setRegionFilter('all');
                    }}
                  >
                    Сбросить фильтры
                  </DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <div className="field-list">
        {filtered.length ? (
          filtered.map((field) => (
            <article
              key={field.id}
              className={`field-row ${selectedFieldId === field.id ? 'is-selected' : ''}`}
            >
              <button
                className="field-row-open"
                aria-label={`Открыть поле ${field.name}`}
                onClick={() => onSelect(field.id)}
              >
                <span
                  className={`field-swatch ${field.dataProvider === 'gee' ? (riskFieldIds.has(field.id) ? 'warning' : field.status) : 'pending'}`}
                />
                <span className="field-main">
                  <strong>{field.name}</strong>
                  <small>
                    {field.crop} ·{' '}
                    {field.areaHa.toLocaleString('ru-RU', {
                      maximumFractionDigits: 1,
                    })}{' '}
                    га
                  </small>
                </span>
                <span className="field-metric">
                  <strong>
                    {field.dataProvider === 'gee' && field.ndvi != null
                      ? field.ndvi.toFixed(2).replace('.', ',')
                      : '—'}
                  </strong>
                  <small>NDVI</small>
                </span>
              </button>
              <button
                className="field-row-delete"
                aria-label={`Удалить поле ${field.name}`}
                title="Удалить поле"
                onClick={() => onDelete(field.id)}
              >
                <Trash2 size={15} />
              </button>
            </article>
          ))
        ) : (
          <div className="empty-filter">
            <Search size={22} />
            <strong>Ничего не найдено</strong>
            <span>Измените запрос или сбросьте фильтр.</span>
          </div>
        )}
      </div>
      <footer className="source-footer">
        <span className="source-status">
          <i />{' '}
          {analysed.length
            ? `${analysed.length} полей рассчитано`
            : 'Нет рассчитанных полей'}
        </span>
        <span>
          {latestScene
            ? `Последний снимок · ${new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' }).format(new Date(latestScene))}`
            : 'Спутниковых данных нет'}
        </span>
      </footer>
      <hr
        className="sidebar-resize-handle"
        aria-label="Изменить ширину списка полей"
        aria-orientation="vertical"
        onPointerDown={onResizeStart}
      />
    </section>
  );
}
