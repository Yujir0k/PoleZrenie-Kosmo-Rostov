import { searchApiRegions } from './api';
import type { RegionResult } from './types';

export const DEFAULT_REGION: RegionResult = {
  id: 'rostov-region',
  name: 'Ростовская область',
  displayName: 'Ростовская область, Россия',
  lat: 47.86,
  lon: 41.18,
  boundingBox: [45.95, 50.21, 38.22, 44.32],
};

export const FALLBACK_REGIONS: RegionResult[] = [
  DEFAULT_REGION,
  { id:'moscow-city', name:'Москва', displayName:'Москва, Центральный федеральный округ, Россия', lat:55.76, lon:37.62, boundingBox:[55.14,56.02,36.80,37.97] },
  { id:'moscow-region', name:'Московская область', displayName:'Московская область, Россия', lat:55.50, lon:38.00, boundingBox:[54.25,56.96,35.15,40.20] },
  { id:'krasnodar-region', name:'Краснодарский край', displayName:'Краснодарский край, Россия', lat:45.04, lon:38.98, boundingBox:[43.38,46.93,36.59,41.75] },
  { id:'stavropol-region', name:'Ставропольский край', displayName:'Ставропольский край, Россия', lat:45.05, lon:41.97, boundingBox:[43.72,46.23,40.84,45.67] },
  { id:'voronezh-region', name:'Воронежская область', displayName:'Воронежская область, Россия', lat:51.67, lon:39.18, boundingBox:[49.55,52.10,38.14,42.95] },
  { id:'belgorod-region', name:'Белгородская область', displayName:'Белгородская область, Россия', lat:50.60, lon:36.59, boundingBox:[49.80,51.44,35.33,39.28] },
  { id:'altai-region', name:'Алтайский край', displayName:'Алтайский край, Россия', lat:53.35, lon:83.78, boundingBox:[50.64,54.45,77.89,87.34] },
];

const normalize = (value:string) => value.trim().toLocaleLowerCase('ru-RU');

function coordinateResult(query:string):RegionResult | undefined {
  const match=query.trim().replace(';',',').match(/^(-?\d{1,2}(?:[.,]\d+)?)\s*[, ]\s*(-?\d{1,3}(?:[.,]\d+)?)$/);
  if(!match)return undefined;
  const lat=Number(match[1].replace(',','.'));
  const lon=Number(match[2].replace(',','.'));
  if(!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180)return undefined;
  return {id:`coords-${lat}-${lon}`,name:`${lat.toFixed(5)}, ${lon.toFixed(5)}`,displayName:'Точка по введённым координатам',lat,lon,boundingBox:[lat-.08,lat+.08,lon-.12,lon+.12]};
}

export interface RegionLookup {
  items: RegionResult[];
  offline: boolean;
}

export async function findRegions(query:string):Promise<RegionLookup> {
  const coordinate=coordinateResult(query);
  if(coordinate)return {items:[coordinate],offline:false};
  const normalized=normalize(query);
  const local=FALLBACK_REGIONS.filter((item)=>normalize(`${item.name} ${item.displayName}`).includes(normalized));
  const exactLocal=local.find((item)=>normalize(item.name)===normalized);
  if(exactLocal)return {items:[exactLocal],offline:false};
  try {
    const remote=await searchApiRegions(query);
    const seen=new Set<string>();
    const items=[...remote,...local].filter((item)=>{const key=`${item.name}-${item.lat.toFixed(3)}-${item.lon.toFixed(3)}`;if(seen.has(key))return false;seen.add(key);return true;}).slice(0,6);
    return {items,offline:false};
  } catch {
    return {items:local.slice(0,6),offline:true};
  }
}
