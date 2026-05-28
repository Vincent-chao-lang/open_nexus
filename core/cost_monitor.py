"""
成本监控：实时 Token 计费、缓存命中追踪与预算熔断。
"""
from typing import Dict, Optional


class CostMonitor:
    # 模型价格（每 1M tokens，美元）
    RATES: Dict[str, Dict[str, float]] = {
        "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
        "gpt-4o":            {"input": 5.0, "output": 15.0},
        "deepseek-chat":     {"input": 0.14, "output": 0.28, "cache_hit": 0.014},
    }

    def __init__(self):
        self.current_session_cost: float = 0.0
        self.total_cache_hit_tokens: int = 0
        self.total_cache_miss_tokens: int = 0
        self.cache_savings: float = 0.0
        self.usage_logs: list = []

    def _get_rate(self, model_name: str, key: str) -> float:
        """按模型名匹配费率，默认回退到 deepseek-chat 标准 input 价"""
        rate = next(
            (v for k, v in self.RATES.items() if k in model_name),
            self.RATES["deepseek-chat"]
        )
        return rate.get(key, rate["input"])

    def record(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cache_hit_tokens: Optional[int] = None,
    ) -> float:
        """
        记录一次模型调用成本。

        Args:
            model_name: 模型标识（含 litellm 前缀如 'deepseek/deepseek-chat'）
            input_tokens: 总输入 token 数
            output_tokens: 输出 token 数
            cache_hit_tokens: 缓存命中的 input token 数（仅 DeepSeek 类模型有效）
        """
        if cache_hit_tokens is None:
            cache_hit_tokens = 0
        cache_miss_tokens = input_tokens - cache_hit_tokens

        input_rate = self._get_rate(model_name, "input")
        output_rate = self._get_rate(model_name, "output")
        cache_hit_rate = self._get_rate(model_name, "cache_hit")

        # 分别计费：命中部分用低价，未命中部分用标准价
        miss_cost = (cache_miss_tokens / 1_000_000) * input_rate
        hit_cost = (cache_hit_tokens / 1_000_000) * cache_hit_rate
        output_cost = (output_tokens / 1_000_000) * output_rate
        cost = miss_cost + hit_cost + output_cost

        # 计算节省金额
        full_input_cost = (input_tokens / 1_000_000) * input_rate
        saving = full_input_cost - (miss_cost + hit_cost)

        self.current_session_cost += cost
        self.total_cache_hit_tokens += cache_hit_tokens
        self.total_cache_miss_tokens += cache_miss_tokens
        self.cache_savings += saving

        self.usage_logs.append({
            "model": model_name,
            "input_tokens": input_tokens,
            "cache_hit_tokens": cache_hit_tokens,
            "cache_miss_tokens": cache_miss_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "cache_saving": saving,
        })

        hit_pct = (cache_hit_tokens / input_tokens * 100) if input_tokens > 0 else 0
        print(
            f"[Cost] {model_name.split('/')[-1]}: "
            f"input={input_tokens} (hit={cache_hit_tokens} miss={cache_miss_tokens}) | "
            f"cost=${cost:.6f} | "
            f"累计=${self.current_session_cost:.4f}"
        )
        if cache_hit_tokens > 0:
            print(f"[Cache] 命中率 {hit_pct:.1f}% | 节省 ${saving:.6f} | 累计节省 ${self.cache_savings:.6f}")

        return cost

    def get_total_cost(self) -> float:
        return self.current_session_cost

    def get_cache_stats(self) -> Dict:
        """返回累计缓存统计"""
        total_input = self.total_cache_hit_tokens + self.total_cache_miss_tokens
        return {
            "cache_hit_tokens": self.total_cache_hit_tokens,
            "cache_miss_tokens": self.total_cache_miss_tokens,
            "overall_hit_rate": (
                self.total_cache_hit_tokens / total_input * 100
                if total_input > 0 else 0
            ),
            "total_cache_savings": self.cache_savings,
        }
