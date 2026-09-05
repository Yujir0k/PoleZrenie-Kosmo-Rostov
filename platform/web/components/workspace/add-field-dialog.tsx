'use client';

import { Crosshair, MapPinned } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DEFAULT_REGION } from '@/lib/regions';
import type { FieldGeometry, FieldSource, RegionResult } from '@/lib/types';
import RegionSearch from './region-search';

interface AddFieldDialogProps {
  open: boolean;
  geometry: FieldGeometry | null;
  areaHa: number;
  source: FieldSource;
  initialRegion: RegionResult | null;
  onOpenChange: (open: boolean) => void;
  onStartCandidates: (region:RegionResult) => void;
  onStartDrawing: () => void;
  onSave: (name: string, crop: string, region:string) => void;
}

const crops = ['Озимая пшеница','Яровой ячмень','Кукуруза','Подсолнечник','Соя','Рапс','Культура не указана'];

export default function AddFieldDialog({ open, geometry, areaHa, source, initialRegion, onOpenChange, onStartCandidates, onStartDrawing, onSave }: AddFieldDialogProps) {
  const [name, setName] = useState('');
  const [crop, setCrop] = useState('Культура не указана');
  const [selectedRegion,setSelectedRegion]=useState<RegionResult>(DEFAULT_REGION);
  const detailsStep = Boolean(geometry);

  useEffect(() => {
    if (!open) return;
    queueMicrotask(()=>{
      if (!geometry) { setName(''); setCrop('Культура не указана'); }
      else setName((current)=>current || (source === 'drawn' ? 'Новое поле' : 'Поле из OSM'));
    });
  }, [open, geometry, source]);

  useEffect(()=>{
    if(open&&!geometry&&initialRegion)queueMicrotask(()=>setSelectedRegion(initialRegion));
  },[geometry,initialRegion,open]);

  const submit = (event: React.SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim() || !geometry) return;
    onSave(name.trim(), crop, selectedRegion.name);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="add-dialog sm:max-w-[540px]" showCloseButton>
        <DialogHeader>
          <div className="dialog-step">Шаг {detailsStep ? '3' : '1'} из 3</div>
          <DialogTitle className="dialog-title">{detailsStep ? 'Сохраните поле' : 'Добавьте территорию'}</DialogTitle>
          <DialogDescription>{detailsStep ? 'Проверьте площадь и добавьте сведения — анализ запустится автоматически.' : 'Сначала укажите регион, затем выберите готовый контур или нарисуйте свой.'}</DialogDescription>
        </DialogHeader>

        {!detailsStep ? (
          <div className="add-dialog-body">
            <Field><FieldLabel className="dialog-label">Регион или координаты</FieldLabel><RegionSearch key={selectedRegion.id} variant="dialog" initialValue={selectedRegion.name} onSelect={setSelectedRegion}/></Field>
            <div className="region-result"><MapPinned size={18} /><div><strong>{selectedRegion.name}</strong><span>{selectedRegion.displayName}</span></div><span className="result-ready">Выбрано</span></div>

            <div className="method-grid">
              <button type="button" className="method-card" onClick={()=>onStartCandidates(selectedRegion)}>
                <span className="method-icon"><MapPinned size={22} /></span>
                <strong>Выбрать на карте</strong>
                <small>Покажем открытые контуры OSM. Нажмите на поле, чтобы выбрать.</small>
                <span className="method-action">Открыть контуры на карте →</span>
              </button>
              <button type="button" className="method-card" onClick={onStartDrawing}>
                <span className="method-icon"><Crosshair size={22} /></span>
                <strong>Нарисовать контур</strong>
                <small>Отметьте вершины вручную и уточните границу прямо на карте.</small>
                <span className="method-action">До 5 000 га</span>
              </button>
            </div>
            <div className="demo-note"><MapPinned size={16} /><span><strong>Реальные источники.</strong> После сохранения сервер проверит сельхозпрофиль и соберёт Sentinel‑2, Landsat, MODIS и ERA5‑Land. При ошибке источник будет показан как недоступный.</span></div>
          </div>
        ) : (
          <form onSubmit={submit} className="add-dialog-body">
            <div className="geometry-summary">
              <div className={`geometry-preview ${source}`}><span /><span /><span /></div>
              <div><span>Площадь контура</span><strong>{areaHa.toLocaleString('ru-RU',{maximumFractionDigits:1})} га</strong><small>{source === 'osm' ? 'Источник: OpenStreetMap' : 'Контур нарисован вручную'}</small></div>
              <span className="valid-badge">Геометрия корректна</span>
            </div>
            <FieldGroup className="field-form-group"><Field><FieldLabel className="dialog-label" htmlFor="field-name">Название поля</FieldLabel><Input id="field-name" className="form-control" value={name} onChange={(event)=>setName(event.target.value)} /></Field><Field><FieldLabel className="dialog-label" htmlFor="crop-select">Культура</FieldLabel><Select value={crop} onValueChange={(value)=>setCrop(value ?? 'Культура не указана')}><SelectTrigger id="crop-select" className="crop-select-trigger"><SelectValue /></SelectTrigger><SelectContent className="crop-select-content" alignItemWithTrigger={false}><SelectGroup>{crops.map((item)=><SelectItem key={item} value={item} className="crop-select-item">{item}</SelectItem>)}</SelectGroup></SelectContent></Select></Field></FieldGroup>
            <DialogFooter className="dialog-footer">
              <Button type="button" variant="outline" onClick={()=>onOpenChange(false)}>Отмена</Button>
              <Button type="submit" disabled={!name.trim()} className="save-field-button">Сохранить и анализировать</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
