import json
import glob
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


BENCH_CACHE_DIR = os.path.expanduser("~/.cache/or-bench")


@dataclass
class BenchmarkResult:
    slug: str
    status: str
    tps: Optional[float] = None
    ttfb_ms: Optional[int] = None
    output_tokens: Optional[int] = None
    total_ms: Optional[int] = None
    error: Optional[str] = None
    response_text: Optional[str] = None


@dataclass
class ModelInfo:
    slug: str
    name: str
    provider: str
    context_length: int
    params_total: Optional[float] = None
    params_active: Optional[float] = None
    rpm: Optional[int] = None
    is_free: bool = False


@dataclass
class BenchmarkReport:
    timestamp: str
    prompt: str
    max_tokens: int
    results: List[BenchmarkResult] = field(default_factory=list)
    models: Dict[str, ModelInfo] = field(default_factory=dict)

    @property
    def passed(self) -> List[BenchmarkResult]:
        return [r for r in self.results if r.status == "ok"]

    @property
    def failed(self) -> List[BenchmarkResult]:
        return [r for r in self.results if r.status != "ok"]

    @property
    def rate_limited(self) -> List[BenchmarkResult]:
        return [r for r in self.results if r.status == "http_429"]


class BenchmarkLoader:
    """
    Loads or-bench results from cache and provides model rankings.

    Usage:
        loader = BenchmarkLoader()
        latest = loader.load_latest()
        best = loader.rank_by_speed(latest)
        available = loader.filter_working(latest, min_params=12)
    """

    def load_latest(self) -> Optional[BenchmarkReport]:
        files = sorted(glob.glob(os.path.join(BENCH_CACHE_DIR, "*.json")), reverse=True)
        if not files:
            return None
        return self._parse_file(files[0])

    def load_all(self) -> List[BenchmarkReport]:
        files = sorted(glob.glob(os.path.join(BENCH_CACHE_DIR, "*.json")), reverse=True)
        return [self._parse_file(f) for f in files if self._parse_file(f)]

    def load_by_date(self, date_str: str) -> Optional[BenchmarkReport]:
        pattern = os.path.join(BENCH_CACHE_DIR, f"*{date_str}*.json")
        files = glob.glob(pattern)
        if not files:
            return None
        return self._parse_file(sorted(files)[-1])

    def rank_by_speed(self, report: BenchmarkReport) -> List[BenchmarkResult]:
        passed = report.passed
        return sorted(passed, key=lambda r: r.tps or 0, reverse=True)

    def rank_by_ttfb(self, report: BenchmarkReport) -> List[BenchmarkResult]:
        passed = report.passed
        return sorted(passed, key=lambda r: r.ttfb_ms or 99999)

    def rank_by_output(self, report: BenchmarkReport) -> List[BenchmarkResult]:
        passed = report.passed
        return sorted(passed, key=lambda r: r.output_tokens or 0, reverse=True)

    def filter_working(
        self,
        report: BenchmarkReport,
        min_params: Optional[float] = None,
        max_params: Optional[float] = None,
        only_free: bool = False,
    ) -> List[BenchmarkResult]:
        results = report.passed
        if min_params is not None:
            results = [
                r
                for r in results
                if self._get_active_params(report, r.slug) is None
                or self._get_active_params(report, r.slug) >= min_params
            ]
        if max_params is not None:
            results = [
                r
                for r in results
                if self._get_active_params(report, r.slug) is None
                or self._get_active_params(report, r.slug) <= max_params
            ]
        if only_free:
            results = [r for r in results if ":free" in r.slug]
        return results

    def get_model_availability(self, report: BenchmarkReport) -> Dict[str, str]:
        availability = {}
        for r in report.results:
            if r.status == "ok":
                availability[r.slug] = "available"
            elif r.status == "http_429":
                availability[r.slug] = "rate_limited"
            else:
                availability[r.slug] = "error"
        return availability

    def to_tier_mapping(self, report: BenchmarkReport) -> Dict[str, List[str]]:
        """
        Generate tier mapping from benchmark results.
        Returns dict like {"opus": [...], "sonnet": [...], "haiku": [...]}
        """
        ranked = self.rank_by_speed(report)
        tiers: Dict[str, List[str]] = {"opus": [], "sonnet": [], "haiku": []}

        for r in ranked:
            info = report.models.get(r.slug)
            params = self._get_active_params(report, r.slug)

            if params and params >= 100:
                tiers["opus"].append(r.slug)
            elif params and params >= 20:
                tiers["sonnet"].append(r.slug)
            else:
                tiers["haiku"].append(r.slug)

        return tiers

    def _parse_file(self, filepath: str) -> Optional[BenchmarkReport]:
        try:
            with open(filepath) as f:
                data = json.load(f)

            results = []
            for r in data.get("results", []):
                results.append(
                    BenchmarkResult(
                        slug=r.get("slug", ""),
                        status=r.get("status", "unknown"),
                        tps=r.get("tps"),
                        ttfb_ms=r.get("ttfb_ms"),
                        output_tokens=r.get("output_tokens"),
                        total_ms=r.get("total_ms"),
                        error=r.get("error"),
                        response_text=r.get("response_text"),
                    )
                )

            models = {}
            for m in data.get("models", []):
                slug = m.get("slug", "")
                models[slug] = ModelInfo(
                    slug=slug,
                    name=m.get("name", ""),
                    provider=m.get("provider", ""),
                    context_length=m.get("context_length", 0),
                    params_total=m.get("params_total"),
                    params_active=m.get("params_active"),
                    rpm=m.get("rpm"),
                    is_free=":free" in slug,
                )

            return BenchmarkReport(
                timestamp=data.get("timestamp", ""),
                prompt=data.get("prompt", ""),
                max_tokens=data.get("max_tokens", 0),
                results=results,
                models=models,
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _get_active_params(self, report: BenchmarkReport, slug: str) -> Optional[float]:
        info = report.models.get(slug)
        if info and info.params_active:
            return info.params_active
        return None
