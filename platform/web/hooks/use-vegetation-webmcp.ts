'use client';

import { useEffect } from 'react';

import type { FieldRecord } from '@/lib/types';

type WebMcpTool = {
  name: string;
  title?: string;
  description: string;
  inputSchema: Record<string, unknown>;
  annotations?: { readOnlyHint?: boolean; untrustedContentHint?: boolean };
  execute: (input: unknown) => unknown;
};

declare global {
  interface Document {
    modelContext?: {
      registerTool: (
        tool: WebMcpTool,
        options?: { signal?: AbortSignal },
      ) => void | Promise<void>;
    };
  }
}

interface WebMcpOptions {
  fields: FieldRecord[];
  selectedId: string;
  onSelectField: (fieldId: string) => void;
  onStartAdd: () => void;
}

export function useVegetationWebMcp({
  fields,
  selectedId,
  onSelectField,
  onStartAdd,
}: WebMcpOptions) {
  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const register = (tool: WebMcpTool) => {
      try {
        void Promise.resolve(
          context.registerTool(tool, { signal: lifecycle.signal }),
        ).catch(() => undefined);
      } catch {
        /* WebMCP остаётся необязательным для неподдерживаемых браузеров. */
      }
    };

    register({
      name: 'list_vegetation_fields',
      title: 'Показать поля',
      description:
        'Возвращает сохранённые поля, их NDVI и статус риска в текущем рабочем пространстве.',
      inputSchema: {
        type: 'object',
        properties: {},
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true, untrustedContentHint: false },
      execute: () => ({
        selectedFieldId: selectedId,
        fields: fields.map(({ id, name, crop, areaHa, ndvi, status }) => ({
          id,
          name,
          crop,
          areaHa,
          ndvi,
          status,
        })),
      }),
    });
    register({
      name: 'select_vegetation_field',
      title: 'Открыть поле',
      description:
        'Открывает существующее поле на карте по его идентификатору.',
      inputSchema: {
        type: 'object',
        properties: {
          fieldId: {
            type: 'string',
            description: 'Идентификатор из list_vegetation_fields',
          },
        },
        required: ['fieldId'],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      execute: (input) => {
        const fieldId = (input as { fieldId?: unknown })?.fieldId;
        if (
          typeof fieldId !== 'string' ||
          !fields.some((field) => field.id === fieldId)
        )
          throw new Error('Поле не найдено');
        onSelectField(fieldId);
        return { selectedFieldId: fieldId, status: 'opened' };
      },
    });
    register({
      name: 'start_field_creation',
      title: 'Добавить поле',
      description:
        'Открывает видимый мастер добавления территории. Пользователь завершает выбор или рисование на карте.',
      inputSchema: {
        type: 'object',
        properties: {},
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      execute: () => {
        onStartAdd();
        return { status: 'creation_started' };
      },
    });
    return () => lifecycle.abort();
  }, [fields, selectedId, onSelectField, onStartAdd]);
}
