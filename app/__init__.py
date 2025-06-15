from flask import Flask
from flask_migrate import Migrate
from .models import db
from .views import customers, providers, orders, costs, ads, expenses, main, products, accounts


def create_app(config_class="config.Config"):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    Migrate(app, db)

    # Register blueprints
    app.register_blueprint(main.bp)  # ← Top page
    app.register_blueprint(customers.bp,   url_prefix="/customers")
    app.register_blueprint(providers.bp,   url_prefix="/providers")
    app.register_blueprint(orders.bp,      url_prefix="/orders")
    app.register_blueprint(costs.bp,       url_prefix="/costs")
    app.register_blueprint(ads.bp,         url_prefix="/ads")
    app.register_blueprint(expenses.bp,    url_prefix="/expenses")
    app.register_blueprint(products.bp,    url_prefix="/products")
    app.register_blueprint(accounts.bp,    url_prefix="/accounts")

    return app