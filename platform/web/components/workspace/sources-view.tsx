'use client';

import { Check, ChevronRight, CloudCog, Database, ExternalLink, KeyRound, RefreshCw, Satellite, Server, ShieldCheck, WifiOff } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { loadApiProviders } from '@/lib/api';
import type { ProviderStatus } from '@/lib/types';

const icons = { gee:CloudCog, cdse:Satellite, osm:Database, era5:Server };

export default function SourcesView() {
  const [checking,setChecking]=useState<string|null>(null);
  const [providers,setProviders]=useState<ProviderStatus[]>([]);
  const [loadError,setLoadError]=useState(false);
  const guideRef=useRef<HTMLElement>(null);
  const refresh=()=>loadApiProviders().then((items)=>{setProviders(items);setLoadError(false);}).catch(()=>{setProviders([]);setLoadError(true);});
  useEffect(()=>{void refresh();},[]);
  const check=(id:string)=>{setChecking(id);loadApiProviders().then(setProviders).catch(()=>undefined).finally(()=>setChecking(null));};
  const openGuide=()=>guideRef.current?.scrollIntoView({behavior:'smooth',block:'start'});
  const connected=providers.filter((item)=>item.status==='connected').length;
  return (
    <section className="wide-view sources-view">
      <header className="wide-header"><div><p className="eyebrow">Прозрачность конвейера</p><h1>Источники данных</h1><span>Доступность, состав данных и состояние подключений</span></div><div className="overall-health"><span><i/>{loadError?'Статус недоступен':providers.length&&connected===providers.length?'Все источники подключены':'Есть неподключённые источники'}</span><small>{connected} из {providers.length} источников подключено</small></div></header>
      <div className="pipeline-strip"><div><span className="pipeline-icon"><Satellite size={19}/></span><span><strong>Снимки</strong><small>Sentinel · Landsat · MODIS</small></span></div><ChevronRight size={16}/><div><span className="pipeline-icon"><CloudCog size={19}/></span><span><strong>Обработка</strong><small>Маска облаков · индексы</small></span></div><ChevronRight size={16}/><div><span className="pipeline-icon"><Database size={19}/></span><span><strong>Временной ряд</strong><small>Норма · восстановление</small></span></div><ChevronRight size={16}/><div><span className="pipeline-icon"><ShieldCheck size={19}/></span><span><strong>Результат</strong><small>Аномалии · объяснение</small></span></div></div>
      <div className="provider-grid">
        {providers.map((provider)=>{const Icon=icons[provider.id];return <article className="provider-card" key={provider.id}>
          <header><span className={`provider-logo ${provider.id}`}><Icon size={21}/></span><div><strong>{provider.name}</strong><span>{provider.description}</span></div><span className={`provider-status ${provider.status}`}>{provider.status==='connected'?<><Check size={13}/>Подключён</>:<><WifiOff size={13}/>Недоступен</>}</span></header>
          <div className="dataset-list">{provider.datasets.map((dataset)=><span key={dataset}>{dataset}</span>)}</div>
          <dl><div><dt>Проверка</dt><dd>{provider.latency}</dd></div><div><dt>Проверено</dt><dd>{provider.updatedAt}</dd></div><div><dt>Роль</dt><dd>{provider.id==='cdse'?'Резерв':provider.id==='gee'?'Основной':'Дополнение'}</dd></div></dl>
          <footer><button onClick={()=>check(provider.id)} className={checking===provider.id?'is-checking':''}><RefreshCw size={15}/> {checking===provider.id?'Проверяем…':'Проверить'}</button>{provider.status==='unavailable'&&<button className="connect-link" onClick={openGuide}><KeyRound size={15}/>Подключить</button>}</footer>
        </article>;})}
      </div>
      <section className="connect-guide" ref={guideRef}><div className="guide-heading"><span><KeyRound size={20}/></span><div><strong>Подключение спутниковых API</strong><p>Ключи хранятся только на сервере. Интерфейс никогда не получает секреты GEE или Copernicus.</p></div></div><div className="guide-columns"><div><strong>Google Earth Engine</strong><ol><li><span>1</span>Создайте Google Cloud Project</li><li><span>2</span>Включите Earth Engine API</li><li><span>3</span>Дайте сервисному аккаунту роль Earth Engine Resource Writer</li></ol><a href="https://developers.google.com/earth-engine/guides/service_account" target="_blank" rel="noreferrer">Официальная инструкция <ExternalLink size={14}/></a></div><div><strong>Copernicus Data Space</strong><ol><li><span>1</span>Создайте учётную запись CDSE</li><li><span>2</span>Зарегистрируйте OAuth-клиент</li><li><span>3</span>Добавьте Client ID и Secret</li></ol><a href="https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html" target="_blank" rel="noreferrer">Официальная инструкция <ExternalLink size={14}/></a></div></div></section>
    </section>
  );
}
