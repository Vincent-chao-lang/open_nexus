"""
记忆存储：SQLite 持久化与双因子置信度衰减。
"""
import sqlite3
import time
import math
import json
import os
from typing import List, Dict, Optional


class MemoryStorage:
    def __init__(
        self,
        db_path: str,
        decay_lambda_t: float = 0.05,
        decay_lambda_v: float = 0.3,
        threshold: float = 0.4
    ):
        self.db_path = db_path
        self.decay_lambda_t = decay_lambda_t
        self.decay_lambda_v = decay_lambda_v
        self.threshold = threshold
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_nodes (
                    id TEXT PRIMARY KEY,
                    content_summary TEXT NOT NULL,
                    base_score REAL DEFAULT 1.0,
                    rewards REAL DEFAULT 0.0,
                    created_at REAL NOT NULL,
                    last_accessed REAL,
                    tags TEXT,
                    model_version_based_on TEXT DEFAULT 'unknown'
                )
            """)
            conn.commit()

    def save_memory(
        self, task_id: str, summary: str, tags: List[str],
        success: bool, model_version: Optional[str] = None
    ):
        reward = 0.5 if success else -1.0
        current_time = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO memory_nodes
                   (id, content_summary, base_score, rewards, created_at,
                    last_accessed, tags, model_version_based_on)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, summary, 1.0, reward, current_time,
                 current_time, json.dumps(tags), model_version or 'unknown')
            )
            conn.commit()

    def get_effective_memory(
        self, current_models: Optional[Dict[str, str]] = None
    ) -> List[Dict]:
        if current_models is None:
            current_models = {}

        valid_memories = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM memory_nodes")
            for row in cursor.fetchall():
                elapsed_days = (time.time() - row['created_at']) / 86400
                source_model = row['model_version_based_on'] if 'model_version_based_on' in row.keys() else 'unknown'
                model_versions = self._count_model_version_changes(
                    source_model,
                    current_models
                )

                time_decay = math.exp(-self.decay_lambda_t * elapsed_days)
                version_decay = math.exp(-self.decay_lambda_v * model_versions)
                score = (row['base_score'] + row['rewards']) * time_decay * version_decay

                if score >= self.threshold:
                    valid_memories.append({
                        "summary": row['content_summary'],
                        "confidence": round(score, 3),
                        "source_model": row['model_version_based_on'] if 'model_version_based_on' in row.keys() else 'unknown',
                        "age_days": round(elapsed_days, 1)
                    })

        sorted_memories = sorted(
            valid_memories, key=lambda x: x['confidence'], reverse=True
        )
        return sorted_memories[:3]

    def _count_model_version_changes(
        self, source_model: str, current_models: Dict[str, str]
    ) -> int:
        if source_model == 'unknown':
            return 0
        if not current_models:
            return 0

        generation_map = {
            'gpt-4': 0, 'gpt-4-turbo': 1, 'gpt-4o': 2,
            'gpt-4o-2024-08-06': 3, 'gpt-4o-2024-11-20': 4,
            'claude-3-opus': 0, 'claude-3-5-sonnet': 1,
            'claude-3-5-sonnet-20241022': 2, 'claude-sonnet-4-6': 3,
            'deepseek-chat': 0, 'deepseek-reasoner': 1
        }
        source_gen = generation_map.get(source_model, 0)
        current_gen_values = [generation_map.get(m, 0) for m in current_models.values()]
        if not current_gen_values:
            return 0
        current_max = max(current_gen_values)
        return max(0, current_max - source_gen)

    def update_feedback(self, task_id: str, is_helpful: bool):
        reward_step = 0.2 if is_helpful else -0.5
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE memory_nodes
                   SET rewards = rewards + ?, last_accessed = ?
                   WHERE id = ?""",
                (reward_step, time.time(), task_id)
            )
            conn.commit()
