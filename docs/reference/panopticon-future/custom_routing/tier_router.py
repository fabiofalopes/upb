import asyncio
import time
from typing import Dict, List, Optional

from litellm.router import CustomRoutingStrategyBase


class TierAwareRouter(CustomRoutingStrategyBase):
    """
    Tier-aware routing strategy for LiteLLM.

    Routing priority:
    1. Prefer local (Ollama) for simple/haiku tasks
    2. Use free cloud models when available and not rate-limited
    3. Fall back to paid models only when needed
    4. Track rate limit signals and cooldown providers
    """

    def __init__(self):
        self.provider_cooldowns: Dict[str, float] = {}
        self.cooldown_seconds = 300
        self.request_counts: Dict[str, int] = {}

    async def async_get_available_deployment(
        self,
        model: str,
        messages: Optional[List[Dict[str, str]]] = None,
        input: Optional[str] = None,
        specific_deployment: Optional[bool] = False,
        request_kwargs: Optional[Dict] = None,
    ):
        model_list = request_kwargs.get("model_list", []) if request_kwargs else []
        if not model_list:
            return None

        now = time.time()
        self._expire_cooldowns(now)

        candidates = self._filter_available(model_list, now)
        if not candidates:
            return model_list[0]

        if self._is_local_tier(model):
            local = self._prefer_local(candidates)
            if local:
                return local

        cloud = [
            c
            for c in candidates
            if not c.get("litellm_params", {}).get("model", "").startswith("ollama/")
        ]
        if not cloud:
            cloud = candidates

        if model in ("opus", "sonnet", "subagent"):
            return self._pick(cloud, key=self._speed_score)

        if self._is_tiny_tier(model):
            return self._pick(cloud, key=self._speed_score)

        return self._pick(cloud, key=self._cost_score)

    def _filter_available(self, model_list: List[Dict], now: float) -> List[Dict]:
        available = []
        for m in model_list:
            litellm_params = m.get("litellm_params", {})
            model_id = litellm_params.get("model", "")
            provider = self._extract_provider(model_id)
            cooldown_until = self.provider_cooldowns.get(provider, 0)
            if now >= cooldown_until:
                available.append(m)
        return available

    def _prefer_local(self, candidates: List[Dict]) -> Optional[Dict]:
        for m in candidates:
            model_id = m.get("litellm_params", {}).get("model", "")
            if model_id.startswith("ollama/"):
                return m
        return None

    def _pick(self, candidates: List[Dict], key) -> Optional[Dict]:
        if not candidates:
            return None
        return max(
            candidates, key=lambda m: key(m.get("litellm_params", {}).get("model", ""))
        )

    def _extract_provider(self, model_id: str) -> str:
        parts = model_id.split("/")
        if len(parts) >= 2:
            return parts[1] if parts[0] == "openrouter" else parts[0]
        return model_id

    def _is_local_tier(self, model: str) -> bool:
        return model in ("haiku", "local")

    def _is_tiny_tier(self, model: str) -> bool:
        return model in ("haiku",)

    def _speed_score(self, model_id: str) -> float:
        speed_rankings = {
            "nvidia/nemotron-3-super-120b-a12b": 100,
            "openai/gpt-oss-20b": 60,
            "openai/gpt-oss-120b": 50,
            "minimax/minimax-m2.5": 40,
            "qwen/qwen3.6-plus": 35,
            "z-ai/glm-4.5-air": 20,
        }
        for key, score in speed_rankings.items():
            if key in model_id:
                return score
        return 25

    def _cost_score(self, model_id: str) -> float:
        if ":free" in model_id:
            return 100
        if model_id.startswith("ollama/"):
            return 110
        return 10

    def _expire_cooldowns(self, now: float):
        expired = [k for k, v in self.provider_cooldowns.items() if now >= v]
        for k in expired:
            del self.provider_cooldowns[k]

    def mark_rate_limited(self, provider: str):
        self.provider_cooldowns[provider] = time.time() + self.cooldown_seconds
