import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.database import Base, get_db
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db(db_session_factory):
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session_factory):
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def _override():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


@pytest.fixture()
def seed(db):
    """种一套覆盖 hot/cold/缺料/跨册共用原料的数据，返回 id 映射。"""
    d_hot = Dish(code="D-H", name="热菜", portion_unit="份", station="hot")
    d_cold = Dish(code="D-C", name="冷菜", portion_unit="份", station="cold")
    d_none = Dish(code="D-N", name="未标", portion_unit="份", station=None)
    db.add_all([d_hot, d_cold, d_none])
    db.flush()
    i_shared = Ingredient(code="I-S", name="生抽", unit="L", stock_qty=2.0)
    i_meat = Ingredient(code="I-M", name="肉", unit="kg", stock_qty=100.0)
    i_short = Ingredient(code="I-X", name="茄子", unit="kg", stock_qty=1.0)
    db.add_all([i_shared, i_meat, i_short])
    db.flush()
    # hot: 肉 1/份（不缺）、共享生抽 0.1/份；cold: 共享生抽 0.1/份；未标: 茄子 1/份（缺料）
    db.add_all([
        BomLine(dish_id=d_hot.id, ingredient_id=i_meat.id, qty_per_portion=1.0),
        BomLine(dish_id=d_hot.id, ingredient_id=i_shared.id, qty_per_portion=0.1),
        BomLine(dish_id=d_cold.id, ingredient_id=i_shared.id, qty_per_portion=0.1),
        BomLine(dish_id=d_none.id, ingredient_id=i_short.id, qty_per_portion=1.0),
    ])
    order = KitchenOrder(code="KO-1", outlet="城西门店", status="open")
    db.add(order)
    db.flush()
    db.add_all([
        OrderLine(order_id=order.id, dish_id=d_hot.id, portions=10),
        OrderLine(order_id=order.id, dish_id=d_cold.id, portions=5),
        OrderLine(order_id=order.id, dish_id=d_none.id, portions=4),
    ])
    db.commit()
    return {
        "order_id": order.id,
        "dishes": {"hot": d_hot.id, "cold": d_cold.id, "none": d_none.id},
        "ingredients": {"shared": i_shared.id, "meat": i_meat.id, "short": i_short.id},
    }
