"""Document-class registry loaded from ``classes/*/class.yaml``."""

from trop.registry.loader import (
    BlockSpec,
    ClassSpec,
    DetectKeyword,
    DetectSpec,
    ExtractorSpec,
    FieldSpec,
    ListFieldSpec,
    ListSpec,
    NegativesConfig,
    default_classes_dir,
    load_class_spec,
    load_classes,
    load_czynnosc_powod_dict,
    load_negatives,
)

__all__ = [
    "BlockSpec",
    "ClassSpec",
    "DetectKeyword",
    "DetectSpec",
    "ExtractorSpec",
    "FieldSpec",
    "ListFieldSpec",
    "ListSpec",
    "NegativesConfig",
    "default_classes_dir",
    "load_class_spec",
    "load_classes",
    "load_czynnosc_powod_dict",
    "load_negatives",
]
