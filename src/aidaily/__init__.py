"""aidaily -- 统一 AI 日报聚合平台。

Layering (strictly one-directional, see docs/ARCHITECTURE.md §4):
    registry → fetchers → http/parse → normalize → dedup → quality
             → rank → llm/analyze → render → publish → store → obs
"""

__version__ = "0.1.0"
