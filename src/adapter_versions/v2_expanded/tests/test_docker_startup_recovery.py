from __future__ import annotations

from types import SimpleNamespace
import json

from docker.errors import NotFound
import pytest
from requests.exceptions import ReadTimeout

from integrations.openapa_osworld import provider
from scripts import supervise_lite_agent_parallel as supervisor


def test_frozen_timeout_reaches_docker_before_first_api_call(monkeypatch):
    calls = []
    client = SimpleNamespace(api=SimpleNamespace(timeout=237))
    monkeypatch.setattr(provider.docker, "from_env", lambda **kw: calls.append(kw) or client)
    settings = provider.DockerStartupSettings.from_protocol(
        {"docker_api_timeout_seconds": 237, "concurrency": 12})
    instance = provider.AdapterDockerProvider.create(settings=settings)
    assert calls == [{"timeout": 237}]
    assert instance.client is client
    assert instance.startup_evidence["effective_api_timeout_seconds"] == 237
    assert settings.port_lock_timeout_seconds == 12 * 3 * 237


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), "180"])
def test_invalid_api_timeouts_are_rejected(value):
    with pytest.raises(ValueError, match="docker_api_timeout_seconds"):
        provider.DockerStartupSettings.from_protocol({"docker_api_timeout_seconds": value})


def test_lost_create_response_recovers_exact_container_without_resubmission(monkeypatch):
    labels = {"openapa.start_attempt": "one-attempt", "openapa.run_owner": "this-run"}
    container = SimpleNamespace(id="late-container", labels=labels)
    calls = []
    def create(**kwargs):
        calls.append(("create", kwargs))
        raise ReadTimeout("the daemon is still creating")
    def get(name):
        calls.append(("get", name))
        if sum(call[0] == "get" for call in calls) == 1:
            raise NotFound("not visible yet")
        return container
    client = SimpleNamespace(containers=SimpleNamespace(create=create, get=get))
    monkeypatch.setattr(provider.time, "sleep", lambda _: None)
    observed = provider.create_owned_container(client, name="unique-name", labels=labels,
                                                recovery_seconds=10, image="image")
    assert observed is container
    assert [call[0] for call in calls] == ["create", "get", "get"]
    assert all(call[1] == "unique-name" for call in calls[1:])


def test_unresolved_create_stops_instead_of_resubmitting():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        raise ReadTimeout("lost response")
    def get(name):
        raise NotFound(name)
    client = SimpleNamespace(containers=SimpleNamespace(create=create, get=get))
    with pytest.raises(provider.DockerStartupError, match="do not resubmit"):
        provider.create_owned_container(client, name="unresolved", labels={"attempt": "ours"},
                                          recovery_seconds=0, image="image")
    assert len(calls) == 1


def test_reconciliation_refuses_foreign_attempt():
    def create(**kwargs):
        raise ReadTimeout("lost response")
    client = SimpleNamespace(containers=SimpleNamespace(
        create=create, get=lambda _: SimpleNamespace(labels={"attempt": "foreign"})))
    with pytest.raises(provider.DockerStartupError, match="identity mismatch"):
        provider.create_owned_container(client, name="unique", labels={"attempt": "ours"},
                                          recovery_seconds=0, image="image")


def test_start_timeout_keeps_handle_and_cleans_only_failed_container(tmp_path, monkeypatch):
    actions = []
    class Container:
        id = "owned-container"
        status = "created"
        def start(self):
            actions.append("start")
            raise ReadTimeout("start response lost")
        def reload(self): actions.append("reload")
        def stop(self): actions.append("stop")
        def remove(self, **kwargs): actions.append(("remove", kwargs))
    container = Container()
    client = SimpleNamespace(api=SimpleNamespace(timeout=180),
                             containers=SimpleNamespace(create=lambda **kw: container))
    monkeypatch.setattr(provider.docker, "from_env", lambda **kw: client)
    instance = provider.AdapterDockerProvider.create()
    instance.lock_file = tmp_path / "ports.lock"
    monkeypatch.setattr(instance, "_get_used_ports", lambda: set())
    with pytest.raises(provider.DockerStartupError, match="ReadTimeout"):
        instance.start_emulator("/synthetic/base", True, "Ubuntu")
    assert actions == ["start", "reload", "stop", ("remove", {"v": True, "force": True})]
    assert instance.container is None


def test_supervisor_stops_on_startup_failure_but_keeps_evaluator_failures(tmp_path):
    worker = tmp_path / "workers/worker-02"
    worker.mkdir(parents=True)
    path = worker / "results.json"
    path.write_text(json.dumps({"tasks": [{"order": 6, "status": "failed"}]}))
    supervisor.abort_on_docker_startup_failure(tmp_path)
    path.write_text(json.dumps({"tasks": [{"order": 6, "status": "environment_failure",
                                           "infrastructure_failure": "docker_startup"}]}))
    with pytest.raises(RuntimeError, match="worker-02, order 6"):
        supervisor.abort_on_docker_startup_failure(tmp_path)
