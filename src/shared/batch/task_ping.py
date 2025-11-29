"""Per-task heartbeat tracking for batch processing."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TaskPingHandle:
    """Per-task heartbeat tracker that emits periodic ping logs.
    
    Used to track progress of long-running tasks and detect stalled work.
    Provides keepalive context manager for blocking operations.
    
    Example:
        handle = TaskPingHandle(stage="facts", article_id="123", article_url="...")
        
        handle.ping("starting content extraction")
        
        with handle.keepalive("calling LLM", interval=5.0):
            response = llm.generate(...)  # Long-running call
        
        handle.ping("completed")
    """

    PING_LOG_INTERVAL = 15  # seconds

    def __init__(self, stage: str, article_id: str, article_url: str):
        """Initialize task ping handle.

        Args:
            stage: Current processing stage
            article_id: Article being processed
            article_url: Article URL for logging
        """
        self.stage = stage
        self.article_id = article_id
        self.article_url = article_url
        self.last_ping = time.time()
        self.last_message = "initialized"
        self._timed_out = False
        self._lock = threading.Lock()
        self._last_log = 0.0
        self._last_logged_message = ""

    def ping(self, message: Optional[str] = None) -> None:
        """Update the heartbeat timestamp and optionally log a status message.

        Args:
            message: Optional status message to log
        """
        now = time.time()
        should_log = False

        with self._lock:
            self.last_ping = now
            if message:
                self.last_message = message

            if message:
                if (message != self._last_logged_message) or (
                    now - self._last_log >= self.PING_LOG_INTERVAL
                ):
                    should_log = True
            else:
                should_log = (now - self._last_log) >= self.PING_LOG_INTERVAL

            if should_log:
                self._last_log = now
                if message:
                    self._last_logged_message = message
                log_message = message or "heartbeat"

        if should_log:
            logger.info("🔁 Ping [%s:%s]: %s", self.stage, self.article_id, log_message)

    @contextmanager
    def keepalive(self, message: str, interval: float = 5.0):
        """Emit periodic pings while a long-running block is executing.

        Args:
            message: Status message to log
            interval: Seconds between pings

        Yields:
            None
        """
        stop_event = threading.Event()

        def _runner() -> None:
            while not stop_event.wait(interval):
                self.ping(message)

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()

        try:
            self.ping(f"{message} (start)")
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)
            self.ping(f"{message} (done)")

    def mark_timed_out(self) -> None:
        """Mark this task as timed out."""
        with self._lock:
            self._timed_out = True

    def is_timed_out(self) -> bool:
        """Check if task is marked as timed out."""
        with self._lock:
            return self._timed_out

    def snapshot(self) -> Dict[str, Any]:
        """Get current state snapshot.

        Returns:
            Dict with task state
        """
        with self._lock:
            return {
                "article_id": self.article_id,
                "stage": self.stage,
                "article_url": self.article_url,
                "last_ping": self.last_ping,
                "last_message": self.last_message,
                "timed_out": self._timed_out,
            }


class TaskPingManager:
    """Manages TaskPingHandle instances and detects stalled work.
    
    Tracks multiple concurrent tasks and can identify which ones
    have exceeded a timeout threshold.
    
    Example:
        manager = TaskPingManager(timeout_seconds=60)
        
        handle = manager.create_handle("facts", article_id, url)
        future = executor.submit(process_article, article)
        manager.track(future, handle)
        
        # Later, check for stalled tasks
        for future, handle in manager.collect_timeouts():
            logger.warning("Task timed out: %s", handle.article_id)
            future.cancel()
    """

    def __init__(self, timeout_seconds: int = 30):
        """Initialize task ping manager.

        Args:
            timeout_seconds: Seconds before a task is considered stalled
        """
        self.timeout_seconds = timeout_seconds
        self._handles: Dict[Any, TaskPingHandle] = {}
        self._lock = threading.Lock()

    def create_handle(
        self, stage: str, article_id: str, article_url: str
    ) -> TaskPingHandle:
        """Create a new task ping handle.

        Args:
            stage: Processing stage
            article_id: Article ID
            article_url: Article URL

        Returns:
            New TaskPingHandle instance
        """
        return TaskPingHandle(stage, article_id, article_url)

    def track(self, future: Any, handle: TaskPingHandle) -> None:
        """Associate a future with a ping handle for tracking.

        Args:
            future: Future/task to track
            handle: Ping handle for the task
        """
        with self._lock:
            self._handles[future] = handle

    def release(self, future: Any) -> Optional[TaskPingHandle]:
        """Remove a future from tracking.

        Args:
            future: Future to release

        Returns:
            Associated handle or None
        """
        with self._lock:
            return self._handles.pop(future, None)

    def collect_timeouts(self) -> List[Tuple[Any, TaskPingHandle]]:
        """Find all tasks that have exceeded the timeout.

        Returns:
            List of (future, handle) tuples for timed out tasks
        """
        now = time.time()
        timed_out: List[Tuple[Any, TaskPingHandle]] = []
        
        with self._lock:
            for future, handle in list(self._handles.items()):
                if handle.is_timed_out():
                    continue
                if now - handle.last_ping >= self.timeout_seconds:
                    handle.mark_timed_out()
                    timed_out.append((future, handle))
        
        return timed_out

    def get_active_count(self) -> int:
        """Get number of actively tracked tasks.

        Returns:
            Number of tracked tasks
        """
        with self._lock:
            return len(self._handles)


def send_ping(ping_handle: Optional[TaskPingHandle], message: str) -> None:
    """Helper to guard ping calls when handle is optional.

    Args:
        ping_handle: Optional ping handle
        message: Message to send
    """
    if ping_handle:
        ping_handle.ping(message)


@contextmanager
def ping_keepalive(
    ping_handle: Optional[TaskPingHandle],
    message: str,
    interval: float = 5.0,
):
    """Context manager that keeps pinging while a block executes.

    Args:
        ping_handle: Optional ping handle
        message: Status message
        interval: Seconds between pings

    Yields:
        None
    """
    if ping_handle:
        with ping_handle.keepalive(message, interval):
            yield
    else:
        yield
