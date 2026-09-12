"""Backward-compatible entry point for the explicitly simulated reference actor."""

from commerce_eval.demo_runtime import _start, main


def _trace(payload, *, resumed=False):
    return _start(payload)["trace"]


if __name__ == "__main__":
    raise SystemExit(main())

