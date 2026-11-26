"""Run the full grounding eval (box_eval_grounding) against another chat model
without touching the live API: a side API instance on 127.0.0.1:PORT uses the
same image, database and code, with OLLAMA_TWIN_MODEL / OLLAMA_BASE_URL set for
this run only. The live service on :8001 keeps its model.

  heirloom-box bench-pipeline MODEL [--ollama URL] [--port 8002]

The side instance skips the letter and routine loops (the live API runs them)
and ignores a saved LAN brain, so every turn is answered by MODEL. The eval
removes its own test rows, as it does on :8001.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request


def serve(port: int) -> None:
    """Child process: the API app with background loops turned off."""
    import uvicorn

    import routers.letters as letters
    import standing_routines

    async def _idle(*_args, **_kwargs):
        return None

    letters.deliver_due_letters = _idle
    standing_routines.run_routines_for_enabled_users = _idle
    import server

    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:  # noqa: S310
            return response.status == 200
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str]) -> int:
    args = list(argv)
    if args[:1] == ["--serve"]:
        serve(int(args[1]))
        return 0
    port = 8002
    base = os.environ.get("OLLAMA_BASE_URL") or "http://ollama:11434"
    model = ""
    while args:
        item = args.pop(0)
        if item == "--ollama" and args:
            base = args.pop(0)
        elif item == "--port" and args:
            port = int(args.pop(0))
        else:
            model = item
    if not model:
        print(__doc__)
        return 2
    from model_tiers import is_cloud_tag

    if is_cloud_tag(model):
        print(f"FAIL refusing cloud model {model}")
        return 2
    env = dict(os.environ)
    env.update({
        "OLLAMA_TWIN_MODEL": model,
        "OLLAMA_BASE_URL": base,
        "HEIRLOOM_BRAIN_URL": "",
        "HEIRLOOM_BRAIN_DISABLE_STORE": "1",
        "HEIRLOOM_BRAIN_STRATEGY": "single",
        "HEIRLOOM_BOX_KEEP_ALIVE": env.get("HEIRLOOM_BOX_KEEP_ALIVE") or "10m",
        "HEIRLOOM_EVAL_API": f"http://127.0.0.1:{port}",
    })
    child = subprocess.Popen([sys.executable, "-m", "model_bench_pipeline", "--serve", str(port)], env=env,
                             cwd=os.path.dirname(os.path.abspath(__file__)))
    try:
        for _ in range(120):
            if _healthy(port):
                break
            if child.poll() is not None:
                print("FAIL side API exited")
                return 1
            time.sleep(1)
        else:
            print("FAIL side API did not start")
            return 1
        print(f"Side API on :{port} with {model} at {base}", flush=True)
        done = subprocess.run([sys.executable, "-m", "box_eval_grounding"], env=env,
                              cwd=os.path.dirname(os.path.abspath(__file__)), check=False)
        return done.returncode
    finally:
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
