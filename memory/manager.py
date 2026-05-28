"""
记忆管理器：语义索引与经验唤醒。
"""
from memory.storage import MemoryStorage


class MemoryManager:
    def __init__(self, storage: MemoryStorage):
        self.storage = storage

    def get_relevant_context(self, task_description: str = "") -> str:
        """唤醒记忆库中的过往经验。返回格式化的上下文文本。"""
        # 从当前配置中获取模型列表，用于版本衰减计算
        # 这里使用一个简化的默认值——在没有 config 的上下文中
        memories = self.storage.get_effective_memory()
        if not memories:
            return "无可用历史经验。"
        lines = []
        for m in memories:
            lines.append(
                f"- [置信度: {m['confidence']}] {m['summary']}"
            )
        return f"过往成功重构经验参考：\n" + "\n".join(lines)

    def archive_success(self, task_id: str, summary: str):
        self.storage.save_memory(task_id, summary, ["refactor", "success"], True)

    def archive_failure(self, task_id: str, summary: str):
        self.storage.save_memory(task_id, summary, ["refactor", "failure"], False)
