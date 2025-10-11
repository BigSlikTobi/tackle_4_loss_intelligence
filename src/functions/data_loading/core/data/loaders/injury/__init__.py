"""Data loaders for NFL injury reports."""

from .injuries import InjuriesDataLoader, build_injuries_pipeline

__all__ = ["InjuriesDataLoader", "build_injuries_pipeline"]
