"""
编排引擎：Planner → Executor → Reviewer 闭环。
纯调度者角色——管节奏、管熔断、管回滚。

缓存优化策略：
  所有阶段 prompt 共享一个"固定前缀"（全局约束 + 任务目标 + 架构契约 + 源码），
  拼在 prompt 最前面。变化部分（角色指令、反馈、新代码）放后面。
  这样 DeepSeek 的前缀匹配缓存可以跨阶段命中，大幅降低 Executor 成本。
"""
import asyncio
import os
from typing import Dict, Any, Optional
from litellm import acompletion
from pydantic import BaseModel, Field


class TaskState(BaseModel):
    task_id: str = "unnamed"
    task_description: str = ""  # 用户指定的重构目标
    target_files: list = Field(default_factory=list)
    code_map: dict = Field(default_factory=dict)
    refined_map: dict = Field(default_factory=dict)
    plan: str = ""
    architecture_contract: str = ""
    impact_nodes: list = Field(default_factory=list)
    review_comments: str = ""
    total_cost: float = 0.0
    iteration: int = 0
    status: str = "initialized"


class Orchestrator:
    def __init__(self, config: Dict, monitor: Any, safety: Any, memory: Any):
        self.config = config
        self.monitor = monitor
        self.safety = safety
        self.memory = memory

        # 延迟导入以避免循环依赖
        from core.code_analyzer import CodeAnalyzer
        from core.test_generator import TestGenerator

        self.analyzer: CodeAnalyzer = CodeAnalyzer(config['safety']['git_repo_path'])
        self.test_gen: TestGenerator = TestGenerator(config['safety']['git_repo_path'])
        self.models = config['models']

        # 缓存前缀：在 run_pipeline 中设置
        self._cache_prefix: str = ""

    def _build_cache_prefix(self, state: TaskState) -> str:
        """构建可缓存固定前缀——所有 _call_model() 调用共享，拼在 prompt 最前面。

        包含：全局约束 + 项目信息 + 任务目标 + 架构契约 + 源码。
        这些内容在任务生命周期内不变，DeepSeek 可跨阶段命中缓存。
        """
        project_name = os.path.basename(
            os.path.abspath(self.config['safety'].get('git_repo_path', './'))
        )
        global_constraints = self.config.get('global_constraints', '').strip()

        prefix = (
            f"# Open-Nexus 重构框架\n"
            f"项目: {project_name}\n"
            f"全局约束:\n{global_constraints}\n\n"
            f"## 当前任务\n"
            f"重构目标: {state.task_description}\n"
            f"目标文件: {', '.join(state.target_files)}\n\n"
            f"## 架构契约\n"
            f"{state.architecture_contract}\n\n"
            f"## 源码\n"
        )
        for fpath, code in state.code_map.items():
            prefix += f"### {fpath}\n```python\n{code}\n```\n\n"

        prefix += f"{'─' * 50}\n\n"
        return prefix

    async def _call_model(self, role: str, prompt: str, state: TaskState) -> str:
        """异构模型调用：自动拼接缓存前缀，集成成本监控与预算熔断。"""
        if state.total_cost > self.config['workflow']['budget_limit']:
            state.status = "human_required"
            raise Exception(f"[Budget] 预算超限 (${state.total_cost:.4f})。任务挂起。")

        # 拼接固定前缀（变化部分放后面，保证前缀可缓存）
        full_prompt = self._cache_prefix + prompt if self._cache_prefix else prompt

        model_name = self.models[role]
        response = await acompletion(
            model=model_name,
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.1 if role != "planner" else 0.3
        )

        # 提取缓存命中 token 数（DeepSeek API 返回此字段）
        cache_hit_tokens = getattr(response.usage, 'prompt_cache_hit_tokens', 0)

        cost = self.monitor.record(
            model_name,
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            cache_hit_tokens=cache_hit_tokens,
        )
        state.total_cost += cost
        return response.choices[0].message.content

    async def run_pipeline(self, state: TaskState, bridge: Any) -> bool:
        """
        ADSE 闭环：Research → Plan → TestGen → Execute → Validate。

        缓存策略：
        - PHASE 1 结束后，构建 _cache_prefix（= 全局约束 + 目标 + 契约 + 源码）
        - PHASE 2+ 所有 _call_model 自动在 prompt 前拼接 _cache_prefix
        - 变化部分（角色指令、反馈、新代码）只放在前缀之后
        - DeepSeek Executor 可跨阶段命中缓存，成本降至 1/10
        """

        # ===== PHASE 1: RESEARCH（依赖分析）=====
        # 注：此阶段尚未构建 _cache_prefix（契约尚未生成）
        state.status = "researching"
        print(f"[Research] 开始对目标域 {state.target_files} 进行森林环境分析...")

        impact_map = self.analyzer.map_dependencies(state.target_files)
        state.impact_nodes = impact_map["inbound"]

        neighbor_context = ""
        for f in state.impact_nodes[:3]:
            sig = self.analyzer.get_signatures(f)
            if sig:
                neighbor_context += f"\nFile {f} Outline:\n{sig}\n"

        past_exp = self.memory.get_relevant_context(str(state.target_files))

        research_prompt = (
            f"你现在是资深代码分析专家。在文档缺失的情况下，分析以下上下文并推断全局约束。\n"
            f"用户的重构目标是：{state.task_description}\n"
            f"目标域文件：{state.target_files}\n"
            f"邻居接口签名：{neighbor_context}\n"
            f"历史成功经验：{past_exp}\n"
            f"请输出一份 JSON 格式的'临时契约'，包含必须遵守的命名规范、异常处理风格及调用模式。"
            f"契约必须服务于用户的重构目标。"
        )
        state.architecture_contract = await self._call_model(
            "planner", research_prompt, state
        )

        # 构建缓存前缀（此后所有调用共享，DeepSeek 可跨阶段命中）
        self._cache_prefix = self._build_cache_prefix(state)
        print("[Cache] 固定前缀已构建，后续 Executor/Reviewer 调用将共享缓存前缀")

        # ===== PHASE 2: PLANNING（战术规划）=====
        state.status = "planning"
        plan_prompt = (
            f"角色: Planner（战术规划）\n"
            f"基于以上上下文（项目信息、重构目标、架构契约、源码），制定实现重构目标的详细计划。\n"
            f"计划应明确每个文件的改动范围、接口变更和协同约束。"
        )
        state.plan = await self._call_model("planner", plan_prompt, state)

        # ===== PHASE 2.5: TEST GENERATION（测试生成）=====
        state.status = "generating_tests"
        existing_tests = self.test_gen.find_existing_tests(state.target_files)
        all_have_tests = all(v for v in existing_tests.values())

        if not all_have_tests:
            print("[TestGen] 目标代码缺少测试覆盖，自动生成基础测试桩...")
            print("[TestGen] 警告：自动生成的测试仅覆盖 happy path，边界情况需人工补充。")
            generated_tests = self.test_gen.generate_test_stubs(
                state.code_map,
                state.architecture_contract
            )
            for test_file, test_code in generated_tests.items():
                self.safety.write_temp_file(test_file, test_code)
            print(f"[TestGen] 已为 {len(generated_tests)} 个文件生成基准测试。")

        # ===== PHASE 3: EXECUTION & HYBRID VALIDATION =====
        max_iters = self.config['workflow']['max_iterations']
        while state.iteration < max_iters:
            state.iteration += 1
            state.status = f"executing_iter_{state.iteration}"
            print(f"[Execute] 异构协作重构循环开始 - 迭代 {state.iteration}/{max_iters}")

            # Executor：变化内容只有规划 + 上轮反馈（源码已在缓存前缀中）
            exec_prompt = (
                f"角色: Executor（代码生成）\n"
                f"基于以上上下文（项目信息、重构目标、架构契约、源码），实现重构。\n"
                f"必须保持多文件之间的协同一致。\n"
                f"规划:\n{state.plan}\n"
                f"上轮反馈: {state.review_comments or '（无）'}\n"
                f"请直接输出重构后的完整代码。"
            )
            raw_output = await self._call_model("executor", exec_prompt, state)
            state.refined_map = {"output": raw_output}

            # L1 门控：本地语法检查（0 Token 消耗）
            all_syntax_pass = True
            for path, code in state.refined_map.items():
                is_ok, msg = self.analyzer.local_static_check(code)
                if not is_ok:
                    state.review_comments = (
                        f"文件 {path} 本地语法校验失败: {msg}。"
                        f"请在内部进行自我修正，无需打扰 Reviewer。"
                    )
                    all_syntax_pass = False
                    break

            if not all_syntax_pass:
                continue  # 打回 Executor 重写，不消耗 Reviewer Token

            # L3 语义审计（Expert Reviewer 终审门控）
            # 变化内容只有重构后代码（原始代码已在缓存前缀中）
            state.status = "verifying_semantic"
            review_prompt = (
                f"角色: Reviewer（语义审计）\n"
                f"基于以上上下文（项目信息、重构目标、架构契约、原始源码），审计以下重构是否正确。\n"
                f"重构后代码:\n{state.refined_map}\n"
                f"如果完美实现目标且无任何隐患，请输出 'LGTM'，否则列出具体驳回原因。"
            )
            state.review_comments = await self._call_model(
                "reviewer", review_prompt, state
            )

            if "LGTM" in state.review_comments:
                state.status = "success"
                self.memory.storage.save_memory(
                    state.task_id,
                    f"成功重构: {state.plan[:80]}",
                    ["success"],
                    True,
                    model_version=self.models.get("executor", "unknown")
                )
                self.safety.commit(f"Nexus 自动重构成功: {state.task_id}")

                # 输出缓存统计
                cache_stats = self.monitor.get_cache_stats()
                if cache_stats['cache_hit_tokens'] > 0:
                    print(
                        f"[Cache] 任务完成。缓存命中率 {cache_stats['overall_hit_rate']:.1f}%，"
                        f"累计节省 ${cache_stats['total_cache_savings']:.6f}"
                    )
                return True

        # 达到迭代上限，任务挂起
        state.status = "human_required"
        print(f"[Orchestrator] 任务挂起：{state.iteration} 次迭代未达成 LGTM。")
        print(f"[Orchestrator] 最后 Reviewer 反馈：{state.review_comments}")
        return False
