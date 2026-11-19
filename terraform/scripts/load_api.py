#!/usr/bin/env python3
"""Gera carga HTTP na API de pedidos para demonstrar o scale-out por CPU.

    python3 scripts/load_api.py http://<alb>:8000 --seconds 300 --threads 32

Só faz GET /produtos (leitura). Ao final mostra o total e os códigos HTTP.
"""
import argparse
import collections
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("api_url", help="URL da API, por exemplo o output api_url")
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--threads", type=int, default=32)
    args = parser.parse_args()

    url = args.api_url.rstrip("/") + "/produtos"
    deadline = time.monotonic() + args.seconds
    codes = collections.Counter()
    lock = threading.Lock()

    def worker():
        local = collections.Counter()
        while time.monotonic() < deadline:
            try:
                with urlopen(url, timeout=10) as response:
                    response.read()
                    local[response.status] += 1
            except HTTPError as error:
                local[error.code] += 1
            except (URLError, OSError):
                local["erro de rede"] += 1
        with lock:
            codes.update(local)

    threads = [threading.Thread(target=worker) for _ in range(args.threads)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    while any(thread.is_alive() for thread in threads):
        time.sleep(min(10, args.seconds))
        print(f"  {min(time.monotonic() - started, args.seconds):4.0f}s de {args.seconds}s", flush=True)
    for thread in threads:
        thread.join()

    total = sum(codes.values())
    elapsed = time.monotonic() - started
    print(f"{total} requisições em {elapsed:.0f}s ({total / elapsed:.0f}/s)")
    for code, count in sorted(codes.items(), key=str):
        print(f"  {code}: {count}")


if __name__ == "__main__":
    main()
