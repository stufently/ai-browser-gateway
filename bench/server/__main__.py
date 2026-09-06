"""Manual stand A. The only module in this milestone that opens a socket."""

from __future__ import annotations

import argparse

from wsgiref.simple_server import make_server

from bench.server.app import build_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stand A WSGI server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    httpd = make_server(args.host, args.port, build_app())
    print(f"stand A on http://{args.host}:{args.port}/")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
