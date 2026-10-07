import pytest
from sqlalchemy import func, select

from app.models.models import Dish, Ingredient, PrepBooking, PrepRun
from app.services import prep_service
from app.services.bom_engine import SplitError, build_result_with_raw
from app.services.prep_service import effective_occupancy, generate_prep


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def _bookings_snapshot(db, run_id):
    return sorted(
        (b.book, b.ingredient_id, round(b.qty, 9))
        for b in db.scalars(select(PrepBooking).where(PrepBooking.run_id == run_id)).all()
    )


# ---- 原子事务：成功 / 幂等 / 改标记重生 ----

def test_generate_twice_returns_same_run_and_single_bookings(db, seed):
    run1, payload1 = generate_prep(db, seed["order_id"])
    run2, payload2 = generate_prep(db, seed["order_id"])
    assert run1.id == run2.id
    assert payload1["id"] == payload2["id"]
    assert _count(db, PrepRun) == 1
    # 三册都落下：hot（肉+生抽）、cold（生抽）、unassigned（茄子）
    books = {b for b in db.scalars(select(PrepBooking.book).distinct())}
    assert books == {"hot", "cold", "unassigned"}
    n_bookings = _count(db, PrepBooking)
    generate_prep(db, seed["order_id"])  # 再来一次
    assert _count(db, PrepBooking) == n_bookings


def test_books_sum_equals_occupancy_and_stock_untouched(db, seed):
    stock_before = {i.id: i.stock_qty for i in db.scalars(select(Ingredient)).all()}
    run, payload = generate_prep(db, seed["order_id"])
    summed: dict[int, float] = {}
    for b in db.scalars(select(PrepBooking).where(PrepBooking.run_id == run.id)).all():
        summed[b.ingredient_id] = summed.get(b.ingredient_id, 0.0) + b.qty
    occ = effective_occupancy(db)
    assert set(summed) == set(occ)
    for iid, qty in summed.items():
        assert abs(qty - occ[iid]) < 1e-6
    # 结存保持生成前
    db.expire_all()
    assert {i.id: i.stock_qty for i in db.scalars(select(Ingredient)).all()} == stock_before
    # 缺料不影响落单：茄子 4 vs 库存 1
    assert any(l["ingredient_id"] == seed["ingredients"]["short"] for l in payload["shortages"])


def test_station_change_regenerates_atomically_and_keeps_history(db, seed):
    run1, payload1 = generate_prep(db, seed["order_id"])
    old_json = run1.result_json
    old_bookings = _bookings_snapshot(db, run1.id)

    hot_dish = db.get(__import__("app.models.models", fromlist=["Dish"]).Dish, seed["dishes"]["hot"])
    hot_dish.station = None
    db.commit()

    run2, payload2 = generate_prep(db, seed["order_id"])
    assert run2.id != run1.id
    # 更早的分册结果不得被这次改标记改动
    db.expire_all()
    assert db.get(PrepRun, run1.id).result_json == old_json
    assert _bookings_snapshot(db, run1.id) == old_bookings
    # 新单：原热厨菜（肉+其生抽份额）移到未分册
    new_books = db.scalars(select(PrepBooking).where(PrepBooking.run_id == run2.id)).all()
    assert {b.book for b in new_books if b.ingredient_id == seed["ingredients"]["meat"]} == {"unassigned"}
    # 占用总量不因改册而变
    occ1 = effective_occupancy(db)
    # cold 生抽 0.5 仍在，热厨生抽份额随热菜离开 hot
    cold_sc = sum(b.qty for b in new_books
                  if b.book == "cold" and b.ingredient_id == seed["ingredients"]["shared"])
    assert abs(cold_sc - 0.5) < 1e-6
    assert abs(occ1[seed["ingredients"]["shared"]] - 1.5) < 1e-6
    assert payload2["id"] == run2.id


def test_effective_occupancy_excludes_superseded_runs(db, seed):
    run1, _ = generate_prep(db, seed["order_id"])
    cold_dish = db.get(__import__("app.models.models", fromlist=["Dish"]).Dish, seed["dishes"]["cold"])
    cold_dish.station = "hot"
    db.commit()
    run2, _ = generate_prep(db, seed["order_id"])
    occ = effective_occupancy(db)
    # 只按最新 run 计占用；两次总量相同（生抽跨 hot/cold 合计不变）
    assert abs(occ[seed["ingredients"]["shared"]] - 1.5) < 1e-6
    latest_rows = _bookings_snapshot(db, run2.id)
    assert sum(q for _, iid, q in latest_rows if iid == seed["ingredients"]["shared"]) == pytest.approx(1.5)


# ---- 分册失败：两册与占用全部退回 ----

def test_split_mismatch_rolls_back_everything(db, seed, monkeypatch):
    stock_before = {i.id: i.stock_qty for i in db.scalars(select(Ingredient)).all()}
    real = build_result_with_raw

    def tampered(order, order_lines, bom_lines, ingredients, stations):
        result, split = real(order, order_lines, bom_lines, ingredients, stations)
        split["_raw"]["occ"][seed["ingredients"]["shared"]] += 9.0  # 占用与册合计对不上
        return result, split

    monkeypatch.setattr(prep_service, "build_result_with_raw", tampered)
    with pytest.raises(SplitError) as ei:
        generate_prep(db, seed["order_id"])
    assert "分册" in str(ei.value)
    assert "结存不够" not in str(ei.value)
    assert _count(db, PrepRun) == 0
    assert _count(db, PrepBooking) == 0
    db.expire_all()
    assert {i.id: i.stock_qty for i in db.scalars(select(Ingredient)).all()} == stock_before


def test_commit_failure_rolls_back(db, seed, monkeypatch):
    def boom(self):
        raise RuntimeError("db down")

    monkeypatch.setattr(db.__class__, "commit", boom)
    with pytest.raises(RuntimeError):
        generate_prep(db, seed["order_id"])
    assert _count(db, PrepRun) == 0
    assert _count(db, PrepBooking) == 0


# ---- HTTP 层 ----

def test_http_generation_and_inventory(client, seed):
    r = client.post(f"/api/prep/run?order_id={seed['order_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["books"]["hot"]["name"] == "热厨册"
    assert body["books"]["cold"]["name"] == "冷荤册"
    assert body["books"]["unassigned"]["name"] == "未分册"
    # 缺料照常 200
    assert any(l["ingredient_id"] == seed["ingredients"]["short"] for l in body["shortages"])
    # 再生成一次：同一 run
    r2 = client.post(f"/api/prep/run?order_id={seed['order_id']}")
    assert r2.status_code == 200 and r2.json()["id"] == body["id"]
    # 库存：结存未动，生抽占用 1.5、可用 0.5
    inv = {r["id"]: r for r in client.get("/api/inventory").json()}
    row = inv[seed["ingredients"]["shared"]]
    assert row["stock_qty"] == 2.0
    assert row["occupied_qty"] == pytest.approx(1.5)
    assert row["available_qty"] == pytest.approx(0.5)


def test_http_split_failure_is_409_not_stock(client, seed, monkeypatch):
    real = build_result_with_raw

    def tampered(order, order_lines, bom_lines, ingredients, stations):
        result, split = real(order, order_lines, bom_lines, ingredients, stations)
        split["_raw"]["occ"][seed["ingredients"]["meat"]] += 3.0
        return result, split

    monkeypatch.setattr(prep_service, "build_result_with_raw", tampered)
    r = client.post(f"/api/prep/run?order_id={seed['order_id']}")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "分册失败" in detail
    assert "结存不够" not in detail


def test_http_latest_empty_and_404(client, seed):
    r = client.get(f"/api/prep/latest?order_id={seed['order_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] is False and body["id"] is None
    assert client.get("/api/prep/latest?order_id=999").status_code == 404


def test_http_dish_patch_station(client, seed):
    did = seed["dishes"]["none"]
    for value in ("hot", "cold", None):
        r = client.patch(f"/api/dishes/{did}", json={"station": value})
        assert r.status_code == 200 and r.json()["station"] == value
    r = client.patch(f"/api/dishes/{did}", json={"station": "grill"})
    assert r.status_code == 422
    assert client.patch("/api/dishes/999", json={"station": "hot"}).status_code == 404
    # 改标记后生成是新 run，且 latest 只读
    client.patch(f"/api/dishes/{did}", json={"station": "cold"})
    r = client.post(f"/api/prep/run?order_id={seed['order_id']}")
    assert r.status_code == 200
    r2 = client.get(f"/api/prep/latest?order_id={seed['order_id']}")
    assert r2.json()["id"] == r.json()["id"]
