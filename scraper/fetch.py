"""HTTP заявки към сайта с повторни опити."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
}


class FetchError(Exception):
    pass


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=3,
        backoff_factor=2,  # 2s, 4s, 8s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_html(session: requests.Session, url: str, timeout: float = 25) -> str:
    try:
        resp = session.get(url, timeout=timeout)
    except requests.RequestException as e:
        raise FetchError(f"Мрежова грешка: {e}") from e

    if resp.status_code == 404:
        raise FetchError("Страницата не съществува (404) – линкът вероятно е сменен.")
    if resp.status_code != 200:
        raise FetchError(f"Сайтът върна HTTP {resp.status_code}.")

    resp.encoding = resp.encoding or "utf-8"
    return resp.text
