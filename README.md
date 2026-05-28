# Open-Nexus

> **定位：面向老旧 Python 项目的安全自动化重构框架。**
>
> 通过异构多 Agent 协同（Claude/DeepSeek/GPT-4o 分别承担 Planner/Executor/Reviewer）和"地图→扫描→重构"三步流程，让开发者安全、可控地完成遗留代码的现代化改造。不靠蛮力生成，靠工程纪律。

基于"**大模型是核心，多 Agent 是流程，外置存储是脊椎**"三层架构的代码重构框架。

## 核心思路

- **大模型提供智商** — Claude/DeepSeek/GPT-4o 各自承担 Planner/Executor/Reviewer，异构对抗降低幻觉
- **多 Agent 提供工程纪律** — L1语法→L2静态→L3测试→L4语义审计 四级门控，不通过就地回滚
- **外置存储提供上下文感知** — 所有 Agent 共享同一份结构化上下文，按需检索，按需更新
- **固定前缀缓存** — 所有阶段 prompt 共享可缓存前缀，DeepSeek Executor 缓存命中率 60-80%，成本降低 70%+

## 三种运行模式

框架提供**地图模式**、**扫描模式**和**重构模式**，对应大型项目重构的三个阶段：

### 模式 1：地图模式（先理解全貌）

接手陌生项目的第一步——生成**项目架构导航文档**，快速理解模块职责、数据流向和核心接口。**消耗 1 次 Planner API 调用（约 $0.02-$0.05）。**

```bash
# 全项目地图
python main.py --map

# 指定关注范围
python main.py --map --scope src/engine/ src/api/

# JSON 格式输出
python main.py --map -f json
```

输出内容：
- **项目概览**：从模块命名和依赖关系推断项目用途
- **分层架构说明**：文件按 in/out degree 自动分为 4 层
  - 入口层（被依赖多、依赖少）— 类似 controllers/routes
  - 核心逻辑层（被依赖多、依赖多）— 类似 services/engines
  - 数据/基础设施层（被依赖少、依赖多）— 类似 models/utils
  - 独立模块（被依赖少、依赖少）— 类似独立工具
- **模块逐个导读**：每个文件的用途和关键接口
- **建议阅读路径**：新人应按什么顺序阅读代码（3-5 步）

地图输出示例：
```
============================================================
  Open-Nexus 项目地图
  项目: legacy-backend
  文件总数: 42
============================================================

## 项目概览
这是一个 FastAPI 后端服务，包含用户认证、任务引擎和数据库持久化三层。

## 分层架构
### 入口层 (3 文件)
  src/api/routes.py       — HTTP 路由定义
  src/cli.py              — 命令行管理入口

### 核心逻辑层 (12 文件)
  src/engine/runner.py    — 任务调度核心（⚠ 145行长函数需拆分）
  src/auth/manager.py     — 用户认证与权限校验
...

## 建议阅读路径
Step 1: src/api/routes.py    — 从 HTTP 入口理解项目对外提供什么
Step 2: src/engine/runner.py — 理解核心业务调度逻辑
Step 3: src/db/connection.py — 理解数据如何存储
...
============================================================
```

> **与地图模式的区别**：地图告诉你"项目是怎么组织的"（模块职责、数据流、阅读顺序），扫描告诉你"哪里有坑"（长函数、多参数等机械问题）。两者互补。

### 模式 2：扫描模式（再做体检）

理解了项目全貌之后，做全局体检，输出问题清单、严重程度分级和重构路线图。**不消耗任何 API Token。**

```bash
# 文本报告
python main.py --scan -p ~/my_project

# JSON 格式（方便喂给其他工具或做 CI 集成）
python main.py --scan -p ~/my_project -f json
```

输出内容：
- 全项目文件统计
- 问题分级清单（Critical / Warning / Info）
  - **Critical**：长函数（>80行）、大类（>12个方法）
  - **Warning**：参数过多、嵌套过深、IO与业务逻辑混杂、中等长度函数
  - **Info**：缺少类型注解、命名建议
- 依赖关系概览
- **重构路线图**（分 3 个 Phase，按依赖关系和严重程度排序）
  - Phase 1：底层依赖 + 严重问题，最优先修复
  - Phase 2：中等优先级
  - Phase 3：上层入口/叶子模块，最后处理

扫描 open_nexus 自身的结果示例：
```
发现问题: 29 个
  Critical: 2 个  (orchestrator.py:run_pipeline 123行, main.py:run_nexus 86行)
  Warning:  23 个  (嵌套深、IO混杂、参数多等)
  Info:     4 个

重构路线图:
  Phase 1: core/orchestrator.py, main.py           ← 严重问题，先修
  Phase 2: memory/storage.py, core/project_scanner.py
  Phase 3: core/code_analyzer.py, ...
```

### 模式 3：重构模式（精准动刀）

对扫描报告建议的目标文件执行多 Agent 协同重构。

```bash
python main.py -t "重构目标描述" <目标文件或目录>
```

| 输入 | 指定方式 | 是否必填 | 示例 |
|------|---------|---------|------|
| **重构目标** | `-t` / `--task` | **必填** | `-t "将同步IO改为async/await"` |
| **目标文件/目录** | 位置参数 | **必填** | `src/legacy_code.py` 或 `src/engine/` |
| **项目路径** | `-p` / `--project` | 可选 | `-p ~/my_project` |

目录会自动展开为 `.py` 文件（跳过 `__pycache__`/`venv`/`.git` 等），支持文件+目录混合。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp config/.env.example config/.env
# 编辑 config/.env，至少填入两家模型的 Key
# ANTHROPIC_API_KEY=sk-ant-xxx
# OPENAI_API_KEY=sk-xxx
# DEEPSEEK_API_KEY=sk-xxx

# 3. 先生成地图，理解项目架构
python main.py --map -p ~/your_project

# 4. 再扫描体检，看清问题全貌
python main.py --scan -p ~/your_project

# 5. 根据路线图选择目标，再重构
python main.py -t "拆分 UserManager，提取邮件发送为独立服务" \
               -p ~/your_project \
               src/user_manager.py
```

## 标准运行流程（重构模式）

一次重构任务分五个阶段：

```
┌──────────────────────────────────────────────────────────────┐
│  Phase 0: PROJECT MAP（项目地图——大型项目第一步）               │
│                                                              │
│  python main.py --map -p ~/project                            │
│                                                              │
│  ProjectMapper 生成架构导航文档：                               │
│  ─ 本地分析：层级分组（入口/核心/数据/独立 4 层）                │
│  ─ 提取所有文件的函数/类签名                                    │
│  ─ 调用 Planner（Claude）生成语义理解                          │
│  ─ 输出项目概览、模块导读、建议阅读路径                          │
│                                                              │
│  产出：架构地图 → 知道项目怎么组织的                              │
│  消耗：~1 次 Planner 调用（约 $0.02-$0.05）                    │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Phase 0.5: PROJECT SCAN（项目扫描——看清问题全貌）             │
│                                                              │
│  python main.py --scan -p ~/project                           │
│                                                              │
│  ProjectScanner 扫描全项目：                                   │
│  ─ 统计所有 .py 文件，分析每个函数/类                           │
│  ─ 检测长函数、大类、参数过多、嵌套过深、IO逻辑混杂               │
│  ─ 构建项目级依赖图                                           │
│  ─ 输出分级问题清单 + 3-Phase 重构路线图                        │
│                                                              │
│  产出：体检报告 → 看清楚问题全貌                                 │
└──────────────────────┬───────────────────────────────────────┘
                       │
         用户根据地图 + 路线图选择目标文件
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Phase 1: RESEARCH（依赖分析）                                 │
│                                                              │
│  CodeAnalyzer 用 AST 扫描目标文件的：                           │
│  ─ 谁引用了它？（inbound 调用方）                                │
│  ─ 它引用了谁？（outbound 依赖）                                │
│  ─ 邻居的函数签名是什么？（只读大纲，不读逻辑，省 Token）           │
│                                                              │
│  Planner（Claude）拿到分析结果 + 历史记忆，                       │
│  生成一份《临时架构契约》——命名规范、异常风格、调用模式。            │
│                                                              │
│  产出：架构契约 + 影响范围报告                                   │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Phase 2: PLANNING（战术规划）                                  │
│                                                              │
│  Planner 基于架构契约制定重构方案。                              │
│  对于多文件任务，规划明确哪些文件改什么接口，保证协同一致。           │
│                                                              │
│  产出：重构计划                                                │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Phase 3: TEST GENERATION（测试生成）                           │
│                                                              │
│  检查目标文件是否已有测试。如果没有：                              │
│  ─ 自动为每个公开函数和类方法生成 pytest 骨架                     │
│  ─ 仅覆盖 happy path，边界情况需人工补充                          │
│  ─ 生成的测试写入临时目录，不污染主分支                            │
│                                                              │
│  警告：没有测试时 L3 物理验证形同虚设，必须先生成                     │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Phase 4: EXECUTION & HYBRID VALIDATION（执行与多级验证）       │
│                                                              │
│  ┌─────────────────┐                                         │
│  │ Executor 生成代码 │──DeepSeek（便宜、快、代码能力强）           │
│  └────────┬────────┘                                         │
│           ▼                                                  │
│  ┌─────────────────┐                                         │
│  │ L1: 语法检查     │──ast.parse()，拦截语法错误，0 Token        │
│  └────────┬────────┘                                         │
│           ▼（通过）                                            │
│  ┌─────────────────┐                                         │
│  │ L2: 静态分析     │──mypy/pylint（如已配置），0 Token          │
│  └────────┬────────┘                                         │
│           ▼（通过）                                            │
│  ┌─────────────────┐                                         │
│  │ L3: 单元测试     │──pytest（包括自动生成的测试桩），0 Token     │
│  └────────┬────────┘                                         │
│           ▼（通过）                                            │
│  ┌─────────────────┐                                         │
│  │ L4: 异构语义审计  │──GPT-4o（与 Executor 不同厂商），         │
│  │                 │   拿架构契约逐条比对，输出 LGTM 或驳回原因    │
│  └────────┬────────┘                                         │
│           ▼                                                  │
│     ┌─ LGTM? ──否──→ 打回 Executor 重写（最多 3 次）           │
│     │                                                        │
│    是                                                        │
│     │                                                        │
│     ▼                                                        │
│  Phase 5: COMMIT（持久化 + 记忆沉淀）                           │
│  ─ git commit 变更                                           │
│  ─ 将成功经验写入记忆库（带置信度分数）                            │
└──────────────────────────────────────────────────────────────┘
```

### 熔断与回滚

- **预算熔断**：累计 Token 费用超过 `budget_limit`（默认 $2.0），任务挂起
- **迭代熔断**：Executor-Reviewer 循环超过 3 次仍未 LGTM，触发 `human_required`
- **安全回滚**：任务开始前建 Git 检查点，失败后 `git reset --hard`

## 运行示例

```bash
# 第一步：扫描项目，看清全貌
python main.py --scan -p ~/my_project

# 第二步：根据路线图选择 Phase 1 的目标文件，执行重构
python main.py -t "拆分 run_pipeline 长函数为 _research + _plan + _execute" \
               core/orchestrator.py

# 重构整个目录
python main.py -t "将同步 IO 全部改为 async/await" \
               -p ~/my_project \
               src/engine/
```

## 配置文件说明

`config/nexus_config.yaml`：

| 配置项 | 说明 | 默认值 |
|-------|------|--------|
| `models.planner` | 架构规划模型 | `anthropic/claude-3-5-sonnet-20241022` |
| `models.executor` | 代码生成模型 | `deepseek/deepseek-chat` |
| `models.reviewer` | 语义审计模型 | `openai/gpt-4o` |
| `workflow.max_iterations` | 最大重试次数 | `3` |
| `workflow.budget_limit` | 单次任务预算上限 (USD) | `2.0` |
| `memory.decay_lambda_t` | 时间衰减系数 | `0.05`（待实验校准） |
| `memory.decay_lambda_v` | 模型版本衰减系数 | `0.3`（待实验校准） |
| `memory.confidence_threshold` | 记忆最低置信度 | `0.4`（待实验校准） |
| `safety.git_repo_path` | 目标项目路径 | `./` |
| `safety.auto_rollback` | 失败时自动回滚 | `true` |

## 模块架构

```
open_nexus/
├── config/
│   ├── nexus_config.yaml      # 模型路由、预算、衰减参数
│   └── .env                   # API Keys（不提交到 Git）
├── core/
│   ├── orchestrator.py        # 编排引擎：管节奏、管熔断、管回滚
│   ├── project_scanner.py     # 项目扫描器：全项目体检 + 重构路线图
│   ├── project_mapper.py      # 项目地图生成器：架构导航文档 + AI 语义分析
│   ├── code_analyzer.py       # 代码分析器：AST 依赖分析 + 签名提取 + 语法检查
│   ├── test_generator.py      # 测试生成器：自动生成 happy-path 测试桩
│   ├── cost_monitor.py        # 成本监控：实时 Token 计费
│   ├── safety.py              # 安全围栏：Git 检查点 + 回滚 + 临时文件
│   ├── freshness.py           # 上下文新鲜度检测
│   ├── retrieval.py           # 检索调度器：意图 → 上下文包
│   └── mcp_bridge.py          # MCP 本地桥接器
├── memory/
│   ├── storage.py             # 记忆存储：双因子衰减 + SQLite 持久化
│   └── manager.py             # 记忆管理器：语义检索与经验唤醒
├── main.py                    # 入口（--scan 扫描模式 / -t 重构模式）
└── requirements.txt
```

## 已知局限
1. 异构审计降低但不消除错误——GPT-4o 和 Claude 在异步并发等领域盲区重合
2. 自动生成的测试仅覆盖 happy path，边界情况需人工补充
3. 记忆衰减参数是初始值，需通过实验校准
4. 代码分析器不处理 `importlib` 动态导入和条件导入
5. 扫描模式的"IO与业务逻辑混杂"检测基于关键词匹配，存在误报可能
6. 地图模式的层级分类基于依赖图的中位数分割，小型项目（<10 文件）分层可能不准确
