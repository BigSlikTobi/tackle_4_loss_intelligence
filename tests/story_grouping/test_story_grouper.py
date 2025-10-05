import pytest

from src.functions.story_grouping.core.clustering.grouper import StoryGrouper


def test_first_story_creates_new_group():
    grouper = StoryGrouper(similarity_threshold=0.8)

    group, similarity = grouper.assign_story("nfl-1", [1.0, 0.0, 0.0])

    assert similarity == pytest.approx(1.0)
    assert group.member_count == 1
    assert len(grouper.groups) == 1
    assert group.get_member_news_url_ids() == ["nfl-1"]


def test_similar_story_reuses_existing_group():
    grouper = StoryGrouper(similarity_threshold=0.75)
    grouper.assign_story("story-1", [0.9, 0.1, 0.0])

    group, similarity = grouper.assign_story("story-2", [0.88, 0.12, 0.0])

    assert group.member_count == 2
    assert similarity > 0.95
    assert len(grouper.groups) == 1


def test_dissimilar_story_creates_new_group():
    grouper = StoryGrouper(similarity_threshold=0.9)
    grouper.assign_story("offense", [1.0, 0.0, 0.0])

    group, similarity = grouper.assign_story("defense", [0.0, 1.0, 0.0])

    assert similarity == pytest.approx(1.0)
    assert len(grouper.groups) == 2
    assert group.member_count == 1


def test_group_stats_reflect_current_groups():
    grouper = StoryGrouper(similarity_threshold=0.5)
    grouper.assign_story("story-1", [1.0, 0.0, 0.0])
    grouper.assign_story("story-2", [0.99, 0.01, 0.0])
    grouper.assign_story("story-3", [0.0, 1.0, 0.0])

    stats = grouper.get_group_stats()

    assert stats["total_groups"] == 2
    assert stats["total_stories"] == 3
    assert stats["singleton_groups"] == 1
    assert stats["avg_group_size"] == pytest.approx(1.5)
