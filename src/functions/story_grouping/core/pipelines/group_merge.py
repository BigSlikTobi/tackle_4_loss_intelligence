"""Merge similar story groups based on centroid similarity."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

from ..db import GroupMemberWriter, GroupWriter

logger = logging.getLogger(__name__)


@dataclass
class MergeResult:
    """Result counters for a merge operation."""

    groups_considered: int = 0
    merge_components: int = 0
    groups_archived: int = 0
    memberships_moved: int = 0
    memberships_skipped: int = 0
    errors: int = 0


class _DisjointSet:
    """Union-find helper for grouping merge candidates."""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            self.parent[rx] = ry
        elif self.rank[rx] > self.rank[ry]:
            self.parent[ry] = rx
        else:
            self.parent[ry] = rx
            self.rank[rx] += 1


class GroupMergeService:
    """
    Merge highly similar story groups by comparing their centroids.

    The service clusters groups whose centroid similarity exceeds a threshold,
    chooses a primary group per cluster, moves memberships from secondary groups,
    and archives the merged groups.
    """

    def __init__(
        self,
        group_writer: GroupWriter,
        member_writer: GroupMemberWriter,
        similarity_threshold: float = 0.92,
        max_pairs: int = 200,
        group_limit: Optional[int] = None,
        dry_run: bool = False,
    ) -> None:
        self.group_writer = group_writer
        self.member_writer = member_writer
        self.similarity_threshold = similarity_threshold
        self.max_pairs = max_pairs
        self.group_limit = group_limit
        self.dry_run = dry_run

    def merge(self) -> MergeResult:
        """Execute the merge workflow."""
        result = MergeResult()

        groups = self.group_writer.get_active_groups()
        if self.group_limit is not None:
            groups = groups[: self.group_limit]

        logger.info("Loaded %s active groups for merge analysis", len(groups))
        result.groups_considered = len(groups)

        plan = self._plan_merges(groups)
        if not plan:
            logger.info("No merge candidates found above threshold %.3f", self.similarity_threshold)
            return result

        logger.info("Planned %s merge components", len(plan))
        result.merge_components = len(plan)

        group_lookup: Dict[str, Dict] = {g["id"]: g for g in groups}

        for target_id, source_ids in plan:
            try:
                moved, skipped = self._merge_into_target(target_id, source_ids, group_lookup)
                result.memberships_moved += moved
                result.memberships_skipped += skipped
                result.groups_archived += len(source_ids)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Error merging into %s: %s", target_id, exc, exc_info=True)
                result.errors += 1

        return result

    def _plan_merges(
        self,
        groups: List[Dict],
    ) -> List[Tuple[str, List[str]]]:
        """Plan merge components using centroid similarity."""
        centroids: List[List[float]] = []
        valid_groups: List[Dict] = []
        for group in groups:
            centroid = group.get("centroid_embedding")
            if centroid:
                centroids.append(centroid)
                valid_groups.append(group)

        if len(valid_groups) < 2:
            return []

        centroid_matrix = np.asarray(centroids, dtype=np.float32)
        norms = np.linalg.norm(centroid_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        centroid_matrix = centroid_matrix / norms

        sim_matrix = centroid_matrix @ centroid_matrix.T

        pairs: List[Tuple[float, int, int]] = []
        n = len(valid_groups)
        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim >= self.similarity_threshold:
                    pairs.append((sim, i, j))

        if not pairs:
            return []

        pairs.sort(reverse=True, key=lambda x: x[0])
        if self.max_pairs and len(pairs) > self.max_pairs:
            pairs = pairs[: self.max_pairs]
            logger.warning(
                "Limiting merge pairs to top %s by similarity (threshold %.3f)",
                self.max_pairs,
                self.similarity_threshold,
            )

        dsu = _DisjointSet(n)
        for _, i, j in pairs:
            dsu.union(i, j)

        components: Dict[int, List[int]] = {}
        for idx in range(n):
            root = dsu.find(idx)
            components.setdefault(root, []).append(idx)

        plan: List[Tuple[str, List[str]]] = []
        for indexes in components.values():
            if len(indexes) < 2:
                continue

            component_groups = [valid_groups[i] for i in indexes]
            primary = self._select_primary(component_groups)
            secondary_ids = [g["id"] for g in component_groups if g["id"] != primary["id"]]
            if not secondary_ids:
                continue
            plan.append((primary["id"], secondary_ids))

        return plan

    @staticmethod
    def _select_primary(groups: List[Dict]) -> Dict:
        """Choose a primary group (largest member_count, then oldest created_at)."""
        sorted_groups = sorted(
            groups,
            key=lambda g: (
                -(g.get("member_count") or 0),
                g.get("created_at") or "",
            ),
        )
        return sorted_groups[0]

    def _merge_into_target(
        self,
        target_group_id: str,
        source_group_ids: Iterable[str],
        group_lookup: Dict[str, Dict],
    ) -> Tuple[int, int]:
        """
        Merge source groups into the target group.

        Returns:
            Tuple of (memberships_moved, memberships_skipped)
        """
        logger.info(
            "Merging %s source groups into target %s",
            len(source_group_ids),
            target_group_id,
        )

        target_members = list(self.member_writer.iter_members_by_group(target_group_id))
        target_fact_ids: Set[str] = {
            m["news_fact_id"] for m in target_members if m.get("news_fact_id")
        }
        target_news_ids: Set[str] = {
            m["news_url_id"] for m in target_members if m.get("news_url_id")
        }

        moved_total = 0
        skipped_total = 0

        for source_id in source_group_ids:
            source_members = list(self.member_writer.iter_members_by_group(source_id))
            to_add: List[Dict] = []

            for member in source_members:
                fact_id = member.get("news_fact_id")
                news_url_id = member.get("news_url_id")

                if fact_id and fact_id in target_fact_ids:
                    skipped_total += 1
                    continue
                if not fact_id and news_url_id in target_news_ids:
                    skipped_total += 1
                    continue

                to_add.append(
                    {
                        "group_id": target_group_id,
                        "news_url_id": news_url_id,
                        "news_fact_id": fact_id,
                        "similarity_score": member.get("similarity_score", 1.0),
                    }
                )

            if to_add:
                moved = self.member_writer.add_members_batch(to_add)
                moved_total += moved
                target_fact_ids.update(m["news_fact_id"] for m in to_add if m.get("news_fact_id"))
                target_news_ids.update(m["news_url_id"] for m in to_add if m.get("news_url_id"))

            # Clean up the source group
            self.member_writer.delete_members_by_group(source_id)
            self.group_writer.update_group(
                group_id=source_id,
                member_count=0,
                status="archived",
            )

            if source_id in group_lookup:
                group_lookup[source_id]["member_count"] = 0
                group_lookup[source_id]["status"] = "archived"

        # Refresh target metadata locally
        if target_group_id in group_lookup:
            current_count = group_lookup[target_group_id].get("member_count") or 0
            group_lookup[target_group_id]["member_count"] = current_count + moved_total

        # Update target member_count in DB (best-effort; triggers may also handle)
        self.group_writer.update_group(
            group_id=target_group_id,
            member_count=(group_lookup.get(target_group_id, {}).get("member_count")),
        )

        return moved_total, skipped_total
