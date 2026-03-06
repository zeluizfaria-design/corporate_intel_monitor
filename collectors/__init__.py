from .base_collector import BaseCollector, RawArticle

__all__ = [
    "BaseCollector",
    "RawArticle",
    "CVMCollector",
    "SECEdgarCollector",
    "MaterialFactsRouter",
    "detect_market",
    "NewsCollector",
    "build_news_collectors",
    "build_social_collectors",
    "build_betting_collectors",
    "InsiderTradingCollector",
    "PoliticianTradingCollector",
]

_LAZY_IMPORTS = {
    "CVMCollector": (".cvm_collector", "CVMCollector"),
    "SECEdgarCollector": (".sec_edgar_collector", "SECEdgarCollector"),
    "MaterialFactsRouter": (".market_router", "MaterialFactsRouter"),
    "detect_market": (".market_router", "detect_market"),
    "NewsCollector": (".news_collector", "NewsCollector"),
    "build_news_collectors": (".news_collector", "build_news_collectors"),
    "build_social_collectors": (".social_collector", "build_social_collectors"),
    "build_betting_collectors": (".betting_collector", "build_betting_collectors"),
    "InsiderTradingCollector": (
        ".insider_trading_collector",
        "InsiderTradingCollector",
    ),
    "PoliticianTradingCollector": (
        ".politician_trading_collector",
        "PoliticianTradingCollector",
    ),
}


def __getattr__(name: str):
    lazy_target = _LAZY_IMPORTS.get(name)
    if lazy_target is None:
        raise AttributeError(f"module 'collectors' has no attribute '{name}'")
    module_name, attr_name = lazy_target
    module = __import__(f"{__name__}{module_name}", fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
