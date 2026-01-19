#!/usr/bin/env python
import os

from dotenv import load_dotenv

from app import create_app, db
from flask.cli import with_appcontext
import click

load_dotenv()

app = create_app()


@app.cli.command("create-db")
@with_appcontext
def create_db():
    db.create_all()
    click.echo("Database tables created.")


if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_RUN_PORT", "5050"))
    app.run(debug=True, host=host, port=port)
