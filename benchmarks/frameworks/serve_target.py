"""ASGI target for Granian or uvicorn: builds BENCH_SUITE/BENCH_SCENARIO at import time.

`run_http.py` starts the server with stdout on /dev/null, so log lines cost a real write.
"""

import importlib
import os


app, _scenario = importlib.import_module(f"{os.environ['BENCH_SUITE']}_suite").build(os.environ["BENCH_SCENARIO"])
