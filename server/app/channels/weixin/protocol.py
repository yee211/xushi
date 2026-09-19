"""Small, OpenClaw-independent representation of the Tencent iLink wire protocol."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Credentials:
    account_id: str
    bot_token: str
    base_url: str
    admin_user_id: str = ""


@dataclass(frozen=True)
class InboundText:
    account_id: str
    sender_id: str
    message_id: str
    text: str
    context_token: str
    received_at: datetime
    run_id: str = ""


def extract_text_items(message: dict, account_id: str, received_at: datetime) -> InboundText | None:
    """Return one normalized text message; voice transcripts are accepted as text."""
    if int(message.get("message_type") or 0) != 1:
        return None
    parts: list[str] = []
    for item in message.get("item_list") or []:
        item_type = int(item.get("type") or 0)
        if item_type == 1:
            value = (item.get("text_item") or {}).get("text")
        elif item_type == 3:
            value = (item.get("voice_item") or {}).get("text")
        else:
            continue
        if value:
            parts.append(str(value))
    text = "\n".join(parts).strip()
    sender_id = str(message.get("from_user_id") or "").strip()
    message_id = str(message.get("message_id") or message.get("client_id") or "").strip()
    if not text or not sender_id or not message_id:
        return None
    return InboundText(account_id, sender_id, message_id, text,
                       str(message.get("context_token") or ""), received_at,
                       str(message.get("run_id") or ""))
