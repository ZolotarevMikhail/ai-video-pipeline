#!/usr/bin/env python3
"""Генерация видео через ProxyAPI (модель Wan 3.0 и другие).

Что делает скрипт:
1. Отправляет задачу на генерацию видео (POST /v1/videos).
2. Ждёт готовности, опрашивая статус (polling_url).
3. Скачивает готовый mp4-файл в текущую папку.

Ключ API берётся из файла .env рядом со скриптом (строка PROXYAPI_KEY=...).
Промпт — из файла prompt.txt рядом со скриптом.

Пример запуска:
    python3 generate_video.py
    python3 generate_video.py --prompt-file мой-промпт.txt --duration 10 --resolution 720p
"""

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# certifi решает типичную проблему macOS: «системный» Python не видит
# корневые сертификаты. Если пакета нет — работаем со стандартными.
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

API_BASE = "https://api.proxyapi.ru"
DEFAULT_MODEL = "alibaba/wan-3.0"
# Сколько раз повторять сетевую операцию при сбое (не бесконечно!)
NETWORK_RETRIES = 3
# Не дольше этого времени (в секундах) ждём готовности видео
POLL_TIMEOUT_SECONDS = 15 * 60
# Пауза между опросами статуса (секунды)
POLL_INTERVAL_SECONDS = 15

SCRIPT_DIR = Path(__file__).resolve().parent


def load_api_key() -> str:
    """Читает ключ из .env рядом со скриптом. Ключ никогда не печатаем."""
    env_path = SCRIPT_DIR / ".env"
    if not env_path.exists():
        print("Ошибка: нет файла .env. Создайте его рядом со скриптом со строкой:")
        print("  PROXYAPI_KEY=ваш_ключ")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("PROXYAPI_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key:
                return key
    print("Ошибка: в .env нет строки PROXYAPI_KEY=... или ключ пуст. "
          "Вставьте ключ после знака равно.")
    sys.exit(1)


def load_prompt(path: Path) -> str:
    """Читает текст промпта из файла."""
    if not path.exists():
        print(f"Ошибка: не найден файл промпта {path}")
        sys.exit(1)
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        print(f"Ошибка: файл промпта пуст: {path}")
        sys.exit(1)
    return prompt


def _request_with_retries(url, *, method="GET", headers=None, data=None, timeout=120):
    """Один HTTP-запрос с ограниченным числом повторов при сетевых сбоях.

    Возвращает (status_code, text|bytes). 4xx-ошибки не повторяем — там
    проблема не в сети, а в запросе.
    """
    request = urllib.request.Request(url, data=data, method=method)
    for name, value in (headers or {}).items():
        request.add_header(name, value)

    last_error = None
    for attempt in range(1, NETWORK_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
                # Разбор ответа: JSON отдаём текстом, остальное (видео) — байтами
                if "json" in content_type or "text" in content_type:
                    return response.status, raw.decode("utf-8", errors="replace")
                return response.status, raw
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if 400 <= error.code < 500:
                # Ошибка на нашей стороне: повторять бессмысленно
                return error.code, body
            last_error = error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
        if attempt < NETWORK_RETRIES:
            # Пауза растёт с каждой попыткой: 3, 6, 9 секунд
            time.sleep(3 * attempt)
    raise RuntimeError(f"Сетевые запросы не проходят ({NETWORK_RETRIES} попыток): {last_error}")


def submit_task(key: str, model: str, prompt: str, duration: int, resolution: str,
                aspect_ratio: str, generate_audio: bool) -> dict:
    """Создаёт задачу на генерацию видео. Возвращает ответ API (id, polling_url)."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "generate_audio": generate_audio,
    }).encode("utf-8")

    status, body = _request_with_retries(
        f"{API_BASE}/v1/videos",
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        data=payload,
    )
    if status not in (200, 201, 202):
        sys.exit(f"Ошибка при создании задачи (HTTP {status}):\n{body}")
    data = json.loads(body)
    if "id" not in data or "polling_url" not in data:
        sys.exit("Неожиданный ответ API без id/polling_url:\n"
                 + json.dumps(data, ensure_ascii=False))
    return data


def poll_until_done(key: str, polling_url: str) -> dict:
    """Опрашивает статус, пока задача не станет completed/failed."""
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    poll_number = 0
    while time.monotonic() < deadline:
        poll_number += 1
        status, body = _request_with_retries(
            polling_url, headers={"Authorization": f"Bearer {key}"})
        if status != 200:
            sys.exit(f"Ошибка при опросе статуса (HTTP {status}):\n{body}")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            sys.exit(f"Неожиданный ответ при опросе статуса:\n{body[:500]}")
        job_status = data.get("status")
        elapsed = poll_number * POLL_INTERVAL_SECONDS
        if job_status == "completed":
            print(f"Готово! Ждали примерно {elapsed} сек.")
            return data
        if job_status == "failed":
            sys.exit(f"Генерация провалилась. Ответ API:\n"
                     f"{json.dumps(data, ensure_ascii=False)}")
        # Статусы pending/процесс — сообщаем и ждём дальше
        print(f"[{elapsed} сек] статус: {job_status or 'неизвестно'} — ждём...")
        time.sleep(POLL_INTERVAL_SECONDS)
    sys.exit(f"Время ожидания вышло (>{POLL_TIMEOUT_SECONDS // 60} минут). "
             f"Задачу можно проверить вручную: {polling_url}")


def download_video(key: str, urls: list, out_path: Path) -> Path:
    """Скачивает первый готовый файл из списка unsigned_urls."""
    if not urls or not isinstance(urls, list):
        sys.exit("API не вернул ссылок на файл. Ответ без unsigned_urls.")
    url = urls[0]
    status, data = _request_with_retries(
        url, headers={"Authorization": f"Bearer {key}"}, timeout=300)
    if status != 200:
        sys.exit(f"Ошибка скачивания (HTTP {status}).")
    with open(out_path, "wb") as file:
        file.write(data)
    size_mb = len(data) / 1024 / 1024
    print(f"Файл сохранён: {out_path} ({size_mb:.1f} МБ)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Генерация видео через ProxyAPI (Wan 3.0).")
    parser.add_argument("--prompt-file", default=str(SCRIPT_DIR / "prompt.txt"),
                        help="файл с промптом (по умолчанию prompt.txt рядом со скриптом)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"модель (по умолчанию {DEFAULT_MODEL})")
    parser.add_argument("--duration", type=int, default=20, help="длина клипа в секундах")
    parser.add_argument("--resolution", default="480p",
                        help="разрешение: 480p (SD, дешевле) / 720p (HD) / 1080p")
    parser.add_argument("--aspect-ratio", default="9:16",
                        help="формат: 9:16 (вертикальный) / 16:9 / 1:1")
    parser.add_argument("--audio", action="store_true",
                        help="генерировать звук сцены вместе с видео (дороже)")
    parser.add_argument("--out", default=None,
                        help="имя итогового файла (по умолчанию rolik-<дата>.mp4)")
    args = parser.parse_args()

    key = load_api_key()
    prompt = load_prompt(Path(args.prompt_file))

    out_name = args.out or time.strftime("rolik-%Y%m%d-%H%M.mp4")
    out_path = SCRIPT_DIR / out_name

    print(f"Модель: {args.model}, длина: {args.duration} сек, "
          f"разрешение: {args.resolution}, формат: {args.aspect_ratio}")
    print("Создаю задачу...")
    task = submit_task(key, args.model, prompt, args.duration, args.resolution,
                       args.aspect_ratio, args.audio)
    print(f"Задача создана: {task['id']}")

    done = poll_until_done(key, task["polling_url"])
    urls = done.get("unsigned_urls") or done.get("signed_urls")
    download_video(key, urls, out_path)


if __name__ == "__main__":
    main()
