import * as pdfMake from 'pdfmake/build/pdfmake';
import * as embeddedFonts from 'pdfmake/build/vfs_fonts';
import type { Content, TDocumentDefinitions } from 'pdfmake/interfaces';

import type { AIResponse, AIVisualization, FieldRecord } from '@/lib/types';

export interface ReportPdfOptions {
  ndviChart: boolean;
  fieldContour: boolean;
  sources: boolean;
}

interface ReportPdfInput {
  field: FieldRecord;
  report: AIResponse;
  options: ReportPdfOptions;
  generatedAt?: Date;
}

const PDF_GREEN = '#174f3f';
const PDF_MUTED = '#6f7e76';
const PDF_LIGHT = '#f0f5ec';

function escapeXml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function inlineMarkdown(value: string) {
  const parts: Array<string | { text: string; bold: true }> = [];
  const pattern = /\*\*(.+?)\*\*/g;
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(value.slice(cursor, index));
    parts.push({ text: match[1], bold: true });
    cursor = index + match[0].length;
  }
  if (cursor < value.length) parts.push(value.slice(cursor));
  return parts.length ? parts : [value];
}

function markdownContent(markdown: string): Content[] {
  return markdown.split('\n').flatMap((line): Content[] => {
    if (line.startsWith('### ')) {
      return [{ text: inlineMarkdown(line.slice(4)), style: 'subheading' } as Content];
    }
    if (line.startsWith('## ')) {
      return [{ text: inlineMarkdown(line.slice(3)), style: 'sectionHeading' } as Content];
    }
    if (/^[-*] /.test(line)) {
      return [
        {
          ul: [{ text: inlineMarkdown(line.slice(2)) }],
          margin: [8, 1, 0, 2],
        } as Content,
      ];
    }
    const numbered = line.match(/^(\d+)\.\s+(.+)$/);
    if (numbered) {
      return [
        {
          columns: [
            { text: `${numbered[1]}.`, width: 20, bold: true, color: '#3f8d63' },
            { text: inlineMarkdown(numbered[2]), width: '*' },
          ],
          margin: [0, 1, 0, 3],
        } as Content,
      ];
    }
    if (!line.trim()) return [{ text: '', margin: [0, 2] } as Content];
    return [{ text: inlineMarkdown(line), style: 'body' } as Content];
  });
}

function chartSvg(visual: AIVisualization) {
  const points = visual.data ?? [];
  const values = points
    .flatMap((point) => [point.value, point.normal])
    .filter((value): value is number => value != null);
  if (points.length < 2 || !values.length) return '';
  const width = 720;
  const height = 230;
  const padX = 38;
  const padY = 28;
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0.9);
  const x = (index: number) =>
    padX + (index / Math.max(1, points.length - 1)) * (width - padX * 2);
  const y = (value: number) =>
    height - padY - ((value - min) / Math.max(0.1, max - min)) * (height - padY * 2);
  const path = (key: 'value' | 'normal') =>
    points
      .map((point, index) =>
        point[key] == null
          ? null
          : `${index ? 'L' : 'M'}${x(index).toFixed(1)} ${y(point[key] as number).toFixed(1)}`,
      )
      .filter(Boolean)
      .join(' ');
  const grid = [0.25, 0.5, 0.75]
    .map(
      (tick) =>
        `<line x1="${padX}" x2="${width - padX}" y1="${y(tick)}" y2="${y(tick)}" stroke="#dfe6dc" stroke-dasharray="5 5"/>`,
    )
    .join('');
  const dots = points
    .map((point, index) =>
      point.value == null
        ? ''
        : `<circle cx="${x(index)}" cy="${y(point.value)}" r="3" fill="${point.restored ? '#ffffff' : PDF_GREEN}" stroke="${point.restored ? '#d79533' : '#ffffff'}" stroke-width="1.5"/>`,
    )
    .join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" rx="14" fill="#f8faf5"/>${grid}<path d="${path('normal')}" fill="none" stroke="#98b65f" stroke-width="2.4" stroke-dasharray="7 6"/><path d="${path('value')}" fill="none" stroke="#287d55" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>${dots}</svg>`;
}

function contourSvg(visual: AIVisualization) {
  const ring = visual.geometry?.coordinates?.[0] ?? [];
  if (!ring.length) return '';
  const xs = ring.map(([x]) => x);
  const ys = ring.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const points = ring
    .map(([lng, lat]) => {
      const x = 35 + ((lng - minX) / Math.max(0.000001, maxX - minX)) * 650;
      const y = 24 + (1 - (lat - minY) / Math.max(0.000001, maxY - minY)) * 185;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="720" height="235" viewBox="0 0 720 235"><rect width="720" height="235" rx="14" fill="#eef3e8"/><path d="M0 55H720M0 110H720M0 165H720M120 0V235M240 0V235M360 0V235M480 0V235M600 0V235" stroke="#d9e3d4" stroke-width="1"/><polygon points="${escapeXml(points)}" fill="#cbe98a" fill-opacity="0.62" stroke="#408359" stroke-width="4"/></svg>`;
}

function visualizationContent(visual: AIVisualization): Content[] {
  const svg = visual.kind === 'ndvi_chart' ? chartSvg(visual) : contourSvg(visual);
  if (!svg) return [];
  return [
    {
      stack: [
        { text: visual.title, style: 'visualHeading' },
        { text: visual.subtitle, style: 'visualSubtitle' },
        {
          svg,
          fit: [500, visual.kind === 'field_contour' ? 112 : 138],
          margin: [0, 8, 0, 0],
        },
      ],
      margin: [0, 0, 0, 14],
      unbreakable: true,
    } as Content,
  ];
}

function safeFilename(value: string) {
  return value.replace(/[^a-zа-яё0-9]+/gi, '-').replace(/^-|-$/g, '') || 'pole';
}

export async function downloadAgronomyReport({
  field,
  report,
  options,
  generatedAt = new Date(),
}: ReportPdfInput) {
  const formattedDate = new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  }).format(generatedAt);
  const content: Content[] = [
    {
      columns: [
        {
          stack: [
            { text: 'ПОЛЕЗРЕНИЕ', style: 'brand' },
            { text: 'AI-ОТЧЁТ АГРОНОМА', style: 'eyebrow' },
          ],
        },
        {
          stack: [
            { text: formattedDate },
            ...(options.sources
              ? [{ text: `ПолеЗрение · ${report.model}`, fontSize: 7, margin: [0, 3, 0, 0] }]
              : []),
          ],
          alignment: 'right',
          color: PDF_MUTED,
          fontSize: 9,
        },
      ],
      margin: [0, 0, 0, 18],
    } as Content,
    { text: field.name, style: 'title' } as Content,
    {
      table: {
        widths: ['*', '*', '*'],
        body: [
          [
            { text: [{ text: 'ПЛОЩАДЬ\n', style: 'metaLabel' }, { text: `${field.areaHa.toLocaleString('ru-RU')} га`, bold: true }] },
            { text: [{ text: 'КУЛЬТУРА\n', style: 'metaLabel' }, { text: field.crop || 'Не указана', bold: true }] },
            { text: [{ text: 'ПОСЛЕДНЯЯ СЦЕНА\n', style: 'metaLabel' }, { text: field.sceneDate || 'Нет данных', bold: true }] },
          ],
        ],
      },
      layout: {
        fillColor: () => PDF_LIGHT,
        hLineColor: () => '#dce5d9',
        vLineColor: () => '#dce5d9',
        paddingLeft: () => 12,
        paddingRight: () => 12,
        paddingTop: () => 10,
        paddingBottom: () => 10,
      },
      margin: [0, 10, 0, 22],
    } as Content,
    ...markdownContent(report.message),
  ];

  if (report.visualizations.length) {
    content.push({ text: 'Визуальные материалы', style: 'sectionHeading' } as Content);
    report.visualizations.forEach((visual) => content.push(...visualizationContent(visual)));
  }
  const definition: TDocumentDefinitions = {
    pageSize: 'A4',
    pageMargins: [46, 44, 46, 52],
    content,
    defaultStyle: {
      font: 'Roboto',
      fontSize: 10,
      color: '#24352e',
      lineHeight: 1.35,
    },
    styles: {
      brand: { fontSize: 11, bold: true, color: PDF_GREEN, characterSpacing: 1.4 },
      eyebrow: { fontSize: 8, bold: true, color: '#4c8b68', characterSpacing: 1.1, margin: [0, 3, 0, 0] },
      title: { fontSize: 26, bold: true, color: '#172820' },
      metaLabel: { fontSize: 7, bold: true, color: PDF_MUTED, characterSpacing: 0.7 },
      sectionHeading: { fontSize: 16, bold: true, color: PDF_GREEN, margin: [0, 15, 0, 7] },
      subheading: { fontSize: 12, bold: true, color: '#245f49', margin: [0, 9, 0, 4] },
      body: { fontSize: 10, margin: [0, 0, 0, 6] },
      visualHeading: { fontSize: 11, bold: true, color: PDF_GREEN },
      visualSubtitle: { fontSize: 8, color: PDF_MUTED, margin: [0, 2, 0, 0] },
    },
    footer: (currentPage, pageCount) => ({
      columns: [
        {
          text: 'Автоматический анализ не заменяет полевой осмотр агронома.',
          color: PDF_MUTED,
          fontSize: 8,
        },
        {
          text: `${currentPage} / ${pageCount}`,
          alignment: 'right',
          color: PDF_MUTED,
          fontSize: 8,
        },
      ],
      margin: [46, 16, 46, 0],
    }),
  };

  const fontNamespace = embeddedFonts as unknown as {
    default?: Record<string, string>;
  };
  const virtualFonts = fontNamespace.default ?? (embeddedFonts as unknown as Record<string, string>);
  const filename = `${safeFilename(field.name)}-ai-report.pdf`;
  await new Promise<void>((resolve) => {
    pdfMake.createPdf(definition, undefined, undefined, virtualFonts).download(filename, resolve);
  });
}
