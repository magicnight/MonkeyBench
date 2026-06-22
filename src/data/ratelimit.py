"""Token-bucket 限速器 —— 所有外部 API 调用(尤其 Tushare 500 次/分**硬顶**)都过它。

线程安全、纯标准库。**对硬顶要留弹性,别顶格**:用 `for_hard_limit(500)` 默认只跑
80%(≈400/min)且突发受控,避免瞬时触线被服务端拒。

    bucket = TokenBucket.for_hard_limit(500)   # 硬顶 500/min,留 20% 余量
    bucket.acquire()                            # 每次调接口前
    pro.daily(ts_code="688205.SH", ...)
"""
from __future__ import annotations

import threading
import time


class TokenBucket:
    """经典令牌桶。

    capacity        桶容量(允许的突发上限)
    refill_per_sec  每秒补充的令牌数(稳态速率)
    """

    def __init__(self, capacity: float, refill_per_sec: float):
        if capacity <= 0 or refill_per_sec <= 0:
            raise ValueError("capacity 和 refill_per_sec 必须为正")
        self.capacity = float(capacity)
        self.refill_per_sec = float(refill_per_sec)
        self._tokens = float(capacity)          # 初始装满
        self._last = time.monotonic()
        self._lock = threading.Lock()

    @classmethod
    def per_minute(cls, n: float, burst: float | None = None) -> "TokenBucket":
        """通用便捷构造:稳态每分钟 n 次(突发上限默认 = n)。"""
        return cls(capacity=burst if burst is not None else n, refill_per_sec=n / 60.0)

    @classmethod
    def for_hard_limit(cls, per_min_cap: int, safety: float = 0.8,
                       burst_seconds: float = 2.0) -> "TokenBucket":
        """对**硬顶** per_min_cap 留弹性,不顶格跑。

        - 稳态速率 = per_min_cap * safety / 60(每秒);safety=0.8 即只用 80%。
        - 突发上限 = burst_seconds 秒的量(而非整个 per_min_cap),避免瞬间涌满触线。

        Tushare 硬顶 500/min → for_hard_limit(500) ≈ 400/min 稳态、突发约 13 次。
        """
        if not 0 < safety <= 1:
            raise ValueError("safety 应在 (0, 1]")
        rate = per_min_cap * safety / 60.0
        return cls(capacity=max(1.0, rate * burst_seconds), refill_per_sec=rate)

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.refill_per_sec)
        self._last = now

    def try_acquire(self, n: float = 1.0) -> bool:
        """非阻塞:够则扣减返回 True,否则不动返回 False。"""
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    def acquire(self, n: float = 1.0) -> float:
        """阻塞到拿到 n 个令牌。返回累计等待秒数(0 表示无需等待)。"""
        if n > self.capacity:
            raise ValueError(f"请求 {n} 超过桶容量 {self.capacity},永远无法满足")
        waited = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= n:
                    self._tokens -= n
                    return waited
                wait = (n - self._tokens) / self.refill_per_sec
            time.sleep(wait)
            waited += wait


if __name__ == "__main__":  # 纯标准库自测:.venv/bin/python src/data/ratelimit.py
    tb = TokenBucket(capacity=2, refill_per_sec=10)        # 突发 2,每秒补 10
    assert tb.try_acquire() and tb.try_acquire(), "满桶应放行 2 次"
    assert not tb.try_acquire(), "桶空应拒绝"
    waited = tb.acquire(1)                                  # 需等约 0.1s 补 1 个
    assert 0.05 < waited < 0.3, f"应阻塞约 0.1s,实际 {waited:.3f}s"

    hl = TokenBucket.for_hard_limit(500)                    # 硬顶 500,留弹性
    assert abs(hl.refill_per_sec - 500 * 0.8 / 60) < 1e-9, "稳态应只用 80% ≈ 400/min"
    assert hl.capacity < 20, f"突发应受控(约 13),实际 {hl.capacity:.1f}"
    print(f"✅ ratelimit 自测通过(硬顶 500 → 稳态 {hl.refill_per_sec*60:.0f}/min、突发 {hl.capacity:.0f})")
