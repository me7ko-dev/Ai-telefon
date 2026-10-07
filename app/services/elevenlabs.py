"""Синхронизация с ElevenLabs: таен ключ, 4-те инструмента, промпт и първо съобщение на агента."""

import hashlib
import json
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AgentConfig, Business
from app.services.agent_tools import elevenlabs_tool_config, tool_specs
from app.services.prompt import build_first_message, build_system_prompt
from app.services.textutil import now_local

log = logging.getLogger(__name__)


class ElevenLabsError(Exception):
    """Грешка със съобщение на български за панела."""


class NotFound(ElevenLabsError):
    pass


class ElevenLabsClient:
    def __init__(self, api_key: str, base_url: str, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"), headers={"xi-api-key": api_key}, timeout=20, transport=transport
        )

    def _request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        try:
            r = self.http.request(method, path, json=json_body)
        except httpx.HTTPError as e:
            raise ElevenLabsError(f"Няма връзка с ElevenLabs: {e}") from e
        if r.status_code == 401:
            raise ElevenLabsError("ElevenLabs отказа API ключа (401). Провери ELEVENLABS_API_KEY и правата му.")
        if r.status_code == 403:
            raise ElevenLabsError("API ключът няма права за ElevenLabs Agents (403). Дай му права за Agents – запис.")
        if r.status_code == 404:
            raise NotFound(f"ElevenLabs: не е намерено ({path}).")
        if r.status_code >= 400:
            raise ElevenLabsError(f"ElevenLabs върна грешка {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else {}

    def create_secret(self, name: str, value: str) -> str:
        return self._request("POST", "/v1/convai/secrets", {"type": "new", "name": name, "value": value})["secret_id"]

    def create_tool(self, tool_config: dict) -> str:
        return self._request("POST", "/v1/convai/tools", {"tool_config": tool_config})["id"]

    def update_tool(self, tool_id: str, tool_config: dict) -> None:
        self._request("PATCH", f"/v1/convai/tools/{tool_id}", {"tool_config": tool_config})

    def get_agent(self, agent_id: str) -> dict:
        try:
            return self._request("GET", f"/v1/convai/agents/{agent_id}")
        except NotFound:
            raise ElevenLabsError(f"Агент с ID „{agent_id}“ не е намерен. Провери Agent ID.") from None

    def update_agent(self, agent_id: str, body: dict) -> dict:
        return self._request("PATCH", f"/v1/convai/agents/{agent_id}", body)


def make_client() -> ElevenLabsClient | None:
    s = get_settings()
    return ElevenLabsClient(s.elevenlabs_api_key, s.elevenlabs_api_url) if s.elevenlabs_api_key else None


# ---------- конфигурация на фирмата ----------

def get_config(db: Session, business: Business) -> AgentConfig:
    cfg = db.scalar(select(AgentConfig).where(AgentConfig.business_id == business.id))
    if cfg is None:
        cfg = AgentConfig(business_id=business.id)
        db.add(cfg)
        db.commit()
    return cfg


def public_base_url(cfg: AgentConfig) -> str:
    return (cfg.public_base_url or get_settings().public_base_url).rstrip("/")


def tools_url(cfg: AgentConfig, business: Business) -> str:
    return f"{public_base_url(cfg)}/api/b/{business.slug}/tools"


def prompt_texts(business: Business) -> tuple[str, str]:
    return build_system_prompt(business, now_local(business.timezone).date()), build_first_message(business)


def prompt_hash(business: Business) -> str:
    prompt, first = prompt_texts(business)
    return hashlib.sha256((prompt + "\0" + first).encode()).hexdigest()


def agent_summary(agent: dict) -> dict:
    """Кратка информация за агента от GET отговора – за показване в панела."""
    conv = agent.get("conversation_config") or {}
    a = conv.get("agent") or {}
    return {
        "name": agent.get("name", ""),
        "language": a.get("language", ""),
        "llm": (a.get("prompt") or {}).get("llm", ""),
        "tts_model": (conv.get("tts") or {}).get("model_id", ""),
    }


def _record(db: Session, cfg: AgentConfig, ok: bool, message: str) -> None:
    cfg.last_sync_at = datetime.now(UTC).replace(tzinfo=None)
    cfg.last_sync_ok = ok
    cfg.last_sync_message = message
    db.commit()


def _check_ready(cfg: AgentConfig) -> None:
    if not cfg.agent_id:
        raise ElevenLabsError("Въведи Agent ID на агента от ElevenLabs.")
    host = httpx.URL(public_base_url(cfg)).host
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or not public_base_url(cfg).startswith("https://"):
        raise ElevenLabsError(
            "ElevenLabs не може да достигне този адрес. Пусни Cloudflare Tunnel и въведи публичния https:// адрес."
        )


# ---------- синхронизация ----------

def push_prompt(db: Session, business: Business, client: ElevenLabsClient, cfg: AgentConfig) -> dict:
    """Изпраща промпта, първото съобщение и списъка с инструменти към агента. Връща кратка информация за агента."""
    prompt, first = prompt_texts(business)
    agent = client.get_agent(cfg.agent_id)
    current = ((agent.get("conversation_config") or {}).get("agent") or {}).get("prompt") or {}
    ours = list(json.loads(cfg.tool_ids or "{}").values())
    # Пазим инструментите, които собственикът е добавил сам в ElevenLabs.
    tool_ids = [t for t in current.get("tool_ids") or [] if t not in ours] + ours
    client.update_agent(
        cfg.agent_id,
        {
            "conversation_config": {
                "agent": {
                    "first_message": first,
                    "prompt": {"prompt": prompt, "tool_ids": tool_ids, "timezone": business.timezone},
                }
            }
        },
    )
    cfg.pushed_prompt_hash = prompt_hash(business)
    return agent_summary(agent)


def sync_all(db: Session, business: Business, client: ElevenLabsClient) -> str:
    """Пълна синхронизация: таен ключ → 4 инструмента → промпт на агента. Безопасно е да се пуска многократно."""
    cfg = get_config(db, business)
    try:
        _check_ready(cfg)
        secret = get_settings().tool_secret
        fingerprint = hashlib.sha256(secret.encode()).hexdigest()[:16]
        if not cfg.secret_id or cfg.secret_fingerprint != fingerprint:
            cfg.secret_id = client.create_secret(f"ai_receptionist_{business.slug}_{fingerprint[:6]}", secret)
            cfg.secret_fingerprint = fingerprint
            db.commit()

        url = tools_url(cfg, business)
        ids: dict[str, str] = json.loads(cfg.tool_ids or "{}")
        for spec in tool_specs(cfg.cancel_only_own_number):
            conf = elevenlabs_tool_config(spec, url, cfg.secret_id)
            tool_id = ids.get(spec.name)
            if tool_id:
                try:
                    client.update_tool(tool_id, conf)
                except NotFound:
                    tool_id = None  # изтрит в ElevenLabs – създаваме наново
            if not tool_id:
                tool_id = client.create_tool(conf)
            ids[spec.name] = tool_id
            cfg.tool_ids = json.dumps(ids)
            db.commit()
        cfg.tools_url = url

        info = push_prompt(db, business, client, cfg)
    except ElevenLabsError as e:
        _record(db, cfg, False, str(e))
        raise
    message = "Агентът е обновен: промпт, първо съобщение и 4 инструмента."
    if info["language"] and info["language"] != "bg":
        message += f" Внимание: езикът на агента е „{info['language']}“ – смени го на Bulgarian в ElevenLabs."
    _record(db, cfg, True, message)
    return message


def auto_push(business_id: int) -> None:
    """Във фонов режим след промяна в панела: изпраща само промпта, ако нещо е променено."""
    from app.db import SessionLocal

    client = make_client()
    if client is None:
        return
    with SessionLocal() as db:
        business = db.get(Business, business_id)
        cfg = db.scalar(select(AgentConfig).where(AgentConfig.business_id == business_id))
        if not business or not cfg or not cfg.auto_sync or not cfg.agent_id or cfg.tool_ids in ("", "{}"):
            return
        if cfg.pushed_prompt_hash == prompt_hash(business):
            return
        try:
            push_prompt(db, business, client, cfg)
            _record(db, cfg, True, "Промптът е изпратен автоматично след промяна.")
        except ElevenLabsError as e:
            log.warning("Автоматичното изпращане на промпта не успя: %s", e)
            _record(db, cfg, False, f"Автоматичното изпращане не успя: {e}")
