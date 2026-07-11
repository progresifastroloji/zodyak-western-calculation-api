"""Production entrypoint that resolves Railway's PORT before starting gunicorn."""

from __future__ import annotations

import os


def _bind_address() -> str:
    port = os.environ.get("PORT") or os.environ.get("WESTERN_CALC_PORT") or "5010"
    return f"0.0.0.0:{port}"


def main() -> None:
    from gunicorn.app.wsgiapp import run

    os.environ.setdefault("GUNICORN_CMD_ARGS", f"--bind {_bind_address()}")
    run(["gunicorn", "zodyak_western_calculation_api.app:app"])


if __name__ == "__main__":
    main()
