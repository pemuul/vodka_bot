"""Client for FNS Open API to fetch receipt data via QR code."""

import json
import logging
import os
import re
import time
from datetime import datetime
from urllib.parse import parse_qsl, unquote_plus, urlsplit
from typing import Optional, Tuple

import requests
import xml.etree.ElementTree as ET

AUTH_ENDPOINT = os.getenv(
    "FNS_AUTH_ENDPOINT",
    "https://openapi.nalog.ru:8090/open-api/AuthService/0.1",
)
ASYNC_ENDPOINT = os.getenv(
    "FNS_ASYNC_ENDPOINT",
    "https://openapi.nalog.ru:8090/open-api/ais3/KktService/0.1",
)
MASTER_TOKEN = os.getenv("FNS_MASTER_TOKEN", "")

NAMESPACES = {
    "soap": "http://schemas.xmlsoap.org/soap/envelope/",
    "cons": "urn://x-artefacts-gnivc-ru/inplat/servin/OpenApiMessageConsumerService/types/1.0",
    "asyn": "urn://x-artefacts-gnivc-ru/inplat/servin/OpenApiAsyncMessageConsumerService/types/1.0",
    "auth": "urn://x-artefacts-gnivc-ru/ais3/kkt/AuthService/types/1.0",
    "kkt": "urn://x-artefacts-gnivc-ru/ais3/kkt/KktTicketService/types/1.0",
}


logger = logging.getLogger(__name__)


def _truncate_payload(data: object, limit: int = 800) -> str:
    """Format payload objects for logging without flooding the console."""

    if isinstance(data, str):
        text = data
    else:
        try:
            text = json.dumps(data, ensure_ascii=False, default=str)
        except Exception:
            text = repr(data)
    text = text.replace("\n", " ")
    if len(text) > limit:
        return f"{text[:limit]}… (truncated)"
    return text


def _post_soap(url: str, soap_action: str, xml_body: str, extra_headers: Optional[dict] = None) -> ET.Element:
    """Send SOAP request and return parsed envelope."""
    headers = {
        "Content-Type": "text/xml;charset=UTF-8",
        "SOAPAction": f"\"urn:{soap_action}\"",
    }
    if extra_headers:
        headers.update(extra_headers)
    r = requests.post(url, data=xml_body.encode("utf-8"), headers=headers, timeout=30)
    if len(r.content) > 1_000_000:
        raise RuntimeError(f"Response size {len(r.content)} exceeds 1MB limit")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
    envelope = ET.fromstring(r.text)
    fault = envelope.find(".//soap:Fault", NAMESPACES)
    if fault is not None:
        raise RuntimeError(f"SOAP Fault: {fault.findtext('faultstring')}")
    return envelope


def get_access_token() -> tuple[str, datetime]:
    """Exchange master token for temporary access token."""
    body = f"""
    <soapenv:Envelope xmlns:soapenv="{NAMESPACES['soap']}" xmlns:cons="{NAMESPACES['cons']}">
      <soapenv:Body>
        <cons:GetMessageRequest>
          <cons:Message>
            <auth:AuthRequest xmlns:auth="{NAMESPACES['auth']}">
              <auth:AuthAppInfo>
                <auth:MasterToken>{MASTER_TOKEN}</auth:MasterToken>
              </auth:AuthAppInfo>
            </auth:AuthRequest>
          </cons:Message>
        </cons:GetMessageRequest>
      </soapenv:Body>
    </soapenv:Envelope>
    """
    env = _post_soap(AUTH_ENDPOINT, "GetMessageRequest", body)
    token = env.findtext(".//auth:Token", namespaces=NAMESPACES)
    expires = env.findtext(".//auth:ExpireTime", namespaces=NAMESPACES)
    return token, datetime.fromisoformat(expires)


def send_get_ticket(access_token: str, params: dict) -> str:
    """Send GetTicket request and return MessageId."""
    get_ticket_xml = f"""
      <kkt:GetTicketRequest xmlns:kkt="{NAMESPACES['kkt']}">
        <kkt:GetTicketInfo>
          <kkt:Sum>{params['Sum']}</kkt:Sum>
          <kkt:Date>{params['Date']}</kkt:Date>
          <kkt:Fn>{params['Fn']}</kkt:Fn>
          <kkt:TypeOperation>{params['TypeOperation']}</kkt:TypeOperation>
          <kkt:FiscalDocumentId>{params['FiscalDocumentId']}</kkt:FiscalDocumentId>
          <kkt:FiscalSign>{params['FiscalSign']}</kkt:FiscalSign>
          <kkt:RawData>{str(params['RawData']).lower()}</kkt:RawData>
        </kkt:GetTicketInfo>
      </kkt:GetTicketRequest>
    """
    body = f"""
    <soapenv:Envelope xmlns:soapenv="{NAMESPACES['soap']}" xmlns:asyn="{NAMESPACES['asyn']}">
      <soapenv:Body>
        <asyn:SendMessageRequest>
          <asyn:Message>
            {get_ticket_xml}
          </asyn:Message>
        </asyn:SendMessageRequest>
      </soapenv:Body>
    </soapenv:Envelope>
    """
    env = _post_soap(
        ASYNC_ENDPOINT,
        "SendMessageRequest",
        body,
        extra_headers={"FNS-OpenApi-Token": access_token},
    )
    return env.findtext(".//asyn:MessageId", namespaces=NAMESPACES)


def poll_message(access_token: str, message_id: str, timeout: int = 60) -> ET.Element:
    """Poll GetMessageRequest until COMPLETED or timeout."""
    template = f"""
    <soapenv:Envelope xmlns:soapenv="{NAMESPACES['soap']}" xmlns:asyn="{NAMESPACES['asyn']}">
      <soapenv:Body>
        <asyn:GetMessageRequest>
          <asyn:MessageId>{message_id}</asyn:MessageId>
        </asyn:GetMessageRequest>
      </soapenv:Body>
    </soapenv:Envelope>
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        env = _post_soap(
            ASYNC_ENDPOINT,
            "GetMessageRequest",
            template,
            extra_headers={"FNS-OpenApi-Token": access_token},
        )
        status_el = env.find(".//asyn:ProcessingStatus", NAMESPACES)
        status = status_el.text if status_el is not None else "UNKNOWN"
        if status == "COMPLETED":
            return env
        time.sleep(1.1)
    raise TimeoutError(f"Ответ не получен за {timeout} с.")


def parse_ticket(env: ET.Element) -> dict:
    """Extract JSON ticket from response."""
    ticket_text = env.findtext(".//kkt:Ticket", namespaces=NAMESPACES)
    if ticket_text is None:
        logger.error(
            "[FNS] В ответе отсутствует элемент Ticket: %s",
            _truncate_payload(ET.tostring(env, encoding="unicode")),
        )
        raise RuntimeError("FNS ticket payload is missing")
    return json.loads(ticket_text)


def _parse_qr_datetime(value: str) -> datetime:
    """Parse the QR timestamp supporting multiple formats.

    We tolerate timestamps with or without separators and with minute or
    second precision.  ``datetime.strptime`` happily *misparses* a value like
    ``20250412T1942`` against a ``%H%M%S`` mask (yielding ``19:04:02``), so we
    normalise the string before selecting the appropriate layout.
    """

    cleaned = unquote_plus(value or "").strip()
    if not cleaned:
        raise ValueError("QR timestamp (t=) is missing")

    cleaned = cleaned.upper()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1]

    # Try strict ISO parsing first (handles "2025-04-12T19:42" etc.).
    for candidate in (cleaned, cleaned.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass

    # Remove separators to inspect the raw digit sequence while keeping the "T".
    normalized = cleaned.replace("-", "").replace(":", "")
    match = re.fullmatch(r"(\d{8})T(\d{2})(\d{2})(\d{2})?", normalized)
    if match:
        date_part, hour, minute, second = match.groups()
        iso_value = (
            f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}T"
            f"{hour}:{minute}:{second or '00'}"
        )
        return datetime.fromisoformat(iso_value)

    raise ValueError(
        "Не удалось распарсить время из QR (ожидаются форматы YYYYMMDDTHHMM или YYYYMMDDTHHMMSS)"
    )


def _split_qr_query(qr: str) -> dict:
    """Return dict of parameters from QR string or URL."""

    qr = qr.strip()
    if not qr:
        return {}
    # Strip leading URL parts if someone passed the full link.
    if "?" in qr or "=" not in qr.split("&", 1)[0]:
        qr = urlsplit(qr).query or qr.split("?", 1)[-1]

    # parse_qsl handles URL decoding and duplicate keys gracefully.
    return {key.lower(): value for key, value in parse_qsl(qr, keep_blank_values=True)}


def _resolve_qr_link(qr: str) -> str:
    """Follow short links (e.g., clck.ru) to extract actual QR query."""

    qr = qr.strip()
    if not qr or not qr.lower().startswith(("http://", "https://")):
        return qr
    try:
        resp = requests.get(qr, allow_redirects=True, timeout=10)
        if resp.url and resp.url != qr:
            logger.info("[FNS] QR link expanded: %s -> %s", qr, resp.url)
            return resp.url
    except Exception as exc:  # pragma: no cover - network issues
        logger.warning("[FNS] Не удалось раскрыть QR ссылку %s: %s", qr, exc)
    return qr


def qr_to_params(qr: str) -> dict:
    """Convert qr query string into FNS fiscal parameters."""

    resolved_qr = _resolve_qr_link(qr)
    parts = _split_qr_query(resolved_qr)
    if not parts:
        raise ValueError("QR строка не содержит параметров")

    # Некоторые сканеры/сервисы отдают дату под альтернативными ключами.
    t_value = (
        parts.get("t")
        or parts.get("dt")
        or parts.get("date")
        or parts.get("datetime")
        or ""
    )
    dt = _parse_qr_datetime(t_value)
    date_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")

    try:
        sum_value = int(round(float(parts.get("s", "0")) * 100))
    except ValueError as exc:
        raise ValueError("Некорректная сумма в QR (s=)") from exc

    required_fields = {"fn": "Fn", "i": "FiscalDocumentId", "fp": "FiscalSign"}
    params = {
        "Sum": sum_value,
        "Date": date_iso,
        "TypeOperation": int(parts.get("n", "1") or 1),
        "RawData": True,
    }
    for key, dest in required_fields.items():
        value = parts.get(key)
        if value in (None, ""):
            raise ValueError(f"В QR отсутствует обязательный параметр {key}=*")
        params[dest] = int(value) if dest == "FiscalDocumentId" else value

    return params


def _describe_exception(exc: Exception) -> str:
    """Return a compact description of an exception for logs and UI."""

    name = exc.__class__.__name__
    message = str(exc) or name
    return f"{name}: {message}" if message != name else name


def get_receipt_by_qr(qr: str) -> Tuple[Optional[dict], Optional[str]]:
    """Fetch receipt info by QR string.

    Returns a tuple of (ticket dict or None, error text or None).
    """
    if not MASTER_TOKEN:
        warning = "FNS master token is not configured"
        logger.warning("[FNS] %s", warning)
        return None, warning
    logger.info("[FNS] Запрос по QR: %s", qr)
    try:
        resolved_qr = _resolve_qr_link(qr)
        if resolved_qr != qr:
            logger.info("[FNS] QR link expanded: %s -> %s", qr, resolved_qr)
        token, _ = get_access_token()
        params = qr_to_params(resolved_qr)
        logger.info("[FNS] Параметры запроса: %s", _truncate_payload(params))
        msg_id = send_get_ticket(token, params)
        logger.info("[FNS] Получен MessageId: %s", msg_id)
        env = poll_message(token, msg_id)
        raw_xml = ET.tostring(env, encoding="unicode")
        logger.info("[FNS] Ответ сервиса (XML): %s", _truncate_payload(raw_xml))
        ticket = parse_ticket(env)
        logger.info("[FNS] Распарсенный чек: %s", _truncate_payload(ticket))
        return ticket, None
    except ValueError as e:
        warning = _describe_exception(e)
        logger.warning("[FNS] QR не содержит необходимых данных: %s", warning)
        return None, warning
    except Exception as e:
        logger.exception("[FNS] Ошибка получения чека по QR: %s", qr)
        return None, _describe_exception(e)
