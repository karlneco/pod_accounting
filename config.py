import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Use DATABASE_URL env var or fall back to SQLite file
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(basedir, "pod_accounting.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "you-should-change-this")