"""
Entry point for ``python -m xian_bridge``.

Launches the FastAPI app on 127.0.0.1:13306 with uvicorn.
"""

import argparse
import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Xian bridge service for MASHA")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=13306, help="Port (default 13306)")
    args = parser.parse_args()

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
