__all__ = ["DEFAULT_FASS_CATEGORY_SLUGS", "FassrideImportPipeline"]


def __getattr__(name):
    if name in {"DEFAULT_FASS_CATEGORY_SLUGS", "FassrideImportPipeline"}:
        from .pipeline import DEFAULT_FASS_CATEGORY_SLUGS, FassrideImportPipeline

        return {
            "DEFAULT_FASS_CATEGORY_SLUGS": DEFAULT_FASS_CATEGORY_SLUGS,
            "FassrideImportPipeline": FassrideImportPipeline,
        }[name]
    raise AttributeError(name)
