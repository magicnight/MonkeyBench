"""启动 MonkeyBench Web App(本地服务,经 tailscale 内网访问)。

  .venv/bin/python run_web.py            # 监听 0.0.0.0:8000
  PORT=9000 .venv/bin/python run_web.py  # 自定端口
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"MonkeyBench Web 启动于 0.0.0.0:{port}(tailscale 设备名:端口 即可访问)")
    uvicorn.run("web.app:app", host="0.0.0.0", port=port, reload=False, log_level="info")
