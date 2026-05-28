"""
项目地图生成器：结合静态分析和 AI 语义理解，为陌生项目生成结构化的架构导航文档。
"""
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from statistics import median
from litellm import acompletion

from core.project_scanner import collect_python_files, ProjectScanner


@dataclass
class LayerGroup:
    name: str
    files: List[str]
    description: str


class ProjectMapper:
    def __init__(self, repo_path: str, config: dict):
        self.repo_path = repo_path
        self.config = config
        self.planner_model = config['models'].get('planner', 'anthropic/claude-3-5-sonnet-20241022')

    async def generate_map(
        self, target_files: Optional[List[str]] = None
    ) -> Dict:
        """生成项目地图。

        Args:
            target_files: 关注的文件列表。为 None 时扫描全项目。

        Returns:
            {
              "project": str,
              "total_files": int,
              "issues_summary": {"critical": int, "warning": int, "info": int},
              "layers": [{"name": str, "files": [...], "description": str}, ...],
              "architecture_summary": str (AI 输出),
            }
        """
        # 1. 收集文件
        if target_files is None:
            all_files = collect_python_files(self.repo_path)
        else:
            all_files = [f for f in target_files
                         if os.path.isfile(os.path.join(self.repo_path, f))
                         and f.endswith('.py')]

        if not all_files:
            return {
                "project": os.path.basename(os.path.abspath(self.repo_path)),
                "total_files": 0,
                "issues_summary": {"critical": 0, "warning": 0, "info": 0},
                "layers": [],
                "architecture_summary": "未找到 Python 文件。"
            }

        # 2. 本地分析：依赖图和健康检查
        scanner = ProjectScanner(self.repo_path)
        dep_graph = scanner.build_dependency_graph(all_files)
        scan_report = scanner.full_scan()
        issues_summary = {
            "critical": len(scan_report['issues']['critical']),
            "warning": len(scan_report['issues']['warning']),
            "info": len(scan_report['issues']['info']),
        }

        # 3. 层级分组
        layers = self._classify_layers(dep_graph, all_files)

        # 4. 提取接口签名
        from core.code_analyzer import CodeAnalyzer
        analyzer = CodeAnalyzer(self.repo_path)
        signatures = {}
        for f in all_files:
            sig = analyzer.get_signatures(f)
            if sig:
                signatures[f] = sig

        # 5. 组装上下文并调用 Planner
        context = self._assemble_context(layers, dep_graph, signatures, issues_summary, all_files)
        architecture_summary = await self._call_planner_for_map(context)

        return {
            "project": os.path.basename(os.path.abspath(self.repo_path)),
            "total_files": len(all_files),
            "issues_summary": issues_summary,
            "layers": [asdict(layer) for layer in layers],
            "architecture_summary": architecture_summary
        }

    def _classify_layers(
        self, dep_graph: Dict[str, set], all_files: List[str]
    ) -> List[LayerGroup]:
        """按被依赖数(in_degree)和出度数(out_degree)将文件分为 4 层。

        - 入口层: 被依赖多、依赖少 → 类似 controllers/routes
        - 核心逻辑层: 被依赖多、依赖多 → 类似 services/engines
        - 数据/基础设施层: 被依赖少、依赖多 → 类似 models/utils
        - 独立模块: 被依赖少、依赖少 → 类似独立工具
        """
        # 计算 in_degree 和 out_degree
        in_deg: Dict[str, int] = {f: 0 for f in all_files}
        for f, deps in dep_graph.items():
            for d in deps:
                if d in in_deg:
                    in_deg[d] += 1

        out_deg: Dict[str, int] = {f: len(deps) for f, deps in dep_graph.items()}
        for f in all_files:
            if f not in out_deg:
                out_deg[f] = 0

        # 用中位数分割
        in_values = [in_deg[f] for f in all_files]
        out_values = [out_deg[f] for f in all_files]
        med_in = median(in_values) if in_values else 0
        med_out = median(out_values) if out_values else 0

        entry_files, core_files, data_files, leaf_files = [], [], [], []

        for f in all_files:
            hi_in = in_deg[f] > med_in or (med_in == 0 and in_deg[f] == 0)
            hi_out = out_deg[f] > med_out or (med_out == 0 and out_deg[f] == 0)

            # 当所有值都相同时，按文件路径启发式分类
            if med_in == med_out == 0 and in_deg[f] == out_deg[f] == 0:
                leaf_files.append(f)
            elif hi_in and not hi_out:
                entry_files.append(f)
            elif hi_in and hi_out:
                core_files.append(f)
            elif not hi_in and hi_out:
                data_files.append(f)
            else:
                leaf_files.append(f)

        layers = []
        if entry_files:
            layers.append(LayerGroup(
                name="入口层",
                files=sorted(entry_files),
                description="被依赖较多但依赖较少——项目对外的接口层，类似 controllers/routes"
            ))
        if core_files:
            layers.append(LayerGroup(
                name="核心逻辑层",
                files=sorted(core_files),
                description="被依赖多且依赖也多——业务逻辑枢纽，类似 services/engines"
            ))
        if data_files:
            layers.append(LayerGroup(
                name="数据/基础设施层",
                files=sorted(data_files),
                description="被依赖少但依赖多——底层支撑模块，类似 models/db/utils"
            ))
        if leaf_files:
            layers.append(LayerGroup(
                name="独立模块",
                files=sorted(leaf_files),
                description="被依赖少且依赖少——相对独立的工具或叶子模块"
            ))

        return layers

    def _assemble_context(
        self,
        layers: List[LayerGroup],
        dep_graph: Dict[str, set],
        signatures: Dict[str, str],
        issues_summary: Dict[str, int],
        all_files: List[str],
    ) -> str:
        """组装给 Planner 的上下文 Prompt。"""
        total_issues = sum(issues_summary.values())

        # 层级分组
        layer_section = ""
        for layer in layers:
            layer_section += f"\n### {layer.name} ({len(layer.files)} 个文件)\n"
            layer_section += f"{layer.description}\n"
            for f in layer.files:
                layer_section += f"  - {f}\n"

        # 依赖关系（最多展示 30 条，避免 Prompt 过长）
        dep_section = ""
        dep_count = 0
        for f, deps in sorted(dep_graph.items()):
            if not deps:
                continue
            for d in sorted(deps):
                if dep_count >= 30:
                    break
                dep_section += f"  {f} → {d}\n"
                dep_count += 1
            if dep_count >= 30:
                dep_section += "  ... (更多依赖关系已省略)\n"
                break
        if not dep_section:
            dep_section = "  （未检测到项目内部依赖）\n"

        # 接口大纲（每个文件最多 10 行签名）
        sig_section = ""
        for f in sorted(signatures.keys()):
            sig_lines = signatures[f].strip().split('\n')
            if len(sig_lines) > 10:
                sig_lines = sig_lines[:10] + [f"  ... 及更多 {len(sig_lines) - 10} 个定义"]
            sig_section += f"\n**{f}**\n"
            for line in sig_lines:
                sig_section += f"  {line}\n"

        prompt = f"""你是资深软件架构分析师。你需要帮助一个刚接手该项目的新人快速理解项目结构。

以下是项目的客观数据：

## 文件层级分组（本地分析结果）
{layer_section}

## 依赖关系
{dep_section}

## 各模块接口大纲
{sig_section}

## 项目健康概览
总文件: {len(all_files)}, 问题: {total_issues} 个 ({issues_summary['critical']} Critical, {issues_summary['warning']} Warning, {issues_summary['info']} Info)

请按以下结构输出：

### 1. 项目概览
从模块命名和依赖关系推断，这个项目大概是做什么的（2-3 句话）。

### 2. 分层架构说明
每一层的职责和数据流向。

### 3. 模块逐个导读
每个文件的用途（一句话）和关键接口。

### 4. 建议阅读路径
新人应该按什么顺序阅读代码（3-5 步）。"""

        return prompt

    async def _call_planner_for_map(self, context: str) -> str:
        """调用 Planner（AI 模型）生成架构地图叙述。"""
        response = await acompletion(
            model=self.planner_model,
            messages=[{"role": "user", "content": context}],
            temperature=0.3
        )
        return response.choices[0].message.content
