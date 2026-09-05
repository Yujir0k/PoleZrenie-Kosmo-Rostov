'use client';

import { LoaderCircle, MapPin, Search, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { findRegions } from '@/lib/regions';
import type { RegionResult } from '@/lib/types';

interface RegionSearchProps {
  initialValue?: string;
  variant?: 'map' | 'dialog';
  onSelect: (region: RegionResult) => void;
}

export default function RegionSearch({
  initialValue = 'Ростовская область',
  variant = 'map',
  onSelect,
}: RegionSearchProps) {
  const [query, setQuery] = useState(initialValue);
  const [results, setResults] = useState<RegionResult[]>([]);
  const [open, setOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const [offline, setOffline] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node))
        setOpen(false);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, []);

  useEffect(() => {
    if (!open || query.trim().length < 2) {
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      setSearching(true);
      void findRegions(query)
        .then((lookup) => {
          if (active) {
            setResults(lookup.items);
            setOffline(lookup.offline);
          }
        })
        .catch(() => {
          if (active) {
            setResults([]);
            setOffline(true);
          }
        })
        .finally(() => {
          if (active) setSearching(false);
        });
    }, 260);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [open, query]);

  const choose = (region: RegionResult) => {
    setQuery(region.name);
    setOpen(false);
    onSelect(region);
  };
  return (
    <div className={`region-combobox ${variant}`} ref={rootRef}>
      <label className={variant === 'map' ? 'map-search' : 'dialog-search'}>
        {variant === 'map' ? <MapPin size={18} /> : <Search size={18} />}
        <input
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            setOffline(false);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setOpen(false);
            if (event.key === 'Enter' && results[0]) {
              event.preventDefault();
              choose(results[0]);
            }
          }}
          aria-label="Поиск региона или координат"
          placeholder="Город, регион или 47.23, 39.70"
          autoComplete="off"
        />
        {searching ? (
          <LoaderCircle className="region-spinner" size={16} />
        ) : query ? (
          <button
            type="button"
            className="region-clear"
            onClick={() => {
              setQuery('');
              setResults([]);
              setOpen(true);
            }}
            aria-label="Очистить поиск"
          >
            <X size={15} />
          </button>
        ) : null}
        {variant === 'map' ? <span className="key-hint">⌘ K</span> : null}
      </label>
      {open && query.trim().length >= 2 ? (
        <div className="region-suggestions" aria-label="Подсказки регионов">
          <div className={`suggestion-caption ${offline ? 'is-warning' : ''}`}>
            {searching
              ? 'Ищем совпадения…'
              : offline
                ? 'Онлайн-поиск временно недоступен'
                : 'Выберите регион — карта переместится автоматически'}
          </div>
          {results.map((item) => (
            <button type="button" key={item.id} onClick={() => choose(item)}>
              <MapPin size={15} />
              <span>
                <strong>{item.name}</strong>
                <small>{item.displayName}</small>
              </span>
            </button>
          ))}
          {!searching && results.length === 0 ? (
            <div className="suggestion-empty">
              {offline
                ? 'Не удалось связаться с сервисом геопоиска. Попробуйте ещё раз или введите координаты.'
                : 'Ничего не найдено. Попробуйте область, город или координаты.'}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
