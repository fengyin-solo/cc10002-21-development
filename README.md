# 数据指标分析平台

面向指标口径定义、多维度聚合分析、AB实验评估、数据服务发布与数据应用交付的数据指标分析平台。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 指标定义 | `metricdef` | 指标口径 | 指标编号、指标名称、计算公式 |
| 维度管理 | `dimension` | 分析维度 | 维度编号、维度名称、数据来源表 |
| 数据源连接 | `datasource` | 数据源配置 | 配置编号、连接类型、接入地址 |
| 聚合查询 | `aggregation` | 聚合规则 | 规则编号、聚合函数、目标指标 |
| 分析看板 | `dashboard` | 看板配置 | 看板编号、看板名称、关联指标 |
| 分群分析 | `cohort` | 用户分群 | 分群编号、分群名称、筛选条件 |
| AB实验 | `abtest` | 实验方案 | 方案编号、实验名称、对照组配置 |
| 分析报告 | `report` | 报告模板 | 模板编号、模板名称、包含指标 |
| 指标预警 | `alert` | 预警规则 | 规则编号、关联指标、阈值上界 |
| 数据挖掘 | `datamine` | 挖掘任务 | 任务编号、输入数据集、算法类型 |
| 数据API | `api` | API服务 | 服务编号、输出数据集、查询参数定义 |
| ETL任务 | `etljob` | 加工任务 | 任务编号、输入源、输出目标 |
| 数据质量 | `quality` | 质量规则 | 规则编号、校验数据集、目标字段 |
| 数据建模 | `datamodel` | 模型定义 | 模型编号、模型名称、事实表名 |
| 数据导出 | `export` | 导出任务 | 任务编号、查询SQL、导出格式 |
| 数据订阅 | `subscribe` | 订阅任务 | 任务编号、数据源标识、订阅频率 |
| 数据血缘 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 人群圈选 | `segment` | 圈选规则 | 规则编号、规则名称、筛选条件组合 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 布局协作域（`app/collab`）

分析看板的带归属隔离布局协作与报告版本锁定能力，独立于通用 dashboard/report 模块：

- **本地身份与工作空间**：不接外部身份服务，请求头 `X-User-Id` / `X-Workspace-Id`
  声明身份，服务端用本地成员表实时鉴权；角色分 `editor` / `viewer`。
- **归属隔离**：看板、报告按 `(workspace_id, 数字ID)` 归属，各空间独立发号，
  故意存在同 ID 实体。跨空间访问（含猜测数字 ID）一律 404，错误信息不回显他空间实体。
- **草稿协作**：看板只有一份共享草稿，带递增修订号与每次修订的部件快照；
  部件有服务端发放的稳定标识 `widget_key`，删除不回收、跨看板不可复用。
  编辑者提交带 `base_revision`，服务端做按部件的三向合并：不同字段自动合并，
  移动 vs 删除、同字段异值返回 409 冲突与双方差异，绝不静默覆盖。
- **发布**：一个事务内固定不可变版本（部件快照）与访问范围；
  幂等键/同修订号重复发布不产生新版本；任一步骤失败整体回滚。
- **报告锁定**：报告只能锁定已发布版本，锁定后布局不随草稿变化；
  被引用部件在新版删除时，锁定版保留旧版内容并返回新版影响清单。
- **分享凭据**：只授予指定版本的匿名只读访问，撤销即失效，永不等于编辑权限。
- **权限撤销**：成员关系置为失效后，其之后的读取和提交由服务端拒绝（非前端隐藏）；
  共享草稿保留，其他编辑者可继续协作。

前端入口：导航「布局协作」（`/collab`），可切换本地身份与工作空间并演示上述全部流程。

### 测试

```bash
# 依赖安装到独立目录后运行（无需 venv）
python3 -m pip install --target=/tmp/pydeps fastapi "uvicorn[standard]" httpx
PYTHONPATH=/tmp/pydeps:backend python3 -s backend/tests/test_merge_unit.py   # 三向合并单元测试
PYTHONPATH=/tmp/pydeps:backend python3 -s backend/tests/test_collab_e2e.py    # 78 项端到端断言
```

端到端测试覆盖：两个空间同 ID 实体、编辑/只读角色、跨空间 ID 猜测、
同时移动与删除部件的冲突裁决、发布中断回滚与幂等、报告版本锁定与删除影响、
分享凭据边界、成员权限撤销的实时生效。

领域：数据工程
子方向：数据分析与数据应用
