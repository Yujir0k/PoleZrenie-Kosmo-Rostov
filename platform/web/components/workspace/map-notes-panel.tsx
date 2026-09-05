'use client';

import { Check, MapPin, Plus, Trash2, X } from 'lucide-react';
import { useState } from 'react';

import type { MapNote, Position } from '@/lib/types';

interface MapNotesPanelProps {
  notes: MapNote[];
  placing: boolean;
  draftPosition: Position | null;
  selectedNoteId: string;
  onBeginPlace: () => void;
  onCancelPlace: () => void;
  onSelect: (id: string) => void;
  onSave: (title: string, text: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

function NoteDraftForm({
  position,
  onSave,
  onCancel,
}: {
  position: Position;
  onSave: (title: string, text: string) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  return (
    <form
      className="note-draft"
      onSubmit={(event) => {
        event.preventDefault();
        if (title.trim()) onSave(title.trim(), text.trim());
      }}
    >
      <span>
        <b>2</b>
        <MapPin size={15} />
        Место выбрано · добавьте пояснение
      </span>
      <label>
        Название
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={160}
          placeholder="Например, очаг сорняков"
        />
      </label>
      <label>
        Комментарий
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={2000}
          placeholder="Необязательно"
        />
      </label>
      <small>
        {position[1].toFixed(5)}, {position[0].toFixed(5)}
      </small>
      <div>
        <button type="button" onClick={onCancel}>
          Отмена
        </button>
        <button className="note-save" disabled={!title.trim()}>
          <Check size={15} />
          Сохранить
        </button>
      </div>
    </form>
  );
}

export default function MapNotesPanel({
  notes,
  placing,
  draftPosition,
  selectedNoteId,
  onBeginPlace,
  onCancelPlace,
  onSelect,
  onSave,
  onDelete,
  onClose,
}: MapNotesPanelProps) {
  return (
    <aside className="map-notes-panel" aria-label="Метки на карте">
      <header>
        <div>
          <span>Левая панель карты</span>
          <h2>Метки и заметки</h2>
        </div>
        <button onClick={onClose} aria-label="Вернуться к полям">
          <X size={18} />
        </button>
      </header>
      <p className="notes-panel-intro">
        Личные наблюдения не смешиваются с системными точками осмотра.
      </p>
      <button
        className={`start-note ${placing ? 'is-active' : ''}`}
        onClick={placing ? onCancelPlace : onBeginPlace}
      >
        <Plus size={17} />
        {placing ? 'Отменить выбор места' : 'Новая метка на карте'}
      </button>
      {placing ? (
        <div className="note-placement-state">
          <b>1</b>
          <MapPin size={18} />
          <div>
            <strong>Укажите место на карте</strong>
            <span>Щёлкните в нужной точке — затем добавьте название.</span>
          </div>
        </div>
      ) : null}
      {draftPosition ? (
        <NoteDraftForm
          key={draftPosition.join(':')}
          position={draftPosition}
          onSave={onSave}
          onCancel={onCancelPlace}
        />
      ) : null}
      <div className="notes-list-title">
        <strong>Список меток</strong>
        <span>{notes.length}</span>
      </div>
      <div className="notes-list">
        {notes.map((note) => (
          <article
            key={note.id}
            className={note.id === selectedNoteId ? 'is-selected' : ''}
          >
            <button className="note-open" onClick={() => onSelect(note.id)}>
              <MapPin size={17} />
              <span>
                <strong>{note.title}</strong>
                <small>
                  {note.text ||
                    new Intl.DateTimeFormat('ru-RU', {
                      day: 'numeric',
                      month: 'long',
                      hour: '2-digit',
                      minute: '2-digit',
                    }).format(new Date(note.createdAt))}
                </small>
              </span>
            </button>
            <button
              className="note-delete"
              onClick={() => onDelete(note.id)}
              aria-label={`Удалить метку ${note.title}`}
            >
              <Trash2 size={15} />
            </button>
          </article>
        ))}
        {!notes.length && !draftPosition ? (
          <div className="notes-empty">
            <MapPin size={22} />
            <strong>Меток пока нет</strong>
            <span>Добавьте точку наблюдения, проблему или напоминание.</span>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
