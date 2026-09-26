"""HTTP заявки към сайта.

Сайтът има защита срещу ботове, която връща 403, ако заявката не прилича
на истински браузър. Проверката е и на ниво TLS („отпечатъкът“ при
установяване на връзката), така че само смяна на User-Agent не стига –
дори влошава нещата, защото UA казва „Chrome“, а TLS казва „Python“.

Затова се пробват няколко начина по ред. Първият успешен се запомня и се
ползва първи за останалите продукти:

  1. curl_cffi, имитиращ Chrome изцяло (TLS + HTTP/2 + заглавки)
  2. curl_cffi, имитиращ Safari
  3. обикновен requests без маскиране (както работеше старият скрипт)
"""
from __future__ import annotations

import re
import time

import requests

try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # локално без curl_cffi – остава само requests
    cffi_requests = None


class FetchError(Exception):
    pass


class BlockedError(FetchError):
    """Сайтът отказа достъп – има смисъл да се пробва друг начин."""


def describe_block(resp) -> str:
    """Кратко описание кой и защо блокира – за логовете."""
    h = {k.lower(): v for k, v in resp.headers.items()}
    parts = [f"HTTP {resp.status_code}"]
    if h.get("server"):
        parts.append(f"server={h['server']}")
    for key in ("cf-mitigated", "x-akamai-session-info", "x-iinfo", "x-datadome"):
        if key in h:
            parts.append(f"{key}={h[key][:40]}")
    m = re.search(r"<title[^>]*>(.*?)</title>", resp.text or "", re.S | re.I)
    if m:
        parts.append(f"title='{' '.join(m.group(1).split())[:60]}'")
    return ", ".join(parts)


class _CffiStrategy:
    def __init__(self, browser: str):
        self.name = f"curl_cffi/{browser}"
        # Заглавките (вкл. User-Agent) ги слага самият curl_cffi, за да
        # съвпадат с имитирания браузър. Добавяме само езика.
        self.session = cffi_requests.Session(impersonate=browser)
        self.session.headers.update({"Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8"})

    def get(self, url, timeout):
        return self.session.get(url, timeout=timeout, allow_redirects=True)


class _RequestsStrategy:
    name = "requests"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept-Language": "bg-BG,bg;q=0.9"})

    def get(self, url, timeout):
        return self.session.get(url, timeout=timeout)


class Fetcher:
    def __init__(self, timeout: float = 30, log=print):
        self.timeout = timeout
        self.log = log
        self.strategies = []
        if cffi_requests is not None:
            self.strategies += [_CffiStrategy("chrome"), _CffiStrategy("safari")]
        self.strategies.append(_RequestsStrategy())
        self.last_used: str | None = None

    def _once(self, strategy, url: str) -> str:
        last = "неизвестна грешка"
        for attempt in range(3):
            try:
                resp = strategy.get(url, self.timeout)
            except Exception as e:  # noqa: BLE001 – различни библиотеки, различни изключения
                last = f"Мрежова грешка: {e}"
                time.sleep(3 * (attempt + 1))
                continue

            code = resp.status_code
            if code == 200:
                return resp.text
            if code == 404:
                raise FetchError("Страницата не съществува (404) – линкът вероятно е сменен.")
            if code in (401, 403):
                raise BlockedError(describe_block(resp))
            if code in (429, 503) or code >= 500:
                last = describe_block(resp)
                time.sleep(5 * (attempt + 1))
                continue
            raise FetchError(f"Сайтът върна HTTP {code}.")

        if "HTTP 429" in last or "HTTP 503" in last:
            raise BlockedError(last)
        raise FetchError(last)

    def get(self, url: str) -> str:
        blocked = []
        for strategy in list(self.strategies):
            try:
                html = self._once(strategy, url)
            except BlockedError as e:
                blocked.append(f"{strategy.name}: {e}")
                continue
            if strategy is not self.strategies[0]:
                # запомняме работещия начин за следващите продукти
                self.strategies.remove(strategy)
                self.strategies.insert(0, strategy)
            if self.last_used != strategy.name:
                self.log(f"Изтегляне чрез {strategy.name}")
                self.last_used = strategy.name
            return html
        # Ако всички начини са блокирани по един и същ начин, показваме го веднъж
        reasons = {b.split(": ", 1)[1] for b in blocked}
        detail = reasons.pop() if len(reasons) == 1 else " | ".join(blocked)
        if "cloudflare" in detail.lower() and "challenge" in detail.lower():
            raise BlockedError(f"Cloudflare поиска проверка „не си робот“ ({detail})")
        raise BlockedError(f"Сайтът блокира достъпа ({detail})")
