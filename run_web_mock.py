"""降级版 web(mock 无 LLM key,不花 token)—— 仅供本机预览/调试切回逻辑。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import web.app as w

w.get_llm_config = lambda: {}   # 强制降级:走确定性模板,不调 LLM

import uvicorn

if __name__ == "__main__":
    uvicorn.run(w.app, host="127.0.0.1", port=8765, log_level="warning")
