#!/usr/bin/env python3
"""Back-compat shim. Prefer `ccv-update` or `python -m ccv.update`."""

from ccv.update import main

if __name__ == "__main__":
    raise SystemExit(main())
