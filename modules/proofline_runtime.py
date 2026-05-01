"""Proofline-named compatibility entry point for the local runtime CLI."""

from __future__ import annotations

from modules.local_runtime import main


if __name__ == "__main__":
    raise SystemExit(main(prog="proofline", product_name="Proofline"))
