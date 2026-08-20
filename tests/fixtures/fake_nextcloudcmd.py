#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time


mode = os.environ.get("FAKE_NEXTCLOUDCMD_MODE", "success")
if not os.environ.get("NC_USER") or not os.environ.get("NC_PASSWORD"):
    print("authentication failed: missing environment credentials", file=sys.stderr)
    raise SystemExit(7)

print("Fake nextcloudcmd started")
print("Arguments:", " ".join(sys.argv[1:]))

if mode == "slow":
    time.sleep(float(os.environ.get("FAKE_NEXTCLOUDCMD_DELAY", "0.2")))
elif mode == "large-output":
    for number in range(1000):
        print(f"processed file {number}")
elif mode == "failure":
    print("simulated synchronization failure", file=sys.stderr)
    raise SystemExit(5)
elif mode == "auth-failure":
    print("authentication failed: invalid credentials", file=sys.stderr)
    raise SystemExit(4)
elif mode == "conflict":
    print("created conflicted copy for Documents/example.txt")

print("Fake nextcloudcmd completed")

