#!/usr/bin/env python3
"""
Open-Nexus 入口程序。

输入方式（三种输入，缺一不可）：

1. 重构目标 — 你想让框架对代码做什么？
   -t, --task   "将 UserManager 的邮件发送逻辑拆分为独立服务"

2. 目标文件 — 要重构哪些文件？
   位置参数，支持多个文件

3. 目标项目路径（可选）— 覆盖配置文件中的 git_repo_path
   -p, --project /path/to/your/project

完整示例：
   python main.py -t "将同步 IO 改为 async/await" src/legacy_code.py
   python main.py -t "拆分为策略模式" -p ~/my_project src/engine/base.py src/engine/runner.py
"""
import argparse
import asyncio
import os
import sys
import yaml
from pathlib import Path
from dotenv import load_dotenv

from core.orchestrator import Orchestrator, TaskState
from core.cost_monitor import CostMonitor
from core.safety import SafetyNet
from core.mcp_bridge import MCPBridge
from memory.storage import MemoryStorage
from memory.manager import MemoryManager


def check_env():
    """启动前预检环境变量"""
    required_keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"]
    missing = [key for key in required_keys if not os.getenv(key)]
    if missing:
        print(f"[WARN] 缺失环境变量: {', '.join(missing)}")
        print("[INFO] 框架可以启动，但对应模型的调用将失败。")
        print("[INFO] 请复制 config/.env.example 为 config/.env 并填入真实 Key。")


def load_config(config_path: str = "config/nexus_config.yaml") -> dict:
    config_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), config_path
    )
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def expand_paths(repo_path: str, inputs: list) -> list:
    """
    将混合输入（文件、目录）展开为 .py 文件列表。
    目录会递归扫描，自动跳过 __pycache__/venv/.git 等非代码目录。
    """
    skip_dirs = {'__pycache__', 'venv', '.git', '.venv', 'node_modules',
                 '.tox', '.mypy_cache', '.pytest_cache', 'dist', 'build',
                 '.claude', '.idea', '.vscode'}

    result = []
    for item in inputs:
        full_path = os.path.join(repo_path, item)
        if os.path.isfile(full_path):
            if item.endswith('.py'):
                result.append(item)
            else:
                print(f"[WARN] 跳过非 Python 文件: {item}")
        elif os.path.isdir(full_path):
            found = []
            for root, dirs, files in os.walk(full_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for f in files:
                    if f.endswith('.py') and not f.startswith('test_'):
                        rel = os.path.relpath(os.path.join(root, f), repo_path)
                        found.append(rel)
            result.extend(sorted(found))
            print(f"[Scan] {item}/ 目录下找到 {len(found)} 个 .py 文件")
        else:
            print(f"[WARN] 路径不存在: {item}")

    # 去重（用户可能同时指定了文件和其父目录）
    seen = set()
    unique = []
    for r in result:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    result = unique

    if len(result) > 10:
        print(f"[WARN] 目标文件数 ({len(result)}) 超过建议上限 (10 个)。")
        print(f"[WARN] 建议缩小范围，否则 Token 消耗会很高且模型容易失焦。")
        print(f"[WARN] 继续执行，但请留意成本和结果质量。")

    return result


def parse_args():
    parser = argparse.ArgumentParser(
        description="Open-Nexus：基于异构多 Agent 协同的代码重构框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
三种运行模式：

  【地图模式】先理解项目全貌，知道模块职责和数据流向：
    python main.py --map
    python main.py --map --scope src/engine/ src/api/
    python main.py --map -f json

  【扫描模式】全项目体检，输出问题清单和重构路线图：
    python main.py --scan -p ~/my_project
    python main.py --scan -p ~/my_project -f json

  【重构模式】对指定目标执行重构：
    python main.py -t "将同步IO改为async/await" src/legacy_code.py
    python main.py -t "重构整个模块" src/engine/
    python main.py -t "拆分长函数" -p ~/my_project src/auth.py src/email.py
        """
    )
    parser.add_argument(
        "--scan", "-s",
        action="store_true",
        help="扫描模式：全项目体检，输出问题清单和重构路线图"
    )
    parser.add_argument(
        "--map", "-m",
        action="store_true",
        help="地图模式：生成项目架构导航文档，帮助理解陌生项目"
    )
    parser.add_argument(
        "--scope", nargs="*",
        help="--map 模式下可指定关注范围（文件或目录），默认全项目"
    )
    parser.add_argument(
        "-t", "--task",
        type=str,
        default=None,
        help="重构目标描述。扫描模式下不需要。"
    )
    parser.add_argument(
        "-p", "--project",
        type=str,
        default=None,
        help="目标项目路径（可选）。覆盖 nexus_config.yaml 中的 git_repo_path"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json"],
        default="text",
        help="输出格式（默认 text，对 --scan 和 --map 模式有效）"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="要重构的目标文件或目录。扫描模式下不需要（自动扫描全项目）。"
    )

    args = parser.parse_args()

    # 参数校验
    if args.scan:
        # 扫描模式
        args.files = []  # 忽略 files 参数
    elif args.map:
        # 地图模式：files 参数可选（scope 优先）
        pass
    else:
        # 重构模式：必须有 task 和 files
        if not args.task:
            parser.error("重构模式需要 -t/--task 参数。或使用 --scan/--map。")
        if not args.files:
            parser.error("重构模式需要指定目标文件。或使用 --scan/--map。")

    return args


def run_scan(args):
    """扫描模式：全项目体检，生成重构建议和路线图"""
    from core.project_scanner import ProjectScanner
    import json as json_mod

    base_dir = os.path.dirname(os.path.abspath(__file__))
    if args.project:
        repo_path = args.project
    else:
        cfg = load_config()
        repo_path = cfg['safety'].get('git_repo_path', './')
    if not os.path.isabs(repo_path):
        repo_path = os.path.join(base_dir, repo_path)
    repo_path = os.path.normpath(repo_path)

    print(f"[Scan] 正在对项目进行全局体检...")
    print(f"[Scan] 项目路径: {repo_path}")

    scanner = ProjectScanner(repo_path)
    report = scanner.full_scan()

    if args.format == "json":
        print(json_mod.dumps(report, indent=2, ensure_ascii=False))
        return

    # ---- 文本格式输出 ----
    print(f"\n{'='*60}")
    print(f"  Open-Nexus 项目体检报告")
    print(f"  项目: {report['project']}")
    print(f"  文件总数: {report['total_files']}")
    print(f"{'='*60}")

    issues = report['issues']
    total_issues = sum(len(v) for v in issues.values())
    print(f"\n  发现问题: {total_issues} 个")
    print(f"    Critical: {len(issues['critical'])} 个")
    print(f"    Warning:  {len(issues['warning'])} 个")
    print(f"    Info:     {len(issues['info'])} 个")

    if issues['critical']:
        print(f"\n{'─'*60}")
        print("  [CRITICAL] 严重问题（建议优先处理）")
        print(f"{'─'*60}")
        for item in issues['critical'][:10]:
            loc = item.get('function') or item.get('class', '')
            print(f"  {item['file']}:{item['line']}  {loc}")
            print(f"    → {item['message']}")

    if issues['warning']:
        print(f"\n{'─'*60}")
        print("  [WARNING] 警告")
        print(f"{'─'*60}")
        for item in issues['warning'][:15]:
            loc = item.get('function') or item.get('class', '')
            print(f"  {item['file']}:{item['line']}  {loc}")
            print(f"    → {item['message']}")

    if issues['info']:
        print(f"\n  [INFO] {len(issues['info'])} 个建议（运行 --scan -f json 查看详情）")

    # 重构路线图
    roadmap = report['refactoring_roadmap']
    print(f"\n{'='*60}")
    print(f"  重构路线图")
    print(f"{'='*60}")
    for phase in roadmap:
        print(f"\n  Phase {phase['phase']}: {phase['reason']}")
        print(f"  {'─'*50}")
        for f_info in phase['files']:
            print(f"    [{f_info['severity'].upper()}] {f_info['file']} "
                  f"(被 {f_info['dependents']} 个模块依赖)")

    print(f"\n{'='*60}")
    print(f"  建议下一步:")
    if roadmap and roadmap[0]['files']:
        first = roadmap[0]['files'][0]['file']
        print(f"  python main.py -t \"你的重构目标\" {first}")
    print(f"  或直接指定一个 phase 的多个文件开始重构。")
    print(f"{'='*60}\n")


async def run_map(args):
    """地图模式：生成项目架构导航文档"""
    import json as json_mod
    from core.project_mapper import ProjectMapper

    base_dir = os.path.dirname(os.path.abspath(__file__))
    if args.project:
        repo_path = args.project
    else:
        cfg = load_config()
        repo_path = cfg['safety'].get('git_repo_path', './')
    if not os.path.isabs(repo_path):
        repo_path = os.path.join(base_dir, repo_path)
    repo_path = os.path.normpath(repo_path)

    cfg = load_config()

    # 解析 scope
    scope_files = None
    if args.scope:
        scope_files = expand_paths(repo_path, args.scope)

    print(f"[Map] 正在生成项目架构地图...")
    print(f"[Map] 项目路径: {repo_path}")
    if scope_files:
        print(f"[Map] 关注范围: {len(scope_files)} 个文件")

    mapper = ProjectMapper(repo_path, cfg)
    result = await mapper.generate_map(target_files=scope_files)

    total_issues = sum(result['issues_summary'].values())

    if args.format == "json":
        print(json_mod.dumps(result, indent=2, ensure_ascii=False))
        return

    # ---- 文本格式输出 ----
    print(f"\n{'='*60}")
    print(f"  Open-Nexus 项目地图")
    print(f"  项目: {result['project']}")
    print(f"  文件总数: {result['total_files']}")
    print(f"  问题: {total_issues} 个 "
          f"({result['issues_summary']['critical']} Critical, "
          f"{result['issues_summary']['warning']} Warning, "
          f"{result['issues_summary']['info']} Info)")
    print(f"{'='*60}")

    # 层级概览
    if result['layers']:
        print(f"\n## 分层架构（本地分析）")
        for layer in result['layers']:
            print(f"\n### {layer['name']} ({len(layer['files'])} 个文件)")
            print(f"{layer['description']}")
            for f in layer['files'][:12]:
                print(f"  - {f}")
            if len(layer['files']) > 12:
                print(f"  ... 及更多 {len(layer['files']) - 12} 个文件")

    # AI 架构分析
    print(f"\n{'='*60}")
    print(f"  AI 架构分析")
    print(f"{'='*60}")
    print(result.get('architecture_summary', '(AI 分析未生成)'))

    print(f"\n{'='*60}")
    print(f"  建议下一步:")
    print(f"  python main.py --scan  查看详细体检报告")
    print(f"  python main.py -t \"你的重构目标\" <目标文件>")
    print(f"{'='*60}\n")


async def run_nexus(args):
    # 0. 初始化配置与环境
    load_dotenv()
    check_env()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg = load_config()

    # 解析项目路径：命令行 > 配置文件 > 默认当前目录
    if args.project:
        repo_path = args.project
    else:
        repo_path = cfg['safety'].get('git_repo_path', './')
    if not os.path.isabs(repo_path):
        repo_path = os.path.join(base_dir, repo_path)
    repo_path = os.path.normpath(repo_path)

    # 1. 初始化核心组件
    monitor = CostMonitor()
    safety = SafetyNet(repo_path)
    memory_storage = MemoryStorage(
        db_path=os.path.join(base_dir, cfg['memory']['sqlite_path']),
        decay_lambda_t=cfg['memory']['decay_lambda_t'],
        decay_lambda_v=cfg['memory']['decay_lambda_v'],
        threshold=cfg['memory']['confidence_threshold']
    )
    memory = MemoryManager(memory_storage)

    bridge = MCPBridge(repo_path)
    await bridge.initialize()

    # 2. 展开输入路径（文件/目录 → .py 文件列表），读取代码
    target_files = expand_paths(repo_path, args.files)

    if not target_files:
        print("[ERROR] 没有找到有效的 Python 文件。")
        return

    code_map = {}
    for tf in target_files:
        full_path = os.path.join(repo_path, tf)
        with open(full_path, "r", encoding="utf-8") as f:
            code_map[tf] = f.read()
        print(f"[Load] 已加载: {tf} ({len(code_map[tf])} 字符)")

    # 3. 创建任务状态
    first_input = args.files[0]
    if os.path.isdir(os.path.join(repo_path, first_input)):
        dir_name = os.path.basename(first_input.rstrip('/'))
        task_id = f"nexus_{dir_name}"
    else:
        task_id = f"nexus_{os.path.basename(first_input).replace('.py', '')}"
    state = TaskState(
        task_id=task_id,
        target_files=list(code_map.keys()),
        code_map=code_map,
        task_description=args.task
    )

    # 4. 建立 Git 检查点
    safety.checkpoint(task_id)

    # 5. 启动编排
    print(f"\n{'='*60}")
    print(f"[Nexus] 启动任务: {task_id}")
    print(f"[Nexus] 目标文件: {list(code_map.keys())}")
    print(f"[Nexus] 重构目标: {args.task}")
    print(f"[Nexus] 项目路径: {repo_path}")
    print(f"[Nexus] 预算上限: ${cfg['workflow']['budget_limit']}")
    print(f"{'='*60}\n")

    orch = Orchestrator(cfg, monitor, safety, memory)

    try:
        success = await orch.run_pipeline(state, bridge)
        if success:
            print(f"\n[Nexus] 重构成功!")
            print(f"[Nexus] 总消耗: ${monitor.get_total_cost():.4f}")
        else:
            print(f"\n[Nexus] 重构未通过验证（状态: {state.status}）。")
            print(f"[Nexus] 总消耗: ${monitor.get_total_cost():.4f}")
            if cfg['safety'].get('auto_rollback', False):
                safety.rollback()
                print("[Nexus] 已自动回滚。")
    except Exception as e:
        print(f"\n[PANIC] 框架运行时崩溃: {e}")
        safety.rollback()


if __name__ == "__main__":
    args = parse_args()
    if args.scan:
        run_scan(args)
    elif args.map:
        asyncio.run(run_map(args))
    else:
        asyncio.run(run_nexus(args))
