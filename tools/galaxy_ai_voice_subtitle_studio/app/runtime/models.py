"""Model catalog adapters shared by runtime-backed features."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class ModelDescriptor:
    model_id: str
    capability_id: str
    label: str
    installed: bool
    version: str = ""
    size_bytes: int | None = None
    source: str = ""
    license_id: str = ""


class ModelAdapter(Protocol):
    capability_id: str

    def list_models(self, refresh: bool = False) -> tuple[ModelDescriptor, ...]: ...

    def install(self, model_id: str, context: Any) -> ModelDescriptor: ...

    def remove(self, model_id: str, context: Any) -> None: ...


class FunctionModelAdapter:
    def __init__(
        self,
        capability_id: str,
        *,
        list_models: Callable[[bool], tuple[ModelDescriptor, ...]],
        install_model: Callable[[str, Any], ModelDescriptor],
        remove_model: Callable[[str, Any], None] | None = None,
    ) -> None:
        self.capability_id = capability_id
        self._list_models = list_models
        self._install_model = install_model
        self._remove_model = remove_model

    def list_models(self, refresh: bool = False) -> tuple[ModelDescriptor, ...]:
        return self._list_models(refresh)

    def install(self, model_id: str, context: Any) -> ModelDescriptor:
        return self._install_model(model_id, context)

    def remove(self, model_id: str, context: Any) -> None:
        if self._remove_model is None:
            raise NotImplementedError(
                f"Removing models is unsupported for {self.capability_id}."
            )
        self._remove_model(model_id, context)


class ModelRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ModelAdapter] = {}
        self._lock = threading.RLock()

    def register(self, adapter: ModelAdapter) -> None:
        with self._lock:
            if adapter.capability_id in self._adapters:
                raise ValueError(
                    f"Model adapter for {adapter.capability_id!r} is already registered."
                )
            self._adapters[adapter.capability_id] = adapter

    def _get(self, capability_id: str) -> ModelAdapter:
        with self._lock:
            adapter = self._adapters.get(capability_id)
        if adapter is None:
            raise KeyError(f"No model adapter for capability: {capability_id}")
        return adapter

    def list_models(
        self,
        capability_id: str,
        refresh: bool = False,
    ) -> tuple[ModelDescriptor, ...]:
        return self._get(capability_id).list_models(refresh)

    def install(self, capability_id: str, model_id: str, context: Any) -> ModelDescriptor:
        return self._get(capability_id).install(model_id, context)

    def remove(self, capability_id: str, model_id: str, context: Any) -> None:
        self._get(capability_id).remove(model_id, context)
