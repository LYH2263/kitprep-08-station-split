import os

# 测试一律走内存 sqlite，不依赖 Postgres / psycopg2，必须在导入 app.* 之前设置
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_ON_EMPTY", "false")
