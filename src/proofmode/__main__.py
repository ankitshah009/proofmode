"""Run the ProofMode web app: `uv run python -m proofmode`.

Environment:
- PROOFMODE_HOST: address to bind. Defaults to 127.0.0.1, so the app is reachable
  only from this machine. Set it to 0.0.0.0 (or a specific interface) only when
  you intend to expose the app; it has no authentication of its own.
- PROOFMODE_PORT: port to bind. Defaults to 8000.
"""

import os

import uvicorn

from proofmode.app import create_app


def main() -> None:
    host = os.environ.get("PROOFMODE_HOST", "127.0.0.1")
    port = int(os.environ.get("PROOFMODE_PORT", "8000"))
    uvicorn.run(
        create_app(),
        host=host,
        port=port,
        # Uvicorn would otherwise rewrite the client address from X-Forwarded-For
        # for local peers. The app decides that itself via PROOFMODE_TRUST_PROXY.
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
