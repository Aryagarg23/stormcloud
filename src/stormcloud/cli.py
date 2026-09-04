import typer
from sqlalchemy import func, select

from .config import get_settings
from .db import session_scope
from .model_registry import ModelRegistry
from .models import Role, User
from .security import hash_password
from .storage import ObjectStore

app = typer.Typer(no_args_is_help=True)


@app.command("init-buckets")
def init_buckets():
    ObjectStore().ensure_buckets()
    typer.echo("S3 buckets are ready")


@app.command("validate-config")
def validate_config():
    settings = get_settings()
    registry = ModelRegistry.load(settings.model_config_path, settings.prompt_root)
    typer.echo(f"model config valid: {registry.config_hash}")


@app.command("bootstrap-admin")
def bootstrap_admin(
    email: str = typer.Option(None, envvar="BOOTSTRAP_ADMIN_EMAIL"),
    password: str = typer.Option(None, envvar="BOOTSTRAP_ADMIN_PASSWORD"),
):
    if not email or not password or len(password) < 10:
        raise typer.BadParameter("email and a password of at least 10 characters are required")
    with session_scope() as db:
        if db.scalar(select(func.count()).select_from(User).where(User.role == Role.admin)):
            raise typer.BadParameter("an administrator already exists")
        user = User(email=email.lower(), password_hash=hash_password(password), role=Role.admin)
        db.add(user)
        db.flush()
        typer.echo(f"created administrator {user.email} ({user.id})")


if __name__ == "__main__":
    app()
