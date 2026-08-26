"""Capability discovery and preflight checks for Galaxy runtimes."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    kind: str
    label: str
    runtime_id: str
    devices: tuple[str, ...] = ()
    default_device: str = "auto"
    resumable: bool = False
    installable: bool = False


@dataclass(frozen=True)
class PreflightRequest:
    capability_id: str
    device: str = "auto"
    model_id: str = ""
    options: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PreflightCheck:
    code: str
    state: str
    message: str
    remediation: str = ""


@dataclass(frozen=True)
class PreflightResult:
    capability_id: str
    state: str
    ready: bool
    requested_device: str = ""
    resolved_device: str = ""
    message: str = ""
    checks: tuple[PreflightCheck, ...] = ()

    @classmethod
    def ready_result(
        cls,
        capability_id: str,
        *,
        requested_device: str = "",
        resolved_device: str = "",
        message: str = "",
        checks: tuple[PreflightCheck, ...] = (),
    ) -> "PreflightResult":
        return cls(
            capability_id=capability_id,
            state="ready",
            ready=True,
            requested_device=requested_device,
            resolved_device=resolved_device,
            message=message,
            checks=checks,
        )

    @classmethod
    def unavailable(
        cls,
        capability_id: str,
        *,
        requested_device: str = "",
        resolved_device: str = "",
        message: str = "",
        checks: tuple[PreflightCheck, ...] = (),
    ) -> "PreflightResult":
        return cls(
            capability_id=capability_id,
            state="unavailable",
            ready=False,
            requested_device=requested_device,
            resolved_device=resolved_device,
            message=message,
            checks=checks,
        )


# Keep the concise constructor used by adapters while retaining a readable
# dataclass field named ``ready``.
PreflightResult.ready = PreflightResult.ready_result  # type: ignore[assignment]


class CapabilityAdapter(Protocol):
    descriptor: CapabilityDescriptor

    def preflight(self, request: PreflightRequest) -> PreflightResult: ...


class FunctionCapabilityAdapter:
    def __init__(
        self,
        descriptor: CapabilityDescriptor,
        preflight: Callable[[PreflightRequest], PreflightResult],
    ) -> None:
        self.descriptor = descriptor
        self._preflight = preflight

    def preflight(self, request: PreflightRequest) -> PreflightResult:
        return self._preflight(request)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, CapabilityAdapter] = {}
        self._lock = threading.RLock()

    def register(self, adapter: CapabilityAdapter) -> None:
        capability_id = adapter.descriptor.capability_id
        with self._lock:
            if capability_id in self._adapters:
                raise ValueError(f"Capability {capability_id!r} is already registered.")
            self._adapters[capability_id] = adapter

    def list_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        with self._lock:
            return tuple(
                self._adapters[key].descriptor for key in sorted(self._adapters)
            )

    def get(self, capability_id: str) -> CapabilityDescriptor:
        with self._lock:
            adapter = self._adapters.get(capability_id)
        if adapter is None:
            raise KeyError(f"Unknown capability: {capability_id}")
        return adapter.descriptor

    def preflight(self, request: PreflightRequest) -> PreflightResult:
        with self._lock:
            adapter = self._adapters.get(request.capability_id)
        if adapter is None:
            return PreflightResult(
                capability_id=request.capability_id,
                state="error",
                ready=False,
                requested_device=request.device,
                message=f"Unknown capability: {request.capability_id}",
            )
        try:
            return adapter.preflight(request)
        except Exception as error:
            return PreflightResult(
                capability_id=request.capability_id,
                state="error",
                ready=False,
                requested_device=request.device,
                message=str(error) or type(error).__name__,
            )
