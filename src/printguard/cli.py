"""CLI utility for PrintGuard."""

import typer
from typing import Annotated

app = typer.Typer(
    name="printguard",
    help="PrintGuard CLI - 3D print failure detection service utilities.",
    add_completion=False,
)


@app.command()
def generate_keys(
    output_env: Annotated[
        bool,
        typer.Option(
            "--env",
            "-e",
            help="Output keys in .env file format",
        ),
    ] = False,
) -> None:
    """Generate VAPID keys for web push notifications.
    
    Uses the pywebpush library to generate a new VAPID key pair.
    The keys can be used for web push notification authentication.
    """
    try:
        from py_vapid import Vapid
    except ImportError:
        typer.echo(
            "Error: pywebpush is not installed. "
            "Install it with: pip install pywebpush",
            err=True,
        )
        raise typer.Exit(code=1)

    vapid = Vapid()
    vapid.generate_keys()
    private_key = vapid.private_pem().decode("utf-8")
    public_key = vapid.public_key_urlsafe_base64()
    if output_env:
        typer.echo("# VAPID Keys for Web Push Notifications")
        typer.echo(f'VAPID_PUBLIC_KEY="{public_key}"')
        typer.echo(f'VAPID_PRIVATE_KEY="{private_key.strip()}"')
    else:
        typer.echo(
            typer.style("\nVAPID Keys Generated Successfully!\n", fg=typer.colors.GREEN, bold=True)
        )
        typer.echo(typer.style("Public Key:", fg=typer.colors.CYAN, bold=True))
        typer.echo(f"  {public_key}\n")
        typer.echo(typer.style("Private Key:", fg=typer.colors.CYAN, bold=True))
        typer.echo(f"  {private_key}")
        typer.echo(
            typer.style(
                "\nTip: Use --env flag to output in .env format\n",
                fg=typer.colors.YELLOW,
            )
        )


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option(
            "--host",
            "-h",
            help="Host to bind the server to",
        ),
    ] = "0.0.0.0",
    port: Annotated[
        int,
        typer.Option(
            "--port",
            "-p",
            help="Port to bind the server to",
        ),
    ] = 8000,
    reload: Annotated[
        bool,
        typer.Option(
            "--reload",
            "-r",
            help="Enable auto-reload for development",
        ),
    ] = False,
) -> None:
    """Start the PrintGuard FastAPI server."""
    try:
        import uvicorn
    except ImportError:
        typer.echo(
            "Error: uvicorn is not installed. "
            "Install it with: pip install uvicorn",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(
        typer.style(
            f"\nStarting PrintGuard server at http://{host}:{port}\n",
            fg=typer.colors.GREEN,
            bold=True,
        )
    )
    uvicorn.run(
        "printguard.main:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def version() -> None:
    """Show the PrintGuard version."""
    try:
        from importlib.metadata import version as get_version
        ver = get_version("printguard")
    except Exception:
        ver = "0.1.0 (development)"
    
    typer.echo(f"PrintGuard version: {ver}")


if __name__ == "__main__":
    app()
