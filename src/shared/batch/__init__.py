"""Shared batch processing infrastructure.

Provides generic utilities for batch processing pipelines:
- CheckpointManager: Per-article, per-stage checkpointing with atomic writes
- FailureTracker: Tracks failed articles for retry and analysis
- ProgressTracker: Processing progress and metrics
- BrowserPool: Thread-safe browser instance pooling
- MemoryMonitor: Daemon thread for memory pressure monitoring
- TaskPingHandle: Per-task heartbeat tracking
- retry_on_network_error: Decorator for network retry with exponential backoff

Usage:
    from src.shared.batch import CheckpointManager, FailureTracker, ProgressTracker
    from src.shared.batch import BrowserPool, MemoryMonitor
    from src.shared.batch import TaskPingHandle, send_ping, ping_keepalive
    from src.shared.batch import retry_on_network_error
"""

from .checkpoint import CheckpointManager
from .failure_tracker import FailureTracker, register_stage_failure
from .progress import ProgressTracker
from .browser_pool import BrowserPool
from .memory_monitor import MemoryMonitor
from .task_ping import TaskPingHandle, TaskPingManager, send_ping, ping_keepalive
from .retry import retry_on_network_error

__all__ = [
    "CheckpointManager",
    "FailureTracker",
    "register_stage_failure",
    "ProgressTracker",
    "BrowserPool",
    "MemoryMonitor",
    "TaskPingHandle",
    "TaskPingManager",
    "send_ping",
    "ping_keepalive",
    "retry_on_network_error",
]
