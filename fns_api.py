"""Client for FNS Open API to fetch receipt data via QR code."""

import os
import time
from datetime import datetime
from typing import Optional
import requests
import xml.etree.ElementTree as ET
import json

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
    print(f"FNS API HTTP {r.status_code} response from {url}:\n{r.text}")
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
    return json.loads(ticket_text)


def qr_to_params(qr: str) -> dict:
    """Convert qr query string into FNS fiscal parameters."""
    parts = dict(item.split("=", 1) for item in qr.split("&"))
    date_raw = parts.get("t", "")
    try:
        dt = datetime.strptime(date_raw, "%Y%m%dT%H%M")
        date_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        date_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    sum_value = int(float(parts.get("s", "0")) * 100)
    return {
        "Sum": sum_value,
        "Date": date_iso,
        "Fn": parts.get("fn", ""),
        "TypeOperation": int(parts.get("n", "1")),
        "FiscalDocumentId": int(parts.get("i", "0")),
        "FiscalSign": parts.get("fp", ""),
        "RawData": True,
    }


def get_receipt_by_qr(qr: str) -> Optional[dict]:
    """Fetch receipt info by QR string. Returns ticket dict or None."""
    if not MASTER_TOKEN:
        print("FNS_MASTER_TOKEN not set; skipping FNS lookup")
        return None
    try:
        token, _ = get_access_token()
        params = qr_to_params(qr)
        msg_id = send_get_ticket(token, params)
        env = poll_message(token, msg_id)
        ticket = parse_ticket(env)
        print(f"FNS ticket data: {json.dumps(ticket, ensure_ascii=False)}")
        return ticket
    except Exception as e:
        print(f"FNS API error: {e}")
        return None

