"""Memory monitoring daemon for batch processing."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger(__name__)


class MemoryMonitor:
    """Daemon thread that monitors memory pressure during batch processing.
    
    Periodically checks system memory usage and can trigger callbacks
    when memory pressure exceeds thresholds.
    
    Example:
        def on_high_memory():
            gc.collect()
            logger.warning("High memory pressure - triggered GC")
        
        monitor = MemoryMonitor(
            warning_threshold=80,
            critical_threshold=90,
            on_warning=on_high_memory,
        )
        monitor.start()
        
        # ... process articles ...
        
        monitor.stop()
        print(monitor.get_stats())
    """

    def __init__(
        self,
        *,
        check_interval: float = 30.0,
        warning_threshold: float = 80.0,
        critical_threshold: float = 90.0,
        on_warning: Optional[Callable[[], None]] = None,
        on_critical: Optional[Callable[[], None]] = None,
    ):
        """Initialize memory monitor.

        Args:
            check_interval: Seconds between memory checks
            warning_threshold: Memory percent to trigger warning callback
            critical_threshold: Memory percent to trigger critical callback
            on_warning: Callback when memory exceeds warning threshold
            on_critical: Callback when memory exceeds critical threshold
        """
        self.check_interval = check_interval
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.on_warning = on_warning
        self.on_critical = on_critical

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Stats
        self._peak_memory_percent = 0.0
        self._warning_count = 0
        self._critical_count = 0
        self._check_count = 0

    def start(self) -> None:
        """Start the memory monitoring daemon thread."""
        if not HAS_PSUTIL:
            logger.warning("psutil not available - memory monitoring disabled")
            return

        if self._thread is not None and self._thread.is_alive():
            logger.warning("Memory monitor already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Memory monitor started (warning=%d%%, critical=%d%%)",
            self.warning_threshold,
            self.critical_threshold,
        )

    def stop(self) -> None:
        """Stop the memory monitoring daemon thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Memory monitor stopped")

    def _monitor_loop(self) -> None:
        """Main monitoring loop running in daemon thread."""
        while not self._stop_event.wait(self.check_interval):
            try:
                memory = psutil.virtual_memory()
                percent = memory.percent

                with self._lock:
                    self._check_count += 1
                    if percent > self._peak_memory_percent:
                        self._peak_memory_percent = percent

                if percent >= self.critical_threshold:
                    with self._lock:
                        self._critical_count += 1
                    logger.warning(
                        "CRITICAL memory pressure: %.1f%% (%.1f/%.1f GB)",
                        percent,
                        memory.used / (1024**3),
                        memory.total / (1024**3),
                    )
                    if self.on_critical:
                        try:
                            self.on_critical()
                        except Exception as e:
                            logger.error("Error in critical callback: %s", e)

                elif percent >= self.warning_threshold:
                    with self._lock:
                        self._warning_count += 1
                    logger.info(
                        "High memory pressure: %.1f%% (%.1f/%.1f GB)",
                        percent,
                        memory.used / (1024**3),
                        memory.total / (1024**3),
                    )
                    if self.on_warning:
                        try:
                            self.on_warning()
                        except Exception as e:
                            logger.error("Error in warning callback: %s", e)

            except Exception as e:
                logger.error("Memory monitor error: %s", e)

    def get_stats(self) -> Dict[str, Any]:
        """Get memory monitoring statistics.

        Returns:
            Dict with monitoring metrics
        """
        with self._lock:
            stats = {
                "peak_memory_percent": self._peak_memory_percent,
                "warning_count": self._warning_count,
                "critical_count": self._critical_count,
                "check_count": self._check_count,
            }

        if HAS_PSUTIL:
            try:
                memory = psutil.virtual_memory()
                stats.update({
                    "current_memory_percent": memory.percent,
                    "current_memory_used_gb": memory.used / (1024**3),
                    "current_memory_total_gb": memory.total / (1024**3),
                })
            except Exception:
                pass

        return stats

    def get_current_memory(self) -> Optional[float]:
        """Get current memory usage percentage.

        Returns:
            Memory percentage or None if psutil unavailable
        """
        if not HAS_PSUTIL:
            return None
        try:
            return psutil.virtual_memory().percent
        except Exception:
            return None
