import time
import threading

class TokenBucketRateLimiter:
    """
    Thread-safe Token Bucket Rate Limiter.
    Enforces a strict maximum requests-per-minute (RPM) ceiling,
    designed to prevent quota exhaustion on Google Gemini Free Tier.
    """
    def __init__(self, rpm: int = 14):
        self.capacity = float(rpm)
        self.tokens = float(rpm)
        self.fill_rate = float(rpm) / 60.0  # tokens added per second
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self, wait: bool = True) -> bool:
        """
        Acquire a token. If wait is True, blocks until a token is available.
        Returns True if token acquired, False if non-blocking and empty.
        """
        with self.lock:
            while True:
                now = time.time()
                elapsed = now - self.last_update
                self.last_update = now
                
                # Replenish tokens
                self.tokens = min(self.capacity, self.tokens + (elapsed * self.fill_rate))
                
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True
                
                if not wait:
                    return False
                
                # Calculate sleep duration needed for 1 token
                deficit = 1.0 - self.tokens
                sleep_time = deficit / self.fill_rate
                # Release lock while sleeping
                self.lock.release()
                try:
                    time.sleep(max(0.05, sleep_time))
                finally:
                    self.lock.acquire()

    def get_available_tokens(self) -> float:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + (elapsed * self.fill_rate))
            return self.tokens
