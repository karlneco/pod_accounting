import os

basedir = os.path.abspath(os.path.dirname(__file__))


def _default_expense_invoice_upload_dir():
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "", 1)
        if db_path:
            return os.path.join(os.path.dirname(db_path), "expense_invoices")
    return os.path.join(basedir, "../data/expense_invoices")

class Config:
    # Use DATABASE_URL env var or fall back to SQLite file
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(basedir, "../data/pod_accounting.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "you-should-change-this")
    EXPENSE_INVOICE_UPLOAD_DIR = os.getenv(
        "EXPENSE_INVOICE_UPLOAD_DIR",
        _default_expense_invoice_upload_dir()
    )
    
    # Printify API credentials
    PRINTIFY_API_TOKEN = os.getenv("PRINTIFY_API_TOKEN")
    PRINTIFY_SHOP_ID = os.getenv("PRINTIFY_SHOP_ID")
