from __future__ import annotations

import time

import httpx

from app.config import Settings, get_settings
from app.providers.base import DataProvider, ProviderHealth


class CopernicusProvider(DataProvider):
    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    process_url = "https://sh.dataspace.copernicus.eu/api/v1/process"
    statistical_url = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._token: str | None = None
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.settings.cdse_client_id and self.settings.cdse_client_secret)

    async def token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        if not self.configured:
            raise RuntimeError("Copernicus OAuth не настроен")
        async with httpx.AsyncClient(timeout=self.settings.external_timeout_seconds) as client:
            response = await client.post(self.token_url, data={"grant_type":"client_credentials", "client_id":self.settings.cdse_client_id, "client_secret":self.settings.cdse_client_secret})
            response.raise_for_status()
            payload = response.json()
        self._token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    async def health(self) -> ProviderHealth:
        datasets = ["Sentinel‑2 Catalog", "Process API", "Statistical API"]
        if not self.configured:
            return ProviderHealth("cdse", "Copernicus Data Space", "unavailable", "OAuth не настроен; резервный источник отключён", datasets, "Резерв Sentinel‑2")
        try:
            await self.token()
            return ProviderHealth("cdse", "Copernicus Data Space", "connected", "OAuth-токен получен", datasets, "Резерв Sentinel‑2")
        except Exception as error:
            return ProviderHealth("cdse", "Copernicus Data Space", "unavailable", f"Ошибка подключения: {type(error).__name__}", datasets, "Резерв Sentinel‑2")

    async def ndvi_statistics(self, geometry: dict, start: str, end: str) -> dict:
        evalscript = """//VERSION=3\nfunction setup(){return {input:[{bands:[\"B04\",\"B08\",\"dataMask\"],units:\"REFLECTANCE\"}],output:[{id:\"ndvi\",bands:1,sampleType:\"FLOAT32\"},{id:\"dataMask\",bands:1}]};}\nfunction evaluatePixel(s){return {ndvi:[(s.B08-s.B04)/(s.B08+s.B04)],dataMask:[s.dataMask]};}"""
        request = {"input":{"bounds":{"geometry":geometry},"data":[{"type":"sentinel-2-l2a","dataFilter":{"mosaickingOrder":"leastCC"}}]},"aggregation":{"timeRange":{"from":f"{start}T00:00:00Z","to":f"{end}T23:59:59Z"},"aggregationInterval":{"of":"P10D"},"evalscript":evalscript,"resx":10,"resy":10},"calculations":{"default":{}}}
        token = await self.token()
        async with httpx.AsyncClient(timeout=self.settings.external_timeout_seconds) as client:
            response = await client.post(self.statistical_url, json=request, headers={"Authorization":f"Bearer {token}"})
            if response.status_code == 429:
                raise RuntimeError(f"CDSE ограничил частоту запросов; Retry-After={response.headers.get('Retry-After','не указан')}")
            response.raise_for_status()
            return response.json()
