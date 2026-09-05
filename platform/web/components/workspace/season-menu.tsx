'use client';

import { CalendarDays, Check, ChevronDown } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

const FIRST_DATA_YEAR = 2021;
const CURRENT_YEAR = new Date().getFullYear();
const SEASONS = Array.from(
  { length: CURRENT_YEAR - FIRST_DATA_YEAR + 1 },
  (_, index) => CURRENT_YEAR - index,
);

export default function SeasonMenu({
  value,
  onChange,
}: {
  value: number;
  onChange: (year: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node))
        setOpen(false);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, []);
  return (
    <div className="season-menu" ref={ref}>
      <button
        className="season-select"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <CalendarDays size={16} />
        Сезон {value}
        <ChevronDown size={16} />
      </button>
      {open ? (
        <div className="season-options" aria-label="Выбор года наблюдений">
          <header>
            <strong>Год спутниковых сцен</strong>
            <span>Январь — декабрь</span>
          </header>
          {SEASONS.map((year) => (
            <button
              key={year}
              aria-pressed={year === value}
              onClick={() => {
                onChange(year);
                setOpen(false);
              }}
            >
              <span>{year}</span>
              <small>
                {year === CURRENT_YEAR ? 'Текущий сезон' : 'Архив наблюдений'}
              </small>
              {year === value ? <Check size={16} /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
