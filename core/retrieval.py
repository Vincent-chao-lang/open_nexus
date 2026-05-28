"""
检索调度器：将 Agent 意图翻译为上下文检索查询。
（最小版本：基于标签匹配的简化实现）
"""
from typing import Dict, List, Any
from memory.storage import MemoryStorage


class RetrievalScheduler:
    def __init__(self, memory_store: Any, max_tokens: int = 4000):
        self.memory_store = memory_store
        self.max_tokens = max_tokens

    def assemble_context_package(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        package: Dict[str, Any] = {}

        target = intent.get("target", "")
        func = intent.get("function", "")

        # 历史经验检索
        search_query = f"refactor {func} in {target}" if func else f"refactor {target}"
        try:
            memories = self.memory_store.get_effective_memory()
            package["past_experiences"] = [m["summary"] for m in memories[:3]]
        except Exception:
            package["past_experiences"] = []

        return package
