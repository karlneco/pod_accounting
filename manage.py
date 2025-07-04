#!/usr/bin/env python
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
    app.run(debug=True)
