from __future__ import annotations

import os
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import docker
import psutil
from docker.errors import NotFound
from filelock import FileLock
from requests.exceptions import ConnectionError, Timeout

from .network_policy import (
    install_agent_egress_policy,
    verify_agent_egress_policy,
)


ADAPTER_PORTS = {
    "libreoffice_calc": 8765,
    "libreoffice_impress": 8766,
    "chrome": 8767,
    "gimp": 8768,
    "os": 8769,
    "libreoffice_writer": 8770,
    "vs_code": 8771,
    "vlc": 8772,
    "thunderbird": 8773,
    "multi_apps": 8774,
}

RUN_OWNER_LABEL = "openapa.run_owner"
DEFAULT_PORT_LOCK_TIMEOUT = 180.0
VM_READINESS_ATTEMPTS = 2
LOGGER = logging.getLogger(__name__)


class DockerStartupError(RuntimeError):
    """An infrastructure failure that must stop task dispatch, not burn a shard."""


@dataclass(frozen=True)
class DockerStartupSettings:
    api_timeout_seconds: float = 180.0
    create_recovery_seconds: float = 180.0
    port_lock_timeout_seconds: float = 540.0

    @classmethod
    def from_protocol(cls, protocol: dict[str, Any]):
        api = protocol.get("docker_api_timeout_seconds", 180.0)
        concurrency = protocol.get("concurrency", 1)
        if isinstance(api, bool) or not isinstance(api, (int, float)) or not math.isfinite(api) or api <= 0:
            raise ValueError("docker_api_timeout_seconds must be finite and positive")
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("concurrency must be a positive integer")
        # The lock covers create, bounded reconciliation, and start for each queued worker.
        lock_budget = max(DEFAULT_PORT_LOCK_TIMEOUT, concurrency * 3 * api)
        return cls(float(api), float(api), float(lock_budget))


_startup_settings = DockerStartupSettings()


def create_owned_container(client: Any, *, name: str, labels: dict[str, str],
                           recovery_seconds: float, **kwargs):
    """Submit create once; reconcile its uncertain result by exact attempt identity."""
    try:
        return client.containers.create(name=name, labels=labels, **kwargs)
    except (Timeout, ConnectionError) as error:
        deadline = time.monotonic() + recovery_seconds
        LOGGER.warning("Docker create response lost; reconciling name=%s without resubmitting", name)
        while True:
            try:
                container = client.containers.get(name)
            except (NotFound, Timeout, ConnectionError):
                if time.monotonic() >= deadline:
                    raise DockerStartupError(
                        f"Docker create outcome unresolved for {name}; do not resubmit; "
                        "check this exact attempt label for late containers"
                    ) from error
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
                continue
            if any(container.labels.get(key) != value for key, value in labels.items()):
                raise DockerStartupError(f"Docker create identity mismatch for {name}") from error
            LOGGER.warning("Recovered original Docker create name=%s id=%s", name, container.id)
            return container


def run_vm_readiness_attempts(
    start: Callable[[], None],
    wait_until_ready: Callable[[], None],
    cleanup: Callable[[], None],
) -> None:
    """Rebuild once when a fresh VM alone times out waiting for readiness."""

    for attempt in range(1, VM_READINESS_ATTEMPTS + 1):
        start()
        try:
            wait_until_ready()
        except TimeoutError:
            cleanup()
            if attempt == VM_READINESS_ATTEMPTS:
                raise
        else:
            return
    raise AssertionError("unreachable")


def collect_used_host_ports(client: Any) -> set[int]:
    system_ports: set[int] = set()
    for connection in psutil.net_connections(kind="inet"):
        local_address = getattr(connection, "laddr", None)
        port = getattr(local_address, "port", None)
        if port is None and isinstance(local_address, tuple) and len(local_address) > 1:
            port = local_address[1]
        if port is not None:
            system_ports.add(int(port))

    docker_ports: set[int] = set()
    for summary in client.api.containers(all=False):
        for mapping in summary.get("Ports") or []:
            public_port = mapping.get("PublicPort")
            if public_port is not None:
                docker_ports.add(int(public_port))
    return system_ports | docker_ports


class AdapterDockerProvider:
    """Factory wrapper installed after OSWorld is importable."""

    @staticmethod
    def create(region: str | None = None, *, settings: DockerStartupSettings | None = None):
        from desktop_env.providers.docker.provider import DockerProvider
        effective = settings or _startup_settings

        class _Provider(DockerProvider):
            adapter_host_ports: dict[str, int]

            def __init__(self, region):
                # Keep pinned OSWorld untouched; configure the client before any API call.
                self.client = docker.from_env(timeout=effective.api_timeout_seconds)
                self.server_port = self.vnc_port = self.chromium_port = self.vlc_port = None
                self.container = None
                self.environment = {"DISK_SIZE": "32G", "RAM_SIZE": "4G", "CPU_CORES": "4"}
                self.lock_file = Path(os.getenv("TEMP", "/tmp") if os.name == "nt" else "/tmp") / "docker_port_allocation.lck"
                self.lock_file.parent.mkdir(parents=True, exist_ok=True)
                self.startup_evidence = {**asdict(effective), "effective_api_timeout_seconds": self.client.api.timeout}

            def _get_used_ports(self) -> set[int]:
                return collect_used_host_ports(self.client)

            def start_emulator(self, path_to_vm: str, headless: bool, os_type: str):
                lock_timeout = float(
                    os.environ.get(
                        "OPENAPA_DOCKER_PORT_LOCK_TIMEOUT",
                        str(effective.port_lock_timeout_seconds),
                    )
                )
                self.adapter_host_ports = {}
                self.agent_egress_policy = {}
                self.startup_evidence["port_lock_timeout_seconds"] = lock_timeout

                def start() -> None:
                    attempt = uuid.uuid4().hex
                    name = "lite-osworld-" + attempt
                    self.startup_evidence.update(container_name=name, attempt=attempt)
                    lock = FileLock(str(self.lock_file), timeout=lock_timeout)
                    queued = time.monotonic()
                    with lock:
                        self.startup_evidence["port_lock_wait_seconds"] = time.monotonic() - queued
                        reserved_ports = self._get_used_ports()

                        def reserve(start: int) -> int:
                            port = start
                            while port in reserved_ports:
                                port += 1
                            if port >= 65354:
                                raise RuntimeError(f"no available port from {start}")
                            reserved_ports.add(port)
                            return port

                        self.vnc_port = reserve(8006)
                        self.server_port = reserve(5000)
                        self.chromium_port = reserve(9222)
                        self.vlc_port = reserve(8080)
                        self.adapter_host_ports = {
                            name: reserve(port) for name, port in ADAPTER_PORTS.items()
                        }

                        devices = []
                        if os.path.exists("/dev/kvm"):
                            devices.append("/dev/kvm")
                        else:
                            self.environment["KVM"] = "N"

                        port_bindings = {
                            8006: self.vnc_port,
                            5000: self.server_port,
                            9222: self.chromium_port,
                            8080: self.vlc_port,
                        }
                        port_bindings.update(
                            {
                                container_port: self.adapter_host_ports[name]
                                for name, container_port in ADAPTER_PORTS.items()
                            }
                        )
                        run_owner = os.environ.get("OPENAPA_RUN_OWNER")
                        labels = {"openapa.start_attempt": attempt}
                        if run_owner:
                            labels[RUN_OWNER_LABEL] = run_owner
                        created = time.monotonic()
                        self.container = create_owned_container(
                            self.client, name=name, labels=labels,
                            recovery_seconds=effective.create_recovery_seconds,
                            image="happysixd/osworld-docker",
                            environment=self.environment,
                            cap_add=["NET_ADMIN"],
                            devices=devices,
                            volumes={
                                os.path.abspath(path_to_vm): {
                                    "bind": "/System.qcow2",
                                    "mode": "ro",
                                }
                            },
                            ports=port_bindings,
                        )
                        self.startup_evidence["create_seconds"] = time.monotonic() - created
                        # Retain the handle before start, even when its response times out.
                        try:
                            self.container.start()
                        except (Timeout, ConnectionError):
                            self.container.reload()
                            if self.container.status != "running":
                                raise
                        self.startup_evidence["container_id"] = self.container.id

                def cleanup() -> None:
                    if self.container:
                        try:
                            self.container.stop()
                        except Exception:
                            pass
                        try:
                            self.container.remove(v=True, force=True)
                        except Exception:
                            pass
                    self.container = None
                    self.server_port = None
                    self.vnc_port = None
                    self.chromium_port = None
                    self.vlc_port = None
                    self.adapter_host_ports = {}
                    self.agent_egress_policy = {}

                try:
                    run_vm_readiness_attempts(
                        start,
                        lambda: self._wait_for_vm_ready(),
                        cleanup,
                    )
                    self.agent_egress_policy = install_agent_egress_policy(
                        self.container
                    )
                except Exception as error:
                    cleanup()
                    if isinstance(error, DockerStartupError):
                        error.startup_evidence = dict(self.startup_evidence)
                        raise
                    failure = DockerStartupError(f"Docker guest startup failed: {type(error).__name__}: {error}")
                    failure.startup_evidence = dict(self.startup_evidence)
                    raise failure from error

            def adapter_urls(self) -> dict[str, str]:
                return {
                    name: f"http://127.0.0.1:{port}"
                    for name, port in self.adapter_host_ports.items()
                }

            def assert_agent_egress_policy(self) -> dict[str, Any]:
                if not self.container:
                    raise RuntimeError("OSWorld container is not running")
                self.agent_egress_policy = verify_agent_egress_policy(self.container)
                return dict(self.agent_egress_policy)

            def stop_emulator(self, path_to_vm: str, region=None, *args, **kwargs):
                super().stop_emulator(path_to_vm, region, *args, **kwargs)
                self.adapter_host_ports = {}
                self.agent_egress_policy = {}

        return _Provider(region)


def install_provider_patch(protocol: dict[str, Any] | None = None) -> dict[str, Any]:
    global _startup_settings
    _startup_settings = DockerStartupSettings.from_protocol(protocol or {})
    from desktop_env import desktop_env as desktop_env_module
    from desktop_env.providers.docker.manager import DockerVMManager

    if hasattr(desktop_env_module, "_v2_original_provider_factory"):
        return asdict(_startup_settings)
    original = desktop_env_module.create_vm_manager_and_provider
    desktop_env_module._v2_original_provider_factory = original

    def factory(provider_name: str, region: str | None, use_proxy: bool = False):
        if provider_name == "docker":
            return DockerVMManager(), AdapterDockerProvider.create(region)
        return original(provider_name, region, use_proxy=use_proxy)

    desktop_env_module.create_vm_manager_and_provider = factory
    return asdict(_startup_settings)
