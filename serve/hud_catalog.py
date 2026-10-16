"""Local catalog for the chat HUD: which models are on disk, a setup.py download, and a restart with chosen context/KV.

Binds 127.0.0.1 only. Family and model come from the table below, never from a free-form path.
"""
from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "Strata-data"
MODELS_DIR = DATA / "models"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PORT = 15091
CHAT_PORT = 15080
CONTEXTS = [8192, 32768, 65536, 131072, 204800, 262144, 393216, 524288]
KV = ["int8", "q4_0", "k8v4"]

# tag is the models/ folder prefix setup.py uses. shards is how many .gguf.done marks mean "present".
CATALOG = [
    {"family": "qwen", "title": "Qwen3.8-Flash-Next", "model": "Q2_0", "gb": 66.4, "tag": "", "shards": 2},
    {"family": "qwen", "title": "Qwen3.8-Flash-Next", "model": "IQ2_XS", "gb": 68.0, "tag": "", "shards": 2},
    {"family": "qwen", "title": "Qwen3.8-Flash-Next", "model": "IQ3_XXS", "gb": 75.8, "tag": "", "shards": 2},
    {"family": "qwen", "title": "Qwen3.8-Flash-Next", "model": "IQ3_S", "gb": 83.6, "tag": "", "shards": 2},
    {"family": "swift", "title": "Swift 1.5", "model": "IQ2_XS", "gb": 68.0, "tag": "swift-", "shards": 2},
    {"family": "swift", "title": "Swift 1.5", "model": "IQ3_XXS", "gb": 75.8, "tag": "swift-", "shards": 2},
    {"family": "swift", "title": "Swift 1.5", "model": "IQ3_S", "gb": 83.6, "tag": "swift-", "shards": 2},
    {"family": "coder", "title": "Flash-Next Coder", "model": "IQ1_M", "gb": 58.4, "tag": "coder-", "shards": 2},
    {"family": "unsloth", "title": "Unsloth", "model": "UD-IQ4_XS", "gb": 93.7, "tag": "unsloth-", "shards": 3},
    {"family": "unsloth", "title": "Unsloth", "model": "UD-Q4_K_XL", "gb": 111.3, "tag": "unsloth-", "shards": 4},
    {"family": "unsloth", "title": "Unsloth", "model": "UD-Q5_K_XL", "gb": 158.3, "tag": "unsloth-", "shards": 6},
    {"family": "unsloth", "title": "Unsloth", "model": "UD-Q6_K_XL", "gb": 169.2, "tag": "unsloth-", "shards": 6},
    {"family": "unsloth", "title": "Unsloth", "model": "Q8_0", "gb": 188.2, "tag": "unsloth-", "shards": 6},
    {"family": "nvfp4", "title": "NVFP4", "model": "NVFP4", "gb": 128.0, "tag": "nvfp4-", "shards": 1},
    {"family": "nvfp4", "title": "NVFP4", "model": "NVFP4-NVIDIA", "gb": 128.0, "tag": "nvfp4-", "shards": 1},
    {"family": "qwen36", "title": "Qwen3.6-35B-A3B", "model": "UD-Q4_K_XL", "gb": 22.9, "tag": "qwen36-", "shards": 1},
    {"family": "qwen36", "title": "Qwen3.6-35B-A3B", "model": "UD-Q6_K_XL", "gb": 32.6, "tag": "qwen36-", "shards": 1},
    {"family": "qwen36", "title": "Qwen3.6-35B-A3B", "model": "Q8_0", "gb": 37.8, "tag": "qwen36-", "shards": 1},
]

_lock = threading.Lock()
_job = {"running": False, "family": "", "model": "", "error": "", "proc": None}


def find_row(family: str, model: str) -> dict | None:
    return next((r for r in CATALOG if r["family"] == family and r["model"] == model), None)


def model_dir(row: dict) -> Path:
    return MODELS_DIR / f"{row['tag']}{row['model']}"


def measure(row: dict) -> dict:
    folder = model_dir(row)
    gguf = list(folder.glob("*.gguf")) if folder.is_dir() else []
    done = [p for p in gguf if p.with_name(p.name + ".done").is_file()]
    parts = list(folder.glob("*.part")) if folder.is_dir() else []
    have = 0
    for p in gguf + parts:
        try:
            have += p.stat().st_size
        except OSError:
            pass
    expected = int(row["gb"] * 1_000_000_000)
    ready = len(gguf) >= row["shards"] and len(done) >= row["shards"] and not parts
    pct = 100.0 if ready else (min(99.0, 100.0 * have / expected) if expected else 0.0)
    return {"downloaded": ready, "bytes": have, "expected": expected, "pct": round(pct, 1)}


def catalog() -> dict:
    rows = []
    for row in CATALOG:
        measured = measure(row)
        rows.append({
            "family": row["family"], "title": row["title"], "model": row["model"],
            "gb": row["gb"], **measured,
        })
    with _lock:
        job = {"running": _job["running"], "family": _job["family"], "model": _job["model"], "error": _job["error"]}
    return {"models": rows, "contexts": CONTEXTS, "kv": KV, "job": job}


def _run_download(row: dict) -> None:
    cmd = [str(PYTHON), str(ROOT / "setup.py"), "--family", row["family"], "--model", row["model"],
           "--yes", "--no-start", "--no-browser", "--data-dir", str(DATA), "--context", "131072",
           "--kv", "int8", "--images", "no"]
    try:
        proc = subprocess.Popen(cmd, cwd=str(ROOT))
    except OSError as exc:
        with _lock:
            _job["running"] = False
            _job["error"] = str(exc)
        return
    with _lock:
        _job["proc"] = proc
    code = proc.wait()
    with _lock:
        _job["running"] = False
        _job["proc"] = None
        _job["error"] = "" if code == 0 else f"setup exited {code}"


def start_download(family: str, model: str) -> dict:
    row = find_row(family, model)
    if row is None:
        return {"error": "unknown model"}
    with _lock:
        if _job["running"]:
            return {"error": "a download is already running"}
        _job.update(running=True, family=family, model=model, error="")
    threading.Thread(target=_run_download, args=(row,), daemon=True).start()
    return {"status": "started"}


def config_path(row: dict) -> Path:
    return ROOT / f"strata-{(row['tag'] + row['model']).lower()}.json"


def listener_pid(port: int) -> int | None:
    out = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True, errors="replace")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def command_line(pid: int) -> str:
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
        text=True, errors="replace")
    return out.strip()


def patch_config(src: Path, context: int, kv: str) -> Path:
    cfg = json.loads(src.read_text(encoding="utf-8-sig"))
    args = list(cfg.get("args") or [])

    def replace(flag: str, value: str) -> None:
        if flag in args:
            args[args.index(flag) + 1] = value
        else:
            args.extend([flag, value])

    replace("--max-context", str(context))
    replace("--kv", kv)
    cfg["args"] = args
    dest = ROOT / "strata-hud-launch.json"
    dest.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest


def launch(family: str, model: str, context: int, kv: str, images: str) -> dict:
    row = find_row(family, model)
    if row is None:
        return {"error": "unknown model"}
    if context not in CONTEXTS or kv not in KV or images not in ("no", "qwen-image"):
        return {"error": "bad setting"}
    if not measure(row)["downloaded"]:
        return {"error": "model is not downloaded"}
    if images == "qwen-image":
        return {"error": "The image encoder is not in this layout."}
    src = config_path(row)
    if not src.is_file():
        return {"error": "Launch settings are not ready yet. Try again after the download finishes."}
    pid = listener_pid(CHAT_PORT)
    if pid:
        line = command_line(pid)
        if "server.py" not in line.replace("/", "\\").lower() and "server.py" not in line.lower():
            return {"error": "port %s is not this Strata server" % CHAT_PORT}
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
    cfg = patch_config(src, context, kv)
    subprocess.Popen(
        [str(PYTHON), str(ROOT / "serve" / "server.py"), "--engine", "strata",
         "--config", str(cfg), "--port", str(CHAT_PORT)],
        cwd=str(ROOT))
    return {"status": "starting", "context": context, "kv": kv}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _cors(self) -> None:
        origin = self.headers.get("Origin") or ""
        if origin in ("http://127.0.0.1:%s" % CHAT_PORT, "http://localhost:%s" % CHAT_PORT):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 8192:
            return {}
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/catalog":
            self._json(200, catalog())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        data = self._body()
        if path == "/download":
            result = start_download(str(data.get("family") or ""), str(data.get("model") or ""))
            self._json(200 if "error" not in result else 400, result)
            return
        if path == "/launch":
            try:
                context = int(data.get("context"))
            except (TypeError, ValueError):
                self._json(400, {"error": "bad context"})
                return
            result = launch(str(data.get("family") or ""), str(data.get("model") or ""),
                            context, str(data.get("kv") or ""), str(data.get("images") or "no"))
            self._json(200 if "error" not in result else 400, result)
            return
        self._json(404, {"error": "not found"})


def main() -> None:
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
