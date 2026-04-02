#!/usr/bin/env python
import os

from dotenv import load_dotenv

from app import create_app, db
from flask.cli import with_appcontext
import click
from app.services.ai_expense_import import run_worker_loop

load_dotenv()

app = create_app()


@app.cli.command("create-db")
@with_appcontext
def create_db():
    db.create_all()
    click.echo("Database tables created.")


@app.cli.command("ai-expense-worker")
@click.option("--poll-interval", default=10, type=int, show_default=True)
@click.option("--once", is_flag=True, help="Process at most one queued document and exit.")
@with_appcontext
def ai_expense_worker(poll_interval, once):
    processed_id = run_worker_loop(poll_interval=poll_interval, once=once)
    if once and processed_id is None:
        click.echo("No queued AI expense documents found.")
    elif once:
        click.echo(f"Processed AI expense document {processed_id}.")


if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_RUN_PORT", "5004"))
    app.run(debug=True, host=host, port=port)
