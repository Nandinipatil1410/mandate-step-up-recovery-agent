"""Deterministic, explainable root-cause classification."""

from .classifier import ClassificationInputError, classify
from .rules import ClassificationConfig, load_classification_config

__all__ = [
    "ClassificationConfig",
    "ClassificationInputError",
    "classify",
    "load_classification_config",
]
