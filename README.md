# KitPrep 中央厨房 BOM 备料

按菜品 BOM 展开订单行、合并同原料需求，对照库存计算缺料并生成备料单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5000 |
| API | http://localhost:10100 |
| API 文档 | http://localhost:10100/docs |
| Postgres | localhost:5451 |

健康检查：`GET http://localhost:10100/api/health`

## 使用说明

1. 在「菜品」给出品标记工位：热厨 / 冷荤 / 未标记，并保存。
2. 在「BOM」维护用料树，在「订单」「库存」确认当日需求与结存。
3. 在「订单」或「备料台」点「生成备料单」：热厨册、冷荤册（未标记出品进同一册）与占用列在**同一事务**内整体落下——要么两册一起落，要么全部退回，绝不只落一册。
   - 占用列按两册（含未分册）需求逐原料加总；热厨册、冷荤册、占用列对不上算分册失败，两册与占用全部退回（错误码 `split_mismatch`，不是结存不够）。
   - 库存结存（stock_qty）只读，生成备料单后数字保持不变。
   - 同标记下订单页、备料台各生成一次，只返回同一套两册；改了标记再生成，两册按新标记一起重生为新版本，旧版本结果不改字。
4. 在「缺料」查看两册加总需求 − 结存为正的原料（仅供参考，有缺料也可以整体落单）。
5. 「库存」页可看每个原料的占用（两册加总）与可用 = 结存 − 占用。

## 开发与测试

```bash
docker compose exec api pytest -q
```
