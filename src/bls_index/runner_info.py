"""Resources of the machine running a build, recorded before choosing an architecture."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

GITHUB_ENV_KEYS = (
    "RUNNER_OS", "RUNNER_ARCH", "RUNNER_ENVIRONMENT", "RUNNER_NAME", "ImageOS",
    "ImageVersion", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_WORKFLOW", "GITHUB_SHA",
)  # fmt: skip


def runner_info(workdir: Path) -> dict[str, Any]:
    disk = shutil.disk_usage(workdir)
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "sched_cpu_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "mem_total_bytes": _meminfo("MemTotal"),
        "mem_available_bytes": _meminfo("MemAvailable"),
        "workdir": str(workdir),
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "github": {k: os.environ[k] for k in GITHUB_ENV_KEYS if k in os.environ},
    }


def _meminfo(field: str) -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, _, rest = line.partition(":")
            if name == field:
                return int(rest.split()[0]) * 1024
    except OSError:
        pass
    return None
