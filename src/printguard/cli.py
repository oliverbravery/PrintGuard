"""CLI utility for PrintGuard."""

import typer
import os
from typing import Annotated
from .config import TunnelProvider

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
    tunnel: Annotated[
        TunnelProvider,
        typer.Option(
            "--tunnel",
            "-t",
            help="Tunnel provider to use",
            envvar="TUNNEL_PROVIDER",
        ),
    ] = TunnelProvider.LOCAL,
    cf_token: Annotated[
        str,
        typer.Option(
            "--cf-token",
            help="Cloudflare API token for tunnel setup",
            envvar="CLOUDFLARE_API_TOKEN",
        ),
    ] = "",
    cf_domain: Annotated[
        str,
        typer.Option(
            "--cf-domain",
            help="Cloudflare domain for tunnel setup",
            envvar="CLOUDFLARE_DOMAIN",
        ),
    ] = "",
    cf_tunnel: Annotated[
        str,
        typer.Option(
            "--cf-tunnel",
            help="Cloudflare tunnel name",
            envvar="CLOUDFLARE_TUNNEL_NAME",
        ),
    ] = "printguard-tunnel",
    cf_subdomain: Annotated[
        str,
        typer.Option(
            "--cf-subdomain",
            help="Cloudflare subdomain for the tunnel",
            envvar="CLOUDFLARE_SUBDOMAIN",
        ),
    ] = "camera",
    ngrok_token: Annotated[
        str,
        typer.Option(
            "--ngrok-token",
            help="ngrok authtoken for tunnel setup",
            envvar="NGROK_AUTHTOKEN",
        ),
    ] = "",
    ngrok_domain: Annotated[
        str,
        typer.Option(
            "--ngrok-domain",
            help="ngrok custom domain",
            envvar="NGROK_DOMAIN",
        ),
    ] = "",
    ngrok_edge: Annotated[
        str,
        typer.Option(
            "--ngrok-edge",
            help="ngrok edge",
            envvar="NGROK_EDGE",
        ),
    ] = "",
) -> None:
    """Start the PrintGuard FastAPI server."""
    if tunnel:
        os.environ["TUNNEL_PROVIDER"] = tunnel.value
    if cf_token:
        os.environ["CLOUDFLARE_API_TOKEN"] = cf_token
    if cf_domain:
        os.environ["CLOUDFLARE_DOMAIN"] = cf_domain
    if cf_tunnel:
        os.environ["CLOUDFLARE_TUNNEL_NAME"] = cf_tunnel
    if cf_subdomain:
        os.environ["CLOUDFLARE_SUBDOMAIN"] = cf_subdomain
    
    if ngrok_token:
        os.environ["NGROK_AUTHTOKEN"] = ngrok_token
    if ngrok_domain:
        os.environ["NGROK_DOMAIN"] = ngrok_domain
    if ngrok_edge:
        os.environ["NGROK_EDGE"] = ngrok_edge

    if tunnel == TunnelProvider.CLOUDFLARE:
        from .tunnel import is_cloudflared_installed
        if not is_cloudflared_installed():
            typer.echo(
                typer.style(
                    "Warning: cloudflared binary not found. Tunnel setup will likely fail.\n"
                    "Install it from: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/tunnel-with-cloudflared/",
                    fg=typer.colors.YELLOW,
                ),
                err=True
            )

    if tunnel == TunnelProvider.NGROK:
        from .ngrok import is_ngrok_installed
        if not is_ngrok_installed():
            typer.echo(
                typer.style(
                    "Warning: ngrok-python package not found. ngrok tunnel setup will fail.\n"
                    "Install it with: pip install ngrok-python",
                    fg=typer.colors.YELLOW,
                ),
                err=True
            )

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
