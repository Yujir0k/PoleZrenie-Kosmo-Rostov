from __future__ import annotations

import hashlib

import httpx
from pyproj import Geod

from app.config import Settings, get_settings
from app.providers.base import DataProvider, ProviderHealth


class OpenGeoProvider(DataProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.headers = {"User-Agent": "vegetation-monitoring-hackathon/1.0"}

    @property
    def configured(self) -> bool:
        return True

    @property
    def overpass_urls(self) -> list[str]:
        fallbacks = [value.strip() for value in self.settings.overpass_fallback_urls.split(",") if value.strip()]
        return list(dict.fromkeys([self.settings.overpass_url, *fallbacks]))

    async def _post_overpass(self, client: httpx.AsyncClient, query: str) -> httpx.Response:
        last_error: Exception | None = None
        for url in self.overpass_urls:
            try:
                response = await client.post(url, content=query)
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as error:
                last_error = error
        if last_error:
            raise last_error
        raise RuntimeError("Не настроен ни один сервер Overpass")

    async def health(self) -> ProviderHealth:
        try:
            timeout = min(self.settings.external_timeout_seconds, 8.0)
            async with httpx.AsyncClient(timeout=timeout, headers=self.headers) as client:
                nominatim = await client.get(
                    f"{self.settings.nominatim_url}/search",
                    params={"q": "Зерноград", "format": "jsonv2", "limit": 1},
                )
                nominatim.raise_for_status()
                await self._post_overpass(client, "[out:json][timeout:5];node(0,0,0.001,0.001);out 1;")
            detail = "Nominatim и Overpass отвечают"
            status = "connected"
        except Exception as error:
            detail = f"Геосервисы недоступны: {type(error).__name__}"
            status = "unavailable"
        return ProviderHealth("osm", "OpenStreetMap / Overpass", status, detail, ["Nominatim", "landuse=farmland", "landuse=meadow"], "Геопоиск")

    async def search_regions(self, query: str, limit: int = 5) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.settings.external_timeout_seconds, headers=self.headers) as client:
            response = await client.get(f"{self.settings.nominatim_url}/search", params={"q":query,"format":"jsonv2","addressdetails":1,"limit":limit,"countrycodes":"ru,kz,by"})
            response.raise_for_status()
            rows = response.json()
        return [{"id":str(item["place_id"]),"name":item.get("name") or item["display_name"].split(",")[0],"display_name":item["display_name"],"lat":float(item["lat"]),"lon":float(item["lon"]),"bounding_box":[float(value) for value in item["boundingbox"]]} for item in rows]

    async def field_candidates(self, bbox: tuple[float, float, float, float], limit: int = 60) -> list[dict]:
        west, south, east, north = bbox
        if east <= west or north <= south or (east - west) * (north - south) > 1.5:
            raise ValueError("Область поиска слишком велика")
        query = f"""[out:json][timeout:20];(way[\"landuse\"=\"farmland\"]({south},{west},{north},{east});way[\"landuse\"=\"meadow\"]({south},{west},{north},{east}););out geom {limit};"""
        async with httpx.AsyncClient(timeout=self.settings.external_timeout_seconds, headers=self.headers) as client:
            response = await self._post_overpass(client, query)
            elements = response.json().get("elements", [])
        features = []
        geod = Geod(ellps="WGS84")
        for item in elements:
            coordinates = [[point["lon"], point["lat"]] for point in item.get("geometry", [])]
            if len(coordinates) < 4:
                continue
            if coordinates[0] != coordinates[-1]:
                coordinates.append(coordinates[0])
            osm_id = str(item.get("id", hashlib.sha1(str(coordinates).encode()).hexdigest()[:12]))
            lons, lats = zip(*coordinates)
            area_ha = abs(geod.polygon_area_perimeter(lons, lats)[0]) / 10_000
            features.append({"type":"Feature","id":f"osm-{osm_id}","properties":{"name":item.get("tags",{}).get("name") or f"Контур OSM {osm_id}","source":"osm","area_ha":round(area_ha,1)},"geometry":{"type":"Polygon","coordinates":[coordinates]}})
        return features
