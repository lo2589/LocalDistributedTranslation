"""
Slave 自测脚本 - 由 install_slave.bat 调用
对 Slave 服务发 5 段并行翻译，验证机器能干活
"""

import sys
import time
import httpx
import concurrent.futures

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
PARAGRAPHS = 5
TIMEOUT = 120

# 先尝试调用标准 /translate；若失败再尝试 /ollama/translate
URLS = [
    f"http://127.0.0.1:{PORT}/translate",
    f"http://127.0.0.1:{PORT}/ollama/translate",
]

TEXTS = [
    "Hello world",
    "Good morning, how are you?",
    "Artificial intelligence is changing the world.",
    "Machine learning algorithms require large datasets.",
    "The quick brown fox jumps over the lazy dog.",
]


def trans(text):
    for url in URLS:
        try:
            r = httpx.post(
                url,
                json={"text": text, "target_lang": "zh"},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            if "translated_text" in data and data["translated_text"]:
                return text, data["translated_text"], None, url
        except Exception as e:
            continue
    return text, "", "all endpoints failed", URLS[0]


def main():
    print(f"  Target: http://127.0.0.1:{PORT}")
    print(f"  Test cases: {PARAGRAPHS}")
    print()

    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARAGRAPHS) as ex:
        results = list(ex.map(trans, TEXTS))
    elapsed = time.time() - start

    passed = sum(1 for _, c, e, _ in results if c and not e)
    failed = PARAGRAPHS - passed

    print(f"  Result: {passed}/{PARAGRAPHS} passed, {elapsed:.1f}s")
    print()
    for t, c, e, url in results:
        if e:
            print(f"  [FAIL] {t[:30]:<30s} -> ERROR: {e}")
        else:
            print(f"  [OK]   {t[:30]:<30s} -> {c[:50]}")

    # 通过判定：5 段至少 4 段成功
    if passed >= PARAGRAPHS - 1:
        print()
        print(f"  SELFTEST_OK elapsed={elapsed:.1f}s passed={passed}/{PARAGRAPHS}")
        sys.exit(0)
    else:
        print()
        print(f"  SELFTEST_FAIL passed={passed}/{PARAGRAPHS}")
        sys.exit(1)


if __name__ == "__main__":
    main()
