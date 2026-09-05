'use client';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select';
import type { AlertLifecycleState, InspectionPoint } from '@/lib/types';

const alertOptions: Array<{
  value: AlertLifecycleState;
  label: string;
  tone: string;
}> = [
  { value: 'detected', label: 'Обнаружен', tone: 'warning' },
  { value: 'assigned', label: 'Назначен на обход', tone: 'assigned' },
  { value: 'verified', label: 'Проверен', tone: 'visited' },
  { value: 'confirmed', label: 'Проблема подтверждена', tone: 'critical' },
  { value: 'rejected', label: 'Ложная тревога', tone: 'neutral' },
  { value: 'closed', label: 'Закрыт', tone: 'normal' },
];

const inspectionOptions: Array<{
  value: InspectionPoint['status'];
  label: string;
  tone: string;
}> = [
  { value: 'planned', label: 'Запланирован', tone: 'assigned' },
  { value: 'visited', label: 'Посещён', tone: 'visited' },
  { value: 'confirmed', label: 'Проблема подтверждена', tone: 'critical' },
  { value: 'rejected', label: 'Проблема не найдена', tone: 'normal' },
];

export function AlertStatusSelect({
  value,
  disabled,
  onChange,
  compact = false,
}: {
  value: AlertLifecycleState;
  disabled?: boolean;
  onChange: (value: AlertLifecycleState) => void;
  compact?: boolean;
}) {
  const current =
    alertOptions.find((item) => item.value === value) ?? alertOptions[0];
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => onChange(next as AlertLifecycleState)}
    >
      <SelectTrigger
        className={`status-select-trigger ${compact ? 'is-compact' : ''}`}
        aria-label="Статус обработки сигнала"
      >
        <i className={`status-dot ${current.tone}`} />
        <span>{current.label}</span>
      </SelectTrigger>
      <SelectContent
        className="status-select-menu"
        align="start"
        sideOffset={6}
        alignItemWithTrigger={false}
      >
        {alertOptions.map((item) => (
          <SelectItem
            key={item.value}
            value={item.value}
            className="status-select-item"
          >
            <i className={`status-dot ${item.tone}`} />
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function InspectionStatusSelect({
  value,
  onChange,
}: {
  value: InspectionPoint['status'];
  onChange: (value: InspectionPoint['status']) => void;
}) {
  const current =
    inspectionOptions.find((item) => item.value === value) ??
    inspectionOptions[0];
  return (
    <Select
      value={value}
      onValueChange={(next) => onChange(next as InspectionPoint['status'])}
    >
      <SelectTrigger
        className="status-select-trigger inspection-status-trigger"
        aria-label="Результат полевого осмотра"
      >
        <i className={`status-dot ${current.tone}`} />
        <span>{current.label}</span>
      </SelectTrigger>
      <SelectContent
        className="status-select-menu inspection-status-menu"
        align="end"
        sideOffset={6}
        alignItemWithTrigger={false}
      >
        {inspectionOptions.map((item) => (
          <SelectItem
            key={item.value}
            value={item.value}
            className="status-select-item"
          >
            <i className={`status-dot ${item.tone}`} />
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
