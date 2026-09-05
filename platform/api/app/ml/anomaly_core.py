"""Обучение нормы и инференс объяснимых аномалий NDVI без leaderboard-модели."""
from __future__ import annotations

from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Any
import warnings
import joblib
import numpy as np
import pandas as pd

MODEL_VERSION="1.0.0"
DAYS=np.arange(91,304)


@dataclass(frozen=True)
class DetectorConfig:
    min_history_years:int=3
    max_phase_shift_days:int=21
    ndvi_z_threshold:float=-1.0
    ndvi_residual_threshold:float=-0.04
    min_event_days:int=7
    severe_min_days:int=3
    severe_z_threshold:float=-2.0
    companion_z_threshold:float=-0.7
    weather_z_threshold:float=1.0
    required_confirmations:int=2
    required_observed_days:int=2


def _validate_base(frame:pd.DataFrame)->None:
    required={"anon_polygon_id","date","primary_ndvi"}
    missing=required.difference(frame.columns)
    if missing:raise ValueError(f"Отсутствуют обязательные колонки: {sorted(missing)}")
    if frame.duplicated(["anon_polygon_id","date"]).any():
        raise ValueError("Найдены дубликаты ключа anon_polygon_id + date")


def _prepare(frame:pd.DataFrame)->pd.DataFrame:
    result=frame.copy();result["date"]=pd.to_datetime(result["date"],errors="raise")
    _validate_base(result)
    return result.sort_values(["anon_polygon_id","date"])


def _fused_signal(group:pd.DataFrame,name:str)->pd.Series:
    direct=f"primary_{name}"
    if direct in group:return group[direct]
    result=pd.Series(np.nan,index=group.index,dtype=float);found=False
    for sensor in ["s2","landsat","modis"]:
        column=f"{sensor}_{name}"
        if column in group:
            result=result.combine_first(group[column]);found=True
    if not found:raise ValueError(f"Для {name} нужна колонка {direct} либо спутниковые колонки s2/landsat/modis")
    return result


def _fast_local_polynomial(x:np.ndarray,y:np.ndarray,t:np.ndarray,bandwidth:float=24.)->np.ndarray:
    distance=np.abs(x[None,:]-t[:,None]);include=distance<=bandwidth;need=min(8,len(x))
    for i in np.flatnonzero(include.sum(axis=1)<need):include[i,np.argsort(distance[i])[:need]]=True
    selected=np.where(include,distance,np.nan);scale=np.maximum(bandwidth,np.nanmax(selected,axis=1)+1e-9)
    xx=x[None,:]-t[:,None];base=np.maximum(0,1-(np.abs(xx)/scale[:,None])**3)**3*include
    design=np.stack([np.ones_like(xx),xx,xx**2],axis=2);robust=np.ones_like(base)
    for _ in range(3):
        weights=base*robust;normal=np.einsum("qni,qn,qnj->qij",design,weights,design)
        rhs=np.einsum("qni,qn,n->qi",design,weights,y)
        coef=np.einsum("qij,qj->qi",np.linalg.pinv(normal,rcond=1e-10),rhs)
        residual=y[None,:]-np.einsum("qni,qi->qn",design,coef)
        hidden=np.where(include,residual,np.nan);center=np.nanmedian(hidden,axis=1)
        mad=np.maximum(.02,1.4826*np.nanmedian(np.abs(hidden-center[:,None]),axis=1))
        u=residual/(6*mad[:,None]);robust=np.where((np.abs(u)<1)&include,(1-u**2)**2,0)
    return coef[:,0]


def _smooth(group:pd.DataFrame,values:pd.Series,physical_bounds:bool=True)->np.ndarray:
    known=pd.DataFrame({"doy":group.date.dt.dayofyear,"value":values}).dropna()
    if physical_bounds:known=known.loc[known.value.between(-1,1)]
    known=known.groupby("doy",as_index=False).value.median()
    if not len(known):return np.repeat(np.nan,len(DAYS))
    query=np.clip(DAYS,known.doy.min(),known.doy.max())
    if len(known)<4:return np.interp(query,known.doy,known.value)
    return _fast_local_polynomial(known.doy.to_numpy(float),known.value.to_numpy(float),query.astype(float))


def _weather(group:pd.DataFrame,column:str)->np.ndarray:
    if column not in group:return np.repeat(np.nan,len(DAYS))
    known=pd.DataFrame({"doy":group.date.dt.dayofyear,"value":group[column]}).dropna().groupby("doy",as_index=False).value.mean()
    if not len(known):return np.repeat(np.nan,len(DAYS))
    return np.interp(DAYS,known.doy,known.value)


def _season_curves(group:pd.DataFrame)->dict[str,np.ndarray]:
    temp=_weather(group,"era5_temp_c");precip=_weather(group,"era5_precip_mm")
    return {"ndvi":_smooth(group,group.primary_ndvi),"evi":_smooth(group,_fused_signal(group,"evi")),
            "ndwi":_smooth(group,_fused_signal(group,"ndwi")),
            "temp":pd.Series(temp).rolling(14,min_periods=5).mean().to_numpy(),
            "precip":pd.Series(precip).rolling(30,min_periods=10).sum().to_numpy()}


def _normal(history:np.ndarray,floor:float)->tuple[np.ndarray,np.ndarray]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",RuntimeWarning)
        median=np.nanmedian(history,axis=0);mad=1.4826*np.nanmedian(np.abs(history-median),axis=0)
    return median,np.maximum(floor,mad)


def fit_detector(frame:pd.DataFrame,config:DetectorConfig|None=None)->dict[str,Any]:
    """Оценивает нормы только по переданным историческим сезонам."""
    config=config or DetectorConfig();data=_prepare(frame);fields={};skipped=[]
    floors={"ndvi":.04,"evi":.04,"ndwi":.05,"temp":1.,"precip":5.}
    for pid,polygon in data.groupby("anon_polygon_id"):
        seasons={int(year):_season_curves(group) for year,group in polygon.groupby(polygon.date.dt.year)}
        years=sorted(seasons)
        if len(years)<config.min_history_years:
            skipped.append({"anon_polygon_id":str(pid),"years":len(years),"reason":"недостаточно исторических сезонов"});continue
        field={"crop_type":str(polygon.crop_type.iloc[0]) if "crop_type" in polygon else None,
               "reference_years":years,"signals":{}}
        for signal,floor in floors.items():
            history=np.vstack([seasons[year][signal] for year in years]);median,scale=_normal(history,floor)
            field["signals"][signal]={"median":median,"scale":scale}
        fields[str(pid)]=field
    return {"model_version":MODEL_VERSION,"created_at":pd.Timestamp.utcnow().isoformat(),
            "days":DAYS,"config":asdict(config),"fields":fields,"skipped":skipped,
            "training_rows":len(data),"training_date_min":str(data.date.min().date()),
            "training_date_max":str(data.date.max().date())}


def save_artifact(model:dict[str,Any],path:str|Path)->None:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);joblib.dump(model,target,compress=3)


def load_artifact(path:str|Path)->dict[str,Any]:
    model=joblib.load(path)
    if model.get("model_version")!=MODEL_VERSION:raise ValueError(f"Неподдерживаемая версия модели: {model.get('model_version')}")
    return model


def _phase_reference(current:np.ndarray,normal:np.ndarray,scale:np.ndarray,max_shift:int)->tuple[np.ndarray,np.ndarray,int]:
    best=(np.inf,0,normal)
    for shift in range(-max_shift,max_shift+1):
        reference=np.interp(DAYS+shift,DAYS,normal);residual=current-reference;finite=np.flatnonzero(np.isfinite(residual))
        if len(finite)<20:continue
        keep=finite[np.argsort(np.abs(residual[finite]))[:max(20,int(.8*len(finite)))]]
        score=float(np.sqrt(np.mean(residual[keep]**2)))
        if score<best[0]:best=(score,shift,reference)
    shifted_scale=np.maximum(.04,np.interp(DAYS+best[1],DAYS,scale))
    return best[2],shifted_scale,best[1]


def _groups(mask:np.ndarray)->list[np.ndarray]:
    ids=np.flatnonzero(mask)
    return [] if not len(ids) else list(np.split(ids,np.flatnonzero(np.diff(ids)>1)+1))


def _origin(group:pd.DataFrame)->np.ndarray:
    indexed=group.set_index(group.date.dt.dayofyear);result=[]
    for day in DAYS:
        if day not in indexed.index:result.append("continuous_fill");continue
        row=indexed.loc[day];row=row.iloc[0] if isinstance(row,pd.DataFrame) else row
        synthetic=bool(row.get("is_synthetic_gap",False)) if pd.notna(row.get("is_synthetic_gap",False)) else False
        if synthetic:result.append("synthetic_gap")
        elif pd.notna(row.primary_ndvi) and -1<=row.primary_ndvi<=1:result.append("observed")
        else:result.append("natural_gap")
    return np.asarray(result)


def _event_explanation(segment:pd.DataFrame,confirmations:list[str])->tuple[str,str]:
    precip=float(segment.precip_z.median());temp=float(segment.temp_z.median())
    ndwi=float(segment.ndwi_z.median());evi=float(segment.evi_z.median())
    if precip<=-1 and (ndwi<=-.5 or temp>=.8):cause="вероятный водный или тепловой стресс"
    elif temp<=-1:cause="возможное замедление развития из-за холода"
    elif ndwi<=-1 and evi<=-1:cause="согласованное снижение растительного и водного индексов"
    elif precip>=1 and temp<=.5:cause="возможный стресс при избытке влаги или облачной погоде"
    else:cause="негативное отклонение без однозначного погодного объяснения"
    evidence=f"подтверждения: {', '.join(confirmations)}; EVI z={evi:.1f}, NDWI z={ndwi:.1f}, осадки z={precip:.1f}, температура z={temp:.1f}"
    explanation=(f"{cause.capitalize()}. NDVI ниже фазово выровненной нормы в среднем на "
                 f"{abs(segment.residual.mean()):.3f}; min z={segment.z.min():.1f}; {evidence}. "
                 f"Фактических наблюдений: {(segment.origin=='observed').sum()} из {len(segment)} дней.")
    return cause,explanation


def detect_anomalies(frame:pd.DataFrame,model:dict[str,Any])->tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    """Возвращает events, daily_points, skipped_fields, quality_flags."""
    data=_prepare(frame);config=DetectorConfig(**model["config"]);events=[];points_parts=[];skipped=[]
    quality=data.loc[data.primary_ndvi.notna()&~data.primary_ndvi.between(-1,1),
                     ["anon_polygon_id","date","primary_ndvi"]].copy()
    quality["flag"]="NDVI вне физического диапазона [-1, 1]"
    for pid,all_rows in data.groupby("anon_polygon_id"):
        current_year=int(all_rows.date.dt.year.max());group=all_rows[all_rows.date.dt.year.eq(current_year)].copy()
        field=model["fields"].get(str(pid))
        normal_source="trained_artifact"
        if field is None:
            past_rows=all_rows[all_rows.date.dt.year.lt(current_year)]
            if past_rows.date.dt.year.nunique()>=config.min_history_years:
                local_model=fit_detector(past_rows,config);field=local_model["fields"].get(str(pid))
                normal_source="input_history"
            if field is None:
                skipped.append({"anon_polygon_id":pid,"year":current_year,
                                "reason":"нет обученной нормы и минимум трёх прошлых сезонов во входе"});continue
        curves=_season_curves(group);ndvi_normal=field["signals"]["ndvi"]["median"]
        ndvi_scale=field["signals"]["ndvi"]["scale"]
        if np.isfinite(curves["ndvi"]).sum()<20:
            skipped.append({"anon_polygon_id":pid,"year":current_year,"reason":"недостаточно наблюдений NDVI"});continue
        reference,aligned_scale,shift=_phase_reference(curves["ndvi"],ndvi_normal,ndvi_scale,config.max_phase_shift_days)
        residual=curves["ndvi"]-reference;z=residual/aligned_scale
        phase_component=(reference-ndvi_normal)/np.maximum(ndvi_scale,.04);context={}
        for signal in ["evi","ndwi","temp","precip"]:
            stats=field["signals"][signal];context[signal]=(curves[signal]-stats["median"])/stats["scale"]
        context["evi"]-=phase_component;context["ndwi"]-=phase_component
        origin=_origin(group);dates=pd.to_datetime(current_year*1000+DAYS,format="%Y%j")
        points=pd.DataFrame({"anon_polygon_id":pid,"date":dates,"year":current_year,
             "crop_type":field["crop_type"],"ndvi_reconstructed":curves["ndvi"],
             "aligned_climatology":reference,"climatology_scale":aligned_scale,
             "residual":residual,"z":z,"evi_z":context["evi"],"ndwi_z":context["ndwi"],
             "temp_z":context["temp"],"precip_z":context["precip"],"origin":origin,
             "estimated_phase_shift_days":shift,"normal_source":normal_source,"is_anomaly":False,"event_id":""})
        mask=(z<config.ndvi_z_threshold)&(residual<config.ndvi_residual_threshold);number=0
        for ids in _groups(mask):
            persistent=len(ids)>=config.min_event_days or (len(ids)>=config.severe_min_days and np.nanmin(z[ids])<config.severe_z_threshold)
            if not persistent:continue
            segment=points.iloc[ids];med={}
            for name,values in context.items():
                selected=np.asarray(values)[ids]
                med[name]=float(np.nanmedian(selected)) if np.isfinite(selected).any() else 0.
            confirmations=[]
            if med["evi"]<config.companion_z_threshold:confirmations.append("EVI")
            if med["ndwi"]<config.companion_z_threshold:confirmations.append("NDWI")
            if med["precip"]<-config.weather_z_threshold:confirmations.append("дефицит осадков")
            if abs(med["temp"])>config.weather_z_threshold:confirmations.append("температура")
            observed=int((segment.origin=="observed").sum())
            if len(confirmations)<config.required_confirmations or observed<config.required_observed_days:continue
            number+=1;event_id=f"{pid}-{current_year}-A{number:02d}";cause,explanation=_event_explanation(segment,confirmations)
            points.iloc[ids,points.columns.get_loc("is_anomaly")]=True
            points.iloc[ids,points.columns.get_loc("event_id")]=event_id
            events.append({"event_id":event_id,"anon_polygon_id":pid,"crop_type":field["crop_type"],
              "start_date":segment.date.min(),"end_date":segment.date.max(),"duration_days":len(segment),
              "mean_ndvi":float(segment.ndvi_reconstructed.mean()),"mean_climatology":float(segment.aligned_climatology.mean()),
              "mean_residual":float(segment.residual.mean()),"min_z":float(segment.z.min()),"mean_z":float(segment.z.mean()),
              "observed_days":observed,"estimated_phase_shift_days":shift,"confirming_signals":", ".join(confirmations),
              "cause_hypothesis":cause,"confidence":"высокая","explanation":explanation,
              "reference_years":len(field["reference_years"]),"normal_source":normal_source})
        points_parts.append(points)
    event_columns=["event_id","anon_polygon_id","crop_type","start_date","end_date","duration_days","mean_ndvi",
      "mean_climatology","mean_residual","min_z","mean_z","observed_days","estimated_phase_shift_days",
      "confirming_signals","cause_hypothesis","confidence","explanation","reference_years"]
    event_columns.append("normal_source")
    return (pd.DataFrame(events,columns=event_columns),pd.concat(points_parts,ignore_index=True) if points_parts else pd.DataFrame(),
            pd.DataFrame(skipped),quality)
