"""分册原子提交全场景：热厨册/冷荤册同成同败、占用加总、库存结存不变。"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import (
    BomLine, Dish, Ingredient, IngredientOccupancy, KitchenOrder, OrderLine, PrepRun,
    STATION_HOT, STATION_COLD, STATION_NONE,
)
from app.services import prep_service
from app.services.bom_engine import (
    SplitMismatch, build_occupancy, cross_check, explode_by_book,
)
from app.services.prep_service import generate_prep


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)(), engine


def seed_world(db, stations=("none", "none", "none"), stocks=None, portions=(40, 30, 50)):
    """三道出品共享 I-SC 生抽：D1(肉+生抽) D2(茄+生抽) D3(鸡+生抽)，便于看加总。"""
    dspec = [("D-01", "出品甲"), ("D-02", "出品乙"), ("D-03", "出品丙")]
    dish_ids = {}
    for (code, name), station in zip(dspec, stations):
        d = Dish(code=code, name=name, station=station)
        db.add(d); db.flush(); dish_ids[code] = d.id
    default_stocks = {"I-PR": 8.0, "I-EG": 3.0, "I-CK": 5.0, "I-SC": 20.0}
    default_stocks.update(stocks or {})
    ing_ids = {}
    for code, name, unit in [("I-PR", "五花肉", "kg"), ("I-EG", "茄子", "kg"),
                             ("I-CK", "鸡肉", "kg"), ("I-SC", "生抽", "L")]:
        i = Ingredient(code=code, name=name, unit=unit, stock_qty=default_stocks[code])
        db.add(i); db.flush(); ing_ids[code] = i.id
    bom = [("D-01", "I-PR", 0.25), ("D-01", "I-SC", 0.02),
           ("D-02", "I-EG", 0.3), ("D-02", "I-SC", 0.015),
           ("D-03", "I-CK", 0.12), ("D-03", "I-SC", 0.01)]
    for dcode, icode, qty in bom:
        db.add(BomLine(dish_id=dish_ids[dcode], ingredient_id=ing_ids[icode], qty_per_portion=qty))
    order = KitchenOrder(code="KO-1", outlet="城西门店", status="open")
    db.add(order); db.flush()
    for (code, _), p in zip(dspec, portions):
        db.add(OrderLine(order_id=order.id, dish_id=dish_ids[code], portions=p))
    db.commit()
    return order.id, dish_ids, ing_ids


def books_by_name(result):
    return {b["book"]: b for b in result["books"]}


# ---------- 引擎层 ----------

def test_engine_explode_by_book_partitions_lines():
    db, _ = make_session()
    _, dids, iids = seed_world(db, stations=(STATION_HOT, STATION_COLD, STATION_NONE))
    rows = db.scalars(select(OrderLine)).all()
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in db.scalars(select(Ingredient)).all()}
    ols = [{"dish_id": r.dish_id, "portions": r.portions,
            "station": db.get(Dish, r.dish_id).station} for r in rows]
    books = explode_by_book(ols, bom, ings)
    occ = build_occupancy(books, ings)
    cross_check(books, occ)  # 不抛即对得上
    sc = next(r for r in occ if r["ingredient_id"] == iids["I-SC"])
    # 40*0.02 热厨 + 30*0.015 冷荤 + 50*0.01 未分册
    assert sc["hot_qty"] == pytest.approx(0.8)
    assert sc["cold_qty"] == pytest.approx(0.45)
    assert sc["common_qty"] == pytest.approx(0.5)
    assert sc["qty"] == pytest.approx(1.75)


def test_engine_cross_check_detects_tampering():
    books = {}
    ings = {1: {"code": "I-X", "name": "X", "unit": "kg", "stock_qty": 10.0}}
    ols = [{"dish_id": 1, "portions": 2, "station": STATION_HOT}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    books = explode_by_book(ols, bom, ings)
    occ = build_occupancy(books, ings)
    occ[0]["qty"] += 1.0  # 人为破坏占用列
    with pytest.raises(SplitMismatch):
        cross_check(books, occ)


# ---------- 服务层：分册与落单 ----------

def test_unmarked_dishes_go_into_single_book():
    db, _ = make_session()
    oid, _, _ = seed_world(db)
    result = generate_prep(db, oid)
    assert set(books_by_name(result)) == {"common"}  # 未标记一次提交只进一册
    assert result["stats"]["book_count"] == 1


def test_hot_and_cold_books_with_summed_occupancy():
    db, _ = make_session()
    oid, _, iids = seed_world(db, stations=(STATION_HOT, STATION_COLD, STATION_NONE))
    result = generate_prep(db, oid)
    bm = books_by_name(result)
    assert set(bm) == {"hot", "cold", "common"}
    sc = next(r for r in result["occupancy"] if r["ingredient_id"] == iids["I-SC"])
    assert sc["qty"] == pytest.approx(1.75)
    assert sc["hot_qty"] + sc["cold_qty"] + sc["common_qty"] == pytest.approx(1.75)
    # prep_lines 是两册加总口径
    sc_total = next(l for l in result["prep_lines"] if l["ingredient_id"] == iids["I-SC"])
    assert sc_total["need_qty"] == pytest.approx(1.75)


def test_same_marks_two_entries_return_same_run():
    db, _ = make_session()
    oid, _, _ = seed_world(db, stations=(STATION_HOT, STATION_COLD, STATION_NONE))
    r1 = generate_prep(db, oid)  # 订单页生成一次
    r2 = generate_prep(db, oid)  # 备料台再生成一次
    assert r1["id"] == r2["id"]  # 只许同一套两册
    assert r2["reused"] is True
    assert db.scalar(select(PrepRun).where(PrepRun.order_id == oid)) is not None
    assert len(db.scalars(select(PrepRun)).all()) == 1


def test_stock_balance_unchanged_after_generate():
    db, _ = make_session()
    oid, _, _ = seed_world(db, stations=(STATION_HOT, STATION_COLD, STATION_NONE))
    before = {i.id: i.stock_qty for i in db.scalars(select(Ingredient)).all()}
    generate_prep(db, oid)
    db.expire_all()
    after = {i.id: i.stock_qty for i in db.scalars(select(Ingredient)).all()}
    assert before == after  # 结存数字保持生成前


def test_shortage_does_not_block_split_commit():
    db, _ = make_session()
    # 生抽需求 1.75，库存只给 0.1 → 有缺料，但分册照样整体落下
    oid, _, _ = seed_world(db, stations=(STATION_HOT, STATION_COLD, STATION_NONE),
                           stocks={"I-SC": 0.1})
    result = generate_prep(db, oid)
    assert result["id"] is not None
    assert result["stats"]["shortage_count"] >= 1
    assert len(db.scalars(select(IngredientOccupancy)).all()) == len(result["occupancy"])


def test_mark_change_regenerates_both_books_together():
    db, _ = make_session()
    oid, dids, iids = seed_world(db, stations=(STATION_NONE, STATION_COLD, STATION_NONE))
    r1 = generate_prep(db, oid)
    assert set(books_by_name(r1)) == {"cold", "common"}
    old_json = json.loads(db.get(PrepRun, r1["id"]).result_json)

    # 改标记：出品甲 未标记 → 热厨
    db.get(Dish, dids["D-01"]).station = STATION_HOT
    db.commit()
    r2 = generate_prep(db, oid)

    assert r2["id"] != r1["id"] and r2["generation"] == 2
    assert set(books_by_name(r2)) == {"hot", "cold", "common"}
    # 更早的分册结果不被这次改标记改字
    frozen = json.loads(db.get(PrepRun, r1["id"]).result_json)
    assert frozen == old_json
    # 占用整体指向新一代并与新两册加总一致
    sc = next(r for r in r2["occupancy"] if r["ingredient_id"] == iids["I-SC"])
    assert sc["qty"] == pytest.approx(1.75)
    occs = db.scalars(select(IngredientOccupancy).where(
        IngredientOccupancy.ingredient_id == iids["I-SC"])).all()
    assert len(occs) == 1 and occs[0].run_id == r2["id"]


def test_split_mismatch_aborts_and_restores_everything():
    db, _ = make_session()
    oid, dids, _ = seed_world(db, stations=(STATION_HOT, STATION_COLD, STATION_NONE))
    r1 = generate_prep(db, oid)
    before_stock = {i.id: i.stock_qty for i in db.scalars(select(Ingredient)).all()}

    # 改标记后重生时让占用列与册对不上：run 已 flush、旧占用已删的中途也必须整笔退回
    db.get(Dish, dids["D-01"]).station = STATION_COLD  # hot → cold，签名必变
    db.commit()
    original_build = prep_service.build_occupancy

    def broken_build(books, ings):
        rows = original_build(books, ings)
        if rows:
            rows[0]["qty"] += 5.0  # 破坏加总
        return rows

    prep_service.build_occupancy = broken_build
    try:
        with pytest.raises(SplitMismatch) as ei:
            generate_prep(db, oid)
    finally:
        prep_service.build_occupancy = original_build

    msg = str(ei.value)
    assert "结存" not in msg and "缺料" not in msg  # 分册失败不得写成结存不够
    # 新一代两册与占用全部退回：只剩旧一代，旧占用完好指向旧 run
    assert len(db.scalars(select(PrepRun)).all()) == 1
    occs = db.scalars(select(IngredientOccupancy)).all()
    assert len(occs) == len(r1["occupancy"])
    assert all(o.run_id == r1["id"] for o in occs)
    db.expire_all()
    assert {i.id: i.stock_qty for i in db.scalars(select(Ingredient)).all()} == before_stock


def test_occupancy_write_failure_rolls_back_run_and_occupancy():
    db, _ = make_session()
    oid, _, _ = seed_world(db, stations=(STATION_HOT, STATION_COLD, STATION_NONE))
    r1 = generate_prep(db, oid)
    occ_count_before = len(db.scalars(select(IngredientOccupancy)).all())

    db.get(Dish, db.scalars(select(Dish)).first().id).station = STATION_COLD
    db.commit()

    real_model = prep_service.IngredientOccupancy

    def exploding_occupancy(**kw):
        raise RuntimeError("占用写入中断（模拟只落一册/占用失败）")

    prep_service.IngredientOccupancy = exploding_occupancy
    try:
        with pytest.raises(RuntimeError):
            generate_prep(db, oid)
    finally:
        prep_service.IngredientOccupancy = real_model

    # run 已 flush 也随事务退回；删除的旧占用恢复
    assert len(db.scalars(select(PrepRun)).all()) == 1
    occs = db.scalars(select(IngredientOccupancy)).all()
    assert len(occs) == occ_count_before
    assert all(o.run_id == r1["id"] for o in occs)


# ---------- API 层 ----------

@pytest.fixture
def client_db():
    db, engine = make_session()
    seed_world(db, stations=(STATION_HOT, STATION_COLD, STATION_NONE))
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app)
    yield client, db
    app.dependency_overrides.clear()


def test_api_patch_station_then_run_and_inventory(client_db):
    client, db = client_db
    did = db.scalars(select(Dish).where(Dish.code == "D-03")).first().id
    res = client.patch(f"/api/dishes/{did}", json={"station": "hot"})
    assert res.status_code == 200 and res.json()["station"] == "hot"

    res = client.post("/api/prep/run?order_id=1")
    assert res.status_code == 200
    body = res.json()
    assert {b["book"] for b in body["books"]} == {"hot", "cold"}

    inv = client.get("/api/inventory").json()
    sc = next(r for r in inv if r["code"] == "I-SC")
    assert sc["occupied_qty"] == pytest.approx(1.75)  # 占用按两册加总
    assert sc["stock_qty"] == 20.0  # 结存不变

    # 订单页/备料台两处再生成：同一套两册
    again = client.post("/api/prep/run?order_id=1").json()
    assert again["id"] == body["id"] and again["reused"] is True


def test_api_split_mismatch_is_not_reported_as_stock_shortage(client_db, monkeypatch):
    client, db = client_db
    original_build = prep_service.build_occupancy

    def broken_build(books, ings):
        rows = original_build(books, ings)
        if rows:
            rows[0]["qty"] += 9.0
        return rows

    monkeypatch.setattr(prep_service, "build_occupancy", broken_build)
    res = client.post("/api/prep/run?order_id=1")
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "split_mismatch"
    assert "结存" not in detail["message"]
    # 失败后没有任何 run 与占用落下
    assert len(db.scalars(select(PrepRun)).all()) == 0
    assert len(db.scalars(select(IngredientOccupancy)).all()) == 0
