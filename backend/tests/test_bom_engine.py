from app.services.bom_engine import (
    SplitError,
    build_result,
    explode_and_merge,
    split_books,
    validate_split,
)

def test_explode_merge():
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.1},
        {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
    ]
    ings = {
        1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 1.0},
        2: {"code": "B", "name": "米", "unit": "kg", "stock_qty": 5.0},
    }
    lines = explode_and_merge(order_lines, bom, ings)
    by_id = {l.ingredient_id: l for l in lines}
    assert by_id[1].need_qty == 3.5  # 10*0.2 + 5*0.3
    assert by_id[1].shortage == 2.5
    assert by_id[2].need_qty == 1.0
    assert by_id[2].shortage == 0.0

def test_no_negative_shortage():
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    ings = {1: {"code": "A", "name": "油", "unit": "L", "stock_qty": 10.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].shortage == 0.0


# ---- 分册 ----

def _fixture():
    # dish 1 hot, dish 2 cold, dish 3 unmarked；原料 1 被冷热两册共用
    order_lines = [
        {"dish_id": 1, "portions": 10},
        {"dish_id": 2, "portions": 5},
        {"dish_id": 3, "portions": 2},
    ]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.1},
        {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
        {"dish_id": 3, "ingredient_id": 3, "qty_per_portion": 1.0},
    ]
    ings = {
        1: {"code": "A", "name": "生抽", "unit": "L", "stock_qty": 10.0},
        2: {"code": "B", "name": "肉", "unit": "kg", "stock_qty": 5.0},
        3: {"code": "C", "name": "花生", "unit": "kg", "stock_qty": 1.0},
    }
    stations = {1: "hot", 2: "cold", 3: None}
    return order_lines, bom, ings, stations

def test_split_routing_and_single_assignment():
    order_lines, bom, ings, stations = _fixture()
    split = split_books(order_lines, bom, ings, stations)
    # 每道出品恰好进一册
    assert sorted((a["dish_id"], a["book"]) for a in split["assignments"]) == [
        (1, "hot"), (2, "cold"), (3, "unassigned")
    ]
    hot = {l["ingredient_id"]: l["qty"] for l in split["books"]["hot"]["lines"]}
    cold = {l["ingredient_id"]: l["qty"] for l in split["books"]["cold"]["lines"]}
    uns = {l["ingredient_id"]: l["qty"] for l in split["books"]["unassigned"]["lines"]}
    assert hot == {1: 2.0, 2: 1.0}
    assert cold == {1: 1.5}
    assert uns == {3: 2.0}

def test_occupancy_equals_sum_of_books_and_explode():
    order_lines, bom, ings, stations = _fixture()
    split = split_books(order_lines, bom, ings, stations)
    validate_split(order_lines, split)  # 不抛即一致
    occ = {l["ingredient_id"]: l["qty"] for l in split["occupancy"]}
    flat = {l.ingredient_id: l.need_qty for l in explode_and_merge(order_lines, bom, ings)}
    assert occ == flat == {1: 3.5, 2: 1.0, 3: 2.0}

def test_validate_split_detects_tampering_and_message_not_stock():
    order_lines, bom, ings, stations = _fixture()
    split = split_books(order_lines, bom, ings, stations)
    # 篡改占用，制造「按两册加总却对不上」
    split["_raw"]["occ"][1] += 5.0
    try:
        validate_split(order_lines, split)
    except SplitError as exc:
        assert "分册" in str(exc)
        assert "结存不够" not in str(exc)
    else:
        raise AssertionError("应当抛 SplitError")

def test_build_result_shape_and_shortage_still_ok():
    order_lines, bom, ings, stations = _fixture()
    # 把库存压低，造成缺料，但结果照常生成
    ings[2]["stock_qty"] = 0.2
    ings[3]["stock_qty"] = 10.0
    result = build_result({"id": 1, "code": "O", "outlet": "店"}, order_lines, bom, ings, stations)
    assert set(result["books"]) == {"hot", "cold", "unassigned"}
    assert result["books"]["hot"]["name"] == "热厨册"
    assert result["books"]["cold"]["name"] == "冷荤册"
    assert result["books"]["unassigned"]["name"] == "未分册"
    shortage_ids = {l["ingredient_id"] for l in result["shortages"]}
    assert shortage_ids == {2}
