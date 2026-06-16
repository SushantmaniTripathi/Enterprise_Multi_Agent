import os
import re
import time
import random
import threading
import asyncio
import shutil
import telebot
import requests
import pandas as pd
import datetime
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
import base64
import json
import csv
from io import BytesIO
import hashlib
from datetime import datetime, timezone, timedelta
import telethon
from telethon import types
from telethon.sync import TelegramClient

# Langchain / Qdrant imports
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# ============================================================================
# 1. CONFIGURATION & PERSONAS
# ============================================================================
load_dotenv()

# Env Vars
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY")
CHAT_ID = int(os.getenv("GROUP_CHAT_ID") or 0)
ENABLE_AUTO_TOPICS = os.getenv("ENABLE_AUTO_TOPICS", "true").lower() == "true"

# Telethon Config
API_ID    = os.getenv("TELEGRAM_API_ID")
API_HASH  = os.getenv("TELEGRAM_API_HASH")
SESSION_FILE = "bot_session"
HISTORY_INTERVAL_HRS = 24
ENABLE_IMAGE_OCR = True
EXTRA_TARGET_USERNAMES = ["Sushant"]

# Bot Tokens
BOT_TOKENS = {
    "helper": os.getenv("BOT_HELPER_TOKEN"),
    "curious": os.getenv("BOT_CURIOUS_TOKEN"),
    "tech": os.getenv("BOT_TECH_TOKEN"),
    "skeptic": os.getenv("BOT_SKEPTIC_TOKEN"),
}

# Qdrant & Path Config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
OFFICIAL_COLLECTION = "official_docs"
COMMUNITY_COLLECTION = "community_data"
EMBEDDING_DIM = 1536
PDFS_DIR = os.path.join(BASE_DIR, "pdfs")
JSON_HISTORY = os.path.join(BASE_DIR, "messages.json")
CSV_HISTORY = os.path.join(PDFS_DIR, "telegram_group_history.csv")

# Bot Personas (length is set per-question in get_persona_prompt — not hardcoded here)
BOT_PERSONAS = {
    "helper": {
        "style": "clear, warm, and direct",
        "traits": "Answer the question directly with complete facts. Use clean, simple language.",
        "tone": "friendly and confident, like a knowledgeable colleague",
        "example": "deod is decentrawood's metaverse token — used for staking, marketplace buys, and in-game rewards."
    },
    "curious": {
        "style": "engaged and thoughtful",
        "traits": "Answer the question first with real detail, then one brief follow-up thought. Sound human, not robotic.",
        "tone": "warm and inquisitive, like someone who enjoys learning",
        "example": "it's a polygon-based metaverse token — staking and events are where most of the action is tbh."
    },
    "tech": {
        "style": "technically precise but conversational",
        "traits": "Lead with the technical truth. Use accurate terms like 'smart contract', 'on-chain', 'protocol'. No unnecessary complexity.",
        "tone": "calm and sharp, like a senior developer explaining simply",
        "example": "deod is an erc-20 on polygon — contracts handle staking rewards and marketplace txs on-chain."
    },
    "skeptic": {
        "style": "honest, analytical, and balanced",
        "traits": "Answer factually first. Acknowledge strengths, then one fair consideration. Never dismissive — always constructive.",
        "tone": "measured and real, like a trusted advisor who thinks critically",
        "example": "deod powers the metaverse economy — adoption and exchange liquidity are the real tests though."
    }
}

# Conversation Dynamics
MIN_REPLY_DELAY = 5
MAX_REPLY_DELAY = 15
AUTO_TOPIC_MIN_INTERVAL = 3000
AUTO_TOPIC_MAX_INTERVAL = 6900
MIN_IDLE_TIME_FOR_AUTO_TOPICS = 4000
RAG_REINDEX_INTERVAL = 21600

# Keywords that indicate a real question worth answering
QUESTION_KEYWORDS = [
    "how", "what", "when", "where", "why", "who",
    "is", "are", "can", "does", "do", "will", "should",
    "any", "anyone", "which", "explain", "tell", "guide", "walk",
    "latest", "recent", "new", "events", "event", "about",
    "deod", "decentrawood", "token", "price", "buy", "sell",
    "airdrop", "listing", "exchange", "wallet", "staking", "reward",
    "winner", "winners", "campaign", "bonanza",
    "regional", "group", "link", "channel", "join", "community", "provide", "grp"
]

# Greeting words
GREETING_WORDS = [
    "hi", "hello", "hey", "gm", "good morning", "good evening",
    "good night", "good afternoon", "hii", "helo", "sup", "wassup"
]

# Admins
ADMINS = {
    "sam_support007"  : (868598080,  True),
    "hossein_teilor"  : (339437672,  True),
    "decentrawoodcom" : (1602118476, True),
}

ADMIN_USERNAMES     = list(ADMINS.keys())
ADMIN_IDS           = {uid for uid, _ in ADMINS.values()}
ANNOUNCER_IDS       = {uid for uid, ann in ADMINS.values() if ann}
ANNOUNCER_USERNAMES = {u for u, (_, ann) in ADMINS.items() if ann}

# ── FIX 2 (part A): base exclude set — real Telegram usernames are added
#    dynamically at index-build time via _get_bot_exclude_set() below ──
BOT_INDEX_EXCLUDE_USERNAMES = {
    "helper", "curious", "tech", "skeptic",
    "decentrawood helper", "decentrawood curious",
    "decentrawood tech", "decentrawood skeptic",
}

# Idle Topic Starters
IDLE_OPENERS = [
    "anyone looking at deod today?", "The decentrawood roadmap is underrated check it out ??",
    "thoughts on staking deod?", "decentrawood vs other eco projects — how do you see it?",
    "ngl, deod community is growing faster than i expected",
    "what did everyone think about the latest decentrawood update?",
    "predictions for deod this year? curious", "the tokenomics on deod are actually solid imo",
    "does anyone actually use the decentrawood platform yet?",
    "been following deod since launch — the progress is real",
    "decentrawood's green angle is actually their biggest strength",
    "anyone else holding deod long term?", "quick take: deod is massively overlooked",
    "what's the most underrated feature of decentrawood?",
    "just checked the deod chart… interesting movement",
    "decentrawood partnership news coming? wonder what's next",
    "have you guys explored the staking dashboard?",
    "the deod contract is solid — verified and clean",
    "anyone else bullish on deod q2?"
]

FOLLOW_TOPIC_HOOKS = [
    "what do you guys actually think about that?", "fr though — anybody have a different take?",
    "interesting, i was wondering the same thing", "that's the part most people sleep on ngl",
    "i mean honestly that's why i got into deod in the first place",
    "same question i had last time..", "yeah i checked that too — makes sense"
]

# State
last_user_message_time = time.time()
CHAT_STATE = {'history': [], 'last_answerer': None, 'last_active': 0}

# ============================================================================
# 2. UTILS
# ============================================================================
client = OpenAI(api_key=OPENAI_API_KEY)

def ask_llm(prompt: str, timeout: int = 15, max_tokens: int = 280) -> str:
    current_date = datetime.now().strftime("%Y-%m-%d")
    messages = [
        {"role": "system", "content": f"System: Current Date is {current_date}. You are an AI persona for Decentrawood. Be helpful, accurate, and write complete sentences — never single-word replies."},
        {"role": "user", "content": prompt}
    ]
    res = client.chat.completions.create(
        model="gpt-4o-mini", messages=messages, temperature=0.7,
        timeout=timeout, max_tokens=max_tokens
    )
    return res.choices[0].message.content.strip()

def describe_image(image_bytes: bytes) -> str:
    try:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "Transcribe ALL visible text from this image into plain English. "
                        "Rules: (1) Plain text only — no emojis, no bullet symbols, no markdown. "
                        "(2) Preserve original words, names, numbers, and dates exactly. "
                        "(3) If the image contains no readable text, return the single word: NONE."
                    )},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                ],
            }],
            max_tokens=200,
            timeout=15
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"      ⚠️ OCR Error: {e}")
        return "[OCR Failed]"

def _clean_text(text: str) -> str:
    import unicodedata
    if not text:
        return ""
    result = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat[0] in ('L', 'N', 'P', 'Z') or ch in (' ', '\n', '\r', '\t'):
            result.append(ch)
        elif ord(ch) < 128:
            result.append(ch)
    cleaned = ''.join(result)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

def human_delay(min_s=5, max_s=15):
    time.sleep(random.randint(min_s, max_s))

def get_crypto_price(symbol: str):
    if not CMC_API_KEY: return None
    try:
        r = requests.get(
            "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
            headers={"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"},
            params={"symbol": symbol, "convert": "USD"}, timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            q = data["data"][symbol]["quote"]["USD"]
            return round(q["price"], 6), round(q["percent_change_24h"], 2)
    except:
        pass
    return None

def _classify_query_intent(message: str) -> str:
    """overview = guide/walk-through; events = campaigns/airdrops; fact = default."""
    msg = (message or "").lower()
    if any(k in msg for k in [
        "guide", "walk me", "walk through", "walk u", "explain", "overview",
        "what is deod", "what is decentrawood", "tell me about", "through deod",
        "about deod", "about decentrawood",
    ]):
        return "overview"
    if any(k in msg for k in [
        "latest", "recent", "new", "events", "event", "campaign", "bonanza",
        "airdrop", "giveaway", "listing", "happening",
    ]):
        return "events"
    return "fact"

def _min_words_for_intent(intent: str) -> int:
    return {"overview": 18, "events": 14, "fact": 8}.get(intent, 8)

def _length_instruction(intent: str) -> str:
    if intent == "overview":
        return (
            "LENGTH: Write 2-4 complete sentences (roughly 25-60 words). "
            "Cover what DEOD/Decentrawood is, what the token does, and how users engage "
            "(metaverse, staking, marketplace, events). This is a walk-through — not a one-liner."
        )
    if intent == "events":
        return (
            "LENGTH: Write 2-3 complete sentences (roughly 20-45 words). "
            "Name specific recent campaigns, dates, or events from Context when available."
        )
    return "LENGTH: One or two complete sentences (roughly 12-30 words). Be direct but never reply with only a single word."

def get_persona_prompt(bot_key: str, intent: str = "fact") -> str:
    persona = BOT_PERSONAS.get(bot_key, BOT_PERSONAS["helper"])
    current_date_str = datetime.now().strftime("%B %d, %Y")
    return f"""You are {bot_key.upper()} in a Telegram group about Decentrawood.
Today is {current_date_str}.
TRAITS: {persona['traits']}
TONE: {persona['tone']}
STYLE: "{persona['example']}"
{_length_instruction(intent)}

RULES:
1. NO AI SPEAK: Never use words like "furthermore", "delve", "explore", "platform".
2. IMPERFECT TEXTING: Use lowercase naturally. Don't use exclamation points frequently. Do NOT sound overly excited or professional.
3. NEVER REPEAT: Do NOT use the exact same phrase from your Style example. Mix it up.
4. NEVER reply with only a token name (e.g. just "DEOD" or just "token"). Always write full sentences.
"""

# ── FIX 2 (part B): fetch real bot usernames from Telegram API ──
def _get_bot_exclude_set() -> set:
    """Returns BOT_INDEX_EXCLUDE_USERNAMES + actual Telegram usernames of all 4 bots."""
    exclude = set(BOT_INDEX_EXCLUDE_USERNAMES)
    for name, token in BOT_TOKENS.items():
        if not token:
            continue
        try:
            res = requests.get(
                f"https://api.telegram.org/bot{token}/getMe", timeout=10
            ).json()
            if res.get("ok"):
                uname = (res["result"].get("username") or "").lower().lstrip("@")
                first = (res["result"].get("first_name") or "").lower().strip()
                if uname:
                    exclude.add(uname)
                if first:
                    exclude.add(first)
        except Exception as e:
            print(f"⚠️  Could not fetch username for {name} bot: {e}")
    print(f"🔒 Bot exclude set: {exclude}")
    return exclude

# --- History Extraction Helpers ---
def _sender_name_telethon(msg) -> str:
    try:
        if msg.sender:
            s = msg.sender
            return (f"@{s.username}" if getattr(s, "username", None)
                    else f"{getattr(s,'first_name','') or ''} {getattr(s,'last_name','') or ''}".strip()
                    or str(s.id))
    except:
        pass
    return "?"

def _media_desc_telethon(msg) -> str:
    if not msg.media: return ""
    return type(msg.media).__name__.replace("MessageMedia", "")

def load_existing_history() -> list:
    try:
        if os.path.exists(JSON_HISTORY):
            with open(JSON_HISTORY, "r", encoding="utf-8") as f:
                return json.load(f).get("messages", [])
    except:
        pass
    return []

def save_history(messages: list):
    messages.sort(key=lambda m: m.get("date", ""))
    with open(JSON_HISTORY, "w", encoding="utf-8") as f:
        json.dump({
            "group_id": CHAT_ID,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_messages": len(messages),
            "messages": messages
        }, f, ensure_ascii=False, indent=2)
    with open(CSV_HISTORY, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "datetime", "username", "message"])
        writer.writeheader()
        for msg in messages:
            message_text = msg.get("text", "")
            media_content = msg.get("media", "")
            if media_content and "[Content:" in media_content:
                message_text = message_text + " [OCR: " + media_content + "]"
            writer.writerow({
                "id": msg.get("id", ""),
                "datetime": msg.get("date", ""),
                "username": msg.get("sender", ""),
                "message": message_text
            })

def merge_history(existing: list, new_msgs: list) -> tuple[list, int]:
    seen_ids = {m["id"] for m in existing}
    added = 0
    for m in new_msgs:
        if m["id"] not in seen_ids:
            existing.append(m)
            seen_ids.add(m["id"])
            added += 1
    return existing, added

LIVE_CSV = os.path.join(PDFS_DIR, "live_updates.csv")
PHOTO_HASH_CACHE = os.path.join(PDFS_DIR, "photo_hashes.json")

def load_photo_hashes() -> set:
    try:
        if os.path.exists(PHOTO_HASH_CACHE):
            with open(PHOTO_HASH_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("hashes", []))
    except:
        pass
    return set()

def save_photo_hash(photo_hash: str):
    try:
        hashes = list(load_photo_hashes())
        if photo_hash not in hashes:
            hashes.append(photo_hash)
        with open(PHOTO_HASH_CACHE, "w", encoding="utf-8") as f:
            json.dump({"hashes": hashes}, f, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to save photo hash: {e}")

def get_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()

def log_message_to_history(id, sender, sender_id, text, media="", reply_to=None):
    try:
        file_exists = os.path.exists(LIVE_CSV)
        with open(LIVE_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "datetime", "username", "message"])
            if not file_exists:
                writer.writeheader()
            message_text = _clean_text(text or "")
            if media and "[Content:" in media:
                ocr_payload = _clean_text(media)
                message_text = (message_text + " " + ocr_payload) if message_text else ocr_payload
            writer.writerow({
                "id": id,
                "datetime": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "username": _clean_text(sender or ""),
                "message": message_text
            })
    except Exception as e:
        print(f"⚠️ Failed to log live message: {e}")

def extract_history_once(client: TelegramClient, offset_date=None, target_list=None) -> list:
    try:
        entity = client.get_entity(CHAT_ID)
        messages = []
        for msg in client.iter_messages(entity, limit=5000):
            if offset_date and msg.date < offset_date:
                break
            if not (msg.text or msg.media or getattr(msg, 'caption', None)):
                continue
            if target_list:
                try:
                    s_uname = (msg.sender.username if msg.sender and hasattr(msg.sender, "username") else "") or ""
                except:
                    s_uname = ""
                if not any(t.lower() == s_uname.lower() for t in target_list):
                    continue
            media_desc = _media_desc_telethon(msg)
            msg_text = msg.text or getattr(msg, 'caption', '') or ""
            if ENABLE_IMAGE_OCR and media_desc == "Photo":
                print(f"   🔍 Transcribing image in message...")
                try:
                    photo_bytes = client.download_media(msg, file=BytesIO())
                    photo_bytes.seek(0)
                    transcription = describe_image(photo_bytes.read())
                except Exception as e:
                    print(f" Failed to process photo #{msg.id}: {e}")
            messages.append({
                "id": msg.id,
                "date": msg.date.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "sender": _sender_name_telethon(msg),
                "sender_id": msg.sender_id,
                "text": msg_text,
                "media": media_desc,
                "reply_to": msg.reply_to_msg_id,
                "views": getattr(msg, "views", None),
            })
        return messages
    except telethon.errors.rpcerrorlist.BotMethodInvalidError:
        print("⚠️ History Extraction Warning: Bot tokens restricted from GetHistory. Bot will only learn from new messages.")
        return []
    except Exception as e:
        print(f"⚠️ History Extraction Error: {e}")
        return []

def run_history_extraction_loop():
    if not all([API_ID, API_HASH, BOT_TOKENS.get('helper')]):
        print("⚠️ Missing Telethon configuration. Skipping history extraction.")
        return

    print("📨 [Background] Starting History Extractor (Telethon)...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    tg_client = TelegramClient(SESSION_FILE, int(API_ID), API_HASH, connection_retries=3, timeout=10)
    try:
        tg_client.start()
        while True:
            print("🔄 [Background] Periodically Fetching Group History...")

            # ── FIX 1: Only track human admins + extra users — never add bot usernames ──
            target_list = list(ADMIN_USERNAMES) + EXTRA_TARGET_USERNAMES
            # (Bot usernames intentionally removed — bots' own messages must NOT be indexed)

            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            new_msgs = extract_history_once(tg_client, offset_date=since_24h, target_list=target_list)

            existing = load_existing_history()
            merged, added = merge_history(existing, new_msgs)
            save_history(merged)
            print(f"✅ [Background] History Updated: {added} new targeted messages. Total: {len(merged)}")

            try:
                build_index()
                init_rag()
                print("✅ [Background] RAG refreshed with new message history.")
            except:
                pass

            time.sleep(HISTORY_INTERVAL_HRS * 3600)
    except Exception as e:
        print(f"❌ [Background] History Extractor Error: {e}")
    finally:
        try:
            if tg_client.is_connected():
                tg_client.disconnect()
        except:
            pass
        asyncio.set_event_loop(None)
        loop.close()

# ============================================================================
# 3. RAG CORE
# ============================================================================
embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)

_qdrant_client = None

def init_rag():
    global _qdrant_client
    try:
        _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    except Exception as e:
        print(f"⚠️ Qdrant connection failed: {e}")
        _qdrant_client = None

CORE_FACTS = """
=== DECENTRAWOOD CORE DATA ===
• Project: Decentrawood ($DEOD)
• Official Site: https://decentrawood.com/
• RAG Status: Aggregating Official Docs, Admin Announcements, and Community History.
• Note: For the most up-to-date info, check pinned messages in the group.
"""

def _clean_source(source: str) -> str:
    return os.path.basename(source)

def retrieve_with_score(query: str, k: int = 10):
    init_rag()
    if not _qdrant_client:
        return CORE_FACTS, 1.0

    query_vector = embeddings.embed_query(query)

    off_res = []
    try:
        off_res = _qdrant_client.query_points(
            collection_name=OFFICIAL_COLLECTION, query=query_vector, limit=8, with_payload=True
        ).points
    except Exception as e:
        print(f"❌ Qdrant official search error: {e}")

    com_res = []
    try:
        com_res = _qdrant_client.query_points(
            collection_name=COMMUNITY_COLLECTION, query=query_vector, limit=k, with_payload=True
        ).points
    except Exception as e:
        print(f"❌ Qdrant community search error: {e}")

    if not off_res and not com_res:
        return CORE_FACTS, 1.0

    formatted_official = []
    for hit in off_res:
        score = 1.0 - hit.score
        payload = hit.payload or {}
        src = _clean_source(payload.get("source", payload.get("filename", "unknown")))
        boost = -0.4 if any(kw in src.lower() for kw in ["faq", "schedule", "roadmap", "manual"]) else 0.0
        formatted_official.append((
            f"SOURCE: {src} [OFFICIAL]\nCONTENT:\n{payload.get('page_content', '')}",
            score + boost
        ))

    formatted_community = []
    for hit in com_res:
        score = 1.0 - hit.score
        payload = hit.payload or {}
        is_announcement = payload.get("category") == "announcement"
        is_admin = payload.get("is_admin", False)
        recency = float(payload.get("recency_score", 0.5))
        date_str = payload.get("date_str", "")

        if is_announcement:
            tag = "[OFFICIAL ANNOUNCEMENT]"
        elif is_admin:
            tag = "[OFFICIAL ADMIN]"
        else:
            tag = "[COMMUNITY]"

        authority_boost = -0.5 if is_announcement else (-0.3 if is_admin else 0.0)
        recency_boost = -0.2 * recency if (is_admin or is_announcement) else 0.0
        final_score = score + authority_boost + recency_boost
        date_note = f" [{date_str[:10]}]" if date_str else ""
        formatted_community.append((
            f"SOURCE: {_clean_source(payload.get('source', 'csv'))} {tag}{date_note}\nCONTENT:\n{payload.get('page_content', '')}",
            final_score
        ))

    all_res = (
        sorted(formatted_official, key=lambda x: x[1])[:8] +
        sorted(formatted_community, key=lambda x: x[1])[:max(0, k - len(formatted_official))]
    )
    if not all_res:
        return CORE_FACTS, 1.0
    ctx = "\n---\n".join([CORE_FACTS] + [r[0] for r in all_res])
    avg = sum(r[1] for r in all_res) / len(all_res)
    return ctx, avg

def retrieve_recent_conversations(query: str, k: int = 3, keywords=None):
    if not _qdrant_client: return "", 1.0
    aug = f"{query} {' '.join(keywords)}" if keywords else query
    try:
        query_vector = embeddings.embed_query(aug)
        results = _qdrant_client.query_points(
            collection_name=COMMUNITY_COLLECTION, query=query_vector, limit=k * 2, with_payload=True
        ).points
        scored = []
        for hit in results:
            score = 1.0 - hit.score
            payload = hit.payload or {}
            bonus = -0.15 if re.search(r'\d{4}', payload.get('page_content', '')) else 0
            scored.append((payload, score + bonus))
        if not scored:
            return "", 1.0
        scored = sorted(scored, key=lambda x: x[1])[:k]
        texts = [
            f"SOURCE: {_clean_source(p.get('source', 'csv'))}\nCONTENT:\n{p.get('page_content', '')}"
            for p, _ in scored
        ]
        avg = sum(s for _, s in scored) / len(scored)
        return "\n---\n".join(texts), avg
    except Exception as e:
        print(f"❌ Qdrant recent-conversations error: {e}")
        return "", 1.0

def _is_price_intent(message: str) -> bool:
    msg = (message or "").lower()
    has_price_term = re.search(r"\b(price|value|worth)\b", msg) is not None
    if not has_price_term:
        return False
    exclusions = [
        "bonanza", "prize", "prizes", "reward", "rewards", "airdrop", "campaign",
        "event", "winner", "winners", "winning", "win", "process", "steps", "after winning",
        "after win", "how to win", "how win"
    ]
    return not any(ex in msg for ex in exclusions)

def _rag_search_query(message: str, intent: str) -> str:
    """Expand retrieval query so guide/event questions pull the right chunks."""
    base = (message or "").strip()
    if intent == "overview":
        return (
            f"{base} Decentrawood DEOD metaverse token polygon staking "
            "marketplace ecosystem what is utility"
        )
    if intent == "events":
        year = datetime.now().year
        return f"{base} Decentrawood DEOD latest events campaigns airdrop bonanza {year}"
    return base

def _is_bad_reply(reply: str, intent: str) -> bool:
    """Reject fragment / echo answers before sending to Telegram."""
    if not reply or not reply.strip():
        return True
    text = reply.strip()
    words = text.split()
    min_w = _min_words_for_intent(intent)
    if len(words) < min_w:
        return True
    # Single-token or token-name-only replies
    lower = text.lower().rstrip(".,!?")
    if lower in ("deod", "token", "decentrawood", "token)"):
        return True
    if len(words) <= 2 and any(w.lower().rstrip(".,!?)") in ("deod", "token", "decentrawood") for w in words):
        return True
    # Broken fragment: ends with unmatched paren, very short
    if text.endswith(")") and "(" not in text and len(words) < 8:
        return True
    # Mostly punctuation / garbage
    alpha = sum(c.isalnum() for c in text)
    if alpha < len(text) * 0.5:
        return True
    return False

def _build_rag_llm_prompt(bot_key: str, message: str, ctx: str, intent: str, retry: bool = False) -> str:
    persona = get_persona_prompt(bot_key, intent)
    retry_note = (
        "\nRETRY: Your last answer was too short or incomplete. "
        "Write a fuller answer using multiple facts from Context. Full sentences only."
    ) if retry else ""
    task = {
        "overview": (
            "The user wants a walk-through of DEOD / Decentrawood. "
            "Explain what the project is, what the DEOD token is for, and how people use it. "
            + (
                "They also asked about events — include recent campaigns or events from Context. "
                if any(k in message.lower() for k in ["event", "events", "campaign", "bonanza", "airdrop"])
                else ""
            )
            + "Pull facts from Context — synthesize into a clear mini-guide."
        ),
        "events": (
            "The user asks about latest events or campaigns. "
            "List the most recent relevant events, campaigns, airdrops, or dates from Context. "
            "Prefer [OFFICIAL ANNOUNCEMENT] and [OFFICIAL ADMIN] sources."
        ),
        "fact": (
            "Answer the user's specific question using facts from Context only."
        ),
    }.get(intent, "Answer using facts from Context only.")
    return (
        persona + retry_note +
        f"\n\nTASK: {task}"
        f"\n\nContext:\n{ctx}"
        f"\n\nUser: {message}"
        "\n\nHIERARCHY: Official Docs & [OFFICIAL ANNOUNCEMENT] > [OFFICIAL ADMIN] > Community."
        "\nCRITICAL 1: Synthesize a complete answer from Context. Combine multiple facts if needed."
        "\nCRITICAL 2: If Context truly has no answer, say 'idk tbh — check pinned messages'."
        "\nCRITICAL 3: Never output only 'DEOD', only 'token', or a sentence fragment. Full sentences."
        "\nCRITICAL 4: Sound like a human texting. Lowercase, casual, but informative."
    )

# ============================================================================
# 4. BOT CORE LOGIC
# ============================================================================
def resolve_coreferences(message: str, history: list) -> str:
    if not history: return message
    msg_lower = message.lower()
    needs = any(w in msg_lower for w in ["it", "that", "this", "when", "latest", "recent"]) or len(message.split()) <= 5
    if not needs: return message
    return message

def generate_reply(bot_key, message, history=None):
    eff_msg = resolve_coreferences(message, history)
    intent = _classify_query_intent(message)

    if any(k in message.lower() for k in ["latest", "recent", "new"]):
        eff_msg += f" {datetime.now().year}"

    is_price_question = _is_price_intent(message)
    if is_price_question:
        price_data = get_crypto_price("DEOD")
        if price_data:
            p, c = price_data
            return f"{'📈' if c>0 else '📉'} DEOD: ${p} ({c:+.2f}% 24h)", ""

    search_q = _rag_search_query(eff_msg, intent)
    ctx, score = retrieve_with_score(search_q, k=12)

    years = [int(y) for y in re.findall(r'\b(20\d{2})\b', ctx)]
    data_year = max(years) if years else None
    is_outdated = (datetime.now().year - data_year >= 1) if data_year else False

    # Always use LLM synthesis — extractive line-picking caused "DEOD" / "token)" fragments
    reply = ask_llm(_build_rag_llm_prompt(bot_key, message, ctx, intent)).strip()
    if _is_bad_reply(reply, intent):
        reply = ask_llm(_build_rag_llm_prompt(bot_key, message, ctx, intent, retry=True)).strip()

    if _is_bad_reply(reply, intent):
        reply = (
            "deod is decentrawood's metaverse token on polygon — "
            "used for staking, marketplace, and in-game stuff. "
            "check pinned messages for the latest events and campaigns."
        )

    if is_outdated and data_year and str(data_year) not in reply and any(
        k in message.lower() for k in ["latest", "recent", "new", "today"]
    ):
        reply += f" (some context is from {data_year} — check pinned for updates)"

    return reply, ctx

# ============================================================================
# 5. NATURAL CONVERSATION MODES
# ============================================================================
def _get_random_db_fact() -> str:
    try:
        csv_path = os.path.join(PDFS_DIR, "telegram_group_history.csv")
        if not os.path.exists(csv_path):
            return ""
        df = pd.read_csv(csv_path)
        col = 'message' if 'message' in df.columns else ('text' if 'text' in df.columns else None)
        if not col:
            return ""
        admin_df = df[df[col].str.len() > 40].dropna(subset=[col])
        if admin_df.empty:
            return ""
        row = admin_df.sample(1).iloc[0]
        return str(row[col]).strip()
    except:
        return ""

def _bot_share_fact(bots, chat_id):
    fact = _get_random_db_fact()
    if not fact or len(fact) < 20:
        return
    bot_key = random.choice(list(bots.keys()))
    intros = [
        "btw just saw this —", "random but —", "not sure if everyone knows this but",
        "just reading through some stuff and —", "ngl this is interesting —",
        "hey, came across this just now —",
    ]
    prompt = f"""You are {bot_key} in a Telegram group. You just found this info:
\"{fact}\"

Write ONE casual sentence sharing this naturally with the group, like a real person would text.
Start with one of these: {random.choice(intros)}
DO NOT copy the text directly. Rephrase it naturally. MAX 1 sentence."""
    try:
        msg = ask_llm(prompt).strip()
        if msg:
            bots[bot_key].send_message(chat_id, msg)
    except:
        pass

def _bot_ask_group(bots, chat_id):
    fact = _get_random_db_fact()
    bot_key = random.choice(list(bots.keys()))
    if fact and len(fact) > 20:
        prompt = f"""You are {bot_key} in a Telegram crypto group about Decentrawood/DEOD.

Based on this info: \"{fact[:200]}\"

Write ONE casual question to ask the group, like you're genuinely curious.
Sound like a real person texting — short, lowercase, maybe with 'tbh', 'ngl', 'anyone', etc.
End with a question mark. MAX 1 sentence."""
    else:
        question = random.choice(IDLE_OPENERS)
        try:
            bots[bot_key].send_message(chat_id, question)
        except:
            pass
        return
    try:
        msg = ask_llm(prompt).strip()
        if msg:
            bots[bot_key].send_message(chat_id, msg)
    except:
        pass

def _bot_react_once(bots, chat_id, primary_key, topic: str):
    others = [k for k in bots if k != primary_key]
    if not others:
        return
    reactor = random.choice(others)

    topic_lower = (topic or "").lower()
    if any(k in topic_lower for k in ["reward", "prize", "winner", "bonanza", "airdrop"]):
        reactions = [
            "ah makes sense, did anyone save the exact reward split?",
            "got it, if anyone has the rank-wise rewards drop it here",
            "nice, curious if first second third had different amounts",
            "okay that helps, anyone got the official reward breakdown?",
        ]
    elif any(k in topic_lower for k in ["price", "chart", "value"]):
        reactions = [
            "yeah makes sense, market keeps moving tho",
            "got it, lets see where price goes next",
            "fair enough, chart's still kinda volatile",
        ]
    else:
        reactions = [
            "yeah that makes sense tbh",
            "got it, thanks for sharing",
            "fair point actually",
            "hmm okay, that helps",
        ]

    try:
        human_delay(15, 35)
        msg = random.choice(reactions)
        if msg:
            bots[reactor].send_message(chat_id, msg)
    except:
        pass

def start_topic(bots, chat_id):
    mode = random.choices(
        ["share", "ask", "opener"],
        weights=[35, 40, 25],
        k=1
    )[0]
    if mode == "share":
        _bot_share_fact(bots, chat_id)
    elif mode == "ask":
        _bot_ask_group(bots, chat_id)
    else:
        bot_key = random.choice(list(bots.keys()))
        line = random.choice(IDLE_OPENERS)
        try:
            bots[bot_key].send_message(chat_id, line)
        except:
            pass

# ============================================================================
# 6. INDEX BUILDER
# ============================================================================
def build_index():
    print("🔨 BUILDING DECENTRAWOOD RAG INDEX (Qdrant)...")

    try:
        qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    except Exception as e:
        print(f"❌ Cannot connect to Qdrant at {QDRANT_URL}: {e}")
        return

    for col_name in [OFFICIAL_COLLECTION, COMMUNITY_COLLECTION]:
        try:
            qdrant.delete_collection(col_name)
            print(f"🗑️  Dropped collection: {col_name}")
        except Exception:
            pass
        qdrant.create_collection(
            collection_name=col_name,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE)
        )
        print(f"✅ Created collection: {col_name}")

    # ── Official Docs (PDFs + TXTs) ──
    off_docs = []
    if not os.path.exists(PDFS_DIR):
        os.makedirs(PDFS_DIR, exist_ok=True)

    for f in os.listdir(PDFS_DIR):
        fpath = os.path.join(PDFS_DIR, f)
        try:
            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            elif f.lower().endswith(".pdf"):
                d = PyPDFLoader(fpath).load()
            elif f.lower().endswith(".txt"):
                d = TextLoader(fpath, encoding="utf-8").load()
            else:
                continue
            for doc in d:
                doc.metadata.update({"source": f, "doc_type": "official"})
            off_docs.extend(d)
        except Exception as e:
            print(f"⚠️ Error loading official doc {f}: {e}")

    print(f"📝 Total official docs loaded: {len(off_docs)}")
    if off_docs:
        print("✂️ Splitting documents...")
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        off_chunks = splitter.split_documents(off_docs)
        print(f"⚡ Embedding & indexing {len(off_chunks)} official chunks...")
        EMBED_BATCH = 100
        all_vectors = []
        for i in range(0, len(off_chunks), EMBED_BATCH):
            batch_texts = [c.page_content for c in off_chunks[i:i + EMBED_BATCH]]
            all_vectors.extend(embeddings.embed_documents(batch_texts))
        points = [
            PointStruct(id=idx, vector=vec, payload={**chunk.metadata, "page_content": chunk.page_content})
            for idx, (chunk, vec) in enumerate(zip(off_chunks, all_vectors))
        ]
        UPSERT_BATCH = 100
        for i in range(0, len(points), UPSERT_BATCH):
            qdrant.upsert(collection_name=OFFICIAL_COLLECTION, points=points[i:i + UPSERT_BATCH])
        print(f"✅ Official Base indexed ({len(points)} points).")

    # ── Community Docs (CSVs) ──

    # ── FIX 2 (part C): use dynamically fetched real bot usernames for exclusion ──
    bot_exclude = _get_bot_exclude_set()

    com_docs = []
    PRIORITY_IDS = ADMIN_IDS
    for f in os.listdir(PDFS_DIR):
        if not f.endswith(".csv"): continue
        try:
            df = pd.read_csv(os.path.join(PDFS_DIR, f))
            TEXT_COL = 'message' if 'message' in df.columns else None
            DATE_COL = 'datetime' if 'datetime' in df.columns else None

            if not TEXT_COL:
                print(f"⚠️ Skipping {f}: No 'message' column found.")
                continue

            if 'id' in df.columns:
                df = df.drop_duplicates(subset=['id'], keep='last')
            df = df.drop_duplicates(subset=[TEXT_COL], keep='last')

            has_dates = DATE_COL is not None
            if has_dates:
                df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors='coerce', utc=True)
                df = df.sort_values(DATE_COL, ascending=False)
                df = df.head(10000)
                min_date = df[DATE_COL].min()
                max_date = df[DATE_COL].max()
                date_range = (max_date - min_date).total_seconds() if pd.notna(min_date) and pd.notna(max_date) else 1

            for _, row in df.iterrows():
                text = str(row.get(TEXT_COL, '')).strip()
                username = str(row.get('username', '')).strip().lower().lstrip('@')

                # ── FIX 2 (part D): check against the full dynamic exclude set ──
                if username in bot_exclude:
                    continue

                sender_id_raw = row.get('sender_id', None)
                sender_id = None
                if pd.notna(sender_id_raw):
                    try:
                        sender_id = int(float(sender_id_raw))
                    except Exception:
                        sender_id = None

                is_admin_msg = (
                    (sender_id is not None and sender_id in PRIORITY_IDS)
                    or (username in ADMIN_USERNAMES)
                )
                is_announcer_msg = (
                    (sender_id is not None and sender_id in ANNOUNCER_IDS)
                    or (username in ANNOUNCER_USERNAMES)
                )

                if not text or len(text) < 10:
                    continue

                relevance_terms = [
                    "deod", "decentrawood", "bonanza", "airdrop", "listing",
                    "winner", "winners", "reward", "campaign", "event",
                    "staking", "wallet", "token", "prize", "prizes",
                    "regional", "t.me/", "telegram.me", "group", "channel",
                    "join", "community", "indonesian", "italian", "portuguese",
                    "japanese", "korean", "german", "vietnamese", "arabic",
                    "russian", "french", "spanish", "hindi", "turkish"
                ]
                is_relevant = len(text.split()) > 8 and any(k in text.lower() for k in relevance_terms)
                if not is_relevant and not is_admin_msg:
                    continue

                recency = 0.5
                if has_dates:
                    row_date = pd.to_datetime(row.get(DATE_COL), errors='coerce', utc=True)
                    if pd.notna(row_date) and date_range > 0:
                        recency = (row_date - min_date).total_seconds() / date_range
                        recency = round(float(recency), 4)

                com_docs.append(Document(
                    page_content=text,
                    metadata={
                        "source": f,
                        "is_admin": bool(is_admin_msg),
                        "category": "announcement" if is_announcer_msg else "community",
                        "recency_score": recency,
                        "date_str": str(row.get(DATE_COL, '')),
                    }
                ))
        except Exception as e:
            print(f"⚠️ Error processing CSV {f}: {e}")

    print(f"💾 Total community docs prepared: {len(com_docs)}")
    if com_docs:
        print("⚡ Embedding & indexing community data in batches...")
        EMBED_BATCH = 100
        all_vectors = []
        for i in range(0, len(com_docs), EMBED_BATCH):
            batch_texts = [d.page_content for d in com_docs[i:i + EMBED_BATCH]]
            print(f"  … Embedding batch {i // EMBED_BATCH + 1} ({len(batch_texts)} docs)")
            all_vectors.extend(embeddings.embed_documents(batch_texts))
        points = [
            PointStruct(id=idx, vector=vec, payload={**doc.metadata, "page_content": doc.page_content})
            for idx, (doc, vec) in enumerate(zip(com_docs, all_vectors))
        ]
        UPSERT_BATCH = 100
        for i in range(0, len(points), UPSERT_BATCH):
            qdrant.upsert(collection_name=COMMUNITY_COLLECTION, points=points[i:i + UPSERT_BATCH])
        print(f"✅ Community data indexed ({len(points)} points).")
    print("✅ RAG Index Built!")

# ============================================================================
# 7. MAIN LISTENER & ENTRY
# ============================================================================
def start_bot():
    global last_user_message_time
    init_rag()

    bots = {k: telebot.TeleBot(v) for k, v in BOT_TOKENS.items() if v}
    listener_key = "curious"
    listener_bot = bots[listener_key]

    @listener_bot.message_handler(func=lambda m: True, content_types=['text', 'photo'])
    def handle(message):
        global last_user_message_time

        # ── GUARD 1: Ignore other bots ──
        if message.from_user.is_bot:
            return

        # ── GUARD 2: Admin messages ──
        sender_username = (message.from_user.username or "").lower()
        is_admin = sender_username in [a.lower() for a in ADMIN_USERNAMES]
        if is_admin:
            admin_text = (message.text or message.caption or "").lower()
            is_reply = message.reply_to_message is not None
            ANNOUNCEMENT_KEYWORDS = [
                "airdrop", "winner", "winners", "congratulations", "reward",
                "listing", "listed", "bitmart", "toobit", "coinsbit", "quickswap",
                "launch", "launched", "important", "announce", "released", "distribute",
                "bounty", "nft", "partnership", "ama", "giveaway", "event"
            ]
            is_big_announcement = (
                not is_reply
                and len(admin_text) > 30
                and "?" not in admin_text
                and any(kw in admin_text for kw in ANNOUNCEMENT_KEYWORDS)
            )
            if is_big_announcement:
                def _admin_reaction():
                    human_delay(8, 20)
                    bot_key1 = random.choice(list(bots.keys()))
                    prompt1 = f"""You are {bot_key1.upper()} in a telegram group.
Your personality: {BOT_PERSONAS[bot_key1]['traits']}
Your tone: {BOT_PERSONAS[bot_key1]['tone']}

The group Admin just posted this announcement:
"{admin_text}"

React to this announcement. Keep it under 10 words. Sound like a real community member texting. Either show hype, agree, or say something related. Use lowercase."""
                    try:
                        msg1 = ask_llm(prompt1).strip()
                        if msg1:
                            bots[bot_key1].send_message(message.chat.id, msg1)
                            CHAT_STATE['history'].append(f"Admin: {admin_text}")
                            CHAT_STATE['history'].append(f"{bot_key1}: {msg1}")
                            if len(CHAT_STATE['history']) > 20:
                                CHAT_STATE['history'] = CHAT_STATE['history'][-20:]
                    except:
                        pass

                    if random.random() < 0.25:
                        others = [k for k in bots if k != bot_key1]
                        if others:
                            bot_key2 = random.choice(others)
                            human_delay(10, 25)
                            prompt2 = f"""You are {bot_key2.upper()} in a telegram group.
Your personality: {BOT_PERSONAS[bot_key2]['traits']}

Admin post: "{admin_text}"
Someone just said: "{msg1}"

Type a short 1-sentence reply to this. Either agree with them, or ask a brief question about the announcement. Keep it casual and lowercase."""
                            try:
                                msg2 = ask_llm(prompt2).strip()
                                if msg2: bots[bot_key2].send_message(message.chat.id, msg2)
                            except:
                                pass
                threading.Thread(target=_admin_reaction, daemon=True).start()
                return

        # ── GUARD 3: Photo messages with OCR ──
        photo_media_desc = ""
        if message.content_type == 'photo':
            try:
                photo_file = listener_bot.get_file(message.photo[-1].file_id)
                photo_bytes = listener_bot.download_file(photo_file.file_path)
                photo_hash = get_file_hash(photo_bytes)
                seen_hashes = load_photo_hashes()

                if photo_hash in seen_hashes:
                    print(f"   ⏭️  Duplicate photo (hash: {photo_hash[:8]}...). Skipping.")
                    return

                msg_id_str = str(message.message_id)
                if os.path.exists(LIVE_CSV):
                    try:
                        existing_ids = pd.read_csv(LIVE_CSV, usecols=["id"], dtype=str)["id"].tolist()
                        if msg_id_str in existing_ids:
                            print(f"   ⏭️  Photo message_id {msg_id_str} already logged. Skipping.")
                            return
                    except Exception:
                        pass

                save_photo_hash(photo_hash)
                sender_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
                print(f"   🔍 Transcribing NEW photo from {sender_name}...")
                caption = message.caption or ""

                if ENABLE_IMAGE_OCR:
                    try:
                        transcription = describe_image(photo_bytes)
                        photo_media_desc = f"Photo [Content: {transcription}]"
                        print(f"      ✓ OCR: {transcription[:120]}...")
                    except Exception as e:
                        print(f"      ⚠️ OCR failed: {e}")
                        photo_media_desc = "Photo [OCR Failed]"
                else:
                    photo_media_desc = "Photo"

                log_message_to_history(
                    id=message.message_id,
                    sender=sender_name,
                    sender_id=message.from_user.id,
                    text=caption,
                    media=photo_media_desc
                )
                print(f"      ✅ Photo logged (id={message.message_id})")
            except Exception as e:
                print(f"      ⚠️ Failed to process photo: {e}")
            return

        inp = message.text or message.caption or ""
        if not inp.strip():
            return

        # ── GUARD 4: Greetings ──
        inp_lower = inp.strip().lower()
        is_greeting = len(inp.split()) <= 4 and any(g in inp_lower for g in GREETING_WORDS)
        if is_greeting:
            user_name = message.from_user.first_name or "there"
            greetings = [
                f"hey {user_name}! 👋",
                f"hi {user_name}! welcome 🙌",
                f"gm {user_name}! 🌟",
                f"hey {user_name}, how's it going?",
            ]
            if random.random() < 0.4:
                human_delay(3, 8)
                all_k = list(bots.keys())
                pk = random.choice(all_k)
                bots[pk].send_message(message.chat.id, random.choice(greetings))
            last_user_message_time = time.time()
            return

        has_question_mark = "?" in inp
        has_question_keyword = any(
            re.search(r'\b' + kw + r'\b', inp_lower)
            for kw in QUESTION_KEYWORDS
        )

        # ── GUARD 5: Very short messages ──
        if len(inp.strip()) < 5:
            last_user_message_time = time.time()
            return

        # ── GUARD 6: Only answer keyword/question matches ──
        if not has_question_keyword and not has_question_mark:
            last_user_message_time = time.time()
            return

        # ── REAL QUESTION ──
        last_user_message_time = time.time()
        all_k = list(bots.keys())
        pk = random.choice(all_k)

        if message.reply_to_message and message.reply_to_message.text:
            inp = f'Replying to: "{message.reply_to_message.text}"\nUser Q: {inp}'

        human_delay(MIN_REPLY_DELAY, MAX_REPLY_DELAY)

        try:
            log_message_to_history(
                message.message_id,
                f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name,
                message.from_user.id, inp
            )

            reply, _ = generate_reply(pk, inp, history=CHAT_STATE['history'])
            bots[pk].send_message(message.chat.id, reply)

            CHAT_STATE['history'].append(f"User: {inp}")
            CHAT_STATE['history'].append(f"{pk}: {reply}")
            if len(CHAT_STATE['history']) > 20:
                CHAT_STATE['history'] = CHAT_STATE['history'][-20:]
            CHAT_STATE['last_answerer'] = pk

            reply_lower = reply.lower()
            is_uncertain_reply = any(
                marker in reply_lower
                for marker in ["idk", "not sure", "don't know", "dont know", "unsure"]
            )
            if random.random() < 0.25 and len(bots) > 1 and not is_uncertain_reply:
                threading.Thread(
                    target=_bot_react_once,
                    args=(bots, message.chat.id, pk, inp),
                    daemon=True
                ).start()

        except Exception as e:
            print(f"Handle Error: {e}")

    # Auto topics
    def loop():
        while True:
            time.sleep(random.randint(AUTO_TOPIC_MIN_INTERVAL, AUTO_TOPIC_MAX_INTERVAL))
            if time.time() - last_user_message_time > MIN_IDLE_TIME_FOR_AUTO_TOPICS:
                start_topic(bots, CHAT_ID)

    if ENABLE_AUTO_TOPICS:
        threading.Thread(target=loop, daemon=True).start()

    # Background RAG Re-indexer
    def index_watcher():
        while True:
            time.sleep(RAG_REINDEX_INTERVAL)
            csv_path = CSV_HISTORY
            live_path = LIVE_CSV
            if os.path.exists(csv_path) or os.path.exists(live_path):
                print("🔄 [Background] Updating Community Knowledge Base...")
                try:
                    build_index()
                    init_rag()
                    print("✅ [Background] Community Knowledge Updated!")
                except Exception as e:
                    print(f"❌ [Background] Sync Error: {e}")

    threading.Thread(target=index_watcher, daemon=True).start()

    # History Extractor Thread
    threading.Thread(target=run_history_extraction_loop, daemon=True).start()

    # Webhook Cleanup
    for name, token in BOT_TOKENS.items():
        if token:
            try:
                requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=True", timeout=10)
            except:
                print(f"⚠️  Could not clear webhook for {name}")

    print("🚀 Polling started...")
    consecutive_poll_stops = 0
    while True:
        try:
            listener_bot.infinity_polling(
                timeout=20,
                long_polling_timeout=30,
                skip_pending=True,
            )
            consecutive_poll_stops += 1
            wait_s = min(60, 5 * consecutive_poll_stops)
            print(f"⚠️ Bot polling stopped. Restarting in {wait_s}s...")
            if consecutive_poll_stops >= 2:
                try:
                    requests.get(
                        f"https://api.telegram.org/bot{BOT_TOKENS.get(listener_key)}/deleteWebhook?drop_pending_updates=True",
                        timeout=10,
                    )
                except Exception:
                    pass
            time.sleep(wait_s)
        except (requests.exceptions.RequestException, ConnectionResetError, OSError) as net_err:
            consecutive_poll_stops = min(consecutive_poll_stops + 1, 12)
            print(f"📡 Network issue: {net_err}. Retrying in 15 seconds...")
            time.sleep(15)
        except KeyboardInterrupt:
            print("🛑 Bot stopped by user.")
            break
        except Exception as e:
            consecutive_poll_stops = min(consecutive_poll_stops + 1, 12)
            print(f"🚨 Unexpected error: {e}. Retrying in 10 seconds...")
            time.sleep(10)
        except:
            consecutive_poll_stops = min(consecutive_poll_stops + 1, 12)
            print("⚠️ Unknown critical error. Restarting in 10s...")
            time.sleep(10)


# ============================================================================
# 8. ONE-TIME CSV CLEANUP UTILITY
# Run once before first start: python main.py --clean-csv
# ============================================================================
def clean_csv_of_bot_messages():
    """Removes all bot-authored rows from existing CSVs AND messages.json."""
    print("🧹 Running one-time cleanup to remove bot-authored rows...")
    bot_exclude = _get_bot_exclude_set()

    # Clean CSVs
    for csv_file in [CSV_HISTORY, LIVE_CSV]:
        if not os.path.exists(csv_file):
            continue
        try:
            df = pd.read_csv(csv_file)
            before = len(df)
            df["_u"] = df["username"].astype(str).str.lower().str.lstrip("@").str.strip()
            df = df[~df["_u"].isin(bot_exclude)].drop(columns=["_u"])
            df.to_csv(csv_file, index=False)
            print(f"  ✅ {os.path.basename(csv_file)}: removed {before - len(df)} bot rows, kept {len(df)}")
        except Exception as e:
            print(f"  ⚠️ Could not clean {csv_file}: {e}")

    # Clean messages.json so the background refresh can't re-poison the CSV
    if os.path.exists(JSON_HISTORY):
        try:
            with open(JSON_HISTORY, "r", encoding="utf-8") as f:
                data = json.load(f)
            msgs = data.get("messages", [])
            before = len(msgs)
            cleaned = []
            for m in msgs:
                uname = str(m.get("sender", "")).lower().lstrip("@").strip()
                # Also strip display-name format like "Decentrawood Helper"
                uname_nospace = uname.replace(" ", "")
                if uname not in bot_exclude and uname_nospace not in bot_exclude:
                    cleaned.append(m)
            data["messages"] = cleaned
            data["total_messages"] = len(cleaned)
            with open(JSON_HISTORY, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  ✅ messages.json: removed {before - len(cleaned)} bot entries, kept {len(cleaned)}")
        except Exception as e:
            print(f"  ⚠️ Could not clean messages.json: {e}")

    print("🧹 Cleanup complete.")


# ============================================================================
# ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    import sys

    if "--clean-csv" in sys.argv:
        # Step 1: purge poisoned bot rows from existing CSVs
        clean_csv_of_bot_messages()
        # Step 2: rebuild a clean Qdrant index from the purged CSVs
        build_index()
        print("✅ Cleanup + rebuild done. Now run: python main.py")
        sys.exit(0)

    should_build = "--build" in sys.argv
    if not should_build:
        try:
            _check = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
            cols = [c.name for c in _check.get_collections().collections]
            if OFFICIAL_COLLECTION not in cols or COMMUNITY_COLLECTION not in cols:
                should_build = True
        except Exception:
            should_build = True

    if should_build:
        build_index()

    start_bot()
