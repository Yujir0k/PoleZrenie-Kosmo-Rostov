'use client';

import {
  BarChart3,
  Bot,
  CheckCircle2,
  Download,
  FileText,
  ImagePlus,
  LoaderCircle,
  Send,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import Image from 'next/image';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  createAIReport,
  loadAIStatus,
  sendAIChat,
  sendAIVision,
} from '@/lib/api';
import type {
  AIResponse,
  AIStatus,
  AIVisualization,
  FieldRecord,
} from '@/lib/types';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  response?: AIResponse;
  imageUrl?: string;
};

type ReportOptions = {
  ndviChart: boolean;
  fieldContour: boolean;
  sources: boolean;
};

const quickPrompts = [
  'Что сейчас происходит с полем?',
  'Объясни ранний риск простыми словами',
  'Какие точки нужно проверить в первую очередь?',
  'Сравни фактический NDVI с сезонной нормой',
];

function renderInlineMarkdown(text: string) {
  return text.split(/(\*\*.+?\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={`${index}-${part.slice(2, 10)}`}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  );
}

function filterReportText(text: string, includeSources: boolean) {
  if (includeSources) return text;
  let skip = false;
  return text
    .split('\n')
    .filter((line) => {
      if (/^##\s+(Ограничения данных|Источники)/i.test(line)) {
        skip = true;
        return false;
      }
      if (skip && /^##\s+/.test(line)) skip = false;
      return !skip;
    })
    .join('\n')
    .trim();
}

function RichText({ text }: { text: string }) {
  return (
    <div className="ai-rich-text">
      {text.split('\n').map((line, index) => {
        const key = `${index}-${line.slice(0, 12)}`;
        if (line.startsWith('## '))
          return <h3 key={key}>{renderInlineMarkdown(line.slice(3))}</h3>;
        if (line.startsWith('### '))
          return <h4 key={key}>{renderInlineMarkdown(line.slice(4))}</h4>;
        if (/^[-*] /.test(line))
          return (
            <p className="ai-list-row" key={key}>
              <span>•</span>
              {renderInlineMarkdown(line.slice(2))}
            </p>
          );
        if (/^\d+\. /.test(line))
          return (
            <p className="ai-list-row" key={key}>
              {renderInlineMarkdown(line)}
            </p>
          );
        if (!line.trim()) return <span className="ai-text-gap" key={key} />;
        return <p key={key}>{renderInlineMarkdown(line)}</p>;
      })}
    </div>
  );
}

function NDVIChart({ visual }: { visual: AIVisualization }) {
  const points = visual.data ?? [];
  const values = points
    .flatMap((point) => [point.value, point.normal])
    .filter((value): value is number => value != null);
  if (points.length < 2 || !values.length) return null;
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0.9);
  const width = 560;
  const height = 190;
  const pad = 24;
  const x = (index: number) =>
    pad + (index / Math.max(1, points.length - 1)) * (width - pad * 2);
  const y = (value: number) =>
    height -
    pad -
    ((value - min) / Math.max(0.1, max - min)) * (height - pad * 2);
  const pathFor = (key: 'value' | 'normal') =>
    points
      .map((point, index) =>
        point[key] == null
          ? null
          : `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(point[key] as number).toFixed(1)}`,
      )
      .filter(Boolean)
      .join(' ');
  const latest = points.at(-1);
  return (
    <figure className="ai-visual-card">
      <figcaption>
        <span>
          <BarChart3 size={17} />
          <strong>{visual.title}</strong>
        </span>
        <small>{visual.subtitle}</small>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} aria-label="График динамики NDVI">
        {[0.25, 0.5, 0.75].map((tick) => (
          <line
            key={tick}
            x1={pad}
            x2={width - pad}
            y1={y(tick)}
            y2={y(tick)}
            className="ai-grid-line"
          />
        ))}
        <path d={pathFor('normal')} className="ai-chart-normal" />
        <path d={pathFor('value')} className="ai-chart-value" />
        {points.map((point, index) =>
          point.value == null ? null : (
            <circle
              key={point.date}
              cx={x(index)}
              cy={y(point.value)}
              r={point.restored ? 2.2 : 3}
              className={point.restored ? 'ai-dot-restored' : 'ai-dot-observed'}
            />
          ),
        )}
      </svg>
      <div className="ai-chart-legend">
        <span>
          <i className="actual" />
          NDVI поля
        </span>
        <span>
          <i className="normal" />
          Сезонная норма
        </span>
        {latest?.value != null ? (
          <strong>Последнее: {latest.value.toFixed(2)}</strong>
        ) : null}
      </div>
    </figure>
  );
}

function FieldContour({ visual }: { visual: AIVisualization }) {
  const polygon = useMemo(() => {
    const ring = visual.geometry?.coordinates?.[0] ?? [];
    if (!ring.length) return '';
    const xs = ring.map(([x]) => x);
    const ys = ring.map(([, y]) => y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    return ring
      .map(([lng, lat]) => {
        const x = 28 + ((lng - minX) / Math.max(0.000001, maxX - minX)) * 244;
        const y =
          22 + (1 - (lat - minY) / Math.max(0.000001, maxY - minY)) * 126;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }, [visual.geometry]);
  return (
    <figure className="ai-visual-card ai-contour-card">
      <figcaption>
        <span>
          <Sparkles size={17} />
          <strong>{visual.title}</strong>
        </span>
        <small>{visual.subtitle}</small>
      </figcaption>
      <svg viewBox="0 0 300 170" aria-label="Схема контура поля">
        <defs>
          <pattern
            id="field-grid"
            width="18"
            height="18"
            patternUnits="userSpaceOnUse"
          >
            <path d="M 18 0 L 0 0 0 18" />
          </pattern>
        </defs>
        <rect width="300" height="170" rx="16" className="ai-field-bg" />
        <rect
          width="300"
          height="170"
          rx="16"
          fill="url(#field-grid)"
          className="ai-field-grid"
        />
        {polygon ? (
          <polygon points={polygon} className="ai-field-polygon" />
        ) : null}
      </svg>
    </figure>
  );
}

function Visuals({ items }: { items: AIVisualization[] }) {
  if (!items.length) return null;
  return (
    <div className="ai-visuals">
      {items.map((item, index) =>
        item.kind === 'ndvi_chart' ? (
          <NDVIChart key={`${item.kind}-${index}`} visual={item} />
        ) : (
          <FieldContour key={`${item.kind}-${index}`} visual={item} />
        ),
      )}
    </div>
  );
}

export default function AIAssistant({
  open,
  field,
  onClose,
}: {
  open: boolean;
  field: FieldRecord | null;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [mode, setMode] = useState<'chat' | 'report'>('chat');
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [attachment, setAttachment] = useState<string | null>(null);
  const [reportRequest, setReportRequest] = useState(
    'Подготовь полный отчёт о состоянии поля, объясни ранние сигналы и составь план полевого осмотра.',
  );
  const [report, setReport] = useState<AIResponse | null>(null);
  const [reportOptions, setReportOptions] = useState<ReportOptions>({
    ndviChart: true,
    fieldContour: true,
    sources: true,
  });
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [error, setError] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    void loadAIStatus()
      .then(setStatus)
      .catch(() => setError('Не удалось проверить подключение AI-сервиса.'));
  }, [open]);
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, busy]);
  if (!open) return null;

  const submitChat = async (value = input) => {
    const text = value.trim();
    if (!text || !field || busy) return;
    const imageUrl = attachment;
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      imageUrl: imageUrl ?? undefined,
    };
    setMessages((current) => [...current, userMessage]);
    setInput('');
    setAttachment(null);
    setBusy(true);
    setError('');
    try {
      const response = imageUrl
        ? await sendAIVision(field.id, text, imageUrl)
        : await sendAIChat(
            field.id,
            text,
            messages.map(({ role, content }) => ({ role, content })),
          );
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: response.message,
          response,
        },
      ]);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Помощник не ответил.',
      );
    } finally {
      setBusy(false);
    }
  };
  const chooseImage = (file?: File) => {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setError('Можно прикрепить только изображение.');
      return;
    }
    if (file.size > 5_500_000) {
      setError('Изображение должно быть меньше 5,5 МБ.');
      return;
    }
    const reader = new FileReader();
    reader.onload = () =>
      setAttachment(typeof reader.result === 'string' ? reader.result : null);
    reader.onerror = () => setError('Не удалось прочитать изображение.');
    reader.readAsDataURL(file);
  };
  const generateReport = async () => {
    if (!field || busy) return;
    setBusy(true);
    setError('');
    try {
      const included = [
        reportOptions.ndviChart ? 'график фактического NDVI и сезонной нормы' : null,
        reportOptions.fieldContour ? 'схему контура поля' : null,
        reportOptions.sources ? 'источники и ограничения данных' : null,
      ].filter(Boolean);
      setReport(
        await createAIReport(
          field.id,
          `${reportRequest}\n\nВ итоговый материал включи: ${included.join(', ') || 'только запрошенный текстовый анализ'}.`,
        ),
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Не удалось сформировать отчёт.',
      );
    } finally {
      setBusy(false);
    }
  };
  const downloadReport = async () => {
    if (!report || !field) return;
    setPdfBusy(true);
    setError('');
    try {
      const { downloadAgronomyReport } = await import('@/lib/report-pdf');
      const visualizations = report.visualizations.filter(
        (visual) =>
          (visual.kind === 'ndvi_chart' && reportOptions.ndviChart) ||
          (visual.kind === 'field_contour' && reportOptions.fieldContour),
      );
      await downloadAgronomyReport({
        field,
        report: {
          ...report,
          message: filterReportText(report.message, reportOptions.sources),
          visualizations,
        },
        options: reportOptions,
      });
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Не удалось создать PDF.',
      );
    } finally {
      setPdfBusy(false);
    }
  };

  const visibleReportText = report
    ? filterReportText(report.message, reportOptions.sources)
    : '';
  const visibleReportVisualizations = report?.visualizations.filter(
    (visual) =>
      (visual.kind === 'ndvi_chart' && reportOptions.ndviChart) ||
      (visual.kind === 'field_contour' && reportOptions.fieldContour),
  );

  return (
    <dialog
      open
      className="ai-assistant-overlay"
      aria-label="AI-помощник агронома"
    >
      <section className="ai-assistant-window">
        <header className="ai-assistant-header">
          <div className="ai-assistant-brand">
            <span>
              <Bot size={22} />
            </span>
            <div>
              <small>AI‑помощник агронома</small>
              <strong>{field?.name ?? 'Выберите поле'}</strong>
            </div>
          </div>
          <div className="ai-header-meta">
            <span className={status?.configured ? 'is-online' : ''}>
              <i />
              {status?.configured
                ? 'Yandex AI подключён'
                : 'Требуется подключение'}
            </span>
            <button onClick={onClose} aria-label="Закрыть">
              <X size={21} />
            </button>
          </div>
        </header>
        <div className="ai-mode-tabs">
          <button
            className={mode === 'chat' ? 'is-active' : ''}
            onClick={() => setMode('chat')}
          >
            <Bot size={17} />
            Задать вопрос
          </button>
          <button
            className={mode === 'report' ? 'is-active' : ''}
            onClick={() => setMode('report')}
          >
            <FileText size={17} />
            Составить отчёт
          </button>
          <div className="ai-model-route">
            <ShieldCheck size={15} />
            <span>Ответы основаны на данных выбранного поля</span>
          </div>
        </div>

        {!field ? (
          <div className="ai-empty">
            <Bot size={34} />
            <h2>Сначала выберите поле</h2>
            <p>
              Помощник всегда работает в контексте одного поля и не смешивает
              данные разных территорий.
            </p>
          </div>
        ) : null}
        {field && status && !status.configured ? (
          <div className="ai-setup-card">
            <span>
              <ShieldCheck size={24} />
            </span>
            <div>
              <h2>Остался один шаг — добавить ключ</h2>
              <p>
                Создайте API‑ключ в Yandex AI Studio и сохраните его в серверном
                файле <code>platform/.env</code>. В браузер ключ не передаётся.
              </p>
              <pre>
                YANDEX_API_KEY=ваш_секретный_ключ{`\n`}
                YANDEX_FOLDER_ID=идентификатор_каталога
              </pre>
              <small>
                После сохранения перезапустите API. Модели уже настроены: Alice
                Flash, YandexGPT 5.1 Pro и Qwen3.6 35B.
              </small>
            </div>
          </div>
        ) : null}

        {field && status?.configured && mode === 'chat' ? (
          <div className="ai-chat-layout">
            <div className="ai-chat-main">
              <div className="ai-chat-scroll" ref={scrollRef}>
                {!messages.length ? (
                  <div className="ai-welcome">
                    <span>
                      <Sparkles size={26} />
                    </span>
                    <h2>Что вы хотите узнать о поле?</h2>
                    <p>
                      Я могу объяснить динамику индексов, ранние сигналы, погоду
                      и точки осмотра. Цифры получаю напрямую из базы
                      «ПолеЗрения».
                    </p>
                    <div>
                      {quickPrompts.map((prompt) => (
                        <button
                          key={prompt}
                          onClick={() => void submitChat(prompt)}
                        >
                          {prompt}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
                {messages.map((message) => (
                  <article
                    key={message.id}
                    className={`ai-message ${message.role}`}
                  >
                    <span>
                      {message.role === 'assistant' ? <Bot size={17} /> : 'Вы'}
                    </span>
                    <div>
                      {message.imageUrl ? (
                        <Image
                          className="ai-message-image"
                          src={message.imageUrl}
                          alt="Прикреплённый снимок поля"
                          width={420}
                          height={230}
                          unoptimized
                        />
                      ) : null}
                      <RichText text={message.content} />
                      {message.response ? (
                        <>
                          <Visuals
                            items={message.response.visualizations.filter(
                              (item) => item.kind === 'ndvi_chart',
                            )}
                          />
                          <small className="ai-answer-source">
                            <CheckCircle2 size={13} />
                            {message.response.model} · проверенные функции:{' '}
                            {message.response.usedTools.join(', ') ||
                              'контекст диалога'}
                          </small>
                        </>
                      ) : null}
                    </div>
                  </article>
                ))}
                {busy ? (
                  <div className="ai-thinking">
                    <LoaderCircle size={17} />
                    Проверяю данные поля…
                  </div>
                ) : null}
              </div>
              <div
                className={`ai-composer ${attachment ? 'has-attachment' : ''}`}
              >
                {attachment ? (
                  <div className="ai-attachment-preview">
                    <Image
                      src={attachment}
                      alt="Снимок для анализа"
                      width={32}
                      height={30}
                      unoptimized
                    />
                    <span>Снимок готов к анализу Qwen3.6</span>
                    <button
                      onClick={() => setAttachment(null)}
                      aria-label="Убрать изображение"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : null}
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      void submitChat();
                    }
                  }}
                  placeholder={
                    attachment
                      ? 'Что нужно проверить на этом снимке?'
                      : 'Например: почему NDVI падает и что проверить?'
                  }
                />
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(event) => {
                    chooseImage(event.target.files?.[0]);
                    event.currentTarget.value = '';
                  }}
                />
                <button
                  className="ai-image-button"
                  onClick={() => fileRef.current?.click()}
                  aria-label="Добавить изображение"
                >
                  <ImagePlus size={18} />
                </button>
                <button
                  className="ai-send-button"
                  disabled={!input.trim() || busy}
                  onClick={() => void submitChat()}
                  aria-label="Отправить"
                >
                  <Send size={18} />
                </button>
                <small>Enter — отправить · можно приложить снимок поля</small>
              </div>
            </div>
            <aside className="ai-context-panel">
              <h3>Контекст ответа</h3>
              <dl>
                <div>
                  <dt>Поле</dt>
                  <dd>{field.name}</dd>
                </div>
                <div>
                  <dt>Площадь</dt>
                  <dd>{field.areaHa.toLocaleString('ru-RU')} га</dd>
                </div>
                <div>
                  <dt>Культура</dt>
                  <dd>{field.crop}</dd>
                </div>
                <div>
                  <dt>Последняя сцена</dt>
                  <dd>{field.sceneDate ?? 'нет анализа'}</dd>
                </div>
              </dl>
              <p>
                <ShieldCheck size={15} />
                Помощник не использует будущие данные и обозначает гипотезы
                отдельно от фактов.
              </p>
            </aside>
          </div>
        ) : null}

        {field && status?.configured && mode === 'report' ? (
          <div className="ai-report-layout">
            <aside className="ai-report-builder">
              <span className="ai-step">1</span>
              <h2>Что включить в отчёт</h2>
              <p>
                Можно попросить краткую сводку, анализ конкретного периода или
                план осмотра.
              </p>
              <textarea
                value={reportRequest}
                onChange={(event) => setReportRequest(event.target.value)}
              />
              <label>
                <input
                  type="checkbox"
                  checked={reportOptions.ndviChart}
                  onChange={(event) =>
                    setReportOptions((current) => ({
                      ...current,
                      ndviChart: event.target.checked,
                    }))
                  }
                />
                График фактического NDVI и нормы
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={reportOptions.fieldContour}
                  onChange={(event) =>
                    setReportOptions((current) => ({
                      ...current,
                      fieldContour: event.target.checked,
                    }))
                  }
                />
                Схема контура выбранного поля
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={reportOptions.sources}
                  onChange={(event) =>
                    setReportOptions((current) => ({
                      ...current,
                      sources: event.target.checked,
                    }))
                  }
                />
                Источники и ограничения данных
              </label>
              <button
                onClick={() => void generateReport()}
                disabled={busy || !reportRequest.trim()}
              >
                {busy ? <LoaderCircle size={18} /> : <Sparkles size={18} />}
                {busy ? 'Собираю отчёт…' : 'Сформировать отчёт'}
              </button>
              <small>Итоговый текст: {status.models.report}</small>
            </aside>
            <div className="ai-report-preview">
              {report ? (
                <>
                  <header>
                    <div>
                      <small>
                        AI‑отчёт ·{' '}
                        {new Intl.DateTimeFormat('ru-RU').format(new Date())} ·{' '}
                        {report.model}
                      </small>
                      <h1>{field.name}</h1>
                    </div>
                    <button
                      onClick={() => void downloadReport()}
                      disabled={pdfBusy}
                    >
                      {pdfBusy ? <LoaderCircle size={16} /> : <Download size={16} />}
                      {pdfBusy ? 'Создаю PDF…' : 'Скачать PDF'}
                    </button>
                  </header>
                  {report.usedTools.includes('fallback_model') ? (
                    <div className="ai-report-fallback-note">
                      Основная модель временно не ответила — отчёт сформирован
                      резервной AI‑моделью по тем же данным поля.
                    </div>
                  ) : null}
                  {report.usedTools.includes('local_fallback') ? (
                    <div className="ai-report-fallback-note is-local">
                      Yandex AI временно недоступен — показана проверенная
                      резервная сводка без выдуманных выводов. Можно скачать PDF
                      или повторить AI‑анализ позже.
                    </div>
                  ) : null}
                  <RichText text={visibleReportText} />
                  {visibleReportVisualizations?.length ? (
                    <>
                      <h3 className="ai-report-visual-title">
                        Визуальные материалы
                      </h3>
                      <Visuals items={visibleReportVisualizations} />
                    </>
                  ) : null}
                  <footer>
                    <ShieldCheck size={15} />
                    Автоматический анализ помогает принять решение, но не
                    заменяет полевой осмотр агронома.
                  </footer>
                </>
              ) : (
                <div className="ai-report-placeholder">
                  <FileText size={42} />
                  <h2>Здесь появится готовый отчёт</h2>
                  <p>
                    Он будет собран только по выбранному полю и автоматически
                    дополнен графиком и схемой территории.
                  </p>
                </div>
              )}
            </div>
          </div>
        ) : null}
        {error ? (
          <div className="ai-error" role="alert">
            <span>{error}</span>
            <button onClick={() => setError('')}>
              <X size={15} />
            </button>
          </div>
        ) : null}
      </section>
    </dialog>
  );
}
