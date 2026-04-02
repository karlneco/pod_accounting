import os

basedir = os.path.abspath(os.path.dirname(__file__))
default_data_dir = os.path.join(basedir, "data")


def _default_expense_invoice_upload_dir():
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "", 1)
        if db_path:
            return os.path.join(os.path.dirname(db_path), "expense_invoices")
    return os.path.join(default_data_dir, "expense_invoices")


def _default_import_upload_dir():
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "", 1)
        if db_path:
            return os.path.join(os.path.dirname(db_path), "uploads")
    return os.path.join(default_data_dir, "uploads")


def _default_ai_expense_import_upload_dir():
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "", 1)
        if db_path:
            return os.path.join(os.path.dirname(db_path), "ai_expense_imports")
    return os.path.join(default_data_dir, "ai_expense_imports")

class Config:
    # Use DATABASE_URL env var or fall back to SQLite file
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(default_data_dir, "pod_accounting.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "you-should-change-this")
    EXPENSE_INVOICE_UPLOAD_DIR = os.getenv(
        "EXPENSE_INVOICE_UPLOAD_DIR",
        _default_expense_invoice_upload_dir()
    )
    IMPORT_UPLOAD_DIR = os.getenv(
        "IMPORT_UPLOAD_DIR",
        _default_import_upload_dir()
    )
    AI_EXPENSE_IMPORT_UPLOAD_DIR = os.getenv(
        "AI_EXPENSE_IMPORT_UPLOAD_DIR",
        _default_ai_expense_import_upload_dir()
    )
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Printify API credentials
    PRINTIFY_API_TOKEN = os.getenv("PRINTIFY_API_TOKEN")
    PRINTIFY_SHOP_ID = os.getenv("PRINTIFY_SHOP_ID")
