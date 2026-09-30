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

1. **染缸还原台**：横滑缸位条，每缸显示状态、最近电位、redox sparkline 与发酵温志条数
2. **发酵温志专页**（顶栏 `/ferment`）：仅「还原中」缸位可登记/改记温志，条数与缸位条对账
3. **工坊 chip**：仅作缸位筛选，无独立工坊 CRUD 页
4. **点缸展开**：同页内登记浸染批次、改状态、看近几笔；无平行「染缸表 / 批次表」

**业务规则**（集中在 `app/services/vat_rules.py::validate_vat_status_change`，电位门槛与温志齐套挂在同一函数，任一不过不改状态）：

- 状态改为 `ready`（可染色）时，最新批次 `redoxMv` 须已填且 **≤ -500 mV**（原门槛照旧，不拆）；
- 同时发酵温志须**齐套**：
  - 至少 **4 条连续志**（取采样时刻最近的 4 条）；
  - 相邻志**液温相差不超过 3℃**；
  - 最近四条**酸碱值平均 ≥ 9**；
  - 最新一条**采样时刻晚于最近一次浸染**。

**发酵温志（FermentLog）**：字段为染缸、志序号、液温摄氏、酸碱值、采样时刻、巡检人；同缸志序号唯一（DB 唯一约束兜底并发，重复提交只有一笔落库，另一笔中文报错）。液温允许 20–42℃，酸碱值允许 8–12；新建与更新共用同一校验。

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
4. **FermentLog**：归属染缸、`seq`（同缸唯一）、`tempC`、`ph`、`sampledAt`、`inspector`；种子仅 V-01 有 3 条

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
    routers/
    services/vat_rules.py
    templates/   # base / bay / login / ferment
```
