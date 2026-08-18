# ETL·Agent 前端（frontend）

「深空数据观测站」深色风单页应用。Vue 3.5 + Vite 6 + TypeScript(strict) + Pinia + Vue Router 4 + Element Plus 2.x（dark 定制）+ ECharts 5。

## 启动

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # vue-tsc -b && vite build（零错误为合并门禁）
npm run preview
```

演示账号：Mock 模式下任意用户名/密码均可登录（固定返回「张伟」，角色与职责槽全集）。

## Mock 开关（后端尚不存在，演示全靠它）

| 环境变量 | 取值 | 行为 |
| --- | --- | --- |
| `VITE_MOCK` | 未设置 / 其他值（**默认**） | 浏览器侧拦截 `/api/*` 与 `/health` 请求 + EventSource，走内存 Mock（120~400ms 随机延迟，刷新重置） |
| `VITE_MOCK` | `false` | 直连真实后端；`vite.config.ts` 已配 proxy：`/api`、`/health` → `http://localhost:8000` |

`.env` 示例：`VITE_MOCK=false`

Mock 代码在 `src/mock/`（fetch 包装、`MockEventSource`、内存 db、演示数据集）。SSE 必须经 `createEventSource()`（`src/mock/index.ts` 导出的可注入工厂）创建 —— `src/sse/useRunStream.ts` 已内置该逻辑。

## 目录结构

```
src/
  main.ts               # 入口（首行 installMock()）
  App.vue               # 根组件（仅 router-view）
  styles/               # 设计系统：tokens.css(变量/极光/网格) base.css element-overrides.css
  router/index.ts       # 路由 + 守卫（无 token→/login；非法 projectId→当前项目）
  stores/               # auth.ts / project.ts / app.ts（健康轮询）
  api/                  # client.ts(fetch封装/ApiError) types.ts(全部DTO) + 领域模块
  sse/useRunStream.ts   # SSE 组合式函数（status/metrics/supervision/done）
  mock/                 # index.ts(安装) router.ts(路由) db.ts(内存库+时间线) data.ts(数据集) handlers/*.ts
  layout/AppShell.vue   # 外壳：导航/健康点/项目选择器/成员抽屉/通知/用户菜单
  components/           # GlassPanel PageHeader StatCard StatusPill RiskTag CodeBlock EmptyState HashChip charts/VChart
  views/                # 各业务页（页面 Agent 只动自己目录）
```

## 页面开发约定（给页面 Agent）

- 路由按项目边界 `/p/:projectId/...`；当前项目从 `useProjectStore()` 取，不要自己解析 localStorage。
- API 一律从 `@/api` 导入（`connApi` / `genApi` / `prepApi` / `runApi` / `benchApi` / `auditApi` / `evolutionApi` / `projectApi` / `fileApi`）；错误统一 `ApiError{code,message,details,traceId}`，401 已全局处理。
- DTO 类型一律从 `@/api` 导入，不要重复定义。
- SSE 用 `useRunStream(runIdRef)`，禁止直接 `new EventSource(...)`。
- 图表用 `<VChart :option="..." :height="..." />`（全局主题 `obs` 已注册；如需手动 init，先 `registerObsTheme()`，来自 `@/components/charts/theme`）。
- 视觉只用 `src/styles/tokens.css` 的 CSS 变量；状态颜色一律用 `StatusPill` / `RiskTag`，不要另起映射。

## ASSUMED 扩展端点（接口文档未列，原型必需；后端落地时须补）

| 方法 | 路径 | 用途 | 使用方 |
| --- | --- | --- | --- |
| GET | `/projects/{id}/members` | 成员列表（文档仅有 POST） | AppShell 成员抽屉 |
| GET | `/projects/{id}/file-assets` | 文件资产列表 | 数据资产页 |
| DELETE | `/file-assets/{id}` | 删除文件资产 | 数据资产页 |
| GET | `/pipelines/{id}` | Pipeline 详情（含 `versions` 数组） | Studio |
| GET | `/projects/{id}/preparations?status=` | 准备单列表 | 运行中心 / 审批视图 |
| GET | `/preparations/{id}` | 准备单详情 | 审批抽屉 |
| GET | `/benchmarks/runs?project_id=&limit=10` | Benchmark 历史列表 | 安全治理趋势图 |

另有两处字段级 ASSUMED 约定（代码内均有 `ASSUMED:` 注释）：

- `GET /agent-runs/{id}` 的 `pending_question.fields[]`：interrupt 表单由后端 schema 驱动渲染（SPEC 8），文档仅有 `{field,message}` 简例。
- 审计列表 `keyword` 过滤参数、`audit/verify` 响应中的 `note` 演示字段。

## 设计令牌速查

`--bg-0 #05080f` · `--panel rgba(15,23,42,.66)` · `--line rgba(148,163,184,.14)` · `--txt-0 #e6edf7` · `--cyan #22d3ee` · `--violet #a78bfa` · `--grad 135° 青→靛→紫` · `--glow` · `--r-lg 16px` · `--font-num 'JetBrains Mono'`（数字/ID/哈希/代码）· 正文 Sora + 系统中文字体。全局背景 `.app-bg`（极光 + 细网格）已在 AppShell/Login 内放置。
