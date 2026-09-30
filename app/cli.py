"""Flask CLI helpers: ``flask init-db``, ``flask generate-sample``, ``flask create-user``."""
import json
import os

import click
from flask import current_app

from app.models import init_db, user as user_model


def register_commands(app):
    @app.cli.command("init-db")
    def init_db_command():
        """Create database tables."""
        init_db()
        click.echo("Database ready.")

    @app.cli.command("generate-sample")
    @click.option("--accounts", default=600, show_default=True)
    @click.option("--normal", default=6000, show_default=True, help="Number of ordinary transactions.")
    @click.option("--seed", default=7, show_default=True)
    def generate_sample(accounts, normal, seed):
        """Write a synthetic dataset with planted fraud rings to data/raw/."""
        from ml.synthetic import generate

        df, truth = generate(n_accounts=accounts, n_normal=normal, seed=seed)
        raw = current_app.config["RAW_FOLDER"]
        csv_path = os.path.join(raw, "sample_transactions.csv")
        truth_path = os.path.join(raw, "sample_ground_truth.json")
        df.to_csv(csv_path, index=False)
        with open(truth_path, "w") as fh:
            json.dump(truth, fh, indent=2)
        click.echo(f"Wrote {len(df):,} transactions to {csv_path}")
        click.echo(f"Wrote ground truth for {len(truth)} planted rings to {truth_path}")

    @app.cli.command("create-user")
    @click.argument("email")
    @click.option("--name", default="Analyst")
    @click.password_option()
    def create_user(email, name, password):
        """Create a user without going through the web form."""
        if user_model.get_user_by_email(email):
            raise click.ClickException("A user with that email already exists.")
        user_model.create_user(name, email, password)
        click.echo(f"Created {email}.")
