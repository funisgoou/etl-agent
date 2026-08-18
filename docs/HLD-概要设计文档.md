# ETL-Agent 数据集成平台 概要设计文档（HLD）

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.0 |
| 状态 | 基线（待评审） |
| 依据文档 | 《生产级ETL平台.md》、《需求基线v2.md》、《docs/PRD.md》、《docs/DATA-数据设计文档.md》 |
| 冲突仲裁 | 与原始需求冲突时，以《需求基线v2.md》为准 |
| 目标读者 | 架构、前后端开发、数据面开发、测试、安全评审 |

---

## 1. 概述

### 1.1 设计目标

以"Agent 智能生成 + 不可绕过的 Harness 安全内核"为核心范式，构建生产级 ETL-Agent 控制面平台：

1. 自然语言需求驱动，经 LangGraph 状态机生成结构化 EtlPlan 与 SeaTunnel HOCON 配置，完成确定性门禁校验。
2. 以 `prepare → approve → commit` 三阶段协议、四眼职责分离、Ed25519 单次 Capability 令牌、防重放 Guard 与防篡改证据账本，保证任何副作用均经授权、审批与留痕。
3. 以 SeaTunnel 哑管道 + Doris 受管 SQL 分流架构，实现 MySQL→Doris 与 CSV→Doris 两条端到端真实链路（本地开发环境以 MySQL `biz_demo` 演示库为源端）。
4. 提供可视化控制台、运行监督、可解释诊断、受管回滚与版本化 Benchmark 评测体系。

### 1.2 范围（v1）

- **In Scope**：两条真实搬运链路（MySQL→Doris、CSV→Doris）；Oracle/PostgreSQL/ClickHouse/REST API 仅连接登记 + 只读元数据探查；Harness 安全内核全流程；Dry-Run；Benchmark；审计与账本校验。
- **Out of Scope**：其余数据源真实搬运（接口化预留）、租户级隔离（按多项目实现）、非 CSV 文件解析、实时/CDC 同步、自由 SQL 通道。

---

## 2. 技术选型（锁定）

| 层 | 选型 | 理由 / 备注 |
| --- | --- | --- |
| 前端 | Vue 3 | 控制台；HOCON 高亮、DAG 渲染、SSE 订阅 |
| 控制面服务 | FastAPI | RESTful + SSE；异步 IO 适配 SSE 推送 |
| Agent 编排 | LangGraph + PostgresSaver | 状态机可中断/可恢复；checkpoint 为恢复唯一真相源（D10） |
| LLM 接入 | OpenAI 兼容协议 | `BASE_URL`/`API_KEY`/`MODEL_ID` 全走 `.env`，代码不硬编码模型名（D6） |
| 异步执行 | Celery Worker / Beat | Redis 作 Broker；消费 Outbox 命令 |
| 控制面数据库 | PostgreSQL | 元数据、Outbox、Capability、证据账本、checkpoint |
| 缓存/推送 | Redis | pub/sub 回传运行状态 → SSE（D7）；不承担防重放（D2） |
| 数据面引擎 | Apache SeaTunnel（Zeta） | 哑管道，单 sink 全量搬运 |
| 数仓 | Doris | `{t}__raw`/`__shadow`/`__err`/正式表 + `tmp_dry_run` 库；原子 Swap |
| 业务源库（本地演示） | MySQL | `biz_demo` 演示库 + 确定性种子数据 |
| 对象存储 | MinIO | CSV 资产；S3A 协议供 SeaTunnel 消费（C3） |
| 凭据管理 | SecretProvider / Vault KV v2 | 密文存储，全链路无明文；本地可用 Vault dev mode |
| 签名算法 | Ed25519 | Capability 令牌签发/验签 |
| 部署 | Docker Compose（本地） | SeaTunnel、Doris、MySQL、PostgreSQL、Redis、MinIO 依赖已就绪 |

**选型约束**：所有扩展点（数据源连接器、发布语义、分流 SQL 方言）必须接口化，新增连接器/方言不得改动 Harness 内核与 PDP 决策逻辑。

---

## 3. 总体架构

### 3.1 控制面与数据面分离

```
┌──────────────────────────────── 控制面 ────────────────────────────────┐
│                                                                        │
│  Vue 控制台 ──► FastAPI 控制面服务 ──► LangGraph 编排引擎               │
│       ▲ SSE           │                        │                       │
│       │               ▼                        ▼                       │
│       │         Harness 安全内核          PostgreSQL（元数据/账本/      │
│       │         PDP│Capability│Tool       checkpoint/Outbox）          │
│       │         Broker│Outbox│Ledger              ▲                   │
│       │               │                           │ checkpoint        │
│       │               ▼ 唯一副作用出口             │                   │
│       │         Celery Worker/Beat ──► Redis（Broker/pub/sub）        │
│       │               │                                                │
└───────┼───────────────┼────────────────────────────────────────────────┘
        │               ▼ 验签后执行
┌───────┼───────────── 数据面 ───────────────────────────────────────────┐
│       │         SeaTunnel（Zeta，哑管道）                                │
│       │           ▲ source              │ sink                          │
│       └───────────┼─────────────────────▼──────────────                 │
│              MySQL biz_demo / MinIO(CSV) ──► Doris                       │
│              （源端）                    {t}__raw ─受管SQL─► {t}__shadow │
│                                                   └─受管SQL─► {t}__err   │
│                                            __shadow ─Swap─► 正式表       │
└─────────────────────────────────────────────────────────────────────────┘
```

- **控制面**（Vue + FastAPI + LangGraph + Harness + Celery + PostgreSQL + Redis）：治理、审批、授权、调度、监督与审计，**不直连搬运海量业务数据**。
- **数据面**：SeaTunnel 负责源到 `{t}__raw` 的全量搬运；Worker 向 Doris 提交受管 SQL 完成行级质量分流；Doris 原子 Swap 发布；MinIO 承载 CSV 资产。
- **唯一副作用出口：Tool Broker**。任何产生外部副作用的动作（执行、Dry-Run、回滚、清理）必须经 PDP 评级、Capability 验签后由 Tool Broker 放行，无例外。

### 3.2 三层状态隔离

| 层 | 载体 | 说明 |
| --- | --- | --- |
| 对话状态（Conversation State） | 会话存储 | 自然语言交互历史 |
| Agent 状态机（Workflow State） | LangGraph + PostgresSaver checkpoint 表 | 澄清、生成、门禁、修复；**checkpoint 是恢复唯一真相源**（D10） |
| 底层执行状态（Execution State） | `execution_runs` 等表 | ExecutionRun 实例、SeaTunnel 作业 ID、指标 |

`agent_runs` 仅为业务投影（状态/步数/错误），不参与恢复；`thread_id` 绑定 `version_id`。

### 3.3 核心数据流（哑管道 + 受管 SQL 分流，D5）

```
源 ──SeaTunnel(单 sink)──> {t}__raw ──受管SQL──> {t}__shadow（合格行）──> 原子 Swap ──> 正式表
                                    └──受管SQL──> {t}__err（违规行 + 错误码，留存证据，不参与 Swap）
```

硬性约束：

1. QualityContract 以结构化 JSON 存储，编译器按方言确定性生成 SQL；禁止手写 SQL 入库。
2. Worker 仅允许固定模板形态：`INSERT INTO {t}__shadow|__err SELECT ... FROM {t}__raw`。
3. 重跑幂等：按 run 隔离（truncate 或 run_id 分区）。
4. 原子 Swap 仅发生在 `__shadow → 正式表`；`__err` 留存证据。
5. 字段脱敏在分流 SQL 的 SELECT 列表内完成，不进 SeaTunnel transform。
6. 执行状态机子阶段：`COPYING → SPLITTING → SWAPPING`，指标分阶段采集。

---

## 4. 模块设计

### 4.1 前端模块（Vue 控制台）

| 模块 | 职责 | 对应页面 |
| --- | --- | --- |
| 总览工作台 | 连接数、Pipeline 数、待审批概况、运行成功率 | 总览 |
| 连接与 Profile 管理 | 连接表单/测试/掩码展示、探查结果与脱敏样本渲染、CSV 上传 | 数据连接与资产 |
| Studio 交互 | 需求输入、Agent 对话与澄清、HOCON 高亮、DAG 渲染、字段映射 Diff、脱敏对比、版本冻结与提交 | Pipeline Studio |
| 审批流与准备单 | Preparation 冻结事实、影响范围、回滚方案、具名审批卡片 | 运行中心 |
| 运行监控 | ExecutionRun 列表、SSE 实时状态、分阶段指标、日志、质量与诊断报告、运维操作（取消/重跑/回滚/清理） | 运行中心 |
| 安全治理与评测 | Benchmark 大盘、改进候选、审查报告、灰度开关 | 安全治理与 Benchmark |
| 审计 | 审计事件列表、证据账本查看、哈希链校验结果 | 审计页 |

### 4.2 控制面服务（FastAPI）

按域划分的路由/服务模块：

| 模块 | 职责 |
| --- | --- |
| 认证与项目 | 注册/登录（密码散列）、会话鉴权、项目 CRUD、成员与角色资格管理；所有接口按项目边界鉴权 |
| 连接与资产 | 连接 CRUD、连通性测试、只读元数据探查（产出 `metadata_profiles`）、CSV 上传与字段推断 |
| 生成与门禁 | 触发 LangGraph 生成、澄清回答恢复、设计查询（EtlPlan/HOCON/DAG/质量契约）、确定性门禁、版本冻结 |
| Harness 接口 | Prepare / Approve / Commit 三阶段入口、Dry-Run（受管 ToolIntent，免四眼进账本） |
| 执行与运行 | ExecutionRun 查询、SSE 推送、取消/重跑/回滚入口（全部经 Harness 授权） |
| 评测与审计 | Benchmark 触发与大盘、`/api/v1/audit/verify` 账本校验 |

### 4.3 LangGraph 编排引擎

状态机节点：**意图解析 → 元数据探查 → 生成 EtlPlan/HOCON → 确定性门禁 → 试运行 → 准备审批**。

- **中断与澄清**：信息缺失时 interrupt 提问；`POST /api/v1/agent-runs/{run_id}/answers` 提交回答后从 checkpoint 恢复。
- **有限自动修复**：门禁失败时在限定次数内自动修复并复检，超限转人工。
- **持久化**：PostgresSaver checkpoint 表为恢复唯一真相源（D10），跨请求/跨进程可恢复。

### 4.4 Harness 安全内核（不可绕过）

| 组件 | 职责 |
| --- | --- |
| PDP（Policy Decision Point） | 输入 ToolIntent、资源范围、环境与数据分级，输出 P0–P3 风险决策与审批要求 |
| Capability Issuer & Verifier | Ed25519 签发/验签短时（5 分钟）单次令牌；令牌绑定工具、主体、环境与制品指纹；nonce 存证表防重放（D2） |
| Tool Broker & Replay Guard | 所有副作用的唯一出口；验签 + 单事务原子置位 `consumed_at`，拦截未授权调用与重放 |
| Transactional Outbox | Commit 时本地业务事实（ExecutionRun）与 Worker 任务投递在同一 PostgreSQL 事务原子落库 |
| Evidence Ledger | 关键事件哈希链（`prev_event_hash`/`event_hash`）+ 只追加约束；`/api/v1/audit/verify` 重算校验 |

### 4.5 Celery Worker 执行服务

消费 Outbox 命令 → 验签 → 物化 Secret（SecretProvider）→ 调用 SeaTunnel → 分阶段（COPYING/SPLITTING/SWAPPING）采集指标 → 提交受管分流 SQL → 原子 Swap → 经 Redis pub/sub 回传状态。

### 4.6 运行时监督引擎

依据 RuntimeSupervisionContract：

- Prepare 阶段冻结预算：最大读取行数、最大写入字节数、最大执行时长。
- 运行中监控：输出放大比、错误拒绝率阈值。
- 越线策略：预警 / 硬中断（Kill Job）/ 隔离告警；快照落 `runtime_supervision_snapshots`。

### 4.7 诊断服务

执行异常或监督超限时：提取错误堆栈 → 生成可解释根因说明与修复建议 → 供运行中心展示。

---

## 5. 核心流程

### 5.1 端到端需求生成与受管执行（主链路）

```
工程师          FastAPI         LangGraph        Harness           Worker          数据面
  │ NL需求        │                │                │                │               │
  ├──────────────►│ 触发生成       │                │                │               │
  │               ├───────────────►│ 意图解析→探查   │                │               │
  │  ◄──interrupt 澄清提问（缺参时） │                │                │               │
  ├──────────────►│ answers 恢复──►│ 生成EtlPlan/HOCON                │               │
  │               │                │ 确定性门禁(有限修复)               │               │
  │               │  冻结不可变版本(SHA256) ◄─────────┘                │               │
  │ (可选)Dry-Run ─────────────────►│ PDP评级→签Capability ───────────►│ tmp_dry_run  │
  │               │  Prepare ─────►│ 推导指纹/范围/预算/回滚，冻结准备单  │               │
  │  Checker1/2 ─►│  Approve      │ 四眼审批(职责槽互斥校验)            │               │
  │  操作员 Commit ───────────────►│ 重比对指纹→签单次Capability        │               │
  │               │                │ 同事务写 ExecutionRun+Outbox ────►│ 消费/验签     │
  │               │                │                │                ├──────────────►│ SeaTunnel 搬运→{t}__raw
  │               │                │                │                ├──────────────►│ 受管SQL分流 shadow/err
  │               │  ◄──SSE 实时状态/指标（Redis pub/sub 回传）─────────┤               │
  │               │                │                │                ├──────────────►│ 原子 Swap 发布
  │               │  关键链路写证据账本 ◄─────────────┴────────────────┘               │
```

步骤细化（对应 PRD 8.1）：

1. 工程师配置源（MySQL `biz_demo` 或 CSV/MinIO）与目标（Doris）连接，生成受管元数据 Profile。
2. Studio 输入自然语言需求。
3. LangGraph 解析；缺参时中断提问，补充回答后从 checkpoint 恢复。
4. 生成 EtlPlan 与 HOCON，经语法编译器与确定性门禁校验（必要时有限自动修复）。
5. 冻结不可变 PipelineVersion，计算 SHA256 摘要。
6. （可选）Dry-Run：受管签发 Capability，`tmp_dry_run` 库跑 COPY+SPLIT，行数硬校验（C1）。
7. Prepare 生成准备单；PDP 计算风险等级并分配 Checker1/Checker2 职责槽。
8. 数据审批人与安全审批人独立审批（四眼原则，互斥校验，禁止自批）。
9. 操作员 Commit：服务端校验审批与指纹，签发单次 Capability，同事务写 ExecutionRun + Outbox。
10. Worker 消费、验签后执行 SeaTunnel 搬运至 `{t}__raw`。
11. Worker 提交受管分流 SQL：合格行入 `__shadow`，违规行入 `__err`；监督引擎持续监控预算。
12. 质量报告通过后 Doris 原子 Swap 发布正式表；关键链路写证据账本。

### 5.2 Dry-Run 流程

注册独立 ToolIntent → PDP 评级（预期 P2 中危）→ 签发短时 Capability（**免四眼审批**）→ Tool Broker 放行 → source 注入采样上限（默认 LIMIT 1000）→ `tmp_dry_run` 库建临时表跑 COPY+SPLIT（跳过 Swap）→ 行数硬判据校验 → 产出指标供对比 → 可清理。全程进证据账本。

### 5.3 任务失败诊断与安全回滚流程

1. 执行异常或监督超限触发中断，记录失败快照（`runtime_supervision_snapshots`）。
2. 诊断服务提取错误堆栈，生成可解释根因说明与修复建议。
3. 操作员发起回滚：注册 ToolIntent → PDP 评级 → 签发 Capability → Tool Broker 放行受管清理（影子表/临时表回收、状态恢复）→ 全程留痕。

### 5.4 Benchmark 评测流程

触发评测 → 逐条执行版本化用例（约 30 条，含恶意/越权与合法低危用例）→ 采集编译通过率、字段 F1、空跑成功率（含 C1 行数硬判据）、安全拦截率、误伤率 → 计算综合健康度（`0.4×编译通过率 + 0.3×字段F1 + 0.2×空跑成功率 + 0.1×max(0, 拦截率−误伤率)`）→ 落 `benchmark_runs` → > 90 分方可进入生产灰度。

### 5.5 审计校验流程

审计人员调用 `GET /api/v1/audit/verify` → 按 `id` 升序重算项目内哈希链 → 报告第一个断点及期望/实际哈希 → 审计页展示（篡改演示验收入口，D9）。

---

## 6. 安全设计要点

| 威胁 | 机制 |
| --- | --- |
| 未授权副作用 | Tool Broker 唯一出口 + PDP 评级 + Capability 验签，无例外 |
| 越权 / 自批 / 职责混用 | 服务端强制职责槽互斥（按 Preparation 实例动态判定，D3）；`project_role_grants` 仅资格表 |
| 重放攻击 | Ed25519 单次令牌（5 分钟）+ nonce 存证表 + 单事务原子消费（D2，禁止 Redis SETNX 替代） |
| 审批后制品被替换 | Prepare 冻结指纹 + Commit 重比对 + 不可变版本（`is_immutable` 触发器强制） |
| 账本篡改 | 只追加约束 + 哈希链 + `/api/v1/audit/verify` 可检测可演示 |
| 凭据泄露 | Vault KV v2 密文引用、Worker 执行时物化、全链路无明文、响应掩码 |
| 任意 SQL 注入数据面 | Worker 仅固定模板形态受管 SQL；契约 JSON 编译产物，门禁校验 |
| 任务投递丢失 | Transactional Outbox 与业务事实同事务落库，失败重试 |
| 生成结果直接投产 | 确定性门禁 + 不可变版本 + 四眼审批 + Benchmark > 90 分准入 |

---

## 7. 接口概要

RESTful 接口详见 PRD 第 10 章（API 接口规格），本文不重复定义。关键接口分组：

- 健康与连接：`/health`、`/api/v1/connections*`、`/api/v1/file-assets`
- 生成与设计：`/api/v1/versions/{id}/generation`、`/agent-runs/{id}/answers`、`/versions/{id}/design`、`/versions/{id}/dry-run`
- 三阶段：`/versions/{id}/prepare`、`/approval-requests/{id}/decisions`、`/preparations/{id}/commit`
- 执行与运维：`/execution-runs/{id}`、`/execution-runs/{id}/stream`（SSE）、`/cancel`、`/rollback`
- 评测与审计：`/benchmarks/run`、`/audit/verify`

通用约定：统一错误码结构；审批/执行类写操作全部进证据账本；权限校验服务端强制；敏感字段响应掩码。

---

## 8. 非功能设计

| 维度 | 设计 |
| --- | --- |
| 可靠性 | Outbox 保证投递不丢；checkpoint 跨请求恢复；按 run 隔离保证重跑幂等 |
| 可观测 | 分阶段指标采集、SSE 秒级推送、监督快照、结构化审计事件 |
| 性能 | SSE 推送延迟秒级；Dry-Run 采样上限可配（默认 LIMIT 1000） |
| 可扩展 | 连接器/方言/发布语义接口化；LLM Provider 全配置化（D6） |
| 安全 | 见第 6 章；生产级对抗标准（D2） |

---

## 9. 部署架构（本地开发环境）

```
docker network（同一网络）
├── frontend        Vue 构建产物（Nginx 或 dev server）
├── control-plane   FastAPI + LangGraph（uvicorn）
├── worker          Celery Worker / Beat
├── postgres        控制面元数据 + checkpoint + Outbox + 账本
├── redis           Broker + pub/sub
├── mysql           业务演示库 biz_demo（确定性种子数据）
├── doris           FE + BE（raw/shadow/err/正式表 + tmp_dry_run）
├── seatunnel       Zeta 引擎（plugins 含 S3 connector + hadoop-aws）
├── minio           CSV 资产（bucket: etl-assets）
└── vault           KV v2（本地 dev mode）
```

**开发第一天查证项**（PRD 附录 14.1）：

1. SeaTunnel 容器 `plugins/` 目录：S3 connector 及 hadoop-aws 依赖是否就绪（C3 前置）。
2. SeaTunnel 版本与 Zeta 模式确认；是否有原生 config check / dry-run 能力（无则按自建 Dry-Run 方案）。
3. Doris 版本确认 `REPLACE TABLE ... swap=true`（或等价原子交换语法）可用。
4. MinIO 与 SeaTunnel 容器间网络连通性（同一 docker network）。

---

## 10. 与需求决策的对照

| 决策 | 落点 |
| --- | --- |
| D1/D8 链路范围 | 范围 1.2；连接器接口化预留 |
| D2 生产级对抗 | Harness 内核 4.4；nonce 存证表 |
| D3 职责槽动态互斥 | 安全设计 6；Approve 时服务端判定 |
| D5 哑管道 + 受管 SQL | 核心数据流 3.3；Worker 4.5 |
| D6 LLM 全配置化 | 技术选型 2 |
| D7 SSE 推送 | 控制面 4.2 / Worker 4.5 / Redis pub/sub |
| D9 账本校验 | 流程 5.5 |
| D10 checkpoint 真相源 | 三层状态 3.2；编排引擎 4.3 |
| C1 行数硬判据 | 流程 5.2 / 5.4 |
| C3 MinIO + S3A | 部署 9；数据面 3.1 |
