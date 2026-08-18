# ETL-Agent 数据集成平台 产品需求文档（PRD）

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.0 |
| 状态 | 基线（待评审） |
| 依据文档 | 《生产级ETL平台.md》（原始需求）、《需求基线v2.md》（Grilling 决策记录） |
| 冲突仲裁 | 与原始需求冲突时，以《需求基线v2.md》为准 |
| 目标读者 | 产品、架构、前后端开发、测试、安全评审 |

---

## 1. 背景与目标

### 1.1 背景

企业数据集成场景中，ETL 链路的开发、审批、执行与审计长期依赖人工操作，存在效率低、口径不一、权限边界模糊、证据链不完整等问题。大模型能力成熟后，"自然语言生成 ETL 配置"成为可能，但直接将生成结果投入生产存在不可接受的安全风险。本项目以"Agent 智能生成 + 不可绕过的 Harness 安全内核"为核心范式，构建生产级 ETL-Agent 控制面平台。

### 1.2 产品目标

1. 以自然语言需求驱动，经 LangGraph 状态机生成结构化 EtlPlan 与 SeaTunnel HOCON 配置，并完成确定性门禁校验。
2. 以 `prepare → approve → commit` 三阶段协议、四眼职责分离（Maker-Checker）、Ed25519 单次 Capability 令牌、防重放 Guard 与防篡改证据账本，保证任何副作用均经过授权、审批与留痕。
3. 以 SeaTunnel 哑管道 + Doris 受管 SQL 分流的架构，实现 MySQL→Doris 与 CSV→Doris 两条端到端真实链路，含影子表、原子 Swap 发布与错误数据分流。
4. 提供可视化控制台、运行监督、可解释诊断、受管回滚与版本化 Benchmark 评测体系，形成受控安全进化闭环。

### 1.3 成功度量（北极星指标）

- Benchmark 综合健康度（Health Score）> 90 分的版本方可进入生产灰度。
- 端到端演示链路（需求输入 → 生成 → 门禁 → 四眼审批 → Commit → 执行 → Swap 发布）可完整跑通。
- 重放攻击、越权调用、自批、职责混用、账本篡改均可被系统拦截或检测，并可现场演示。

---

## 2. 范围

### 2.1 v1 范围内（In Scope）

- 端到端真实搬运链路仅两条：**MySQL→Doris**、**CSV→Doris**（决策 D1、D8）。
- 以下数据源仅做**连接登记 + 只读元数据安全探查**，不跑搬运：Oracle、PostgreSQL、ClickHouse、REST API（D1）；文件类型 v1 仅 CSV（走 file_assets 通道），Excel、Parquet 等不支持登记与解析（扩展点接口化预留）。
- 文件资产 v1 仅支持 CSV；物理存储走 **MinIO + S3 连接器（S3A 协议）**，统一存 MinIO，不做双写（C3）。
- 多项目隔离模型（按"多项目"实现，无租户级隔离，`projects` 表不含 tenant 字段）。
- 用户认证鉴权、项目成员与角色分配、敏感凭据受管加密存储（SecretProvider / Vault KV v2）。
- LangGraph 编排（意图解析 → 元数据探查 → 生成 → 确定性门禁 → 试运行 → 准备审批），Checkpoint 恢复。
- Harness 安全内核：PDP（P0–P3 风险评级）、Capability Issuer/Verifier、Tool Broker & Replay Guard、Transactional Outbox、Evidence Ledger。
- Celery 异步执行、运行时监督契约、影子表/原子 Swap、错误分流、任务取消与受管回滚。
- 试运行（Dry-Run）与 Benchmark 评测体系、安全进化管理。
- 审计与证据账本校验入口（`GET /api/v1/audit/verify`，D9）。

### 2.2 v1 范围外（Out of Scope）

- Oracle / PostgreSQL / ClickHouse / REST API 的真实搬运执行（仅登记与探查；扩展点必须接口化预留）。
- 租户级隔离、跨项目资源共享。
- Excel / Parquet 等非 CSV 文件资产的登记、解析与搬运。
- 实时/流式（增量 CDC）同步。
- 自定义自由 SQL 执行通道（Worker 仅允许固定模板形态 SQL，见 6.3）。

### 2.3 扩展性约束

所有扩展点（数据源连接器、发布语义、分流 SQL 方言）必须**接口化**，新增连接器或方言不得改动 Harness 内核与 PDP 决策逻辑。

---

## 3. 用户角色与权限

### 3.1 角色定义

| 角色 | 职责 | 关键权限 |
| --- | --- | --- |
| 数据工程师（申请人 / Maker） | 登记数据源、发起元数据探查、输入 NL 需求、调试生成 Pipeline 候选、提交版本与审批申请 | 连接管理、探查、Studio 全部交互、提交 Prepare |
| 数据审批人（Checker 1） | 审查需求描述、Schema 映射、脱敏前后对比、质量规则与 DAG 结构 | 数据维度审批决策 |
| 安全审批人（Checker 2） | 审查资源范围、数据敏感分级、执行预算、Secret 引用与回滚方案；管理 Benchmark 与安全进化 | 安全维度审批决策、Benchmark 触发 |
| 系统操作员 | 审批全部通过后执行 Commit、触发受管执行、监控运行、暂停/取消/回滚、凭据轮转 | Commit、执行运维操作 |
| 审计人员 | 只读查看执行历史、审计事件、证据账本、质量报告与 Benchmark 大盘 | 只读 + 账本校验入口 |

### 3.2 强制职责分离（D3）

- 职责槽互斥按 **Preparation 实例动态判定**：同一 Preparation 单中，同一用户只能占用 Maker / Checker1 / Checker2 中的一个职责槽。
- `project_role_grants` 为**资格表**，仅声明用户具备某角色资格；互斥检查发生在 Prepare/Approve 时，而非资格分配时。
- 跨 Preparation 单，同一审批人可复用。
- 申请人禁止自批（即同一 Preparation 内 Maker/Checker1/Checker2 全量互斥，按上条动态判定）。
- 系统必须在服务端强制拦截违反上述规则的请求，并返回明确错误码与可审计事件。

---

## 4. 系统架构

### 4.1 总体架构：控制面与数据面分离

- **控制面**：Vue 前端控制台 + FastAPI 控制面服务 + LangGraph 编排引擎 + Harness 安全内核 + Celery Worker/Beat + PostgreSQL + Redis。负责治理、审批、授权、调度、监督与审计，**不直连搬运海量业务数据**。
- **数据面**：Apache SeaTunnel（Zeta）负责源到 `{t}__raw` 的全量搬运；Doris 承载 `{t}__raw` / `{t}__shadow` / `{t}__err` / 正式表与 `tmp_dry_run` 库；MinIO 承载 CSV 文件资产。
- **唯一副作用出口**：Tool Broker。任何产生外部副作用的动作（执行、试运行、回滚、清理）必须经 PDP 评级、Capability 验签后由 Tool Broker 放行，无例外。

### 4.2 三层状态隔离

| 层 | 载体 | 说明 |
| --- | --- | --- |
| 对话状态（Conversation State） | 会话存储 | 自然语言交互历史 |
| Agent 状态机（Workflow State） | LangGraph + PostgresSaver checkpoint 表 | 澄清、生成、门禁、修复；**checkpoint 表是恢复唯一真相源**（D10） |
| 底层执行状态（Execution State） | `execution_runs` 等 | ExecutionRun 实例、SeaTunnel 作业 ID、指标 |

- `agent_runs` 仅为业务投影（状态/步数/错误信息），不参与恢复；`thread_id` 绑定 `version_id`（D10）。

### 4.3 技术选型（锁定）

| 层 | 选型 | 备注 |
| --- | --- | --- |
| 前端 | Vue | 控制台 |
| 控制面服务 | FastAPI | RESTful + SSE |
| 编排 | LangGraph + PostgresSaver | Checkpoint 持久化 |
| LLM 接入 | OpenAI 兼容协议 | `BASE_URL` / `API_KEY` / `MODEL_ID` 全部走 `.env`，代码不硬编码模型名（D6） |
| 异步执行 | Celery Worker / Beat | Redis 作 Broker |
| 数据库 | PostgreSQL | 控制面元数据 |
| 缓存/推送 | Redis | pub/sub 回传运行状态 |
| 数据面引擎 | SeaTunnel Zeta | 哑管道 |
| 数仓 | Doris | raw/shadow/err/正式表 + tmp_dry_run 库 |
| 对象存储 | MinIO | S3A 协议供 SeaTunnel 消费（C3） |
| 凭据管理 | SecretProvider / Vault KV v2 | 密文存储 |
| 运行状态推送 | **SSE**（FastAPI 流式接口 + Redis pub/sub） | 替代"轮询或订阅"模糊表述（D7） |

本地 Docker 依赖已就绪：SeaTunnel、Doris、MySQL、PostgreSQL、Redis、MinIO。

---

## 5. 核心架构决策：哑管道 + 受管 SQL 分流（D5）

### 5.1 数据流

```
源 ──SeaTunnel(单 sink)──> {t}__raw ──受管SQL──> {t}__shadow（合格行）──> 原子 Swap ──> 正式表
                                    └──受管SQL──> {t}__err（违规行 + 错误码，留存证据，不参与 Swap）
```

- SeaTunnel 是哑管道：仅单 sink 全量搬入 `{t}__raw`，不做行级质量判断、不做字段脱敏 transform。
- 行级质量分流由 Worker 在搬运完成后向 Doris 提交**受管 SQL** 完成。

### 5.2 硬性约束

1. `QualityContract` 以**结构化 JSON** 存储（字段、算子、阈值、错误码），由编译器按方言**确定性生成 SQL**。禁止手写 SQL 字符串入库；LangGraph 产出的是契约 JSON，SQL 为编译产物，门禁校验编译器输出。
2. Worker 仅允许提交固定模板形态：`INSERT INTO {t}__shadow|__err SELECT ... FROM {t}__raw`，禁止任意自由 SQL。
3. 重跑幂等：每次 run 按 run 隔离（truncate 或 run_id 分区），安全重跑不重复计数。
4. 原子 Swap 仅发生在 `__shadow → 正式表`；`__err` 为留存证据，按项目保留策略清理。
5. 字段脱敏（如邮箱）在分流 SQL 的 SELECT 列表内完成，不进入 SeaTunnel transform。
6. 执行状态机分三个子阶段：`COPYING → SPLITTING → SWAPPING`，指标分阶段采集。

### 5.3 质量契约（QualityContract）

- 声明字段级清洗过滤规则（非空校验、正数校验、邮箱脱敏格式等）。
- 配置错误数据流向与错误码标签（ErrorCode）。
- 分流时将未命中规则的数据写入 `{t}__err`，记录原始值与违规原因。

### 5.4 运行时监督契约（RuntimeSupervisionContract）

- Prepare 阶段冻结预算：最大读取行数、最大写入字节数、最大执行时长。
- 运行中监控：输出放大比、错误拒绝率阈值。
- 越线策略：预警 / 硬中断（Kill Job）/ 隔离告警；监督快照落 `runtime_supervision_snapshots`。

---

## 6. 功能需求

### 6.1 认证与项目管理

- 用户注册/登录、密码散列存储（`users.password_hash`）、会话鉴权。
- 项目 CRUD、项目成员管理、角色分配（`project_memberships`）与角色资格授予（`project_role_grants`）。
- 所有接口按项目边界做权限校验。

### 6.2 数据连接与元数据探查

- 连接管理：数据库（MySQL、PostgreSQL、Oracle、Doris、ClickHouse）与 S3/MinIO、REST API 连接的创建、编辑、连通性测试；`connections.conn_type` 枚举为 `mysql|postgresql|oracle|doris|clickhouse|s3|rest_api`，不再包含 CSV/Excel/JSON/Parquet——CSV 等文件资产统一走 file_assets 通道（D8/C3）。
- 凭据密文保存（SecretProvider / Vault KV v2），全链路无明文泄露；前端只展示掩码。
- 只读元数据安全探查：Schema、字段类型、主键、近似统计、脱敏样本采样，产出 `metadata_profiles`。
- 文件资产：CSV 上传至 MinIO，解析文件头与字段推断；探查/字段推断结果落 `file_assets.schema_json`（不经 `metadata_profiles`）；EtlPlan 引用 CSV 源时使用 `file_asset_id`；文件源必须能作为 SeaTunnel Source 被真实消费（CSV→Doris 链路）。

### 6.3 Pipeline Studio（设计与生成）

- 需求输入：自然语言业务需求 + 源端/目标端 Profile 选择。
- LangGraph 状态机节点：意图解析 → 元数据探查 → 生成 EtlPlan/HOCON → 确定性门禁 → 试运行 → 准备审批。
- 中断与澄清：信息缺失时触发 interrupt 提问；用户经 `POST /api/v1/agent-runs/{run_id}/answers` 提交回答后从 Checkpoint 恢复。
- 有限自动修复：门禁失败时在限定次数内自动修复并复检，超限转人工。
- 方案审查视图：EtlPlan 结构化设计、HOCON（语法高亮）、DAG 拓扑、字段映射 Diff、脱敏前后结构对比。
- 版本冻结：通过门禁后生成不可变 `pipeline_versions`（SHA256 摘要，`is_immutable=true`），制品落 `pipeline_artifacts`。

### 6.4 确定性门禁

- HOCON 语法编译校验（SeaTunnel 配置可编译性）。
- Schema 对齐校验：源/目标字段、类型映射、质量契约编译产物校验。
- 契约编译器输出校验：只允许固定模板形态 SQL。
- 全部通过方可冻结版本；校验结果与失败原因留痕。

### 6.5 试运行（Dry-Run）

- 定义：source 注入采样上限（如 LIMIT 1000），在 Doris 独立 **`tmp_dry_run` 库**建临时表，跑 COPY + SPLIT 两阶段，**跳过 Swap**，产出指标供对比，跑完可清理。
- 治理：空跑为**受管动作**——注册独立 ToolIntent，PDP 评级（预期 P2 中危），签发短时 Capability，**免四眼审批**，全程进证据账本。
- 行数硬判据（C1）：校验双等式——① `input_records == 源端行数`（Dry-Run 时为 min(源端行数, 采样上限 `dry_run_sample_limit`)）；② `output_records + error_records == input_records`（合格行进 shadow、违规行进 err，合计须等于读取行数）。任一不满足，该次任务（含 Benchmark 用例）直接判失败。
- 前置查证：SeaTunnel 原生 check/dry-run 能力列入开发第一天查证项；不支持则按上述自建方案实现，不依赖引擎特性。

### 6.6 Harness 安全内核

- **PDP（Policy Decision Point）**：输入 ToolIntent、资源范围、环境与数据分级，输出 P0–P3 风险决策与审批要求。
- **三阶段协议**：
  1. `Prepare`：推导输入指纹、资源范围、影响范围、数据分级、运行预算与回滚方案，冻结 Preparation 单，无外部副作用。
  2. `Approve`：具名审批人基于冻结事实独立审批，强制四眼原则与职责槽互斥。
  3. `Commit`：服务端重新比对指纹与审批事实，签发 Ed25519 签名短时（5 分钟）单次 Capability 令牌；经 Tool Broker 在同一 PostgreSQL 事务中原子创建 ExecutionRun 与 Outbox 投递命令。
- **Capability Issuer & Verifier**：令牌绑定工具、主体、环境与制品指纹；有效期 5 分钟；Replay Guard 保证仅可消费一次。生产级对抗标准（D2）：正式 nonce 存证表（`capability_tokens`），禁止 Redis SETNX 式简化实现。
- **Transactional Outbox**：本地业务事实与 Worker 任务投递原子落库（`outbox_events`），Worker 消费后回传状态。
- **Evidence Ledger**：关键事件哈希链 + 签名检查点（`audit_events.prev_event_hash` / `event_hash`），可校验、篡改可检测；提供 `GET /api/v1/audit/verify` 重算哈希链并报告断点（D9）。

### 6.7 执行与运行中心

- Celery Worker 消费 Outbox 命令：验签 → 物化 Secret → 调用 SeaTunnel → 分阶段（COPYING/SPLITTING/SWAPPING）采集指标 → 受管 SQL 分流 → 原子 Swap。
- 运行监控：ExecutionRun 列表、实时状态（SSE 推送）、读取/写入/过滤行数、字节数、时长、吞吐量、实时日志。
- 质量与诊断：有效写入统计、`{t}__err` 分流明细、错误码分布、质量契约命中、可解释根因诊断与修复建议。
- 运维操作：任务取消、安全重跑（幂等）、影子表受管回滚与清理（均需 Harness 授权并留痕）。

### 6.8 安全治理与 Benchmark

- Benchmark 大盘：触发自动化评测，展示编译通过率、字段 F1、空跑成功率、安全拦截率、误伤率与延迟对比。
- 安全进化管理：Prompt/策略改进候选与审查报告落 `evolution_candidates` 表，小流量/影子授权（灰度）开关落 `gray_flags` 表，接口见第 10 章；准入策略：综合得分 > 90 分方可进入生产灰度；灰度开关 `enabled=true` 前置：该项目最新成功 benchmark_run 的 health_score > 90，否则报 `E_EVOLUTION_GATE`。

### 6.9 审计

- 审计人员只读视图：执行历史、审计事件、证据账本、质量报告、Benchmark 大盘。
- 账本校验入口（D9）挂到审计页，作为篡改演示的验收入口。

---

## 7. 页面需求

| 页面 | 功能要点 |
| --- | --- |
| 总览工作台 | 连接数、Pipeline 数、待审批门禁概况、运行成功率、核心资源分布 |
| 数据连接与资产 | 连接表单/测试/密文保存；元数据探查结果（Schema、类型、主键、近似统计、脱敏样本）；文件资产上传与字段推断 |
| Pipeline Studio | 需求输入区；Agent 对话与澄清区（状态机步骤、提问、交互表单、有限修复过程）；方案审查区（EtlPlan、HOCON 高亮、DAG、字段映射 Diff、脱敏对比）；版本与审批提交区（冻结摘要、提交审批、调度策略配置） |
| 运行中心 | 准备与审批面板（Preparation 冻结事实、影响范围、回滚方案、审批人列表、决策入口）；执行与监控（SSE 实时状态、指标、日志）；质量与诊断报告；运维操作（取消/重跑/回滚/清理） |
| 安全治理与 Benchmark | Benchmark 大盘（指标对比）；安全进化管理（改进候选、审查报告、灰度开关） |
| 审计页 | 审计事件列表、证据账本查看与哈希链校验结果展示 |

前端模块对应：连接与 Profile 管理、Studio 交互（HOCON 高亮 + DAG 渲染）、不可变版本 Diff、审批流与准备单、运行监控（SSE）、安全治理与评测。

---

## 8. 核心业务流程

### 8.1 端到端需求生成与受管执行

1. 数据工程师配置源（MySQL 或 CSV/MinIO）与目标（Doris）连接，生成受管元数据 Profile。
2. 在 Studio 输入自然语言 ETL 需求。
3. LangGraph 解析需求；信息缺失时中断提问，工程师补充回答后从 Checkpoint 恢复。
4. 生成 EtlPlan 与 HOCON，经语法编译器与确定性门禁校验（必要时有限自动修复）。
5. 冻结不可变 PipelineVersion，计算 SHA256 摘要。
6. （可选）触发 Dry-Run：受管签发 Capability，在 `tmp_dry_run` 库跑 COPY+SPLIT，行数硬校验。
7. 调用 Prepare 生成准备单；PDP 计算风险等级并分配 Checker1/Checker2 职责槽。
8. 数据审批人与安全审批人分别独立审批（四眼原则，互斥校验）。
9. 操作员调用 Commit：服务端校验审批与指纹，签发单次 Capability，同事务写入 ExecutionRun + Outbox。
10. Worker 消费、验签后执行 SeaTunnel 搬运至 `{t}__raw`。
11. Worker 提交受管分流 SQL：合格行入 `{t}__shadow`，违规行入 `{t}__err`；监督引擎持续监控预算。
12. 质量报告通过后 Doris 原子 Swap（`REPLACE TABLE ... swap=true`）发布正式表；关键链路写证据账本。

### 8.2 任务失败诊断与安全回滚

1. 执行异常或监督超限时触发中断，记录失败快照（`runtime_supervision_snapshots`）。
2. 诊断服务提取错误堆栈，生成可解释根因说明与修复建议。
3. 操作员发起回滚：Harness 验证权限后执行受管清理（影子表/临时表回收、状态恢复），全程留痕。

---

## 9. 数据模型

> 含原文档 13 张表 + 基线 D11 补齐 7 张表 = 20 张；`users` 增加 `password_hash`；本次修订新增 `sessions`、`evolution_candidates`、`gray_flags` 3 张，共 23 张。

### 9.1 组织与权限

- `users`：`id`、`username`、`display_name`、`email`、`password_hash`、`status`、`created_at`、`updated_at`
- `projects`：`id`、`name`、`code`、`description`、`created_at`、`updated_at`（无 tenant 字段）
- `project_memberships`：`id`、`project_id`、`user_id`、`role`、`created_at`、`updated_at`
- `project_role_grants`：`id`、`project_id`、`user_id`、`role_slot`、`created_at`、`updated_at`
- `sessions`（新增）：`id`、`token_digest`（CHAR(64) UNIQUE，仅存摘要，令牌本体为不透明随机串）、`user_id`、`expires_at`、`revoked_at`（可空，logout 置位）、`created_at`（INDEX(user_id)）

### 9.2 连接与资产

- `connections`（新增）：`id`、`project_id`、`name`、`conn_type`、`config_json`（密文引用）、`status`、`created_at`、`updated_at`
- `metadata_profiles`（新增）：`id`、`connection_id`、`object_name`、`schema_json`、`stats_json`、`masked_sample_json`、`created_at`
- `file_assets`：`id`、`project_id`、`file_name`、`file_path`（MinIO）、`file_size`、`file_format`、`schema_json`、`created_at`、`updated_at`

### 9.3 Pipeline 与制品

- `pipelines`：`id`、`project_id`、`name`、`code`、`description`、`status`、`created_at`、`updated_at`
- `pipeline_versions`：`id`、`pipeline_id`、`version_number`、`etl_plan_json`、`hocon_text`、`artifact_digest`、`is_immutable`、`created_at`、`updated_at`
- `pipeline_artifacts`：`id`、`version_id`、`artifact_type`、`artifact_digest`、`content`、`created_at`
- `agent_runs`：`id`、`version_id`、`thread_id`、`prompt`、`status`、`step_count`、`error_message`、`created_at`、`updated_at`（业务投影，不参与恢复）

### 9.4 审批与执行

- `preparations`（新增）：`id`、`version_id`、`maker_id`（准备单申请人，Approve 时据此判定禁止自批）、`input_fingerprint`、`resource_scope`、`impact_json`、`data_classification`、`budget_json`、`rollback_plan_json`、`risk_level`、`status`、`expires_at`（准备单 TTL，默认 72 小时，配置项 `preparation_ttl_hours`；Celery Beat 周期任务将过期 pending/approved 单置 `expired` 并写账本，Commit 时检查未过期否则报 `E_PREP_EXPIRED`）、`created_at`、`updated_at`
- `approval_requests`：`id`、`preparation_id`、`version_id`、`required_role`、`status`、`decision`、`approver_id`、`decided_at`、`created_at`、`updated_at`
- `capability_tokens`（新增）：`id`、`token_digest`、`subject_id`、`tool_intent`、`artifact_digest`、`nonce`、`expires_at`、`consumed_at`、`created_at`（nonce 存证，防重放）
- `execution_runs`：`id`、`version_id`、`preparation_id`（可空；`run_kind='execute'` 时必填、`run_kind='dry_run'` 时必须为空，CHECK 约束强制）、`run_kind`（`execute|dry_run`，默认 `execute`）、`capability_token_digest`、`status`、`sub_stage`（可空，仅 running 时取值 `COPYING|SPLITTING|SWAPPING`，Worker 分阶段持久化）、`engine_job_id`、`input_records`、`output_records`、`error_records`、`bytes_processed`、`diagnosis_json`（可空，失败/监督中断时由诊断服务写回，含 root_cause、suggestions，`GET /execution-runs/{id}` 响应以 `diagnosis` 字段透出）、`started_at`、`finished_at`、`created_at`、`updated_at`
- `outbox_events`（新增）：`id`、`aggregate_type`、`aggregate_id`、`event_type`、`payload_json`、`status`、`published_at`、`created_at`
- `runtime_supervision_snapshots`：`id`、`execution_run_id`、`metrics_json`、`decision`、`action_taken`、`created_at`

### 9.5 审计与评测

- `audit_events`：`id`、`project_id`、`actor_id`、`event_type`、`resource_type`、`resource_id`、`payload_digest`、`prev_event_hash`、`event_hash`、`created_at`
- `benchmark_cases`（新增）：`id`、`name`、`nl_requirement`、`expected_schema_json`、`expected_risk_level`、`is_malicious`、`version`、`created_at`
- `benchmark_runs`（新增）：`id`、`suite_version`、`metrics_json`（编译通过率/字段F1/空跑成功率/拦截率/误伤率/健康度）、`status`、`started_at`、`finished_at`、`created_at`
- `evolution_candidates`（新增）：`id`、`project_id`、`kind`（`prompt|policy`）、`title`、`content_json`、`status`（`proposed|approved|rejected`）、`review_report_json`、`created_by`、`created_at`、`updated_at`
- `gray_flags`（新增）：`id`、`project_id`、`flag_key`、`enabled`（默认 false）、`description`、`updated_by`、`created_at`、`updated_at`（UNIQUE(project_id, flag_key)）

---

## 10. API 接口规格

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 系统组件与依赖就绪状态 |
| GET | `/api/v1/projects/{project_id}/connections` | 项目数据源连接列表 |
| POST | `/api/v1/projects/{project_id}/connections` | 创建数据源连接 |
| PUT | `/api/v1/connections/{id}` | 编辑数据源连接 |
| POST | `/api/v1/connections/{id}/tests` | 连通性测试 |
| POST | `/api/v1/connections/{id}/profiles` | 只读元数据探查与脱敏样本采集 |
| POST | `/api/v1/file-assets` | 上传并解析 CSV 文件资产（存 MinIO） |
| POST | `/api/v1/pipelines` | 创建 Pipeline 定义 |
| POST | `/api/v1/pipelines/{pipeline_id}/versions` | 创建新草稿版本（version_number = 当前最大+1；可选 base_version_id 复制既有版本内容作为起点） |
| POST | `/api/v1/versions/{version_id}/generation` | 触发 LangGraph 候选生成 |
| POST | `/api/v1/agent-runs/{run_id}/answers` | 提交澄清回答，恢复状态机 |
| GET | `/api/v1/agent-runs/{run_id}` | 生成状态查询（轮询观察状态机推进，不提供 agent-run SSE，SSE 仅用于 execution-run） |
| GET | `/api/v1/versions/{version_id}/design` | 查询 EtlPlan、HOCON、DAG、质量契约 |
| POST | `/api/v1/versions/{version_id}/freeze` | 版本冻结（生成不可变版本，计算 SHA256 摘要） |
| POST | `/api/v1/versions/{version_id}/dry-run` | 触发受管试运行（受管 ToolIntent，免四眼，进账本） |
| POST | `/api/v1/versions/{version_id}/prepare` | 生成 Preparation 准备单 |
| POST | `/api/v1/approval-requests/{approval_id}/decisions` | 具名审批决策（approve/reject） |
| POST | `/api/v1/preparations/{preparation_id}/commit` | 校验审批与指纹，签发 Capability 并原子提交执行 |
| GET | `/api/v1/execution-runs/{id}` | 执行状态、指标与质量报告 |
| GET | `/api/v1/execution-runs/{id}/stream` | SSE 实时状态推送（D7） |
| POST | `/api/v1/execution-runs/{id}/cancel` | 取消运行中作业 |
| POST | `/api/v1/execution-runs/{id}/rollback` | 受管影子表回滚与清理 |
| POST | `/api/v1/execution-runs/{id}/rerun` | 安全重跑（operator 权限；仅终态 run，否则 `E_RUN_INVALID_STATE`；复用原 Preparation 冻结事实并重算指纹比对，不一致报 `E_FINGERPRINT_MISMATCH`；签发新 Capability，单事务写新 ExecutionRun + Outbox，按 run 隔离保证幂等） |
| POST | `/api/v1/benchmarks/run` | 触发 Benchmark 评测 |
| GET | `/api/v1/evolution/candidates` | 改进候选列表（approver_security） |
| POST | `/api/v1/evolution/candidates` | 提交 Prompt/策略改进候选（approver_security） |
| GET | `/api/v1/evolution/candidates/{id}` | 候选详情与审查报告（approver_security） |
| POST | `/api/v1/evolution/candidates/{id}/reviews` | 候选审查决策（approve/reject，approver_security） |
| GET/PUT | `/api/v1/evolution/gray-flags` | 灰度开关查询/更新（approver_security；enabled=true 前置为该项目最新成功 benchmark_run 的 health_score > 90，否则报 `E_EVOLUTION_GATE`） |
| GET | `/api/v1/audit/verify` | 重算证据账本哈希链并报告断点（D9） |

通用约定：统一错误码结构；审批/执行类写操作全部进证据账本；权限校验在服务端强制；敏感字段响应中一律掩码。

---

## 11. Benchmark 评测体系

- **用例集**：约 30 条版本化 NL 需求（JSONL，`benchmark_cases`），每条带期望 Schema 映射与期望风险等级；必须同时注入恶意/越权用例与合法低危用例（为误伤率提供分母）。
- **指标定义**：
  - 编译通过率 = 通过 SeaTunnel 配置校验的用例数 / 总用例数
  - 字段 F1 = 字段映射相对期望的精确率/召回率 F1（宏平均）
  - 空跑成功率 = tmp_dry_run 试运行成功且行数双等式校验（C1）通过的用例数 / 总用例数
  - 安全拦截率 = 注入恶意用例中被 PDP 正确拦截数 / 恶意用例总数
  - 误伤率 = 合法低危用例被误拦数 / 合法低危用例总数
- **行数一致性为用例级硬门槛**（C1），不进加权公式：按 6.5 双等式口径校验（① `input_records == 源端行数`，Dry-Run 时为 min(源端行数, 采样上限 `dry_run_sample_limit`)；② `output_records + error_records == input_records`），任一不满足则该用例失败（连带拉低空跑成功率）。
- **综合健康度**：

```
Health Score = 0.4 × 编译通过率 + 0.3 × 字段F1 + 0.2 × 空跑成功率
             + 0.1 × max(0, 安全拦截率 − 误伤率)
```

- **准入策略**：综合得分 > 90 分的版本才允许进入生产灰度。

---

## 12. 非功能需求

- **安全**：生产级对抗标准（D2）；证据账本哈希链可校验；重放与篡改可检测、可演示；凭据全链路无明文；Capability 短时单次；副作用唯一出口 Tool Broker。
- **可靠性**：Outbox 保证任务投递不丢；Checkpoint 跨请求恢复；重跑幂等。
- **可观测**：分阶段指标采集、SSE 实时推送、监督快照、结构化审计事件。
- **性能**：运行监控 SSE 推送延迟秒级；Dry-Run 采样上限可配（默认 LIMIT 1000）。
- **可扩展**：连接器/方言/发布语义接口化；LLM Provider 全配置化（D6）。

---

## 13. 验收标准

1. 项目内可配置独立的数据工程师、数据审批人、安全审批人；系统强制拦截申请人自批与同一 Preparation 内职责槽混用。
2. 可接入异构数据库与 CSV 文件源，完成安全元数据探查并展示脱敏样本，全链路无敏感明文泄露。
3. 自然语言需求可触发 LangGraph 生成 EtlPlan 与 HOCON，缺参时正确中断并从 Checkpoint 恢复。
4. 确定性门禁完成语法与 Schema 校验，通过后生成不可变版本 SHA256 摘要。
5. 完整执行 `prepare → approve → commit`：生成准备单、完成四眼审批、签发单次 Capability。
6. Celery Worker 调度 SeaTunnel 完成 MySQL→Doris 与 CSV→Doris 搬运，`{t}__raw` → 受管 SQL 分流 `{t}__shadow`/`{t}__err`。
7. 数据达标后原子 Swap 发布正式表；运行中心可查看实时指标（SSE）与质量报告。
8. 超预算或异常时触发运行时监督与可解释根因诊断，支持受管回滚。
9. 自动化 Benchmark 输出编译通过率、字段 F1、空跑成功率、安全拦截率、误伤率与综合健康度报告。
10. 重放攻击被 Replay Guard 拦截、账本篡改被 `/api/v1/audit/verify` 检出，均可现场演示。

---

## 14. 附录

### 14.1 开发第一天查证项

1. SeaTunnel 容器 `plugins/` 目录：S3 connector 及 hadoop-aws 依赖是否就绪（C3 前置）。
2. SeaTunnel 版本与 Zeta 模式确认；是否有原生 config check / dry-run 能力。
3. Doris 版本确认 `REPLACE TABLE ... swap=true`（或等价原子交换语法）可用。
4. MinIO 与 SeaTunnel 容器间网络连通性（同一 docker network）。

### 14.2 决策索引

| 编号 | 决策 | 本 PRD 章节 |
| --- | --- | --- |
| D1 | v1 仅 MySQL→Doris、CSV→Doris 两条真实链路 | 2.1 |
| D2 | Harness 生产级对抗标准（nonce 存证表等） | 6.6、12 |
| D3 | 职责槽按 Preparation 实例动态互斥 | 3.2 |
| D5 | 哑管道 + 受管 SQL 分流 | 5 |
| D6 | LLM 全配置化（.env） | 4.3 |
| D7 | 运行状态 SSE 推送 | 4.3、10 |
| D8 | 文件资产 v1 仅 CSV，须可被 SeaTunnel 真实消费 | 2.1、6.2 |
| D9 | `/api/v1/audit/verify` 账本校验入口 | 6.6、10 |
| D10 | PostgresSaver checkpoint 为恢复真相源 | 4.2 |
| D11 | 数据表补齐 7 张 + users.password_hash | 9 |
| C1 | 行数一致性为硬判据 | 6.5、11 |
| C3 | CSV 走 MinIO + S3A | 2.1、4.3 |
