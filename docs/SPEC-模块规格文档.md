# ETL-Agent 数据集成平台 模块规格文档（SPEC）

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.0 |
| 状态 | 基线（待评审） |
| 依据文档 | 《需求基线v2.md》、《docs/PRD.md》、《docs/HLD-概要设计文档.md》、《docs/DATA-数据设计文档.md》 |
| 冲突仲裁 | 与上游文档冲突时，以《需求基线v2.md》为准 |
| 目标读者 | 前后端开发、测试 |

> 本文档定义各模块的职责、公开接口（函数/方法签名级）、依赖关系、关键不变式与错误码，作为编码与 Code Review 的依据。字段级定义见 DATA 文档，接口路径见 PRD 第 10 章，本文不重复。

---

## 1. 工程结构

```
etl-agent/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 装配
│   │   ├── core/                   # 公共基础设施（第 2 章）
│   │   │   ├── config.py  db.py  security.py  errors.py  masking.py
│   │   │   ├── llm_client.py  secret_provider.py  redis_client.py  minio_client.py
│   │   ├── domain/                 # 领域模块（第 3 章）
│   │   │   ├── auth/  projects/  connections/  profiling/  file_assets/
│   │   │   ├── pipelines/  studio/  preparations/  executions/
│   │   │   ├── benchmark/  audit/  evolution/
│   │   ├── harness/                # 安全内核（第 4 章，不可绕过）
│   │   │   ├── pdp.py  capability.py  broker.py  outbox.py  ledger.py  intents.py
│   │   ├── agent/                  # LangGraph 编排（第 5 章）
│   │   │   ├── graph.py  state.py  nodes/  gate/  repair.py
│   │   ├── compiler/               # 契约编译器（第 6 章）
│   │   │   ├── quality_contract.py  dialects/  templates/
│   │   └── worker/                 # Celery 任务（第 7 章）
│   │       ├── celery_app.py  tasks/  supervision.py  diagnostics.py  seatunnel_client.py
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/  stores/  views/  components/  sse/
└── deploy/                         # docker-compose、初始化脚本、造数脚本
```

**分层规则**：`domain/*` 的写操作凡产生外部副作用，禁止直接触达数据面，必须构造 ToolIntent 走 `harness.broker`；`harness/*` 不 import `domain/*`（内核可独立演进）；`compiler/*` 为纯函数，无 IO。

---

## 2. 公共基础设施模块（core）

### 2.1 config

- 职责：集中读取 `.env`，全项目唯一配置入口。
- 接口：
  ```python
  class Settings(BaseSettings):
      database_url: str
      redis_url: str
      minio_endpoint: str; minio_access_key: str; minio_secret_key: str; minio_bucket: str = "etl-assets"
      vault_addr: str; vault_token: str; vault_mount: str = "secret"
      llm_base_url: str; llm_api_key: str; llm_model_id: str   # D6：代码不硬编码模型名
      seatunnel_api_url: str
      doris_mysql_url: str            # Worker 提交受管 SQL 用（MySQL 协议）
      capability_private_key: str     # Ed25519 PEM；本地开发走 .env，生产环境应经 KMS/Vault 注入
      capability_public_key: str
      capability_ttl_seconds: int = 300
      dry_run_sample_limit: int = 1000
      gate_max_repair_rounds: int = 3
      preparation_ttl_hours: int = 72  # 准备单 TTL，过期由周期任务置 expired
  def get_settings() -> Settings      # lru_cache 单例
  ```

### 2.2 db

- 职责：SQLAlchemy 2.x 异步引擎与会话；声明式 Base；事务工具。
- 接口：
  ```python
  async def get_session() -> AsyncIterator[AsyncSession]     # FastAPI Depends
  @asynccontextmanager
  async def atomic() -> AsyncIterator[AsyncSession]          # 显式事务（Commit 三阶段/Outbox 用）
  ```

### 2.3 security

- 职责：密码散列、会话令牌签发与校验、项目边界鉴权依赖。
- 接口：
  ```python
  def hash_password(plain: str) -> str
  def verify_password(plain: str, hashed: str) -> bool
  async def current_user(request) -> User                    # 依赖注入
  async def require_project_role(project_id: int, *roles: str)  # 依赖工厂：项目边界强制校验
  ```
- 会话校验：鉴权中间件查 `sessions` 表，`token_digest` 未吊销（`revoked_at IS NULL`）且未过期方放行；logout 置 `revoked_at` 吊销会话。

### 2.4 errors

- 职责：统一错误码结构 `{"code": "E_XXXX", "message": str, "details": dict?}`；全局异常处理器。
- 错误码总表见第 9 章。

### 2.5 masking

- 职责：敏感字段掩码（邮箱、电话、密钥），供 API 响应与样本展示。
- 接口：`def mask_value(value: str, kind: Literal["email","phone","secret"]) -> str`

### 2.6 llm_client

- 职责：OpenAI 兼容协议客户端封装（chat/structured output）；重试与超时；模型名仅来自 Settings（D6）。
- 接口：
  ```python
  class LLMClient:
      async def chat(self, messages: list[dict], *, response_schema: type[BaseModel] | None = None) -> str | BaseModel
  ```

### 2.7 secret_provider

- 职责：Vault KV v2 读写；连接配置中的敏感字段以 `vault://{mount}/{path}#{key}` 引用形式入库。
- 接口：
  ```python
  class SecretProvider(Protocol):
      async def put(self, path: str, data: dict) -> None
      async def get(self, ref: str) -> dict        # ref = vault://...
  def redact_config(config: dict) -> dict           # 入库前：明文→vault 引用
  def resolve_config(config: dict) -> dict          # Worker 执行时物化（仅此一处允许还原）
  ```
- 不变式：`redact_config` 之外的任何代码路径不得将明文凭据写库；`resolve_config` 仅允许 Worker 执行路径调用。

### 2.8 redis_client / minio_client

- `redis_client`：连接池单例；`publish_status(run_id: int, event: dict)`。
- `minio_client`：`put_file / get_file / presigned_url`，bucket 默认 `etl-assets`。

---

## 3. 领域模块（domain）

> 每模块内部固定分四层：`router.py`（HTTP）、`service.py`（业务逻辑）、`repository.py`（SQLAlchemy）、`schemas.py`（Pydantic）。以下仅列 service 层公开接口与关键不变式。

### 3.1 auth

- 职责：注册、登录、会话。
- 接口：
  ```python
  async def register(username: str, password: str, display_name: str, email: str | None) -> User
  async def login(username: str, password: str) -> SessionToken   # 生成不透明随机令牌并写 sessions，库内仅存 token_digest
  async def logout(actor) -> None                                  # 吊销会话：sessions.revoked_at = now()
  ```
- 不变式：密码仅存散列；登录失败不区分"用户不存在/密码错误"；令牌本体为不透明随机串，库内只存摘要。

### 3.2 projects

- 职责：项目 CRUD、成员管理、角色资格授予。
- 接口：
  ```python
  async def create_project(actor, name, code, description) -> Project
  async def add_member(actor, project_id, user_id, role) -> Membership
  async def grant_role_slot(actor, project_id, user_id, role_slot) -> RoleGrant
  ```
- 不变式（D3）：`grant_role_slot` **不做**职责槽互斥检查——资格与判定分离；互斥仅发生在 Prepare/Approve（见 3.8）。

### 3.3 connections

- 职责：连接 CRUD、连通性测试；连接器扩展点注册表。
- 接口：
  ```python
  class Connector(Protocol):                       # 扩展点：新增数据源实现本接口，不动内核
      conn_type: str
      async def test(self, config: dict) -> TestResult
      async def list_objects(self, config: dict) -> list[str]
      async def profile(self, config: dict, object_name: str, sample_size: int) -> ProfileResult
  CONNECTOR_REGISTRY: dict[str, Connector]         # 注册表键不含 csv/excel/json/parquet：CSV 等文件资产统一走 file_assets 通道；mysql/doris 为可搬运实现，oracle/pg/... 为探查-only 实现
  async def create_connection(actor, project_id, name, conn_type, config) -> Connection
  async def test_connection(actor, connection_id) -> TestResult
  ```
- 不变式：入库前必经 `secret_provider.redact_config`；响应必经掩码；`conn_type` 校验注册表存在性；EtlPlan 引用 CSV 源时用 `file_asset_id`（file_assets 通道，D8/C3），CSV 探查/字段推断结果落 `file_assets.schema_json`，不经 metadata_profiles。
- v1 行为约束：仅 `mysql`、`doris` 连接器允许进入搬运链路（D1）；CSV 源经 file_assets 通道以 `file_asset_id` 引用进入；其余连接器 `profile()` 可用、不可被 EtlPlan 引用为执行源/目标（门禁拦截）。

### 3.4 profiling（元数据探查）

- 职责：只读安全探查，产出 `metadata_profiles`。
- 接口：
  ```python
  async def run_profile(actor, connection_id, object_name, sample_size: int = 100) -> MetadataProfile
  ```
- 关键逻辑：调用连接器 `profile()` → 样本经 `masking` 脱敏 → 落库；**只读**（SELECT/LIMIT/信息Schema，禁止写操作与 DDL）。
- 不变式：`masked_sample_json` 不得含未脱敏敏感值（入库前扫描校验，命中即拒绝并告警）。

### 3.5 file_assets

- 职责：CSV 上传 MinIO、文件头解析与字段推断。
- 接口：
  ```python
  async def upload_csv(actor, project_id, file: UploadFile) -> FileAsset
  async def infer_schema(file_path: str) -> dict    # 表头 + 类型推断（抽样前 N KB）
  ```
- 不变式：`file_format` 仅允许 `csv`（D8）；对象键按 `projects/{pid}/file_assets/{id}/{name}`；统一存 MinIO 不双写（C3）。

### 3.6 pipelines

- 职责：Pipeline 定义 CRUD、版本冻结与制品管理。
- 接口：
  ```python
  async def create_pipeline(actor, project_id, name, code, description) -> Pipeline
  async def create_version(actor, pipeline_id, base_version_id: int | None = None) -> PipelineVersion
  async def freeze_version(actor, version_id) -> PipelineVersion   # 门禁通过后才能调用
  async def get_design(actor, version_id) -> DesignView            # EtlPlan/HOCON/DAG/质量契约/Diff
  ```
- 不变式：
  - `create_version`：创建 `version_number = 当前最大 + 1` 的草稿版本；`base_version_id` 存在时复制该版本内容作为起点。
  - `freeze_version` 前置条件：门禁全部通过（`gate_report` 无 blocking 项）；冻结时计算 SHA256 → `artifact_digest`，置 `is_immutable=true`。
  - 冻结后版本及制品只读（DB 触发器兜底，见 DATA 5.3）。

### 3.7 studio（生成编排入口）

- 职责：触发/恢复 LangGraph 生成，暴露 AgentRun 业务投影。
- 接口：
  ```python
  async def start_generation(actor, version_id, prompt) -> AgentRun      # 建 thread_id=uuid，绑定 version_id
  async def submit_answer(actor, run_id, answer: dict) -> AgentRun       # 写入 interrupt 恢复值，继续状态机
  async def get_run(actor, run_id) -> AgentRunView                       # 状态/步数/错误（业务投影）
  ```
- 不变式：恢复状态一律从 PostgresSaver checkpoint 读取（D10）；`agent_runs` 只写投影，不作为恢复依据。

### 3.8 preparations（三阶段协议入口）

- 职责：Prepare / Approve / Commit 编排，调用 Harness 内核。
- 接口：
  ```python
  async def prepare(actor, version_id) -> Preparation
  async def decide(actor, approval_id, decision: Literal["approve","reject"], comment: str | None) -> ApprovalRequest
  async def commit(actor, preparation_id) -> ExecutionRun
  ```
- **Prepare** 逻辑：
  1. 推导 `input_fingerprint = SHA256(canonical(version 制品 + 连接引用 + 目标表))`；
  2. 推导资源范围、影响范围、数据分级、运行预算（RuntimeSupervisionContract）、回滚方案；
  3. 构造 ToolIntent(`execute_pipeline`) → `pdp.evaluate()` 得 `risk_level` 与审批要求；
  4. 记录 `maker_id = actor`、`expires_at = now() + preparation_ttl_hours`；冻结准备单，创建 `approval_requests`（checker1/checker2 各一）；写证据账本。
- **Approve** 不变式（D3，服务端强制）：
  - `approver` 须持有对应 `role_slot` 资格；
  - 同一 Preparation 内：approver ≠ Maker（禁止自批，依据 `preparations.maker_id` 判定）；checker1.approver ≠ checker2.approver；
  - 违反 → `E_FORBIDDEN_DUTY` 并写审计事件。
- **Commit** 逻辑：
  1. 校验准备单状态 = approved（两张审批单均 approve）；
  2. 检查 `expires_at` 未过期，否则 `E_PREP_EXPIRED`；
  3. **重算指纹**与准备单比对，不一致 → `E_FINGERPRINT_MISMATCH`；
  4. `capability.issue(tool_intent, subject, artifact_digest)` 签发单次令牌；
  5. **单事务**：`preparations.status→committed` + 插 `execution_runs` + 插 `outbox_events`；
  6. 写证据账本。
- 过期机制：Celery Beat 周期任务将过期的 pending/approved 准备单置 `expired` 并写证据账本。

### 3.9 executions（运行中心）

- 职责：执行查询、SSE 推送、运维操作入口。
- 接口：
  ```python
  async def get_run(actor, run_id) -> ExecutionRunView          # 状态/指标/质量报告
  async def stream_run(actor, run_id) -> EventSourceResponse    # SSE：订阅 redis channel exec_run:{id}（D7）
  async def cancel(actor, run_id) -> None
  async def rollback(actor, run_id) -> None
  async def rerun(actor, run_id) -> ExecutionRun                # 安全重跑（R6，语义见下）
  async def dry_run(actor, version_id) -> ExecutionRun          # 创建的 ExecutionRun run_kind='dry_run'、preparation_id 为空
  ```
- **rerun** 语义（权限 operator）：
  - 仅允许对终态 run（succeeded/failed/cancelled/rolled_back）发起，否则 `E_RUN_INVALID_STATE`；
  - 复用原 Preparation 冻结事实，服务端重算指纹比对，不一致 → `E_FINGERPRINT_MISMATCH`，须重新 Prepare；
  - 签发新 Capability，**单事务**写新 ExecutionRun + Outbox；幂等由按 run 隔离保证。
- 不变式：`cancel/rollback/cleanup/dry_run/rerun` 一律构造对应 ToolIntent 走 Tool Broker（Dry-Run 免四眼但进账本）；本模块不直接触达 SeaTunnel/Doris。

### 3.10 benchmark

- 职责：用例集管理、评测执行、大盘。
- 接口：
  ```python
  async def import_cases(actor, jsonl_path, version) -> int
  async def run_benchmark(actor, suite_version) -> BenchmarkRun
  ```
- 关键逻辑：逐用例跑"生成 → 门禁 → Dry-Run → PDP"管线并采集指标；C1 行数硬判据校验双等式——① `input_records == 源端行数`（Dry-Run 时为 min(源端行数, 采样上限 `dry_run_sample_limit`)）；② `output_records + error_records == input_records`（合格行进 shadow、违规行进 err，合计须等于读取行数）——任一不满足即判该用例失败；按 PRD 公式计算健康度落 `benchmark_runs.metrics_json`。

### 3.11 audit

- 职责：审计只读视图与账本校验。
- 接口：
  ```python
  async def list_events(actor, project_id, filters) -> Page[AuditEvent]
  async def verify_ledger(actor, project_id) -> VerifyReport   # {ok, broken_at, expected_hash, actual_hash}
  ```
- `verify_ledger` 逻辑：按 `id` 升序重算 `SHA256(prev_event_hash ‖ canonical(event))`，与库内 `event_hash` 逐一比对，报告首个断点（D9）。

### 3.12 evolution（安全进化管理）

- 职责：改进候选（prompt/policy）与审查报告管理、灰度开关；数据落 `evolution_candidates` / `gray_flags` 表。
- 接口：
  ```python
  async def propose_candidate(actor, project_id, kind, title, content) -> EvolutionCandidate
  async def review_candidate(actor, candidate_id, decision, report) -> EvolutionCandidate
  async def set_gray_flag(actor, project_id, flag_key, enabled) -> GrayFlag
  ```
- 不变式：操作权限 `approver_security`；灰度开关 `enabled=true` 前置：该项目最新成功 benchmark_run 的 `health_score > 90`，否则 `E_EVOLUTION_GATE`。

---

## 4. Harness 安全内核（harness）

> 内核无 HTTP 入口；只暴露 Python API 给 domain 层。任何外部副作用必须经由 `broker.execute()`。

### 4.1 intents

- 职责：ToolIntent 定义与注册表（扩展点）。
  ```python
  @dataclass(frozen=True)
  class ToolIntent:
      tool: Literal["execute_pipeline","dry_run","rollback","cleanup","cancel"]
      version_id: int
      resource_scope: dict
      data_classification: str
      params: dict
  ```

### 4.2 pdp

- 职责：风险评级与审批策略。
- 接口：
  ```python
  def evaluate(intent: ToolIntent, env: str) -> PdpDecision
  # PdpDecision = {risk_level: P0|P1|P2|P3, requires: ["checker1","checker2"] | [], auto_allowed: bool}
  ```
- 规则基线：DDL/删除/跨项目 → P0；敏感分级 `secret/confidential` 的执行 → P1；正式执行（internal 以下）→ P1/P2；`dry_run` → P2（免四眼）；`rollback/cleanup` → P2。
- 不变式：规则表数据驱动；新增连接器/方言不得改动本模块（扩展性约束）。

### 4.3 capability

- 职责：Ed25519 令牌签发与验签 + nonce 存证。
- 接口：
  ```python
  async def issue(intent: ToolIntent, subject_id: int, artifact_digest: str) -> str   # 返回明文令牌（仅此一次）
  async def verify_and_consume(token: str, expected_tool: str) -> CapabilityClaims    # 单事务内消费
  ```
- 不变式（D2）：
  - 明文令牌不落库；库内仅存 `token_digest = SHA256(token)` 与 `nonce`（双 UNIQUE）；
  - 消费 = `UPDATE capability_tokens SET consumed_at=now() WHERE token_digest=? AND consumed_at IS NULL AND expires_at>now()`，影响行数 0 → `E_TOKEN_REPLAYED` / `E_TOKEN_EXPIRED`；
  - 校验绑定：`tool`、`subject_id`、`artifact_digest` 任一不符 → 拒绝。

### 4.4 broker（Tool Broker & Replay Guard）

- 职责：**唯一副作用出口**。
- 接口：
  ```python
  async def execute(intent: ToolIntent, token: str, handler: Callable[[CapabilityClaims], Awaitable[T]]) -> T
  ```
- 逻辑：验签消费 → 校验 intent 与 claims 一致 → 调用 handler（Worker 任务封装）→ 写证据账本（成功/失败均写）。
- 不变式：代码库内除本模块外，任何位置不得直接调用 `seatunnel_client`、Doris 写操作、MinIO 删除；CI 静态检查强制。

### 4.5 outbox

- 职责：事务性事件写入与后台中继。
  ```python
  async def emit(session, aggregate_type, aggregate_id, event_type, payload) -> None   # 与业务写同事务
  async def relay_loop() -> None        # 轮询 pending → 投递 Celery → published；失败指数退避重试
  ```

### 4.6 ledger（Evidence Ledger）

- 职责：证据账本追加与校验。
  ```python
  async def append(session, project_id, actor_id, event_type, resource_type, resource_id, payload: dict) -> AuditEvent
  def compute_hash(prev_hash: str, event: dict) -> str
  ```
- 不变式：同项目内串行追加（锁尾事件行）；`prev_event_hash` 取前一事件 `event_hash`，创世为 64 个 `0`；payload 以规范 JSON（键排序、无空白）参与哈希。

---

## 5. LangGraph 编排（agent）

### 5.1 state（Workflow State Schema）

```python
class StudioState(TypedDict):
    version_id: int
    thread_id: str
    prompt: str
    intent: IntentSpec | None            # 意图解析产物（源/目标/表/映射/质量要求）
    clarifications: list[QA]             # 澄清问答历史
    source_profile: dict | None
    target_profile: dict | None
    etl_plan: EtlPlan | None             # 含 QualityContract 契约 JSON
    hocon: str | None
    gate_report: GateReport | None
    repair_round: int                    # 有限自动修复计数
    status: Literal["running","waiting_input","gated","failed","succeeded"]
    error: str | None
```

### 5.2 节点规格（nodes/）

| 节点 | 输入→输出 | 要点 |
| --- | --- | --- |
| `parse_intent` | prompt → intent | LLM 结构化输出；缺参字段标记 `missing` |
| `clarify` | intent.missing → interrupt | 生成提问表单，`interrupt()` 挂起；回答写入 `clarifications` 后回到 `parse_intent` 复检 |
| `probe_metadata` | intent → profiles | 只读探查（复用 domain.profiling） |
| `generate` | intent+profiles → etl_plan, hocon | LLM 产出契约 JSON 与 HOCON；HOCON 由模板渲染 + LLM 填充参数 |
| `gate` | etl_plan, hocon → gate_report | 确定性门禁（5.3），纯函数 |
| `repair` | gate_report → 修正 prompt | `repair_round < gate_max_repair_rounds` 时回 `generate`；超限 → `failed` 转人工 |
| `finalize` | → status=succeeded | 写 `agent_runs` 投影 |

### 5.3 确定性门禁（gate/）

纯函数，四类校验，输出 `GateReport{passed, findings: [{rule, level: blocking|warning, message}]}`：

1. `hocon_compile`：SeaTunnel 配置语法/可编译性校验；
2. `schema_alignment`：源/目标字段、类型映射与 profile 对齐；
3. `contract_compile`：QualityContract JSON 经编译器产出，校验 SQL 形态白名单（仅 `INSERT INTO {t}__shadow|__err SELECT ... FROM {t}__raw`）；
4. `scope_guard`：EtlPlan 引用的连接器/表属于允许搬运范围（D1：mysql/csv → doris，其中 csv 经 file_assets 通道以 `file_asset_id` 引用）。

不变式：门禁不调用 LLM；同一输入输出恒定（可复现、可审计）。

### 5.4 持久化

- `PostgresSaver` 挂 PostgreSQL；`thread_id` = `agent_runs.thread_id`；恢复唯一真相源（D10）。

---

## 6. 契约编译器（compiler）

- 职责：QualityContract 契约 JSON → 目标方言 SQL，**确定性、纯函数**。
- 接口：
  ```python
  class SqlDialect(Protocol):                        # 扩展点：新方言实现本接口
      def compile_split(self, contract: QualityContract, table: str) -> SplitSql
  # SplitSql = {shadow_sql: str, err_sql: str}，形态固定：
  #   INSERT INTO {t}__shadow SELECT <masked_cols> FROM {t}__raw WHERE <all_rules_pass>
  #   INSERT INTO {t}__err    SELECT *, <run_meta> FROM {t}__raw WHERE NOT (<all_rules_pass>)
  def compile(contract_json: dict, dialect: str = "doris") -> SplitSql
  ```
- 算子基线（对应 PRD 5.3）：`not_null` / `positive` / `email_format`；脱敏算子作用于 SELECT 列表（如 `mask_email`），不进入 SeaTunnel transform。
- 不变式：输出 SQL 仅含白名单形态与内联函数；禁止拼接任何外部字符串（表名/列名来自 profile 白名单校验）。

---

## 7. Worker 模块（worker）

### 7.1 任务（tasks/）

| 任务 | 触发 | 逻辑 |
| --- | --- | --- |
| `execute_pipeline` | Outbox relay | 验签（broker 已完成）→ `resolve_config` 物化 Secret → `seatunnel_client.submit(hocon)` → 轮询作业 → 分阶段执行（7.2）→ 回传状态 |
| `dry_run` | 受管 ToolIntent | 同上，但 hocon source 注入 `LIMIT {dry_run_sample_limit}`、目标 `tmp_dry_run` 库、跳过 SWAP |
| `rollback` / `cleanup` | 运维入口 | 影子表/临时表回收、状态恢复（Doris 侧受管清理） |
| `cancel_run` | 运维入口 | SeaTunnel kill job |

### 7.2 执行状态机（子阶段）

```
COPYING   SeaTunnel 搬运 → {t}__raw（run 隔离：先 truncate/分区清理）
SPLITTING 提交编译产物 SplitSql → __shadow / __err；采集 input/output/error_records
SWAPPING  行数硬校验（C1）+ 质量报告通过 → REPLACE TABLE ... swap=true
```

- 每阶段切换持久化到 `execution_runs.sub_stage`（仅 running 时取值 COPYING|SPLITTING|SWAPPING）；每阶段开始/结束写 `execution_runs` 指标并经 `publish_status` 推送；失败写 `runtime_supervision_snapshots` 并触发诊断，失败/监督中断时诊断结果写回 `execution_runs.diagnosis_json`。

### 7.3 supervision（运行时监督）

- 接口：`async def supervise(run_id, budget: Budget) -> None`（随任务启动的后台协程/周期任务）
- 逻辑：周期采集引擎指标 → 计算输出放大比、错误拒绝率 → 对照 `budget_json` → 决策 `ok/warning/breach` → 动作 `alert/kill_job/isolate` → 快照落库 + SSE 推送。

### 7.4 diagnostics

- 接口：`def diagnose(run_id, error_ctx: dict) -> Diagnosis`（根因分类 + 修复建议，可调用 LLM 做解释，但分类规则确定性优先）。
- `diagnose()` 结果由 Worker 写回 `execution_runs.diagnosis_json`（含 root_cause、suggestions），经 GET /execution-runs/{id} 响应的 `diagnosis` 字段透出。

### 7.5 seatunnel_client

- 接口：`submit(hocon) -> job_id`、`status(job_id)`、`kill(job_id)`；仅供 worker 任务经 broker handler 使用。

---

## 8. 前端模块（frontend）

| 模块 | 关键组件 | 依赖 API | 要点 |
| --- | --- | --- | --- |
| api 层 | `api/client.ts`（拦截器：错误码归一、401 跳转） | 全部 | 敏感字段按掩码渲染，不做前端解密 |
| 连接与资产 | `views/Connections.vue`、`ProfilePanel.vue`、`FileUpload.vue` | connections/profiles/file-assets | 探查样本分页；类型推断结果可编辑确认 |
| Studio | `views/Studio.vue`、`ChatPanel.vue`、`HoconViewer.vue`、`DagGraph.vue`、`MappingDiff.vue` | generation/answers/design | 状态机步骤时间线；interrupt 表单由后端 schema 驱动渲染 |
| 版本与审批 | `VersionList.vue`、`PreparationCard.vue`、`ApprovalActions.vue` | prepare/decisions | 冻结事实只读展示；审批按钮按角色显隐（服务端仍强制） |
| 运行中心 | `RunList.vue`、`RunMonitor.vue`、`QualityReport.vue` | execution-runs/stream | **SSE**：`sse/useRunStream.ts` 封装 EventSource，断线自动重连；子阶段进度条 |
| 治理与评测 | `BenchmarkDashboard.vue` | benchmarks | 指标对比图 + 健康度公式展示 |
| 审计 | `AuditList.vue`、`LedgerVerify.vue` | audit/verify | 校验结果断点高亮 |

状态管理：Pinia；路由按项目边界 `/:projectId/...` 组织。

---

## 9. 错误码规范

| 码段 | 含义 | 示例 |
| --- | --- | --- |
| `E_AUTH_*` | 认证鉴权 | `E_AUTH_INVALID_CREDENTIALS`、`E_FORBIDDEN_PROJECT`、`E_FORBIDDEN_DUTY`（职责槽冲突/自批） |
| `E_VALID_*` | 参数校验 | `E_VALID_CONN_TYPE`、`E_VALID_FILE_FORMAT` |
| `E_GATE_*` | 门禁 | `E_GATE_HOCON`、`E_GATE_SCHEMA`、`E_GATE_SQL_FORM` |
| `E_FINGERPRINT_MISMATCH` | Commit 指纹不一致 | — |
| `E_TOKEN_*` | Capability | `E_TOKEN_INVALID`、`E_TOKEN_EXPIRED`、`E_TOKEN_REPLAYED`、`E_TOKEN_SCOPE` |
| `E_PREP_*` | 准备单状态机 | `E_PREP_NOT_APPROVED`、`E_PREP_EXPIRED` |
| `E_RUN_*` | 执行 | `E_RUN_ROWCOUNT_MISMATCH`（C1）、`E_RUN_BUDGET_BREACH`、`E_RUN_ENGINE`、`E_RUN_INVALID_STATE`（重跑非终态） |
| `E_EVOL_*` | 安全进化 | `E_EVOLUTION_GATE`（灰度前置健康度不达标） |
| `E_LEDGER_*` | 账本 | `E_LEDGER_BROKEN` |
| `E_INTERNAL` | 未分类 | 兜底，须带 trace_id |

---

## 10. 关键不变式汇总（Review 清单）

1. 副作用唯一出口：仅 `harness.broker.execute()` 触达数据面（CI 静态检查）。
2. 凭据：仅 `resolve_config` 还原明文，仅 Worker 执行路径调用；库内/API 无明文。
3. 职责分离：互斥判定只在 Approve/Prepare，资格表写入不判定（D3）。
4. 恢复真相源：LangGraph checkpoint；`agent_runs` 只读投影（D10）。
5. 门禁与编译器：纯函数、确定性、不调 LLM；SQL 形态白名单。
6. 账本：`audit_events` 只追加；写操作类接口必 `ledger.append`。
7. Capability：nonce 存证表 + 单事务消费，禁 Redis SETNX（D2）。
8. 行数硬判据（C1）：双等式——① `input_records == 源端行数`（Dry-Run 时为 min(源端行数, 采样上限 `dry_run_sample_limit`)）；② `output_records + error_records == input_records`；任一不满足即判失败。执行与 Benchmark 共用同一校验函数。
