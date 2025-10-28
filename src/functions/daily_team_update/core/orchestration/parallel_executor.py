"""Utilities for parallel team processing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Iterator, Sequence, Tuple, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class ParallelExecutor:
    """Simple wrapper around ThreadPoolExecutor for predictable iteration order."""

    def __init__(self, max_workers: int) -> None:
        self._max_workers = max_workers

    def execute(
        self,
        items: Sequence[T],
        func: Callable[[T], R],
    ) -> Iterator[Tuple[T, R]]:
        """Run *func* for each item concurrently and yield the results."""

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(func, item): item for item in items}
            for future in as_completed(futures):
                item = futures[future]
                yield item, future.result()

    def map(self, items: Iterable[T], func: Callable[[T], R]) -> Iterator[R]:
        for _, result in self.execute(list(items), func):
            yield result
