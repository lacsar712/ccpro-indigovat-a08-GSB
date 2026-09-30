# IndigoVat-01 · 染缸还原台

FastAPI + PostgreSQL + Jinja2：主界面是横向**缸位条**（Alpine 反应式），不是工坊/染缸/批次三表导航。Session Cookie 登录；规则在 `app/services/vat_rules.py`。

## 技术栈

- FastAPI、SQLAlchemy 2、PostgreSQL
- 启动时 `create_all` + 幂等种子（蓝靛湾一号坊 / 清水江二号坊）
- Session Cookie 认证（Starlette SessionMiddleware）
- Jinja2 + Alpine.js + Pico（叠靛蓝水墨自定义样式）
- Docker Compose：`web` + `db`

## 端口与数据库

| 服务 | 端口 |
|------|------|
| Web  | **4720** |
| Postgres | **6120**（容器内 5432） |

数据库账号：`indigovat` / `indigovat` / 库名 `indigovat`

## 快速启动

```bash
cd IndigoVat/IndigoVat-01
docker compose up --build -d
```

浏览器打开：http://localhost:4720

演示账号（登录页已预填）：

- `admin` / `123456`
- `worker` / `123456`

## 交互（信息架构）

1. **染缸还原台**：横滑缸位条，每缸显示状态、最近电位、redox sparkline 与发酵温志条数；点缸展开记浸染、改状态
2. **发酵温志**（顶栏专页 `/ferment`）：按缸登记/更新靛蓝发酵温志，条数与还原台缸位条对账
3. **工坊 chip**：仅作缸位筛选，无独立工坊 CRUD 页

**业务规则**（判定集中在 `app/services/vat_rules.py` 的 `validate_vat_status_change`）：状态改为 `ready`（可染色）时，**两类门槛挂在同一改状态函数里、缺一不可**：

- 浸染电位门槛（原有，不拆）：最新批次 `redoxMv` 须已填且 ≤ -500；
- 发酵温志齐套：最近 **4 条**连续温志，相邻液温差 **≤ 3 ℃**，四条**酸碱值平均 ≥ 9**，且最新采样时刻**晚于最近一次浸染**。

任一不满足都不改状态（无半改）。

### 发酵温志

字段：染缸、志序号、液温摄氏、酸碱值、采样时刻、巡检人。

- 同缸志序号唯一（数据库唯一约束兜底，并发写入同序号只许一笔落库，另一笔中文报错，回滚后专页与还原台仍可继续操作）；
- 液温 20~42 ℃、酸碱值 8~12，新建与更新共用同一读数校验；
- 仅**还原中**的染缸可登记温志；
- 种子：V-01 四条齐套，V-03 只有 3 条（少一条不放行）。

## 本地开发（可选）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
set POSTGRES_HOST=localhost
set POSTGRES_PORT=6120
uvicorn app.main:app --host 0.0.0.0 --port 4720 --reload
```

## 业务模型

1. **Workshop**：`name`、`region`、`notes`（UI 上仅为筛选片）
2. **Vat**：归属工坊、`code`、`dyeType`、`volumeL`、状态 `idle|reducing|ready`
3. **DipLot**：归属染缸、`dippedAt`、`clothMeters`、`redoxMv`（可空）
4. **FermentLog**：归属染缸、同缸唯一 `seq`、`tempC`、`ph`、`sampledAt`、`inspector`

## 目录结构

```
IndigoVat-01/
  Dockerfile
  entrypoint.sh
  docker-compose.yml
  requirements.txt
  app/
    main.py
    db.py
    models.py
    schemas.py
    auth.py
    seed.py
    routers/           # auth / pages（还原台）/ ferment（温志专页）
    services/vat_rules.py
    templates/         # base / bay / login / ferment
```
