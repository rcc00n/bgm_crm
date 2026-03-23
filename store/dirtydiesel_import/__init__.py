__all__ = ["DEFAULT_EXCLUDED_CATEGORY_PREFIXES", "DirtyDieselImportPipeline"]


def __getattr__(name):
    if name in {"DEFAULT_EXCLUDED_CATEGORY_PREFIXES", "DirtyDieselImportPipeline"}:
        from .pipeline import DEFAULT_EXCLUDED_CATEGORY_PREFIXES, DirtyDieselImportPipeline

        return {
            "DEFAULT_EXCLUDED_CATEGORY_PREFIXES": DEFAULT_EXCLUDED_CATEGORY_PREFIXES,
            "DirtyDieselImportPipeline": DirtyDieselImportPipeline,
        }[name]
    raise AttributeError(name)
