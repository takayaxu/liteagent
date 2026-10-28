"""Cross-worktree repair leases; guest execution is isolated by the Docker provider."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time


DEFAULT_SLOTS = 5
MAX_SLOTS = 12


def resource_root():
    # Stable across detached worktrees and snapshot directories for this account.
    return Path.home() / ".local/state/liteagent/repair-resources"


def _dump(path, value):
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _try_lock(path):
    handle = path.open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _close(handles):
    # close, rather than LOCK_UN: a running child may still hold the inherited fd.
    for handle in reversed(handles):
        handle.close()


class RepairResources:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else resource_root()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "tasks").mkdir(exist_ok=True)

    @contextmanager
    def _guard(self):
        with (self.root / "registry.lock").open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            config = self.root / "pool.json"
            if not config.exists():
                _dump(config, {"slots": DEFAULT_SLOTS})
            yield

    def _capacity(self):
        slots = json.loads((self.root / "pool.json").read_text())["slots"]
        if type(slots) is not int or not 1 <= slots <= MAX_SLOTS:
            raise ValueError(f"repair pool slots must be between 1 and {MAX_SLOTS}")
        return slots

    def configure(self, slots):
        if type(slots) is not int or not 1 <= slots <= MAX_SLOTS:
            raise ValueError(f"slots must be between 1 and {MAX_SLOTS}")
        with self._guard():
            held = []
            try:
                capacity = self._capacity()
                for index in range(capacity):
                    path = self.root / f"slot-{index}.lock"
                    handle = _try_lock(path)
                    if handle is None:
                        if slots <= capacity:
                            raise RuntimeError("cannot shrink/reconfigure repair pool while a run holds a slot")
                        # Increasing capacity preserves existing leases, but must not
                        # create usable slots outside an active exclusive reservation.
                        try:
                            lease = json.loads(path.with_suffix(".json").read_text())
                        except (OSError, ValueError) as error:
                            raise RuntimeError("cannot expand repair pool with unknown active lease") from error
                        if not isinstance(lease, dict) or lease.get("exclusive") is not False:
                            raise RuntimeError("cannot expand repair pool with exclusive or unknown active lease")
                        continue
                    held.append(handle)
                _dump(self.root / "pool.json", {"slots": slots})
            finally:
                _close(held)
        return self.status()

    def status(self):
        with self._guard():
            slots = self._capacity()
            leases = []
            for index in range(slots):
                path = self.root / f"slot-{index}.lock"
                handle = _try_lock(path)
                if handle is not None:
                    handle.close()
                    continue
                receipt = path.with_suffix(".json")
                try:
                    lease = json.loads(receipt.read_text())
                except (OSError, ValueError):
                    lease = {"metadata_unavailable": True}
                leases.append({"slot": index + 1, **lease})
            return {"resource_directory": str(self.root), "capacity": slots,
                    "occupied_slots": len(leases), "available_slots": slots-len(leases),
                    "leases": leases}

    @contextmanager
    def acquire(self, *, task_ids, metadata, exclusive=False, on_wait=None, timeout=None):
        if not task_ids or any(not isinstance(task, str) or not task for task in task_ids):
            raise ValueError("task_ids must contain explicit nonempty identities")
        started = time.monotonic()
        handles = []
        receipt = None
        try:
            while receipt is None:
                reason = "no_free_slot"
                with self._guard():
                    capacity = self._capacity()
                    try:
                        # Acquire every task claim before a slot; release partial claims on conflict.
                        for identity in sorted(set(task_ids)):
                            key = hashlib.sha256(identity.encode()).hexdigest()
                            handle = _try_lock(self.root / "tasks" / (key + ".lock"))
                            if handle is None:
                                reason = "same_task_running"
                                break
                            handles.append(handle)
                        else:
                            slots = []
                            for index in range(capacity):
                                handle = _try_lock(self.root / f"slot-{index}.lock")
                                if handle is not None:
                                    handles.append(handle)
                                    slots.append(index)
                                    if not exclusive:
                                        break
                            if len(slots) == (capacity if exclusive else 1):
                                receipt = {**metadata, "pid": os.getpid(),
                                           "acquired_at": datetime.now(timezone.utc).isoformat(),
                                           "task_ids": list(task_ids), "exclusive": exclusive,
                                           "slots": [index+1 for index in slots],
                                           "resource_directory": str(self.root),
                                           "pool_capacity": capacity}
                                for index in slots:
                                    _dump(self.root / f"slot-{index}.json", receipt)
                        if receipt is None:
                            _close(handles)
                            handles = []
                    except BaseException:
                        _close(handles)
                        handles = []
                        raise
                if receipt is None:
                    if on_wait is not None:
                        on_wait(reason)
                    if timeout is not None and time.monotonic()-started >= timeout:
                        raise TimeoutError(f"repair resources unavailable: {reason}")
                    time.sleep(1)
            yield receipt, tuple(handle.fileno() for handle in handles)
        finally:
            _close(handles)
