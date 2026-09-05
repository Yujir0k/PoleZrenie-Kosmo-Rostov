from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class ProviderHealth:
    provider_id: str
    name: str
    status: str
    detail: str
    datasets: list[str]
    role: str


class DataProvider(ABC):
    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def health(self) -> ProviderHealth: ...

