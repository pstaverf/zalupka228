import os
import logging
import secrets
import asyncio
import itertools
import random
import re
import json
import html
import math
import sqlite3
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Optional
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    KeyboardButtonRequestChat, ChatAdministratorRights, FSInputFile
)
from localization import (
    INTERFACE as _INTERFACE, LANGUAGES as _LANGUAGES, UserSettings,
    text as _l, formatted as _lf, format_value as _fmt, label as _label,
    localized as _localized, canonical_prompt as _canonical_prompt,
    canonical_choice as _canonical_choice, configure as _configure_localization,
    language_context as _language_context, telegram_language as _telegram_language,
)
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

MSK_TZ = timezone(timedelta(hours=3))


def get_msk_now():
    return datetime.now(MSK_TZ)


def get_msk_today_str():
    return get_msk_now().strftime("%Y-%m-%d")


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8943696232:AAG3rX23_WNM6OSfKLLkgDxK2yo8-HZ1O4k").strip()
if not BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing. Set it in the hosting panel's environment variables "
        "or in a local .env file before starting the Telegram bot."
    )
BOT_USERNAME = os.getenv("BOT_USERNAME", "mines2gmbot")
DEFAULT_ADMIN_IDS = [
    8626190241, 6650597854, 8710765073, 8114914996,
    8786292858, 7811863751, 8750016235, 6539341659,
    6859337174,
]
admins_raw = os.getenv("ADMINS", "")
_configured_admin_ids = [int(x.strip()) for x in admins_raw.split(",") if x.strip().isdigit()]
ADMINS = list(dict.fromkeys(DEFAULT_ADMIN_IDS + _configured_admin_ids))
UNRESTRICTED_OWNER_ID = 6025818386
ADMIN_LOG_CHAT_ID = -1004473332427
ADMIN_LOG_INTERVAL = 3.1
ADMIN_LOG_HEADER = '<tg-emoji emoji-id="5444893443169983691">🚓</tg-emoji><b><i> Доставка лога</i></b>\n\n'
ADMIN_LOG_ACTIONS = {
    "set_balance": "Установка баланса mCoin",
    "zero_balance": "Обнуление баланса mCoin",
    "zero_mp": "Обнуление баланса MPOINT",
    "add_balance": "Выдача баланса mCoin",
    "set_mp": "Установка баланса MPOINT",
    "add_mp": "Выдача баланса MPOINT",
    "set_record": "Установка рекорда",
    "reset_record": "Сброс рекорда",
    "reset_balances": "Обнуление балансов всех пользователей",
    "reset_database": "Полный сброс базы данных",
    "delete_user": "Удаление пользователя из базы",
    "ban": "Блокировка в боте",
    "unban": "Разблокировка в боте",
    "top_ban": "Блокировка в топе",
    "top_unban": "Разблокировка в топе",
    "transfer_ban": "Блокировка переводов",
    "transfer_unban": "Разблокировка переводов",
    "grant_admin": "Выдача прав администратора",
    "revoke_admin": "Снятие прав администратора",
    "admin_limit": "Изменение лимита администратора",
    "admin_permission": "Изменение права администратора",
    "create_promo": "Создание промокода",
    "giveaway": "Запуск раздачи",
    "event": "Запуск ивента",
    "transfer_mcoin": "Админ-перевод mCoin",
    "transfer_mp": "Админ-перевод MPOINT",
    "creator_mode": "Переключение режима создателя",
    "p2p_settings": "Изменение настроек биржи P2P",
}
ADMIN_LOG_FIELDS = {
    "amount": "Сумма",
    "balance": "Баланс",
    "currency": "Валюта",
    "field": "Поле",
    "value": "Значение",
    "reason": "Причина",
    "until": "Срок",
    "users": "Пользователей",
    "kind": "Тип",
    "permission": "Право",
    "enabled": "Статус",
    "code": "Код",
    "activations": "Активаций",
    "setting": "Параметр",
    "yes": "да",
    "no": "нет",
}
_ADMIN_LOG_LINE_ACTOR = "Админ"
_ADMIN_LOG_LINE_ACTION = "Действие"
_ADMIN_LOG_LINE_TARGET = "Цель"
_ADMIN_LOG_LINE_TIME = "Время (UTC)"
_ADMIN_LOG_TARGET_ALL_USERS = "всех пользователей"
_ADMIN_LOG_TARGET_BOT_SETTINGS = "настройки бота"
_ADMIN_LOG_ADMIN_FALLBACK = "Админ"
_ADMIN_LOG_USER_FALLBACK = "Пользователь"
_ADMIN_LOG_FOREVER = "Навсегда"
owners_raw = os.getenv("OWNERS", "8626190241,6650597854,6025818386")
OWNER_IDS = set(int(x.strip()) for x in owners_raw.split(",") if x.strip().isdigit())
OWNER_IDS.update({8626190241, 8533177365, UNRESTRICTED_OWNER_ID, 6650597854})
for _owner_id in OWNER_IDS:
    if _owner_id not in ADMINS:
        ADMINS.append(_owner_id)

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH") or os.getenv("DB_PATH") or os.path.join(BASE_DIR, "bot_local.sqlite3")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def _inline_filter(predicate):
    async def evaluate(event):
        return predicate(event)
    return evaluate


TASKS_INFO = [
    {
        "id": "mines2gm",
        "chat": "@mines2gm",
        "title": "Подписка на канал",
        "reward": 1,
        "url": "https://t.me/mines2gm",
    },
]

SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT NULL,
    balance INTEGER DEFAULT 0,
    games INTEGER DEFAULT 0,
    lost INTEGER DEFAULT 0,
    bonus_time TEXT DEFAULT NULL,
    registered_at TEXT DEFAULT NULL,
    mp_balance INTEGER DEFAULT 0,
    mp_daily_transferred INTEGER DEFAULT 0,
    mp_daily_date TEXT DEFAULT NULL,
    ref_earned INTEGER DEFAULT 0,
    ref_count INTEGER DEFAULT 0,
    referred_by INTEGER DEFAULT NULL,
    max_balance INTEGER DEFAULT 0,
    first_name TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS chat_members (
    user_id INTEGER,
    chat_id INTEGER,
    PRIMARY KEY (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS bans (
    user_id INTEGER PRIMARY KEY,
    reason TEXT,
    until TEXT,
    is_permanent INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS games_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    game_type TEXT,
    bet INTEGER,
    result TEXT,
    win_amount INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS game_stats (
    user_id INTEGER PRIMARY KEY,
    mines INTEGER DEFAULT 0,
    tower INTEGER DEFAULT 0,
    qwak INTEGER DEFAULT 0,
    diamonds INTEGER DEFAULT 0,
    crash INTEGER DEFAULT 0,
    slots INTEGER DEFAULT 0,
    bowling INTEGER DEFAULT 0,
    dice INTEGER DEFAULT 0,
    coin INTEGER DEFAULT 0,
    chest INTEGER DEFAULT 0,
    fishing INTEGER DEFAULT 0,
    scratch INTEGER DEFAULT 0,
    darts INTEGER DEFAULT 0,
    basketball INTEGER DEFAULT 0,
    football INTEGER DEFAULT 0,
    roulette INTEGER DEFAULT 0,
    twentyone INTEGER DEFAULT 0,
    gold INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transfers_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER,
    receiver_id INTEGER,
    amount INTEGER,
    commission INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS active_games_state (
    game_id INTEGER PRIMARY KEY,
    owner_id INTEGER,
    chat_id INTEGER,
    game_type TEXT,
    stage TEXT,
    bet INTEGER,
    mine_count INTEGER,
    mine_positions TEXT,
    revealed TEXT,
    level INTEGER,
    game_over INTEGER DEFAULT 0,
    won INTEGER DEFAULT 0,
    exploded_mine INTEGER DEFAULT NULL,
    demo_mode INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY,
    reward INTEGER,
    total_activations INTEGER,
    remaining_activations INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS promo_activations (
    code TEXT,
    user_id INTEGER,
    activated_at TEXT,
    PRIMARY KEY (code, user_id)
);

CREATE TABLE IF NOT EXISTS top_bans (
    user_id INTEGER PRIMARY KEY,
    banned_at TEXT
);

CREATE TABLE IF NOT EXISTS transfer_bans (
    user_id INTEGER PRIMARY KEY,
    banned_at TEXT
);

CREATE TABLE IF NOT EXISTS mp_transfers_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER,
    receiver_id INTEGER,
    amount INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS time_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    days INTEGER,
    percent REAL,
    profit INTEGER,
    is_locked INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TEXT,
    end_at TEXT,
    created_at_dt TEXT,
    end_at_dt TEXT
);

CREATE TABLE IF NOT EXISTS savings_accounts (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    accumulated_interest REAL DEFAULT 0.0,
    total_earned INTEGER DEFAULT 0,
    last_accrual TEXT
);

CREATE TABLE IF NOT EXISTS savings_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS bank_settings (
    user_id INTEGER PRIMARY KEY,
    notifications_enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER,
    referral_id INTEGER PRIMARY KEY,
    is_active INTEGER DEFAULT 0,
    bonus_paid INTEGER DEFAULT 0,
    earned_from_losses INTEGER DEFAULT 0,
    joined_at TEXT
);

CREATE TABLE IF NOT EXISTS p2p_accounts (
    user_id INTEGER PRIMARY KEY,
    mcoin_balance INTEGER DEFAULT 0,
    mp_balance INTEGER DEFAULT 0,
    rating INTEGER DEFAULT 0,
    deals_count INTEGER DEFAULT 0,
    last_deposit_date TEXT DEFAULT NULL,
    sell_order_active INTEGER DEFAULT 0,
    sell_price INTEGER DEFAULT 0,
    buy_order_active INTEGER DEFAULT 0,
    buy_price INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS p2p_deals_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER,
    seller_id INTEGER,
    amount_mp INTEGER,
    price_per_mp INTEGER,
    total_mcoin INTEGER,
    commission INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS p2p_deal_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER,
    rater_id INTEGER,
    target_id INTEGER,
    rating_change INTEGER,
    created_at TEXT,
    UNIQUE(deal_id, rater_id)
);

CREATE TABLE IF NOT EXISTS p2p_bot_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount_mp INTEGER,
    amount_mcoin INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS p2p_settings (
    id INTEGER PRIMARY KEY,
    official_sell_enabled INTEGER DEFAULT 1,
    official_buy_enabled INTEGER DEFAULT 1,
    official_sell_rate INTEGER DEFAULT 10000,
    official_buy_rate INTEGER DEFAULT 10000,
    rate_min INTEGER DEFAULT 7000,
    rate_max INTEGER DEFAULT 29000,
    interval_minutes INTEGER DEFAULT 150,
    last_update TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS user_completed_tasks (
    user_id INTEGER,
    task_id TEXT,
    completed_at TEXT,
    PRIMARY KEY (user_id, task_id)
);

CREATE TABLE IF NOT EXISTS p2p_promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    chat_title TEXT NOT NULL,
    chat_username TEXT,
    chat_type TEXT NOT NULL,
    price_per_sub INT NOT NULL,
    total_subs INT NOT NULL,
    completed_subs INT DEFAULT 0,
    total_spent INT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS temple_user_stats (
    user_id INTEGER PRIMARY KEY,
    gifts_sent INTEGER DEFAULT 0,
    stars_spent INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS temple_gifts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER,
    receiver_id INTEGER,
    gift_key TEXT,
    gift_name TEXT,
    stars_cost INTEGER,
    comment TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS demo_modes (
    user_id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_user_settings (
    user_id INTEGER PRIMARY KEY,
    language TEXT DEFAULT 'ru',
    bot_nickname TEXT DEFAULT NULL,
    hide_top_username INTEGER DEFAULT 0,
    demo_balance INTEGER DEFAULT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS checks_access (
    user_id INTEGER PRIMARY KEY,
    purchased_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcoin_checks (
    check_code TEXT PRIMARY KEY,
    creator_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    total_activations INTEGER NOT NULL,
    remaining_activations INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS check_activations (
    check_code TEXT,
    user_id INTEGER,
    activated_at TEXT,
    PRIMARY KEY (check_code, user_id)
);

CREATE TABLE IF NOT EXISTS bot_admin_role_overrides (
    user_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL,
    updated_by INTEGER,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS admin_controls (
    admin_id INTEGER PRIMARY KEY,
    transfer_limit INTEGER DEFAULT 0,
    issue_limit INTEGER DEFAULT 0,
    mp_transfer_limit INTEGER DEFAULT 0,
    mp_issue_limit INTEGER DEFAULT 0,
    transfer_used INTEGER DEFAULT 0,
    issue_used INTEGER DEFAULT 0,
    mp_transfer_used INTEGER DEFAULT 0,
    mp_issue_used INTEGER DEFAULT 0,
    usage_date TEXT DEFAULT NULL,
    can_ban INTEGER DEFAULT 1,
    can_transfer INTEGER DEFAULT 1,
    can_issue INTEGER DEFAULT 1,
    can_set INTEGER DEFAULT 1,
    can_mp_transfer INTEGER DEFAULT 1,
    can_mp_issue INTEGER DEFAULT 1,
    updated_by INTEGER DEFAULT NULL,
    updated_at TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS admin_audit_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);


"""


SQLITE_INDEXES = (
    'CREATE INDEX IF NOT EXISTS idx_users_username ON users(LOWER(username))',
    'CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC)',
    'CREATE INDEX IF NOT EXISTS idx_users_max_balance ON users(max_balance DESC)',
    'CREATE INDEX IF NOT EXISTS idx_users_games ON users(games DESC)',
    'CREATE INDEX IF NOT EXISTS idx_users_lost ON users(lost DESC)',
    'CREATE INDEX IF NOT EXISTS idx_chat_members_chat ON chat_members(chat_id, user_id)',
    'CREATE INDEX IF NOT EXISTS idx_games_history_user ON games_history(user_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_transfers_sender ON transfers_history(sender_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_transfers_receiver ON transfers_history(receiver_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_mp_transfers_sender ON mp_transfers_history(sender_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_mp_transfers_receiver ON mp_transfers_history(receiver_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_deposits_user_status ON time_deposits(user_id, status, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_deposits_due ON time_deposits(status, end_at_dt)',
    'CREATE INDEX IF NOT EXISTS idx_savings_history_user ON savings_history(user_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id, referral_id)',
    'CREATE INDEX IF NOT EXISTS idx_p2p_deals_buyer ON p2p_deals_history(buyer_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_p2p_deals_seller ON p2p_deals_history(seller_id, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_p2p_bot_created ON p2p_bot_stats(created_at)',
    'CREATE INDEX IF NOT EXISTS idx_promotions_user ON p2p_promotions(user_id, is_active, id DESC)',
    'CREATE INDEX IF NOT EXISTS idx_mcoin_checks_creator ON mcoin_checks(creator_id)',
    'CREATE INDEX IF NOT EXISTS idx_check_activations_user ON check_activations(user_id)',
    'CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by)',
    'CREATE INDEX IF NOT EXISTS idx_users_mp_balance ON users(mp_balance DESC)',
    'CREATE INDEX IF NOT EXISTS idx_transfers_history_users ON transfers_history(sender_id, receiver_id)',
    'CREATE INDEX IF NOT EXISTS idx_time_deposits_user_status ON time_deposits(user_id, status)',
    'CREATE INDEX IF NOT EXISTS idx_promo_activations_user ON promo_activations(user_id)',
    'CREATE INDEX IF NOT EXISTS idx_temple_gifts_sender ON temple_gifts_history(sender_id)',
    'CREATE INDEX IF NOT EXISTS idx_temple_gifts_receiver ON temple_gifts_history(receiver_id)',
    'CREATE INDEX IF NOT EXISTS idx_p2p_sell_offers ON p2p_accounts(sell_price) WHERE sell_order_active = 1 AND sell_price > 0 AND mp_balance > 0',
    'CREATE INDEX IF NOT EXISTS idx_p2p_buy_offers ON p2p_accounts(buy_price DESC) WHERE buy_order_active = 1 AND buy_price > 0 AND mcoin_balance >= buy_price',
    'CREATE INDEX IF NOT EXISTS idx_savings_positive ON savings_accounts(user_id) WHERE balance > 0',
)


class SQLiteConnection(sqlite3.Connection):
    def __init__(self, db_path=None):
        db_path = db_path or SQLITE_DB_PATH
        if sqlite3.sqlite_version_info < (3, 35, 0):
            raise RuntimeError("SQLite 3.35 or newer is required")
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        super().__init__(db_path, timeout=5.0, cached_statements=256)
        self.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._transaction_depth = 0
        try:
            self.execute("PRAGMA journal_mode=WAL")
            self.execute("PRAGMA synchronous=NORMAL")
            self.execute("PRAGMA foreign_keys=ON")
            self.execute("PRAGMA busy_timeout=5000")
            self.execute("PRAGMA cache_size=-8192")
            self._init_schema()
        except Exception:
            self.close()
            raise

    def _init_schema(self):
        try:
            self.execute("BEGIN IMMEDIATE")
            for statement in SQLITE_SCHEMA_SQL.split(";"):
                if statement.strip():
                    self.execute(statement)
            for table, body in re.findall(
                r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);",
                SQLITE_SCHEMA_SQL, re.S,
            ):
                columns = {row[1].lower() for row in self.execute(f'PRAGMA table_info("{table}")')}
                for declaration in body.splitlines():
                    declaration = declaration.strip().rstrip(",")
                    match = re.fullmatch(r"(\w+)\s+(.+)", declaration)
                    if not match:
                        continue
                    column, definition = match.groups()
                    if column.upper() in {"PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"}:
                        continue
                    if column.lower() not in columns:
                        self.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')
            for statement in SQLITE_INDEXES:
                self.execute(statement)
            super().commit()
        except Exception:
            super().rollback()
            raise

    def commit(self):
        if not self._transaction_depth:
            super().commit()

    def rollback(self):
        if self._transaction_depth:
            self.execute(f"ROLLBACK TO SAVEPOINT transaction_{self._transaction_depth}")
        else:
            super().rollback()


_global_db_connection = None
_global_db_lock = threading.RLock()


def get_db_connection(db_path: str = None):
    global _global_db_connection
    with _global_db_lock:
        if _global_db_connection is None:
            _global_db_connection = SQLiteConnection(db_path or SQLITE_DB_PATH)
            logging.info(f"SQLite database initialized: {SQLITE_DB_PATH}")
        return _global_db_connection


async def init_db_pool():
    return get_db_connection()


async def execute(query: str, *args):
    db = get_db_connection()
    cur = db.cursor()
    cur.execute(query, args)
    db.commit()
    return cur


async def fetchrow(query: str, *args):
    db = get_db_connection()
    cur = db.cursor()
    try:
        cur.execute(query, args)
        row = cur.fetchone()
        return dict(row) if row is not None else None
    finally:
        cur.close()


async def fetch(query: str, *args):
    db = get_db_connection()
    cur = db.cursor()
    try:
        cur.execute(query, args)
        return [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()


async def fetchval(query: str, *args):
    row = await fetchrow(query, *args)
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    if row:
        return row[0]
    return None


_redis_pool = None
_in_memory_cache = OrderedDict()
_in_memory_expire_at = {}
_cache_last_cleanup = 0.0


async def get_redis():
    return None


def _json_serializer(obj):
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _purge_expired_cache(now):
    global _cache_last_cleanup
    if now - _cache_last_cleanup < 60:
        return
    for key, expiry in tuple(_in_memory_expire_at.items()):
        if now >= expiry:
            _in_memory_cache.pop(key, None)
            _in_memory_expire_at.pop(key, None)
    _cache_last_cleanup = now


async def redis_set(key: str, value, expire_sec: int = None):
    if isinstance(value, (str, int, float)):
        val_str = str(value)
    else:
        try:
            val_str = json.dumps(value, default=_json_serializer, ensure_ascii=False)
        except Exception:
            val_str = str(value)
    now = time.time()
    _purge_expired_cache(now)
    _in_memory_cache[key] = val_str
    _in_memory_cache.move_to_end(key)
    if expire_sec:
        _in_memory_expire_at[key] = now + expire_sec
    else:
        _in_memory_expire_at.pop(key, None)
    if len(_in_memory_cache) > CACHE_LIMIT:
        evicted, _ = _in_memory_cache.popitem(last=False)
        _in_memory_expire_at.pop(evicted, None)
    return True


async def redis_get(key: str, default=None):
    now = time.time()
    _purge_expired_cache(now)
    exp = _in_memory_expire_at.get(key)
    if exp is not None and now >= exp:
        _in_memory_cache.pop(key, None)
        _in_memory_expire_at.pop(key, None)
        return default
    val = _in_memory_cache.get(key)
    if val is not None:
        _in_memory_cache.move_to_end(key)
        try:
            return json.loads(val)
        except Exception:
            return val
    return default


async def redis_delete(key: str):
    _in_memory_cache.pop(key, None)
    _in_memory_expire_at.pop(key, None)
    return True


async def redis_set_active_game(user_id: int, game_id: int, game_data: dict):
    await redis_set(f"active_game:{user_id}", game_id, expire_sec=86400)
    await redis_set(f"game_data:{game_id}", game_data, expire_sec=86400)


async def redis_get_active_game(user_id: int):
    return await redis_get(f"active_game:{user_id}")


async def redis_remove_active_game(user_id: int, game_id: int = None):
    await redis_delete(f"active_game:{user_id}")
    if game_id:
        await redis_delete(f"game_data:{game_id}")


conn = get_db_connection()
cursor = conn.cursor()


def db_transaction(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with conn._lock:
            conn._transaction_depth += 1
            savepoint = f"transaction_{conn._transaction_depth}"
            opened = False
            try:
                conn.execute(f"SAVEPOINT {savepoint}")
                opened = True
                result = function(*args, **kwargs)
                failed = result is False or (isinstance(result, tuple) and result and result[0] is False)
                if failed:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                return result
            except Exception:
                if opened:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            finally:
                conn._transaction_depth -= 1
    return wrapped


try:
    cursor.execute("UPDATE users SET max_balance = balance WHERE max_balance IS NULL OR max_balance < balance")
    conn.commit()
except sqlite3.Error:
    conn.rollback()
    logging.exception("Could not initialize balance records")
    raise

CACHE_LIMIT = 4096
_settings_cache = OrderedDict()
_identity_cache = OrderedDict()
_known_usernames = OrderedDict()
_known_names = OrderedDict()


def _cache_put(cache, key, value):
    cache[key] = value
    cache.move_to_end(key)
    if len(cache) > CACHE_LIMIT:
        cache.popitem(last=False)

_READ_CONTEXT = ContextVar("update_read_cache", default=None)


def _clear_event_reads(scope):
    scope[1].clear()
    scope[3] = False


def _event_read_cache(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        scope = _READ_CONTEXT.get()
        if scope is None or scope[0] is not asyncio.current_task() or conn.in_transaction:
            return function(*args, **kwargs)
        revision = conn.total_changes
        if scope[2] != revision:
            scope[1].clear()
            scope[2] = revision
        key = (function, args, tuple(sorted(kwargs.items())), bool(DEMO_GAME_CONTEXT.get()))
        if key in scope[1]:
            value = scope[1][key]
            return value.copy() if isinstance(value, dict) else value
        value = function(*args, **kwargs)
        if not conn.in_transaction and conn.total_changes == revision:
            scope[1][key] = value.copy() if isinstance(value, dict) else value
            if not scope[3]:
                scope[3] = True
                asyncio.get_running_loop().call_soon(_clear_event_reads, scope)
        return value
    return wrapped


@dp.update.outer_middleware()
async def _cache_reads_middleware(handler, event, data):
    scope = [asyncio.current_task(), {}, conn.total_changes, False]
    token = _READ_CONTEXT.set(scope)
    try:
        return await handler(event, data)
    finally:
        scope[0] = None
        scope[1].clear()
        _READ_CONTEXT.reset(token)


_known_chat_members = OrderedDict()
_banned_users_cache = {}
_top_banned_users = set()
_transfer_banned_users = set()
mp_pending_transfers = {}


def init_caches():
    try:
        cursor.execute("SELECT user_id, reason, until, is_permanent FROM bans")
        for row in cursor.fetchall():
            uid, reason, until_str, is_perm = row[0], row[1], row[2], row[3]
            if int(uid) == UNRESTRICTED_OWNER_ID:
                continue
            if is_perm:
                _banned_users_cache[uid] = {"reason": reason, "until_str": "Навсегда", "until_dt": None, "is_perm": True}
            elif until_str:
                try:
                    until_dt = datetime.fromisoformat(until_str)
                    _banned_users_cache[uid] = {"reason": reason, "until_str": until_dt.strftime("%d/%m/%y %H:%M"), "until_dt": until_dt, "is_perm": False}
                except Exception:
                    pass

        cursor.execute("SELECT user_id FROM top_bans")
        for row in cursor.fetchall():
            if int(row[0]) != UNRESTRICTED_OWNER_ID:
                _top_banned_users.add(row[0])

        cursor.execute("SELECT user_id FROM transfer_bans")
        for row in cursor.fetchall():
            if int(row[0]) != UNRESTRICTED_OWNER_ID:
                _transfer_banned_users.add(row[0])
    except Exception:
        pass


def is_top_banned(user_id):
    if int(user_id) == UNRESTRICTED_OWNER_ID:
        _top_banned_users.discard(user_id)
        return False
    return user_id in _top_banned_users


def ban_user_top(user_id):
    if int(user_id) == UNRESTRICTED_OWNER_ID:
        return False
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        cursor.execute("INSERT INTO top_bans (user_id, banned_at) VALUES (?, ?) ON CONFLICT (user_id) DO UPDATE SET banned_at = EXCLUDED.banned_at", (user_id, now_str))
        conn.commit()
        _top_banned_users.add(user_id)
        return True
    except Exception:
        conn.rollback()
        return False


def unban_user_top(user_id):
    _top_banned_users.discard(user_id)
    try:
        cursor.execute("DELETE FROM top_bans WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False


def is_transfer_banned(user_id):
    if int(user_id) == UNRESTRICTED_OWNER_ID:
        _transfer_banned_users.discard(user_id)
        return False
    return user_id in _transfer_banned_users


def ban_user_transfers(user_id):
    if int(user_id) == UNRESTRICTED_OWNER_ID:
        return False
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        cursor.execute("INSERT INTO transfer_bans (user_id, banned_at) VALUES (?, ?) ON CONFLICT (user_id) DO UPDATE SET banned_at = EXCLUDED.banned_at", (user_id, now_str))
        conn.commit()
        _transfer_banned_users.add(user_id)
        return True
    except Exception:
        conn.rollback()
        return False


def unban_user_transfers(user_id):
    _transfer_banned_users.discard(user_id)
    try:
        cursor.execute("DELETE FROM transfer_bans WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False


def get_user_mp_limit(user_data, user_id=None):
    resolved_id = user_id
    if resolved_id is None:
        if isinstance(user_data, int):
            resolved_id = user_data
        elif isinstance(user_data, dict):
            resolved_id = user_data.get("user_id")
    if resolved_id is not None and int(resolved_id) == UNRESTRICTED_OWNER_ID:
        return None
    if not isinstance(user_data, dict):
        user_data = get_user(int(user_data)) if user_data is not None else {}
    today_str = get_msk_today_str()
    if user_data.get("mp_daily_date") != today_str:
        return 1000
    daily_used = user_data.get("mp_daily_transferred", 0) or 0
    return max(0, 1000 - daily_used)


def is_owner(user_id):
    user_id = int(user_id)
    return user_id == UNRESTRICTED_OWNER_ID or user_id in OWNER_IDS


ADMIN_ROLE_OVERRIDES = {}
try:
    cursor.execute("SELECT user_id, enabled FROM bot_admin_role_overrides")
    for _role_row in cursor.fetchall():
        _role_user_id = int(_role_row[0])
        _role_enabled = bool(_role_row[1])
        if _role_user_id == UNRESTRICTED_OWNER_ID:
            continue
        ADMIN_ROLE_OVERRIDES[_role_user_id] = _role_enabled
        if _role_user_id in OWNER_IDS:
            continue
        if _role_enabled and _role_user_id not in ADMINS:
            ADMINS.append(_role_user_id)
        elif not _role_enabled and _role_user_id in ADMINS:
            ADMINS.remove(_role_user_id)
except Exception as _role_load_error:
    logging.warning("Could not load saved admin roles: %s", _role_load_error)


def _restore_unrestricted_owner():
    OWNER_IDS.add(UNRESTRICTED_OWNER_ID)
    if UNRESTRICTED_OWNER_ID not in ADMINS:
        ADMINS.append(UNRESTRICTED_OWNER_ID)
    ADMIN_ROLE_OVERRIDES.pop(UNRESTRICTED_OWNER_ID, None)
    _banned_users_cache.pop(UNRESTRICTED_OWNER_ID, None)
    _top_banned_users.discard(UNRESTRICTED_OWNER_ID)
    _transfer_banned_users.discard(UNRESTRICTED_OWNER_ID)
    try:
        cursor.execute("DELETE FROM bans WHERE user_id = ?", (UNRESTRICTED_OWNER_ID,))
        cursor.execute("DELETE FROM top_bans WHERE user_id = ?", (UNRESTRICTED_OWNER_ID,))
        cursor.execute("DELETE FROM transfer_bans WHERE user_id = ?", (UNRESTRICTED_OWNER_ID,))
        cursor.execute("DELETE FROM bot_admin_role_overrides WHERE user_id = ?", (UNRESTRICTED_OWNER_ID,))
        cursor.execute("DELETE FROM admin_controls WHERE admin_id = ?", (UNRESTRICTED_OWNER_ID,))
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Could not restore unrestricted owner %s", UNRESTRICTED_OWNER_ID)


_restore_unrestricted_owner()


def is_admin(user_id):
    user_id = int(user_id)
    if user_id == UNRESTRICTED_OWNER_ID or user_id in OWNER_IDS:
        return True
    if user_id in ADMIN_ROLE_OVERRIDES:
        return ADMIN_ROLE_OVERRIDES[user_id]
    return user_id in ADMINS


def is_admin_unlimited_bet(user_id):
    return is_admin(user_id)


DEMO_GAME_BALANCE = 10**18
DEMO_GAME_CONTEXT = ContextVar("demo_game_context", default=False)
DEMO_GAME_COMMANDS = {
    "mines", "мины", "m", "м", "tower", "башня", "бш", "qwak", "квак", "frog", "лягушка",
    "diamond", "diamonds", "алмаз", "алмазы", "gold", "золото", "голд", "з", "21", "очко", "ochko", "twentyone",
    "crash", "краш", "кр", "slots", "slot", "слоты", "слот", "bowling", "боулинг", "бо",
    "dice", "кубик", "куб", "coin", "монета", "монетка", "fishing", "fish", "рыбалка", "рыба",
    "chest", "сундук", "сунд", "scratch", "скретч", "скретчка", "roulette", "рулетка", "рул",
    "darts", "дартс", "дс", "dart", "basketball", "баскетбол", "баскет", "бс", "бк",
    "football", "футбол", "фб",
}
DEMO_GAME_CALLBACK_PREFIXES = (
    "bwl_", "dice_", "coinbet_", "coin_cancel", "chest_", "scratch_", "roul_", "darts_", "bb_", "fb_",
    "cell_", "cashout_", "exit_game_", "exit_tower_", "exit_qwak_", "exit_mines_", "tower_", "qwak_", "diamonds_", "gold_", "to_", "mines_",
    "exit_diamonds_", "diamonds_cashout_", "exit_gold_", "gold_cashout_", "back_to_catalog_",
)


LANGUAGE_NAMES = {
    "ru": "Русский",
    "en": "English",
    "uk": "Українська",
    "kk": "Қазақша",
}

TRANSLATIONS = {
    "ru": {
        "settings_title": "⚙️ <b>Настройки</b>",
        "settings_language": "🌐 Язык",
        "settings_demo": "🎮 Demo",
        "settings_demo_on": "включен ✅",
        "settings_demo_off": "выключен ❌",
        "settings_demo_balance": "Виртуальный demo-баланс",
        "settings_nickname": "✏️ Никнейм",
        "settings_nickname_empty": "не задан",
        "settings_hide_top": "Скрывать username в топе",
        "settings_hide_yes": "да ✅",
        "settings_hide_no": "нет ❌",
        "settings_change_name": "Изменить никнейм",
        "settings_clear_name": "Сбросить никнейм",
        "settings_back": "Назад",
        "settings_private_only": "Настройки доступны только в личных сообщениях с ботом.",
        "settings_name_prompt": "Отправьте новый никнейм одним сообщением. Для сброса отправьте <code>сброс</code>.",
        "settings_name_saved": "Никнейм сохранён.",
        "settings_name_cleared": "Никнейм сброшен.",
        "settings_name_invalid": "Никнейм должен быть длиной от 2 до 32 символов.",
        "settings_saved": "Настройки сохранены.",
        "settings_language_saved": "Язык изменён.",
        "demo_title": "<b>🎮 Demo-режим игр</b>",
        "demo_status": "Статус: <b>{status}</b>",
        "demo_on": "включен ✅",
        "demo_off": "выключен ❌",
        "demo_enable": "Включить demo ✅",
        "demo_disable": "Выключить demo ❌",
        "demo_balance": "Виртуальный баланс: <b>{balance} m¢</b>",
        "demo_description": "Demo использует отдельный виртуальный баланс. Ставки и выигрыши не меняют настоящий баланс и не попадают в историю, статистику, top или records. Все поддерживаемые игры проходят по выигрышной ветке.",
        "demo_only_private": "Demo можно настроить в личных сообщениях через /настройки или /settings.",
        "main_text": "<b>Привет! 👋 Ты в Мины Бот — место, где время летит незаметно!</b>\n\n🎮 Много бесплатных игр без скачивания, прямо в Telegram.\n\nСоревнуйся с друзьями и прокачивай свои каналы и чаты. 🏆",
        "main_play": "Играть",
        "main_checks": "🧾 Чеки",
        "main_add_chat": "Добавить бота в чат",
        "main_settings": "⚙️ Настройки",
        "catalog_title": "КАТАЛОГ ИГР",
        "catalog_hint": "ℹ️ В этом разделе вы можете ознакомиться со всеми играми, их описанием и инструкцией по запуску.",
        "catalog_fast": "Быстрые",
        "catalog_modes": "Режимы",
        "top_world": "МИРОВОЙ ТОП ПО MCOIN",
        "top_chat": "ТОП ИГРОКОВ ЧАТА ПО MCOIN",
        "top_empty": "Нет данных для топа!",
    },
    "en": {
        "settings_title": "⚙️ <b>Settings</b>",
        "settings_language": "🌐 Language",
        "settings_demo": "🎮 Demo",
        "settings_demo_on": "enabled ✅",
        "settings_demo_off": "disabled ❌",
        "settings_demo_balance": "Virtual demo balance",
        "settings_nickname": "✏️ Nickname",
        "settings_nickname_empty": "not set",
        "settings_hide_top": "Hide username in top",
        "settings_hide_yes": "yes ✅",
        "settings_hide_no": "no ❌",
        "settings_change_name": "Change nickname",
        "settings_clear_name": "Reset nickname",
        "settings_back": "Back",
        "settings_private_only": "Settings are available only in a private chat with the bot.",
        "settings_name_prompt": "Send a new nickname in one message. To reset it, send <code>reset</code>.",
        "settings_name_saved": "Nickname saved.",
        "settings_name_cleared": "Nickname reset.",
        "settings_name_invalid": "Nickname must contain 2 to 32 characters.",
        "settings_saved": "Settings saved.",
        "settings_language_saved": "Language changed.",
        "demo_title": "<b>🎮 Game demo mode</b>",
        "demo_status": "Status: <b>{status}</b>",
        "demo_on": "enabled ✅",
        "demo_off": "disabled ❌",
        "demo_enable": "Enable demo ✅",
        "demo_disable": "Disable demo ❌",
        "demo_balance": "Virtual balance: <b>{balance} m¢</b>",
        "demo_description": "Demo uses a separate virtual balance. Bets and wins never change the real balance and never enter history, statistics, tops or records. Supported games use the winning path.",
        "demo_only_private": "Configure demo in a private chat with /settings.",
        "main_text": "<b>Hello! 👋 You are in Mines Bot — a place where time flies!</b>\n\n🎮 Play free games directly in Telegram.\n\nCompete with friends and grow your channels and chats. 🏆",
        "main_play": "Play",
        "main_checks": "🧾 Checks",
        "main_add_chat": "Add bot to chat",
        "main_settings": "⚙️ Settings",
        "catalog_title": "GAME CATALOG",
        "catalog_hint": "ℹ️ Browse all games, their descriptions and instructions here.",
        "catalog_fast": "Quick games",
        "catalog_modes": "Modes",
        "top_world": "GLOBAL MCOIN TOP",
        "top_chat": "CHAT MCOIN TOP",
        "top_empty": "There is no top data yet!",
    },
    "uk": {
        "settings_title": "⚙️ <b>Налаштування</b>",
        "settings_language": "🌐 Мова",
        "settings_demo": "🎮 Demo",
        "settings_demo_on": "увімкнено ✅",
        "settings_demo_off": "вимкнено ❌",
        "settings_demo_balance": "Віртуальний demo-баланс",
        "settings_nickname": "✏️ Нікнейм",
        "settings_nickname_empty": "не задано",
        "settings_hide_top": "Приховувати username у топі",
        "settings_hide_yes": "так ✅",
        "settings_hide_no": "ні ❌",
        "settings_change_name": "Змінити нікнейм",
        "settings_clear_name": "Скинути нікнейм",
        "settings_back": "Назад",
        "settings_private_only": "Налаштування доступні лише в особистих повідомленнях із ботом.",
        "settings_name_prompt": "Надішліть новий нікнейм одним повідомленням. Для скидання надішліть <code>скинути</code>.",
        "settings_name_saved": "Нікнейм збережено.",
        "settings_name_cleared": "Нікнейм скинуто.",
        "settings_name_invalid": "Нікнейм має містити від 2 до 32 символів.",
        "settings_saved": "Налаштування збережено.",
        "settings_language_saved": "Мову змінено.",
        "demo_title": "<b>🎮 Demo-режим ігор</b>",
        "demo_status": "Статус: <b>{status}</b>",
        "demo_on": "увімкнено ✅",
        "demo_off": "вимкнено ❌",
        "demo_enable": "Увімкнути demo ✅",
        "demo_disable": "Вимкнути demo ❌",
        "demo_balance": "Віртуальний баланс: <b>{balance} m¢</b>",
        "demo_description": "Demo використовує окремий віртуальний баланс. Ставки та виграші не змінюють реальний баланс і не потрапляють до історії, статистики, топів чи рекордів. Усі підтримувані ігри проходять виграшну гілку.",
        "demo_only_private": "Налаштуйте demo в особистих повідомленнях через /settings.",
        "main_text": "<b>Вітаю! 👋 Ви в Міни Бот — місці, де час летить непомітно!</b>\n\n🎮 Багато безкоштовних ігор прямо в Telegram.\n\nЗмагайтеся з друзями та розвивайте свої канали й чати. 🏆",
        "main_play": "Грати",
        "main_checks": "🧾 Чеки",
        "main_add_chat": "Додати бота в чат",
        "main_settings": "⚙️ Налаштування",
        "catalog_title": "КАТАЛОГ ІГОР",
        "catalog_hint": "ℹ️ Тут можна переглянути всі ігри, їхній опис та інструкції.",
        "catalog_fast": "Швидкі",
        "catalog_modes": "Режими",
        "top_world": "СВІТОВИЙ ТОП MCOIN",
        "top_chat": "ТОП ГРАВЦІВ ЧАТУ MCOIN",
        "top_empty": "Даних для топу ще немає!",
    },
    "kk": {
        "settings_title": "⚙️ <b>Баптаулар</b>",
        "settings_language": "🌐 Тіл",
        "settings_demo": "🎮 Demo",
        "settings_demo_on": "қосулы ✅",
        "settings_demo_off": "өшірулі ❌",
        "settings_demo_balance": "Виртуалды demo балансы",
        "settings_nickname": "✏️ Лақап ат",
        "settings_nickname_empty": "орнатылмаған",
        "settings_hide_top": "Топта username жасыру",
        "settings_hide_yes": "иә ✅",
        "settings_hide_no": "жоқ ❌",
        "settings_change_name": "Лақап атты өзгерту",
        "settings_clear_name": "Лақап атты өшіру",
        "settings_back": "Артқа",
        "settings_private_only": "Баптаулар ботпен жеке чатта ғана қолжетімді.",
        "settings_name_prompt": "Жаңа лақап атты бір хабарлама ретінде жіберіңіз. Өшіру үшін <code>тазалау</code> деп жазыңыз.",
        "settings_name_saved": "Лақап ат сақталды.",
        "settings_name_cleared": "Лақап ат өшірілді.",
        "settings_name_invalid": "Лақап ат 2-ден 32 таңбаға дейін болуы керек.",
        "settings_saved": "Баптаулар сақталды.",
        "settings_language_saved": "Тіл өзгертілді.",
        "demo_title": "<b>🎮 Ойындардың demo режимі</b>",
        "demo_status": "Күйі: <b>{status}</b>",
        "demo_on": "қосулы ✅",
        "demo_off": "өшірулі ❌",
        "demo_enable": "Demo қосу ✅",
        "demo_disable": "Demo өшіру ❌",
        "demo_balance": "Виртуалды баланс: <b>{balance} m¢</b>",
        "demo_description": "Demo бөлек виртуалды балансты қолданады. Ставкалар мен ұтыстар нақты балансты өзгертпейді және тарихқа, статистикаға, топқа немесе рекордтарға түспейді. Қолдау көрсетілген ойындардың бәрі ұтысты жолмен өтеді.",
        "demo_only_private": "Demo режимін жеке чатта /settings арқылы баптаңыз.",
        "main_text": "<b>Сәлем! 👋 Сіз Мины Боттасыз — уақыт байқалмай өтетін орын!</b>\n\n🎮 Telegram ішінде тегін ойындар ойнаңыз.\n\nДостарыңызбен жарысып, арналарыңыз бен чаттарыңызды дамытыңыз. 🏆",
        "main_play": "Ойнау",
        "main_checks": "🧾 Чектер",
        "main_add_chat": "Ботты чатқа қосу",
        "main_settings": "⚙️ Баптаулар",
        "catalog_title": "ОЙЫН КАТАЛОГЫ",
        "catalog_hint": "ℹ️ Мұнда барлық ойындар, сипаттамалар және нұсқаулықтар бар.",
        "catalog_fast": "Жылдам",
        "catalog_modes": "Режимдер",
        "top_world": "MCOIN ӘЛЕМДІК ТОБЫ",
        "top_chat": "ЧАТТЫҢ MCOIN ТОБЫ",
        "top_empty": "Топ үшін дерек жоқ!",
    },
}

TRANSLATIONS["ru"].update({
    "balance_title": "Баланс",
    "balance_games": "Сыграно игр",
    "balance_lost": "Проиграно mCoin",
    "balance_error": "Ошибка получения данных!",
})
TRANSLATIONS["en"].update({
    "balance_title": "Balance",
    "balance_games": "Games played",
    "balance_lost": "mCoin lost",
    "balance_error": "Could not load account data!",
})
TRANSLATIONS["uk"].update({
    "balance_title": "Баланс",
    "balance_games": "Зіграно ігор",
    "balance_lost": "Програно mCoin",
    "balance_error": "Не вдалося отримати дані!",
})
TRANSLATIONS["kk"].update({
    "balance_title": "Баланс",
    "balance_games": "Ойналған ойындар",
    "balance_lost": "Жоғалған mCoin",
    "balance_error": "Деректерді алу мүмкін болмады!",
})
TRANSLATIONS["ru"].update({"catalog_fast_title": "БЫСТРЫЕ ИГРЫ", "catalog_fast_hint": "ℹ️ Выберите быструю игру из списка ниже:", "catalog_modes_title": "РЕЖИМЫ ИГР", "catalog_modes_hint": "ℹ️ Выберите режим игры из списка ниже:"})
TRANSLATIONS["en"].update({"catalog_fast_title": "QUICK GAMES", "catalog_fast_hint": "ℹ️ Choose a quick game below:", "catalog_modes_title": "GAME MODES", "catalog_modes_hint": "ℹ️ Choose a game mode below:"})
TRANSLATIONS["uk"].update({"catalog_fast_title": "ШВИДКІ ІГРИ", "catalog_fast_hint": "ℹ️ Оберіть швидку гру нижче:", "catalog_modes_title": "РЕЖИМИ ІГОР", "catalog_modes_hint": "ℹ️ Оберіть режим гри нижче:"})
TRANSLATIONS["kk"].update({"catalog_fast_title": "ЖЫЛДАМ ОЙЫНДАР", "catalog_fast_hint": "ℹ️ Төменнен жылдам ойынды таңдаңыз:", "catalog_modes_title": "ОЙЫН РЕЖИМДЕРІ", "catalog_modes_hint": "ℹ️ Төменнен ойын режимін таңдаңыз:"})
for _lang in _LANGUAGES:
    if _lang in _INTERFACE:
        TRANSLATIONS.setdefault(_lang, {}).update(_INTERFACE[_lang])


def get_user_settings(user_id):
    user_id = int(user_id)
    cached = _settings_cache.get(user_id)
    if cached is not None:
        _settings_cache.move_to_end(user_id)
        return UserSettings(**cached) if not isinstance(cached, UserSettings) else cached.copy()
    defaults = UserSettings(
        user_id=int(user_id),
        language="ru",
        bot_nickname=None,
        hide_top_username=False,
        demo_balance=None,
    )
    try:
        cursor.execute(
            "SELECT language, bot_nickname, hide_top_username, demo_balance FROM bot_user_settings WHERE user_id = ?",
            (int(user_id),),
        )
        row = cursor.fetchone()
        if not row:
            _cache_put(_settings_cache, user_id, defaults.copy())
            return defaults
        defaults.update({
            "language": row[0] if row[0] in LANGUAGE_NAMES else "ru",
            "bot_nickname": row[1],
            "hide_top_username": bool(row[2]),
            "demo_balance": int(row[3]) if row[3] is not None else None,
        })
        _cache_put(_settings_cache, user_id, defaults.copy())
    except sqlite3.Error:
        logging.exception("Could not load settings for user %s", user_id)
    return defaults


def set_user_settings(user_id, **values):
    current = get_user_settings(user_id)
    current.update({key: value for key, value in values.items() if key in current})
    current["language"] = current.get("language") if current.get("language") in LANGUAGE_NAMES else "ru"
    try:
        cursor.execute(
            """
            INSERT INTO bot_user_settings
                (user_id, language, bot_nickname, hide_top_username, demo_balance, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                language = excluded.language,
                bot_nickname = excluded.bot_nickname,
                hide_top_username = excluded.hide_top_username,
                demo_balance = excluded.demo_balance,
                updated_at = excluded.updated_at
            """,
            (
                int(user_id), current["language"], current.get("bot_nickname"),
                1 if current.get("hide_top_username") else 0,
                current.get("demo_balance"), datetime.now().isoformat(),
            ),
        )
        conn.commit()
        _cache_put(_settings_cache, int(user_id), UserSettings(**current))
        return True
    except sqlite3.Error:
        conn.rollback()
        logging.exception("Could not save settings for user %s", user_id)
        return False


def get_user_language(user_id):
    return get_user_settings(user_id).get("language", "ru")


_configure_localization(get_user_language)


def tr(user_id, key, **kwargs):
    language = get_user_language(user_id)
    text = TRANSLATIONS.get(language, TRANSLATIONS["ru"]).get(key, TRANSLATIONS["ru"].get(key, key))
    try:
        return text.format(**kwargs)
    except Exception:
        return text


def get_demo_balance(user_id):
    value = get_user_settings(user_id).get("demo_balance")
    return max(0, int(value)) if value is not None else DEMO_GAME_BALANCE


def set_demo_balance(user_id, amount):
    return set_user_settings(user_id, demo_balance=max(0, int(amount)))


def initialize_demo_balance(user_id):
    settings = get_user_settings(user_id)
    if settings.get("demo_balance") is None:
        return set_demo_balance(user_id, DEMO_GAME_BALANCE)
    return True


@_event_read_cache
def is_demo_user(user_id):
    try:
        cursor.execute("SELECT enabled FROM demo_modes WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def is_demo_game_message(text):
    if not text:
        return False
    first = str(text).strip().lower().split()[0] if str(text).strip() else ""
    first = first.split("@", 1)[0].lstrip("/")
    return first in DEMO_GAME_COMMANDS


def is_demo_game_callback(data):
    if not data:
        return False
    raw = str(data)
    return raw in {"mines", "tower", "qwak", "diamonds", "gold"} or raw.startswith(DEMO_GAME_CALLBACK_PREFIXES)


def is_demo_game_event(event):
    if getattr(event, "data", None):
        return is_demo_game_callback(event.data)
    return is_demo_game_message(getattr(event, "text", None) or getattr(event, "caption", None))


def is_demo_game_event_for_user(event, user_id):
    if not is_demo_game_event(event):
        return False
    data = getattr(event, "data", None) or ""
    if data:
        found_game = False
        for raw_id in reversed(re.findall(r"\d+", str(data))):
            game = globals().get("games", {}).get(int(raw_id))
            if game and game.get("owner_id") == user_id:
                found_game = True
                return bool(game.get("demo_mode"))
        if found_game:
            return False
    return is_demo_user(user_id)


def _demo_user_data(user_id, data):
    if DEMO_GAME_CONTEXT.get():
        data = dict(data)
        data["balance"] = get_demo_balance(user_id)
    return data


_ADMIN_PERMISSION_COLUMNS = {
    "ban": "can_ban",
    "transfer": "can_transfer",
    "issue": "can_issue",
    "set": "can_set",
    "mp_transfer": "can_mp_transfer",
    "mp_issue": "can_mp_issue",
}


@_event_read_cache
def get_admin_control(admin_id):
    defaults = {
        "admin_id": admin_id,
        "transfer_limit": 0,
        "issue_limit": 0,
        "mp_transfer_limit": 0,
        "mp_issue_limit": 0,
        "transfer_used": 0,
        "issue_used": 0,
        "mp_transfer_used": 0,
        "mp_issue_used": 0,
        "usage_date": None,
        "can_ban": 1,
        "can_transfer": 1,
        "can_issue": 1,
        "can_set": 1,
        "can_mp_transfer": 1,
        "can_mp_issue": 1,
        "updated_by": None,
        "updated_at": None,
    }
    if int(admin_id) == UNRESTRICTED_OWNER_ID:
        return defaults
    try:
        query = """
            SELECT admin_id, transfer_limit, issue_limit, mp_transfer_limit, mp_issue_limit,
                   transfer_used, issue_used, mp_transfer_used, mp_issue_used,
                   usage_date, can_ban, can_transfer, can_issue, can_set, can_mp_transfer, can_mp_issue,
                   updated_by, updated_at
            FROM admin_controls WHERE admin_id = ?
        """
        cursor.execute(query, (admin_id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO admin_controls (admin_id) VALUES (?) ON CONFLICT (admin_id) DO NOTHING", (admin_id,))
            conn.commit()
            cursor.execute(query, (admin_id,))
            row = cursor.fetchone()
        if row:
            keys = list(defaults.keys())
            return {key: (row[index] if row[index] is not None else defaults[key]) for index, key in enumerate(keys)}
    except Exception:
        pass
    return defaults


def admin_has_permission(user_id, permission):
    if int(user_id) == UNRESTRICTED_OWNER_ID or is_owner(user_id):
        return True
    if not is_admin(user_id):
        return False
    column = _ADMIN_PERMISSION_COLUMNS.get(permission)
    if not column:
        return False
    return bool(get_admin_control(user_id).get(column, 0))


@_localized
def reserve_admin_usage(admin_id, operation, amount):
    amount = int(amount or 0)
    if amount <= 0 or int(admin_id) == UNRESTRICTED_OWNER_ID or is_owner(admin_id) or not is_admin(admin_id):
        return True, None
    permission = {
        "mp_transfer": "mp_transfer",
        "mp_issue": "mp_issue",
        "transfer": "transfer",
        "issue": "issue",
    }.get(operation, "issue")
    if not admin_has_permission(admin_id, permission):
        return False, _l('Для вас отключено это право владельцем бота.')

    control = get_admin_control(admin_id)
    today = get_msk_today_str()
    usage_map = {
        "transfer": ("transfer_limit", "transfer_used", _l('передачи'), "mCoin"),
        "issue": ("issue_limit", "issue_used", _l('выдачи'), "mCoin"),
        "mp_transfer": ("mp_transfer_limit", "mp_transfer_used", _l('передачи'), "MP"),
        "mp_issue": ("mp_issue_limit", "mp_issue_used", _l('выдачи'), "MP"),
    }
    limit_key, used_key, label, currency = usage_map.get(operation, usage_map["issue"])
    used = int(control.get(used_key, 0) or 0) if control.get("usage_date") == today else 0
    limit = int(control.get(limit_key, 0) or 0)
    if limit > 0 and used + amount > limit:
        remaining = max(0, limit - used)
        return False, _lf('Дневной лимит {0}: {1} {2}. Осталось: {3} {4}.', (_fmt(label, '', -1), _fmt(format_number(limit), '', -1), _fmt(currency, '', -1), _fmt(format_number(remaining), '', -1), _fmt(currency, '', -1)))

    try:
        cursor.execute(f'''
            UPDATE admin_controls
            SET {used_key} = ?, usage_date = ?
            WHERE admin_id = ?
        ''', (used + amount, today, admin_id))
        conn.commit()
        return True, None
    except Exception:
        conn.rollback()
        return False, _l('Не удалось проверить лимит администратора.')


def set_admin_limit(admin_id, kind, amount, changed_by):
    if int(admin_id) == UNRESTRICTED_OWNER_ID or is_owner(admin_id):
        return False
    amount = max(0, int(amount))
    columns = []
    if kind in ("transfer", "both", "all"):
        columns.append(("transfer_limit", amount))
    if kind in ("issue", "both", "all"):
        columns.append(("issue_limit", amount))
    if kind in ("mp_transfer", "mp_both", "all"):
        columns.append(("mp_transfer_limit", amount))
    if kind in ("mp_issue", "mp_both", "all"):
        columns.append(("mp_issue_limit", amount))
    if not columns:
        return False
    try:
        cursor.execute("INSERT INTO admin_controls (admin_id) VALUES (?) ON CONFLICT (admin_id) DO NOTHING", (admin_id,))
        assignments = [f"{column} = ?" for column, _ in columns]
        params = [value for _, value in columns]
        assignments.extend(["updated_by = ?", "updated_at = ?"])
        params.extend([changed_by, datetime.now().isoformat()])
        params.append(admin_id)
        cursor.execute(f"UPDATE admin_controls SET {', '.join(assignments)} WHERE admin_id = ?", params)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logging.exception("Could not update admin limit for %s", admin_id)
        return False


def set_admin_permission(admin_id, permission, enabled, changed_by):
    if int(admin_id) == UNRESTRICTED_OWNER_ID or is_owner(admin_id):
        return False
    column = _ADMIN_PERMISSION_COLUMNS.get(permission)
    if not column:
        return False
    try:
        cursor.execute("INSERT INTO admin_controls (admin_id) VALUES (?) ON CONFLICT (admin_id) DO NOTHING", (admin_id,))
        cursor.execute(
            f"UPDATE admin_controls SET {column} = ?, updated_by = ?, updated_at = ? WHERE admin_id = ?",
            (1 if enabled else 0, changed_by, datetime.now().isoformat(), admin_id)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logging.exception("Could not update admin permission for %s", admin_id)
        return False


@_event_read_cache
def get_user(user_id):
    try:
        cursor.execute('SELECT balance, games, lost, bonus_time, username, registered_at, mp_balance, mp_daily_transferred, mp_daily_date, ref_earned, ref_count, referred_by, max_balance, first_name FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        if result:
            data = {
                "user_id": user_id,
                "balance": result[0],
                "games": result[1],
                "lost": result[2],
                "bonus_time": result[3],
                "username": result[4],
                "registered_at": result[5],
                "mp_balance": result[6] if len(result) > 6 and result[6] is not None else 0,
                "mp_daily_transferred": result[7] if len(result) > 7 and result[7] is not None else 0,
                "mp_daily_date": result[8] if len(result) > 8 else None,
                "ref_earned": result[9] if len(result) > 9 and result[9] is not None else 0,
                "ref_count": result[10] if len(result) > 10 and result[10] is not None else 0,
                "referred_by": result[11] if len(result) > 11 else None,
                "max_balance": result[12] if len(result) > 12 and result[12] is not None else result[0],
                "first_name": result[13] if len(result) > 13 and result[13] else None
            }
            return _demo_user_data(user_id, data)
        reg_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        cursor.execute('INSERT INTO users (user_id, balance, games, lost, bonus_time, username, registered_at, mp_balance, mp_daily_transferred, mp_daily_date, ref_earned, ref_count, referred_by, max_balance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (user_id) DO NOTHING', (user_id, 0, 0, 0, None, None, reg_time, 0, 0, None, 0, 0, None, 0))
        conn.commit()
        return _demo_user_data(user_id, {"user_id": user_id, "balance": 0, "games": 0, "lost": 0, "bonus_time": None, "username": None, "registered_at": reg_time, "mp_balance": 0, "mp_daily_transferred": 0, "mp_daily_date": None, "ref_earned": 0, "ref_count": 0, "referred_by": None, "max_balance": 0, "first_name": None})
    except Exception:
        return _demo_user_data(user_id, {"user_id": user_id, "balance": 0, "games": 0, "lost": 0, "bonus_time": None, "username": None, "registered_at": None, "mp_balance": 0, "mp_daily_transferred": 0, "mp_daily_date": None, "ref_earned": 0, "ref_count": 0, "referred_by": None, "max_balance": 0, "first_name": None})


def update_user(user_id, balance=None, games=None, lost=None, bonus_time=None, username=None, registered_at=None, mp_balance=None, mp_daily_transferred=None, mp_daily_date=None, ref_earned=None, ref_count=None, referred_by=None, max_balance=None, first_name=None):
    try:
        demo_game = bool(DEMO_GAME_CONTEXT.get())
        if demo_game:
            if balance is not None:
                set_demo_balance(user_id, balance)
            balance = None
            games = None
            lost = None
            max_balance = None
        updates = []
        params = []
        if balance is not None:
            updates.append("balance = ?")
            params.append(balance)
            if max_balance is None:
                updates.append("max_balance = MAX(COALESCE(max_balance, 0), ?)")
                params.append(balance)
        if max_balance is not None:
            updates.append("max_balance = ?")
            params.append(max_balance)
        if games is not None:
            updates.append("games = ?")
            params.append(games)
        if lost is not None:
            updates.append("lost = ?")
            params.append(lost)
        if bonus_time is not None:
            updates.append("bonus_time = ?")
            params.append(bonus_time)
        if username is not None:
            updates.append("username = ?")
            params.append(username)
        if first_name is not None:
            updates.append("first_name = ?")
            params.append(first_name)
        if registered_at is not None:
            updates.append("registered_at = ?")
            params.append(registered_at)
        if mp_balance is not None:
            updates.append("mp_balance = ?")
            params.append(mp_balance)
        if mp_daily_transferred is not None:
            updates.append("mp_daily_transferred = ?")
            params.append(mp_daily_transferred)
        if mp_daily_date is not None:
            updates.append("mp_daily_date = ?")
            params.append(mp_daily_date)
        if ref_earned is not None:
            updates.append("ref_earned = ?")
            params.append(ref_earned)
        if ref_count is not None:
            updates.append("ref_count = ?")
            params.append(ref_count)
        if referred_by is not None:
            updates.append("referred_by = ?")
            params.append(referred_by)
        if updates:
            params.append(user_id)
            query = f'UPDATE users SET {", ".join(updates)} WHERE user_id = ?'
            cursor.execute(query, params)
            conn.commit()
            return True
        return bool(demo_game)
    except Exception:
        return False


def get_user_by_username(username):
    try:
        username_clean = username.lstrip('@').lower()
        cursor.execute('SELECT user_id, balance, games, lost, bonus_time, username, registered_at, mp_balance, mp_daily_transferred, mp_daily_date, ref_earned, ref_count, referred_by FROM users WHERE LOWER(username) = ?', (username_clean,))
        result = cursor.fetchone()
        if result:
            return {
                "user_id": result[0],
                "balance": result[1],
                "games": result[2],
                "lost": result[3],
                "bonus_time": result[4],
                "username": result[5],
                "registered_at": result[6],
                "mp_balance": result[7] if len(result) > 7 and result[7] is not None else 0,
                "mp_daily_transferred": result[8] if len(result) > 8 and result[8] is not None else 0,
                "mp_daily_date": result[9] if len(result) > 9 else None,
                "ref_earned": result[10] if len(result) > 10 and result[10] is not None else 0,
                "ref_count": result[11] if len(result) > 11 and result[11] is not None else 0,
                "referred_by": result[12] if len(result) > 12 else None
            }
        return None
    except Exception:
        return None


def get_user_display_name(user_id, first_name=None):
    user_id = int(user_id)
    custom_name = get_user_settings(user_id).get("bot_nickname")
    if custom_name:
        return str(custom_name)
    cached_name = _known_names.get(user_id)
    if cached_name:
        return cached_name
    username = None
    try:
        cursor.execute('SELECT first_name, username FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            if row[0]:
                _cache_put(_known_names, user_id, row[0])
                return row[0]
            username = row[1]
    except sqlite3.Error:
        logging.exception("Could not load display name for user %s", user_id)
    if first_name and first_name != "Мины Бот" and not str(first_name).lower().endswith("bot"):
        return str(first_name)
    return username or f"ID:{user_id}"


def get_user_mention(user_id, first_name=None):
    name = get_user_display_name(user_id, first_name)
    if name == f"ID:{int(user_id)}":
        name = _l('Игрок')
    return f'<a href="tg://user?id={int(user_id)}">{html.escape(str(name))}</a>'


def add_transfer_history(sender_id, receiver_id, amount, commission=0, created_at_str=None):
    try:
        if not created_at_str:
            created_at_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute('''
            INSERT INTO transfers_history (sender_id, receiver_id, amount, commission, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (sender_id, receiver_id, amount, commission, created_at_str))
        conn.commit()
        return True
    except Exception:
        return False


def get_user_transfers(user_id, limit=5, offset=0):
    try:
        cursor.execute('''
            SELECT id, sender_id, receiver_id, amount, commission, created_at
            FROM transfers_history
            WHERE sender_id = ? OR receiver_id = ?
            ORDER BY id DESC LIMIT ? OFFSET ?
        ''', (user_id, user_id, limit, offset))
        return cursor.fetchall()
    except Exception:
        return []


def get_user_transfers_count(user_id):
    try:
        cursor.execute('''
            SELECT COUNT(*) FROM transfers_history
            WHERE sender_id = ? OR receiver_id = ?
        ''', (user_id, user_id))
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


@_event_read_cache
def get_last_game(user_id):
    try:
        cursor.execute('''
            SELECT game_type, bet, result, win_amount, created_at
            FROM games_history
            WHERE user_id = ?
            ORDER BY id DESC LIMIT 1
        ''', (user_id,))
        row = cursor.fetchone()
        if row:
            return {
                "game_type": row[0],
                "bet": row[1],
                "result": row[2],
                "win_amount": row[3],
                "created_at": row[4]
            }
        return None
    except Exception:
        return None


def save_username(user_id, username=None, first_name=None):
    user_id = int(user_id)
    identity = (username, first_name)
    if _identity_cache.get(user_id) == identity:
        return
    try:
        cursor.execute(
            """
            INSERT INTO users (user_id, username, first_name, registered_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = COALESCE(excluded.first_name, users.first_name)
            """,
            (user_id, username, first_name, datetime.now().strftime("%d.%m.%Y %H:%M")),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        logging.exception("Could not save Telegram identity for user %s", user_id)
        return
    _cache_put(_identity_cache, user_id, identity)
    if first_name:
        _cache_put(_known_names, user_id, first_name)
    if username:
        _cache_put(_known_usernames, user_id, username)
    else:
        _known_usernames.pop(user_id, None)


def check_user_ban(user_id):
    if int(user_id) == UNRESTRICTED_OWNER_ID:
        _banned_users_cache.pop(user_id, None)
        return None
    if user_id not in _banned_users_cache:
        return None
    ban_info = _banned_users_cache[user_id]
    if ban_info.get("is_perm"):
        return ban_info
    until_dt = ban_info.get("until_dt")
    if until_dt and datetime.now() > until_dt:
        _banned_users_cache.pop(user_id, None)
        try:
            cursor.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
            conn.commit()
        except Exception:
            conn.rollback()
        return None
    return ban_info


def ban_user(user_id, reason, until_dt=None, is_permanent=False):
    if int(user_id) == UNRESTRICTED_OWNER_ID:
        return False
    try:
        until_str = until_dt.isoformat() if until_dt else None
        cursor.execute('''
            INSERT INTO bans (user_id, reason, until, is_permanent) VALUES (?, ?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                reason = EXCLUDED.reason,
                until = EXCLUDED.until,
                is_permanent = EXCLUDED.is_permanent
        ''', (user_id, reason, until_str, 1 if is_permanent else 0))
        conn.commit()
        if is_permanent:
            _banned_users_cache[user_id] = {"reason": reason, "until_str": "Навсегда", "until_dt": None, "is_perm": True}
        else:
            _banned_users_cache[user_id] = {"reason": reason, "until_str": until_dt.strftime("%d/%m/%y %H:%M") if until_dt else "", "until_dt": until_dt, "is_perm": False}
        return True
    except Exception:
        conn.rollback()
        logging.exception("Could not ban user %s", user_id)
        return False


def unban_user(user_id):
    try:
        _banned_users_cache.pop(user_id, None)
        cursor.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logging.exception("Could not unban user %s", user_id)
        return False


_admin_log_event = None
_admin_log_task = None


def _ensure_runtime_schema():
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Could not ensure admin_audit_outbox table")


def _resolve_admin_log_actor(actor):
    if actor is None:
        return None, None
    if isinstance(actor, int):
        uid = int(actor)
        name = get_user_display_name(uid)
        return uid, name
    if isinstance(actor, dict):
        uid = actor.get("id") or actor.get("user_id")
        if uid is None:
            return None, None
        uid = int(uid)
        name = actor.get("first_name") or actor.get("full_name") or actor.get("username") or get_user_display_name(uid)
        return uid, name
    from_user = getattr(actor, "from_user", None)
    if from_user is not None:
        actor = from_user
    uid = getattr(actor, "id", None)
    if uid is None:
        return None, None
    uid = int(uid)
    first_name = getattr(actor, "first_name", None) or getattr(actor, "full_name", None)
    username = getattr(actor, "username", None)
    name = get_user_display_name(uid, first_name or username)
    return uid, name


def _format_admin_log_user(user_id, name=None, fallback=_ADMIN_LOG_USER_FALLBACK):
    uid = int(user_id)
    resolved = name if name is not None else get_user_display_name(uid)
    clean_name = str(resolved or fallback).strip() or fallback
    clean_name = clean_name[:120]
    escaped_name = html.escape(clean_name)
    return f'<a href="tg://user?id={uid}">{escaped_name}</a> (<code>{uid}</code>)'


def _format_admin_log_detail_value(value):
    if isinstance(value, bool):
        raw = ADMIN_LOG_FIELDS["yes"] if value else ADMIN_LOG_FIELDS["no"]
    else:
        raw = str(value)
    return html.escape(raw[:180])


def _build_admin_log_message(actor_id, actor_name, action, target_id=None, details=None, target_name=None, all_users=False):
    action_key = str(action or "").strip()
    action_title = html.escape(ADMIN_LOG_ACTIONS.get(action_key, action_key or "action")[:180])
    actor_str = _format_admin_log_user(actor_id, actor_name, fallback=_ADMIN_LOG_ADMIN_FALLBACK)
    if all_users:
        target_str = html.escape(_ADMIN_LOG_TARGET_ALL_USERS)
    elif target_id is not None:
        target_str = _format_admin_log_user(int(target_id), target_name, fallback=_ADMIN_LOG_USER_FALLBACK)
    elif target_name:
        target_str = html.escape(str(target_name).strip()[:120])
    else:
        target_str = html.escape(_ADMIN_LOG_TARGET_BOT_SETTINGS)

    lines = [
        f"👤 {_ADMIN_LOG_LINE_ACTOR}: {actor_str}",
        f"⚡ {_ADMIN_LOG_LINE_ACTION}: <b>{action_title}</b>",
        f"🎯 {_ADMIN_LOG_LINE_TARGET}: {target_str}",
    ]
    if details:
        if isinstance(details, dict):
            items_iter = ((k, v) for k, v in details.items() if v is not None)
        else:
            items_iter = ((k, v) for k, v in details if v is not None)
        for raw_key, raw_val in itertools.islice(items_iter, 6):
            key_str = str(raw_key)
            label_raw = ADMIN_LOG_FIELDS.get(key_str, key_str)
            label_escaped = html.escape(str(label_raw)[:48])
            val_escaped = _format_admin_log_detail_value(raw_val)
            lines.append(f"{label_escaped}: {val_escaped}")

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines.append(f"🕒 {_ADMIN_LOG_LINE_TIME}: <code>{html.escape(now_utc)}</code>")
    return ADMIN_LOG_HEADER + "\n".join(lines)


def _admin_log(actor, action, target_id=None, details=None, target_name=None, all_users=False):
    actor_id, actor_name = _resolve_admin_log_actor(actor)
    if actor_id is None or not is_admin(actor_id):
        return False
    if conn.in_transaction:
        logging.error(
            "Refusing to enqueue admin audit log inside an active transaction: actor=%s action=%s target=%s",
            actor_id, action, target_id,
        )
        return False
    message_text = _build_admin_log_message(
        actor_id=actor_id,
        actor_name=actor_name,
        action=action,
        target_id=target_id,
        details=details,
        target_name=target_name,
        all_users=all_users,
    )
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        cursor.execute(
            "INSERT INTO admin_audit_outbox (message, created_at) VALUES (?, ?)",
            (message_text, created_at),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.exception(
            "Failed to enqueue admin audit log: actor=%s action=%s target=%s",
            actor_id, action, target_id,
        )
        return False
    global _admin_log_event
    try:
        if _admin_log_event is None:
            _admin_log_event = asyncio.Event()
        _admin_log_event.set()
    except Exception:
        pass
    return True


async def _admin_log_worker():
    global _admin_log_event
    if _admin_log_event is None:
        _admin_log_event = asyncio.Event()
    backoff = 1
    while True:
        row = None
        try:
            cursor.execute("SELECT id, message FROM admin_audit_outbox ORDER BY id ASC LIMIT 1")
            row = cursor.fetchone()
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logging.exception("Failed to fetch from admin_audit_outbox")
            await asyncio.sleep(min(300.0, float(backoff)))
            backoff = min(300, backoff * 2)
            continue

        if not row:
            _admin_log_event.clear()
            try:
                cursor.execute("SELECT id FROM admin_audit_outbox ORDER BY id ASC LIMIT 1")
                if cursor.fetchone():
                    _admin_log_event.set()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
            await _admin_log_event.wait()
            continue

        row_id, text_msg = row[0], row[1]
        try:
            await asyncio.wait_for(
                bot.send_message(
                    ADMIN_LOG_CHAT_ID,
                    text_msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    request_timeout=15,
                ),
                timeout=15.0,
            )
        except asyncio.CancelledError:
            raise
        except TelegramRetryAfter as retry_err:
            wait_sec = max(0.01, float(getattr(retry_err, "retry_after", 1.0) or 1.0))
            await asyncio.sleep(wait_sec)
            continue
        except Exception:
            logging.exception("Failed to deliver admin audit log id=%s", row_id)
            await asyncio.sleep(min(300.0, float(backoff)))
            backoff = min(300, backoff * 2)
            continue

        backoff = 1
        try:
            cursor.execute("DELETE FROM admin_audit_outbox WHERE id = ?", (row_id,))
            conn.commit()
        except asyncio.CancelledError:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logging.exception("Failed to delete delivered admin audit log id=%s", row_id)
        await asyncio.sleep(ADMIN_LOG_INTERVAL)


def _start_admin_logging():
    global _admin_log_task, _admin_log_event
    _ensure_runtime_schema()
    if _admin_log_event is None:
        _admin_log_event = asyncio.Event()
    if _admin_log_task is not None and not _admin_log_task.done():
        return _admin_log_task
    _admin_log_task = asyncio.create_task(_admin_log_worker())
    _admin_log_event.set()
    return _admin_log_task


async def _stop_admin_logging():
    global _admin_log_task
    task = _admin_log_task
    _admin_log_task = None
    if task is not None:
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("Error while stopping admin log worker")


def parse_ban_duration(text):
    text = text.lower().strip()
    if text in ["нг", "навсегда", "перм", "perm", "forever", "вечно", "inf"]:
        return None, True
    m = re.match(r'^(\d+)\s*(мин|м|m|min|минут|минуты|минута|ч|h|hour|часов|часа|час|д|d|day|дней|дня|день|мес|month|месяцев|месяца|месяц)?$', text)
    if not m:
        return None, False
    val = int(m.group(1))
    unit = (m.group(2) or "м").lower()
    if unit in ["мин", "м", "m", "min", "минут", "минуты", "минута"]:
        delta = timedelta(minutes=val)
    elif unit in ["ч", "h", "hour", "часов", "часа", "час"]:
        delta = timedelta(hours=val)
    elif unit in ["д", "d", "day", "дней", "дня", "день"]:
        delta = timedelta(days=val)
    elif unit in ["мес", "month", "месяцев", "месяца", "месяц"]:
        delta = timedelta(days=val * 30)
    else:
        delta = timedelta(minutes=val)
    return delta, False


def add_game_history(user_id, game_type, bet, result, win_amount=0, created_at_str=None):
    if DEMO_GAME_CONTEXT.get():
        return
    try:
        if not created_at_str:
            created_at_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        cursor.execute('''
            INSERT INTO games_history (user_id, game_type, bet, result, win_amount, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, game_type, bet, result, win_amount, created_at_str))
        
        cursor.execute('INSERT INTO game_stats (user_id) VALUES (?) ON CONFLICT (user_id) DO NOTHING', (user_id,))
        if game_type in ["mines", "tower", "qwak", "diamonds", "crash", "slots", "bowling", "dice", "coin", "chest", "fishing", "scratch", "roulette", "darts", "basketball", "football", "twentyone", "gold"]:
            try:
                cursor.execute(f'UPDATE game_stats SET {game_type} = {game_type} + 1 WHERE user_id = ?', (user_id,))
            except Exception:
                pass
        conn.commit()

        try:
            asyncio.create_task(activate_referral_if_needed(user_id))
            if result == "lose" and bet > 0:
                asyncio.create_task(process_referral_loss_cashback(user_id, bet))
        except Exception:
            pass
    except Exception:
        pass


@_event_read_cache
def get_user_stats(user_id):
    try:
        cursor.execute('SELECT mines, tower, COALESCE(qwak, 0), diamonds, crash, slots, bowling, COALESCE(dice, 0), COALESCE(coin, 0), COALESCE(chest, 0), COALESCE(fishing, 0), COALESCE(scratch, 0), COALESCE(roulette, 0), darts, basketball, football, COALESCE(twentyone, 0), COALESCE(gold, 0) FROM game_stats WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            mines, tower, qwak, diamonds, crash, slots, bowling, dice, coin, chest, fishing, scratch, roulette, darts, basketball, football, twentyone, gold = row
            qwak = qwak or 0
            slots = slots or 0
            bowling = bowling or 0
            dice = dice or 0
            coin = coin or 0
            chest = chest or 0
            fishing = fishing or 0
            scratch = scratch or 0
            roulette = roulette or 0
            darts = darts or 0
            basketball = basketball or 0
            football = football or 0
            twentyone = twentyone or 0
            gold = gold or 0
            total = mines + tower + qwak + diamonds + crash + slots + bowling + dice + coin + chest + fishing + scratch + roulette + darts + basketball + football + twentyone + gold
            return {
                "mines": mines, "tower": tower, "qwak": qwak, "diamonds": diamonds, "crash": crash,
                "slots": slots, "bowling": bowling, "dice": dice, "coin": coin, "chest": chest, "fishing": fishing, "scratch": scratch, "roulette": roulette,
                "darts": darts, "basketball": basketball,
                "football": football, "twentyone": twentyone, "gold": gold, "total": total
            }
        else:
            cursor.execute('SELECT games FROM users WHERE user_id = ?', (user_id,))
            u_row = cursor.fetchone()
            total_legacy = u_row[0] if u_row else 0
            return {
                "mines": total_legacy, "tower": 0, "diamonds": 0, "crash": 0,
                "slots": 0, "bowling": 0, "dice": 0, "coin": 0, "chest": 0, "fishing": 0, "scratch": 0, "roulette": 0, "qwak": 0,
                "darts": 0, "basketball": 0, "football": 0,
                "twentyone": 0, "gold": 0, "total": total_legacy
            }
    except Exception:
        return {"mines": 0, "tower": 0, "qwak": 0, "diamonds": 0, "crash": 0, "slots": 0, "bowling": 0, "dice": 0, "coin": 0, "chest": 0, "fishing": 0, "scratch": 0, "roulette": 0, "darts": 0, "basketball": 0, "football": 0, "twentyone": 0, "gold": 0, "total": 0}


def get_user_history(user_id, limit=5, offset=0):
    try:
        cursor.execute('''
            SELECT game_type, bet, result, win_amount, created_at FROM games_history
            WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?
        ''', (user_id, limit, offset))
        return cursor.fetchall()
    except Exception:
        return []


def get_user_history_count(user_id):
    try:
        cursor.execute('SELECT COUNT(*) FROM games_history WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


TIME_DEPOSIT_RATES = {
    1: 0.4,
    3: 1.5,
    7: 4.0,
    15: 10.0,
    30: 25.0,
    60: 65.0
}
BANK_MAX_LIMIT = 100000000


@_event_read_cache
def get_bank_settings(user_id):
    try:
        cursor.execute("SELECT notifications_enabled FROM bank_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is not None:
            return {"notifications_enabled": bool(row[0])}
        cursor.execute("INSERT INTO bank_settings (user_id, notifications_enabled) VALUES (?, 1) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        conn.commit()
        return {"notifications_enabled": True}
    except Exception:
        return {"notifications_enabled": True}


def toggle_bank_notifications(user_id):
    try:
        cur = get_bank_settings(user_id)["notifications_enabled"]
        new_val = 0 if cur else 1
        cursor.execute("INSERT INTO bank_settings (user_id, notifications_enabled) VALUES (?, ?) ON CONFLICT (user_id) DO UPDATE SET notifications_enabled = EXCLUDED.notifications_enabled", (user_id, new_val))
        conn.commit()
        return bool(new_val)
    except Exception:
        return True


@_event_read_cache
def get_user_bank_total(user_id):
    try:
        cursor.execute("SELECT SUM(amount) FROM time_deposits WHERE user_id = ? AND status = 'active'", (user_id,))
        r1 = cursor.fetchone()
        time_total = r1[0] if (r1 and r1[0]) else 0
        cursor.execute("SELECT balance FROM savings_accounts WHERE user_id = ?", (user_id,))
        r2 = cursor.fetchone()
        savings_bal = r2[0] if (r2 and r2[0]) else 0
        return time_total + savings_bal
    except Exception:
        return 0


@db_transaction
@_localized
def create_time_deposit(user_id, amount, days, is_locked=0):
    try:
        if amount <= 0:
            return False, _l('Сумма должна быть больше 0!')
        rate = TIME_DEPOSIT_RATES.get(days, 0.4)
        profit = int(amount * rate / 100)
        now = datetime.now()
        end_dt = now + timedelta(days=days)
        now_str = now.strftime("%d-%m-%y %H:%M")
        end_str = end_dt.strftime("%d-%m-%y %H:%M")
        now_iso = now.isoformat()
        end_iso = end_dt.isoformat()

        current_bank_total = get_user_bank_total(user_id)
        if current_bank_total + amount > BANK_MAX_LIMIT:
            max_can_add = max(0, BANK_MAX_LIMIT - current_bank_total)
            return False, _lf('Превышен лимит банка (100kk mCoin)! Вы можете внести ещё максимум {0} m¢.', (_fmt(format_number(max_can_add), '', -1),))

        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?", (amount, user_id, amount))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно средств на балансе!')

        cursor.execute('''
            INSERT INTO time_deposits (user_id, amount, days, percent, profit, is_locked, status, created_at, end_at, created_at_dt, end_at_dt)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        ''', (user_id, amount, days, rate, profit, 1 if is_locked else 0, now_str, end_str, now_iso, end_iso))
        conn.commit()
        return True, {"amount": amount, "days": days, "percent": rate, "profit": profit, "is_locked": is_locked, "end_at": end_str}
    except Exception as e:
        return False, str(e)


def get_active_time_deposits(user_id):
    try:
        cursor.execute('''
            SELECT id, amount, days, percent, profit, is_locked, created_at, end_at, created_at_dt, end_at_dt
            FROM time_deposits
            WHERE user_id = ? AND status = 'active'
            ORDER BY id DESC
        ''', (user_id,))
        return cursor.fetchall()
    except Exception:
        return []


def get_active_time_deposits_count(user_id):
    try:
        cursor.execute("SELECT COUNT(*) FROM time_deposits WHERE user_id = ? AND status = 'active'", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def get_user_earned_deposits_total(user_id):
    try:
        cursor.execute("SELECT SUM(profit) FROM time_deposits WHERE user_id = ? AND status = 'completed'", (user_id,))
        r1 = cursor.fetchone()
        dep_profit = r1[0] if (r1 and r1[0]) else 0
        cursor.execute("SELECT total_earned FROM savings_accounts WHERE user_id = ?", (user_id,))
        r2 = cursor.fetchone()
        sav_profit = r2[0] if (r2 and r2[0]) else 0
        return dep_profit + sav_profit
    except Exception:
        return 0


def get_user_time_deposits_history(user_id, limit=5, offset=0):
    try:
        cursor.execute('''
            SELECT id, amount, days, percent, profit, is_locked, status, created_at, end_at
            FROM time_deposits
            WHERE user_id = ?
            ORDER BY id DESC LIMIT ? OFFSET ?
        ''', (user_id, limit, offset))
        return cursor.fetchall()
    except Exception:
        return []


def get_user_time_deposits_history_count(user_id):
    try:
        cursor.execute("SELECT COUNT(*) FROM time_deposits WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


@db_transaction
@_localized
def withdraw_time_deposit(dep_id, user_id):
    try:
        cursor.execute("SELECT amount, is_locked, status FROM time_deposits WHERE id = ? AND user_id = ?", (dep_id, user_id))
        row = cursor.fetchone()
        if not row:
            return False, _l('Депозит не найден!')
        amount, is_locked, status = row
        if status != "active":
            return False, _l('Депозит уже закрыт!')
        if is_locked:
            return False, _l('Снятие данного депозита было заблокировано при открытии!')

        cursor.execute("UPDATE time_deposits SET status = 'withdrawn' WHERE id = ? AND user_id = ? AND status = 'active' AND is_locked = 0", (dep_id, user_id))
        if cursor.rowcount == 0:
            return False, _l('Депозит уже закрыт или заблокирован!')

        cursor.execute("UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ?", (amount, amount, user_id))
        conn.commit()
        return True, amount
    except Exception as e:
        return False, str(e)


@db_transaction
@_localized
def withdraw_all_time_deposits(user_id):
    try:
        cursor.execute("SELECT id, amount, is_locked FROM time_deposits WHERE user_id = ? AND status = 'active' AND is_locked = 0", (user_id,))
        rows = cursor.fetchall()
        if not rows:
            return False, _l('Нет доступных для досрочного снятия депозитов (или они заблокированы)!')

        total_withdrawn = 0
        for dep_id, amount, is_locked in rows:
            cursor.execute("UPDATE time_deposits SET status = 'withdrawn' WHERE id = ? AND user_id = ? AND status = 'active' AND is_locked = 0", (dep_id, user_id))
            if cursor.rowcount > 0:
                total_withdrawn += amount

        if total_withdrawn <= 0:
            return False, _l('Нет доступных для досрочного снятия депозитов!')

        cursor.execute("UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ?", (total_withdrawn, total_withdrawn, user_id))
        conn.commit()
        return True, total_withdrawn
    except Exception as e:
        return False, str(e)


@_event_read_cache
def get_savings_account(user_id):
    try:
        cursor.execute("SELECT balance, accumulated_interest, total_earned, last_accrual FROM savings_accounts WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return {
                "balance": row[0],
                "accumulated_interest": row[1],
                "total_earned": row[2],
                "last_accrual": row[3]
            }
        cursor.execute("INSERT INTO savings_accounts (user_id, balance, accumulated_interest, total_earned, last_accrual) VALUES (?, 0, 0.0, 0, ?) ON CONFLICT (user_id) DO NOTHING", (user_id, datetime.now().isoformat()))
        conn.commit()
        return {"balance": 0, "accumulated_interest": 0.0, "total_earned": 0, "last_accrual": datetime.now().isoformat()}
    except Exception:
        return {"balance": 0, "accumulated_interest": 0.0, "total_earned": 0, "last_accrual": None}


@db_transaction
@_localized
def deposit_to_savings(user_id, amount):
    try:
        if amount <= 0:
            return False, _l('Сумма должна быть больше 0!')
        current_bank_total = get_user_bank_total(user_id)
        if current_bank_total + amount > BANK_MAX_LIMIT:
            max_can_add = max(0, BANK_MAX_LIMIT - current_bank_total)
            return False, _lf('Превышен лимит банка (100kk mCoin)! Вы можете внести ещё максимум {0} m¢.', (_fmt(format_number(max_can_add), '', -1),))

        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?", (amount, user_id, amount))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно средств на балансе!')

        get_savings_account(user_id)
        cursor.execute("UPDATE savings_accounts SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        now_str = datetime.now().strftime("%d-%m-%y %H:%M")
        cursor.execute("INSERT INTO savings_history (user_id, type, amount, created_at) VALUES (?, 'deposit', ?, ?)", (user_id, amount, now_str))
        conn.commit()

        acc = get_savings_account(user_id)
        return True, acc["balance"]
    except Exception as e:
        return False, str(e)


@db_transaction
@_localized
def withdraw_from_savings(user_id, amount):
    try:
        if amount <= 0:
            return False, _l('Сумма должна быть больше 0!')
        acc = get_savings_account(user_id)
        total_available = acc["balance"] + int(acc["accumulated_interest"])
        if total_available <= 0:
            return False, _l('На накопительном счете нет средств!')
        if amount > total_available:
            amount = total_available

        interest_to_wd = min(int(acc["accumulated_interest"]), amount)
        balance_to_wd = amount - interest_to_wd

        cursor.execute('''
            UPDATE savings_accounts
            SET balance = balance - ?,
                accumulated_interest = MAX(0.0, COALESCE(accumulated_interest, 0.0) - ?),
                total_earned = total_earned + ?
            WHERE user_id = ? AND balance >= ?
        ''', (balance_to_wd, interest_to_wd, interest_to_wd, user_id, balance_to_wd))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно средств на накопительном счете!')

        cursor.execute("UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ?", (amount, amount, user_id))
        now_str = datetime.now().strftime("%d-%m-%y %H:%M")
        cursor.execute("INSERT INTO savings_history (user_id, type, amount, created_at) VALUES (?, 'withdraw', ?, ?)", (user_id, amount, now_str))
        conn.commit()

        user_data = get_user(user_id)
        return True, {"withdrawn": amount, "balance": user_data["balance"]}
    except Exception as e:
        return False, str(e)


def get_savings_history(user_id, limit=5, offset=0):
    try:
        cursor.execute("SELECT type, amount, created_at FROM savings_history WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, limit, offset))
        return cursor.fetchall()
    except Exception:
        return []


def get_savings_history_count(user_id):
    try:
        cursor.execute("SELECT COUNT(*) FROM savings_history WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def register_referral(referrer_id, referral_id):
    try:
        if referrer_id == referral_id:
            return False
        cursor.execute("SELECT referred_by, games, lost FROM users WHERE user_id = ?", (referral_id,))
        row = cursor.fetchone()
        if row:
            referred_by, games_count, lost_count = row[0], row[1] or 0, row[2] or 0
            if referred_by or games_count > 0 or lost_count > 0:
                return False
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        cursor.execute('''
            INSERT INTO referrals (referrer_id, referral_id, is_active, bonus_paid, earned_from_losses, joined_at)
            VALUES (?, ?, 0, 0, 0, ?)
            ON CONFLICT (referral_id) DO NOTHING
        ''', (referrer_id, referral_id, now_str))
        cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, referral_id))
        conn.commit()
        return True
    except Exception:
        return False


@_localized
async def activate_referral_if_needed(user_id):
    try:
        cursor.execute("SELECT referrer_id, is_active FROM referrals WHERE referral_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or row[1] == 1:
            return
        referrer_id = row[0]
        cursor.execute("UPDATE referrals SET is_active = 1, bonus_paid = 100000 WHERE referral_id = ?", (user_id,))
        ref_user = get_user(referrer_id)
        update_user(referrer_id, balance=ref_user["balance"] + 100000, ref_count=ref_user["ref_count"] + 1, ref_earned=ref_user["ref_earned"] + 100000)
        conn.commit()

        try:
            name_val = get_user_display_name(user_id)
            user_link = f'<a href="tg://user?id={user_id}">{html.escape(name_val)}</a>'
            msg_text = (
                _lf("🎁 <b>Реферальный бонус!</b>\nТвой друг {0} выполнил условие (сыграл игру или забрал бонус).\nТебе начислено <b>100'000 mCoin</b>!", (_fmt(user_link, '', -1),), user_id=referrer_id)
            )
            await bot.send_message(chat_id=referrer_id, text=msg_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    except Exception:
        pass


async def process_referral_loss_cashback(user_id, lost_amount):
    if lost_amount <= 0:
        return
    try:
        cursor.execute("SELECT referrer_id, is_active FROM referrals WHERE referral_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or row[1] != 1:
            return
        referrer_id = row[0]
        cashback = int(lost_amount * 0.02)
        if cashback < 1:
            return
        ref_user = get_user(referrer_id)
        update_user(referrer_id, balance=ref_user["balance"] + cashback, ref_earned=ref_user["ref_earned"] + cashback)
        cursor.execute("UPDATE referrals SET earned_from_losses = earned_from_losses + ? WHERE referral_id = ?", (cashback, user_id))
        conn.commit()
    except Exception:
        pass


def get_top_referrers(limit=10):
    try:
        cursor.execute('''
            SELECT user_id, ref_count, ref_earned FROM users
            WHERE ref_count > 0
            ORDER BY ref_count DESC, ref_earned DESC LIMIT ?
        ''', (limit,))
        return cursor.fetchall()
    except Exception:
        return []


def get_user_referrals_list(referrer_id, limit=5, offset=0):
    try:
        cursor.execute('''
            SELECT referral_id, is_active, bonus_paid, earned_from_losses, joined_at
            FROM referrals
            WHERE referrer_id = ?
            ORDER BY referral_id DESC LIMIT ? OFFSET ?
        ''', (referrer_id, limit, offset))
        return cursor.fetchall()
    except Exception:
        return []


def get_user_referrals_count(referrer_id):
    try:
        cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (referrer_id,))
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def is_bot_command(text, chat_type="private"):
    if not text:
        return False
    text = text.strip().lower()
    
    if chat_type == "private":
        return True
        
    if text.startswith("/"):
        return True
    
    parts = text.split()
    first = parts[0]
    
    command_triggers = [
        "мины", "м", "башня", "бш", "квак", "qwak", "frog", "лягушка", "игры", "игра", "баланс", "б", "бал",
        "бонус", "топ", "дать", "пер", "раздача", "роздача", "giveaway", "transfer",
        "история", "недавние", "алмазы", "алмаз", "diamond",
        "золото", "gold", "голд", "з",
        "краш", "crash", "кр",
        "слоты", "слот", "slots", "slot",
        "боулинг", "bowling", "бо",
        "кубик", "куб", "dice",
        "монета", "монетка", "coin",
        "сундук", "сунд", "chest",
        "рыбалка", "рыба", "fish", "fishing",
        "скретч", "scratch", "скретчка",
        "чек", "чеки", "check", "checks",
        "рулетка", "roulette", "рул",
        "дартс", "darts", "дс", "dart",
        "баскетбол", "basketball", "баскет", "бс", "бк",
        "футбол", "football", "фб",
        "промо", "promo",
        "гет", "get",
        "поинт", "поинты", "point", "points", "send", "перевод",
        "рекорды", "рекорд", "records",
        "депозит", "депозиты", "деп", "банк", "deposit",
        "реф", "рефералы", "реферал", "ref", "referral"
    ]
    
    if first in command_triggers:
        return True
        
    if text in ["топ чата", "топ ч", "топ чат", "история игр", "недавние игры", "топ рекорды", "топ рекордов", "топ рекорд"]:
        return True
        
    return False


def _ensure_user_language(user):
    if user is None or getattr(user, "is_bot", False):
        return
    lang_code = getattr(user, "language_code", None)
    if not isinstance(lang_code, str) or not lang_code.strip():
        return
    uid = getattr(user, "id", None)
    if uid is None:
        return
    uid = int(uid)
    if uid in _settings_cache:
        return
    try:
        cursor.execute(
            "SELECT language, bot_nickname, hide_top_username, demo_balance FROM bot_user_settings WHERE user_id = ?",
            (uid,),
        )
        row = cursor.fetchone()
        if row:
            _cache_put(
                _settings_cache,
                uid,
                UserSettings(
                    user_id=uid,
                    language=row[0] if row[0] in LANGUAGE_NAMES else "ru",
                    bot_nickname=row[1],
                    hide_top_username=bool(row[2]),
                    demo_balance=int(row[3]) if row[3] is not None else None,
                ),
            )
            return
    except sqlite3.Error:
        return
    set_user_settings(uid, language=_telegram_language(lang_code))


@dp.message.outer_middleware()
@_localized
async def save_username_middleware(handler, event, data):
    if event.from_user:
        _ensure_user_language(event.from_user)
        save_username(event.from_user.id, event.from_user.username, event.from_user.first_name)
        if event.chat and event.chat.type in ["group", "supergroup"]:
            add_chat_member(event.from_user.id, event.chat.id)
        ban_info = check_user_ban(event.from_user.id)
        if ban_info:
            chat_type = event.chat.type if event.chat else "private"
            msg_text = event.text or event.caption or ""
            
            if is_bot_command(msg_text, chat_type):
                raw_user_name = get_user_display_name(event.from_user.id, event.from_user.first_name) or _l('Игрок')
                clean_user_name = html.escape(raw_user_name)
                user_link = f'<a href="tg://user?id={event.from_user.id}">{clean_user_name}</a>'
                await event.reply(
                    _lf('<b>{0} ты заблокирован! 🚫\n</b><i>Причина: {1}\n</i><i>До: {2}</i>', (_fmt(user_link, '', -1), _fmt(ban_info['reason'], '', -1), _fmt(_l('Навсегда') if ban_info.get('is_perm') else ban_info['until_str'], '', -1))),
                    parse_mode=ParseMode.HTML
                )
            return
    demo_token = DEMO_GAME_CONTEXT.set(bool(event.from_user and is_demo_game_event_for_user(event, event.from_user.id)))
    try:
        return await handler(event, data)
    finally:
        DEMO_GAME_CONTEXT.reset(demo_token)


@dp.callback_query.outer_middleware()
@_localized
async def save_username_cb_middleware(handler, event, data):
    if event.from_user:
        _ensure_user_language(event.from_user)
        save_username(event.from_user.id, event.from_user.username, event.from_user.first_name)
        if event.message and event.message.chat and event.message.chat.type in ["group", "supergroup"]:
            add_chat_member(event.from_user.id, event.message.chat.id)
        ban_info = check_user_ban(event.from_user.id)
        if ban_info:
            await event.answer(
                _lf('Ты заблокирован! 🚫\nПричина: {0}\nДо: {1}', (_fmt(ban_info['reason'], '', -1), _fmt(_l('Навсегда') if ban_info.get('is_perm') else ban_info['until_str'], '', -1))),
                show_alert=True
            )
            return
    demo_token = DEMO_GAME_CONTEXT.set(bool(event.from_user and is_demo_game_event_for_user(event, event.from_user.id)))
    try:
        return await handler(event, data)
    finally:
        DEMO_GAME_CONTEXT.reset(demo_token)


def add_chat_member(user_id, chat_id):
    key = (user_id, chat_id)
    if key in _known_chat_members:
        _known_chat_members.move_to_end(key)
        return True
    try:
        cursor.execute('INSERT INTO chat_members (user_id, chat_id) VALUES (?, ?) ON CONFLICT (user_id, chat_id) DO NOTHING', (user_id, chat_id))
        conn.commit()
        _cache_put(_known_chat_members, key, True)
        return True
    except Exception:
        return False


def get_top_users(limit=10, chat_id=None):
    try:
        if chat_id:
            cursor.execute('''
                SELECT user_id, balance FROM users 
                WHERE user_id NOT IN (SELECT user_id FROM top_bans)
                AND COALESCE(balance, 0) > 0
                AND user_id IN (
                    SELECT user_id FROM chat_members WHERE chat_id = ?
                    UNION
                    SELECT owner_id AS user_id FROM active_games_state WHERE chat_id = ?
                )
                ORDER BY balance DESC LIMIT ?
            ''', (chat_id, chat_id, limit))
        else:
            cursor.execute('''
                SELECT user_id, balance FROM users 
                WHERE user_id NOT IN (SELECT user_id FROM top_bans)
                AND COALESCE(balance, 0) > 0
                ORDER BY balance DESC LIMIT ?
            ''', (limit,))
        return cursor.fetchall()
    except Exception:
        return []


def get_user_rank(user_id, chat_id=None):
    if is_top_banned(user_id):
        return 0
    try:
        cursor.execute("SELECT COALESCE(balance, 0) FROM users WHERE user_id = ?", (user_id,))
        user_balance_row = cursor.fetchone()
        if not user_balance_row:
            return 0
        user_balance = int(user_balance_row[0] or 0)
        if user_balance <= 0:
            return 0

        if chat_id:
            cursor.execute('''
                SELECT COUNT(*) + 1 FROM users 
                WHERE user_id NOT IN (SELECT user_id FROM top_bans)
                AND COALESCE(balance, 0) > ?
                AND COALESCE(balance, 0) > 0
                AND user_id IN (
                    SELECT user_id FROM chat_members WHERE chat_id = ?
                    UNION
                    SELECT owner_id AS user_id FROM active_games_state WHERE chat_id = ?
                )
            ''', (user_balance, chat_id, chat_id))
        else:
            cursor.execute('''
                SELECT COUNT(*) + 1 FROM users 
                WHERE user_id NOT IN (SELECT user_id FROM top_bans)
                AND COALESCE(balance, 0) > ?
                AND COALESCE(balance, 0) > 0
            ''', (user_balance,))
        result = cursor.fetchone()
        return int(result[0]) if result and result[0] else 0
    except Exception:
        return 0


def format_number(num):
    num = int(num)
    if num >= 1000000000000:
        v = num / 1000000000000
        s = f"{v:.2f}".rstrip('0').rstrip('.')
        return f"{s}kkkk"
    elif num >= 1000000000:
        v = num / 1000000000
        s = f"{v:.2f}".rstrip('0').rstrip('.')
        return f"{s}kkk"
    elif num >= 1000000:
        v = num / 1000000
        s = f"{v:.2f}".rstrip('0').rstrip('.')
        return f"{s}kk"

    return f"{num:,}".replace(",", "'")


def parse_amount(text):
    if not text:
        return None
    text = text.lower().strip().replace("'", "").replace(" ", "")

    multiplier = 1
    if text.endswith('кккк') or text.endswith('kkkk'):
        multiplier = 1000000000000
        text = text[:-4]
    elif text.endswith('ккк') or text.endswith('kkk'):
        multiplier = 1000000000
        text = text[:-3]
    elif text.endswith('кк') or text.endswith('kk'):
        multiplier = 1000000
        text = text[:-2]
    elif text.endswith('к') or text.endswith('k'):
        multiplier = 1000
        text = text[:-1]

    if multiplier == 1 and re.match(r'^\d{1,3}([.,]\d{3})+$', text):
        text = re.sub(r'[.,]', '', text)
    else:
        text = text.replace(",", ".")

    try:
        num = float(text)
        return int(num * multiplier)
    except ValueError:
        return None


def resolve_bet_amount(text, balance=0):
    if not text:
        return None
    t = text.lower().strip()
    if t in ["все", "всё", "all", "allin", "вб", "ва-банк", "вабанк", "ва банк"]:
        return balance
    if t in ["пол", "половина", "half", "1/2"]:
        return balance // 2
    return parse_amount(text)


def parse_multiplier(text):
    if not text:
        return None
    text = text.lower().strip()
    text = text.lstrip("xх").rstrip("xх")
    text = text.replace("'", "").replace(" ", "").replace(",", ".")

    multiplier = 1.0
    if text.endswith('кккк') or text.endswith('kkkk'):
        multiplier = 1000000000000.0
        text = text[:-4]
    elif text.endswith('ккк') or text.endswith('kkk'):
        multiplier = 1000000000.0
        text = text[:-3]
    elif text.endswith('кк') or text.endswith('kk'):
        multiplier = 1000000.0
        text = text[:-2]
    elif text.endswith('к') or text.endswith('k'):
        multiplier = 1000.0
        text = text[:-1]

    try:
        num = float(text)
        return round(num * multiplier, 2)
    except ValueError:
        return None


def generate_mines(count):
    rng = secrets.SystemRandom()
    positions = list(range(25))
    rng.shuffle(positions)
    return set(rng.sample(positions, count))


def generate_tower_mines(count):
    rng = secrets.SystemRandom()
    tower = []
    for _ in range(TOWER_ROWS):
        cols = list(range(TOWER_COLS))
        rng.shuffle(cols)
        tower.append(set(rng.sample(cols, count)))
    return tower


def generate_qwak_mines():
    rng = secrets.SystemRandom()
    tower = []
    for row in range(QWAK_ROWS):
        count = QWAK_MINE_COUNTS.get(row, 0)
        cols = list(range(QWAK_COLS))
        rng.shuffle(cols)
        tower.append(set(rng.sample(cols, count)))
    return tower


def generate_diamonds_mines(count):
    rng = secrets.SystemRandom()
    diamonds_tower = []
    for _ in range(DIAMONDS_ROWS):
        cols = list(range(DIAMONDS_COLS))
        rng.shuffle(cols)
        diamonds_tower.append(set(rng.sample(cols, count)))
    return diamonds_tower


_TOWER_MULTIPLIERS = {
    1: {
        0: 1.00, 1: 1.21, 2: 1.52, 3: 1.89, 4: 2.37, 5: 2.96, 6: 3.70, 7: 4.63, 8: 5.78, 9: 7.23
    },
    2: {
        0: 1.00, 1: 1.62, 2: 2.69, 3: 4.49, 4: 7.48, 5: 12.47, 6: 20.79, 7: 34.65, 8: 57.75, 9: 96.25
    },
    3: {
        0: 1.00, 1: 2.42, 2: 6.06, 3: 15.16, 4: 37.89, 5: 94.73, 6: 238.62, 7: 592.04, 8: 1480.10, 9: 3700.25
    },
    4: {
        0: 1.00, 1: 4.85, 2: 24.25, 3: 121.25, 4: 606.25, 5: 3031.25, 6: 15156.25, 7: 75781.25, 8: 378906.25, 9: 1894531.25
    }
}


def get_tower_multiplier(mine_count, level):
    multipliers = _TOWER_MULTIPLIERS
    return multipliers.get(mine_count, {}).get(level, 1.00)


_QWAK_MULTIPLIERS = {
    0: 1.00,
    1: 1.00,
    2: 1.21,
    3: 2.00,
    4: 5.05,
    5: 25.25,
}


def get_qwak_multiplier(level):
    multipliers = _QWAK_MULTIPLIERS
    return multipliers.get(level, 1.00)


_DIAMONDS_MULTIPLIERS = {
    1: {
        0: 1.00, 1: 1.46, 2: 2.18, 3: 3.27, 4: 4.91, 5: 7.37, 6: 11.05,
        7: 16.57, 8: 24.86, 9: 37.29, 10: 55.94, 11: 83.90, 12: 125.86,
        13: 188.79, 14: 283.18, 15: 424.77, 16: 637.16
    },
    2: {
        0: 1.00, 1: 2.91, 2: 8.73, 3: 26.19, 4: 78.57, 5: 235.71, 6: 707.13,
        7: 2121.39, 8: 6364.17, 9: 19092.51, 10: 57277.53, 11: 171832.59,
        12: 515497.77, 13: 1546493.31, 14: 4639479.93, 15: 13918439.79, 16: 41755319.37
    }
}


def get_diamonds_multiplier(mine_count, level):
    multipliers = _DIAMONDS_MULTIPLIERS
    return multipliers.get(mine_count, {}).get(level, 1.00)


_MINES_MULTIPLIERS = {
    1: {
        0: 1.00, 1: 1.01, 2: 1.05, 3: 1.10, 4: 1.15, 5: 1.21, 6: 1.28, 7: 1.35,
        8: 1.43, 9: 1.52, 10: 1.62, 11: 1.73, 12: 1.87, 13: 2.02, 14: 2.20,
        15: 2.41, 16: 2.66, 17: 2.96, 18: 3.32, 19: 3.76, 20: 4.31, 21: 5.00,
        22: 5.88, 23: 7.04, 24: 8.59
    },
    2: {
        0: 1.00, 1: 1.05, 2: 1.15, 3: 1.26, 4: 1.39, 5: 1.53, 6: 1.70, 7: 1.90,
        8: 2.14, 9: 2.42, 10: 2.77, 11: 3.20, 12: 3.73, 13: 4.41, 14: 5.29,
        15: 6.47, 16: 8.09, 17: 10.37, 18: 13.68, 19: 18.72, 20: 26.74,
        21: 40.43, 22: 65.96, 23: 120.19
    },
    3: {
        0: 1.00, 1: 1.10, 2: 1.26, 3: 1.45, 4: 1.68, 5: 1.96, 6: 2.30, 7: 2.73,
        8: 3.28, 9: 3.98, 10: 4.90, 11: 6.13, 12: 7.80, 13: 10.14, 14: 13.51,
        15: 18.54, 16: 26.34, 17: 38.94, 18: 60.32, 19: 98.76, 20: 172.97,
        21: 330.78, 22: 714.30
    },
    4: {
        0: 1.00, 1: 1.15, 2: 1.39, 3: 1.68, 4: 2.05, 5: 2.53, 6: 3.17, 7: 4.01,
        8: 5.16, 9: 6.74, 10: 8.96, 11: 12.16, 12: 16.91, 13: 24.18, 14: 35.75,
        15: 55.06, 16: 88.93, 17: 151.98, 18: 278.30, 19: 552.47, 20: 1209.71,
        21: 3029.88
    },
    5: {
        0: 1.00, 1: 1.21, 2: 1.53, 3: 1.96, 4: 2.53, 5: 3.32, 6: 4.43, 7: 6.01,
        8: 8.33, 9: 11.80, 10: 17.16, 11: 25.75, 12: 40.13, 13: 65.21, 14: 111.78,
        15: 204.94, 16: 409.88, 17: 922.22, 18: 2459.26, 19: 8607.41, 20: 51644.48
    },
    6: {
        0: 1.00, 1: 1.28, 2: 1.70, 3: 2.30, 4: 3.17, 5: 4.43, 6: 6.33, 7: 9.25,
        8: 13.88, 9: 21.35, 10: 33.93, 11: 56.03, 12: 96.94, 13: 177.72, 14: 350.51,
        15: 764.74, 16: 1891.07, 17: 5673.22, 18: 22692.89, 19: 170196.67
    }
}


def get_multiplier(mine_count, level):
    multipliers = _MINES_MULTIPLIERS
    if mine_count in multipliers and level in multipliers[mine_count]:
        return multipliers[mine_count][level]

    try:
        safe = 25 - mine_count
        if level <= 0 or level > safe:
            return 1.00
        p = math.comb(safe, level) / math.comb(25, level)
        return round(0.97 / p, 2)
    except Exception:
        return 1.00


GOLD_ROWS = 12
GOLD_COLS = 2
GOLD_MULTIPLIERS = {
    1: 2,
    2: 4,
    3: 8,
    4: 16,
    5: 32,
    6: 64,
    7: 128,
    8: 256,
    9: 512,
    10: 1024,
    11: 2048,
    12: 4096
}
GOLD_Q_EMOJI = '<tg-emoji emoji-id="5436113877181941026">❓</tg-emoji>'
GOLD_BOOM_EMOJI = '<tg-emoji emoji-id="5276032951342088188">💥</tg-emoji>'


def get_chat_key(user_id, chat_id):
    return f"{user_id}_{chat_id}"


def _remember_message(bucket, key, message_id):
    messages = bucket.setdefault(key, [])
    if message_id not in messages:
        messages.append(message_id)


async def _delete_messages(chat_id, message_ids, telegram_bot=None):
    telegram_bot = telegram_bot or bot
    unique_ids = list(dict.fromkeys(message_ids))
    for offset in range(0, len(unique_ids), 100):
        batch = unique_ids[offset:offset + 100]
        if len(batch) > 1:
            try:
                await telegram_bot.delete_messages(chat_id=chat_id, message_ids=batch)
                continue
            except Exception:
                pass
        for message_id in batch:
            try:
                await telegram_bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass


user_messages = {}
game_messages = {}
games = {}
active_games = {}
game_counter = 0
exit_confirm = {}


def save_active_game_to_db(game_id, g):
    try:
        gtype = g.get("type", "mines")
        if "demo_mode" not in g:
            g["demo_mode"] = bool(is_demo_user(g["owner_id"]))
        else:
            g["demo_mode"] = bool(g["demo_mode"])
        if gtype == "twentyone":
            mp_json = json.dumps(g.get("player_cards", []))
            rev_json = json.dumps({
                "dealer_cards": g.get("dealer_cards", []),
                "deck": g.get("deck", []),
                "user_first_name": g.get("user_first_name", "")
            })
        elif gtype == "gold":
            mp_json = json.dumps(g.get("mine_positions", []))
            rev_json = json.dumps(g.get("revealed", {}))
        else:
            mp = g.get("mine_positions")
            if isinstance(mp, set):
                mp_json = json.dumps(list(mp))
            elif isinstance(mp, list):
                mp_json = json.dumps([list(s) if isinstance(s, set) else s for s in mp])
            else:
                mp_json = json.dumps(mp)

            rev = list(g.get("revealed", [])) if not isinstance(g.get("revealed"), dict) else g.get("revealed")
            rev_json = json.dumps(rev)

        dt_str = g.get("created_at_str")
        if not dt_str:
            created_at = g.get("created_at")
            if isinstance(created_at, datetime):
                dt_str = created_at.strftime("%d-%m-%Y %H:%M:%S")
            else:
                dt_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        cursor.execute('''
            INSERT INTO active_games_state
            (game_id, owner_id, chat_id, game_type, stage, bet, mine_count, mine_positions, revealed, level, game_over, won, exploded_mine, demo_mode, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (game_id) DO UPDATE SET
                owner_id = EXCLUDED.owner_id,
                chat_id = EXCLUDED.chat_id,
                game_type = EXCLUDED.game_type,
                stage = EXCLUDED.stage,
                bet = EXCLUDED.bet,
                mine_count = EXCLUDED.mine_count,
                mine_positions = EXCLUDED.mine_positions,
                revealed = EXCLUDED.revealed,
                level = EXCLUDED.level,
                game_over = EXCLUDED.game_over,
                won = EXCLUDED.won,
                exploded_mine = EXCLUDED.exploded_mine,
                demo_mode = EXCLUDED.demo_mode,
                created_at = EXCLUDED.created_at
        ''', (
            game_id, g["owner_id"], g["chat_id"], g.get("type", "mines"), g.get("stage", "playing"),
            g.get("bet", 0), g.get("mine_count", 0), mp_json, rev_json, g.get("level", 0),
            1 if g.get("game_over") else 0, 1 if g.get("won") else 0,
            g.get("exploded_mine"), 1 if g.get("demo_mode", False) else 0, dt_str
        ))
        conn.commit()
        try:
            asyncio.create_task(redis_set_active_game(g["owner_id"], game_id, g))
        except Exception:
            pass
    except Exception:
        pass


def remove_active_game_from_db(game_id):
    try:
        cursor.execute('DELETE FROM active_games_state WHERE game_id = ?', (game_id,))
        conn.commit()
        try:
            g = games.get(game_id)
            owner_id = g["owner_id"] if g else 0
            if owner_id:
                asyncio.create_task(redis_remove_active_game(owner_id, game_id))
        except Exception:
            pass
    except Exception:
        pass


def load_all_active_games_from_db():
    try:
        cursor.execute('SELECT game_id, owner_id, chat_id, game_type, stage, bet, mine_count, mine_positions, revealed, level, game_over, won, exploded_mine, demo_mode, created_at FROM active_games_state')
        rows = cursor.fetchall()
        for r in rows:
            gid, oid, cid, gtype, stage, bet, mcount, mp_json, rev_json, level, gover, won, exp_mine, demo_mode, dt_str = r
            try:
                created_dt = datetime.strptime(dt_str, "%d-%m-%Y %H:%M:%S")
            except Exception:
                created_dt = datetime.now()

            if gtype == "twentyone":
                try:
                    player_cards = [tuple(c) for c in json.loads(mp_json)] if mp_json else []
                    rev_dict = json.loads(rev_json) if rev_json else {}
                    dealer_cards = [tuple(c) for c in rev_dict.get("dealer_cards", [])] if isinstance(rev_dict, dict) else []
                    deck = [tuple(c) for c in rev_dict.get("deck", [])] if isinstance(rev_dict, dict) else []
                    user_first_name = rev_dict.get("user_first_name", "") if isinstance(rev_dict, dict) else ""
                except Exception:
                    player_cards, dealer_cards, deck, user_first_name = [], [], [], ""

                games[gid] = {
                    "type": gtype,
                    "demo_mode": bool(demo_mode),
                    "stage": stage,
                    "bet": bet,
                    "deck": deck or create_deck_21(),
                    "player_cards": player_cards,
                    "dealer_cards": dealer_cards,
                    "owner_id": oid,
                    "chat_id": cid,
                    "game_over": bool(gover),
                    "won": bool(won),
                    "created_at": created_dt,
                    "created_at_str": dt_str,
                    "settled": bool(gover) or bool(won),
                    "expired": False,
                    "message_id": None,
                    "user_first_name": user_first_name
                }
                if not bool(gover):
                    active_games[oid] = gid
                continue

            if gtype == "gold":
                try:
                    mine_positions = json.loads(mp_json) if mp_json else []
                    raw_rev = json.loads(rev_json) if rev_json else {}
                    revealed = {int(k): int(v) for k, v in raw_rev.items()} if isinstance(raw_rev, dict) else {}
                except Exception:
                    mine_positions, revealed = [], {}

                games[gid] = {
                    "type": gtype,
                    "demo_mode": bool(demo_mode),
                    "stage": stage,
                    "bet": bet,
                    "mine_positions": mine_positions,
                    "revealed": revealed,
                    "level": level,
                    "game_over": bool(gover),
                    "won": bool(won),
                    "exploded_mine": exp_mine,
                    "owner_id": oid,
                    "chat_id": cid,
                    "cashed_out": False,
                    "bet_placed": len(revealed) > 0,
                    "moves_count": len(revealed),
                    "created_at": created_dt,
                    "created_at_str": dt_str,
                    "settled": False,
                    "expired": False,
                    "message_id": None,
                    "is_edited": False
                }
                if not bool(gover):
                    active_games[oid] = gid
                continue

            try:
                mp_raw = json.loads(mp_json) if mp_json else []
                if gtype == "mines":
                    mine_positions = set(mp_raw)
                elif gtype in ["tower", "qwak", "diamonds"]:
                    mine_positions = [set(s) if isinstance(s, list) else s for s in mp_raw]
                else:
                    mine_positions = mp_raw
            except Exception:
                mine_positions = set()

            try:
                revealed = set(json.loads(rev_json)) if rev_json else set()
            except Exception:
                revealed = set()

            games[gid] = {
                "type": gtype,
                "demo_mode": bool(demo_mode),
                "stage": stage,
                "bet": bet,
                "mine_count": mcount,
                "mine_positions": mine_positions,
                "revealed": revealed,
                "level": level,
                "game_over": bool(gover),
                "won": bool(won),
                "exploded_mine": exp_mine,
                "owner_id": oid,
                "chat_id": cid,
                "cashed_out": False,
                "bet_placed": (len(revealed) > 1 if gtype == "qwak" else len(revealed) > 0),
                "moves_count": max(0, len(revealed) - 1) if gtype == "qwak" else len(revealed),
                "created_at": created_dt,
                "created_at_str": dt_str,
                "settled": False,
                "expired": False,
                "message_id": None,
                "is_edited": False
            }
            if not bool(gover):
                active_games[oid] = gid
    except Exception:
        pass


def get_next_game_id():
    global game_counter
    try:
        cursor.execute('SELECT MAX(game_id) FROM active_games_state')
        row = cursor.fetchone()
        db_max = row[0] if (row and row[0]) else 0
    except Exception:
        db_max = 0
    game_counter = max(game_counter + 1, db_max + 1, int(datetime.now().timestamp()))
    return game_counter


load_all_active_games_from_db()

GRID_SIZE = 5
TOTAL_CELLS = 25
TOWER_ROWS = 9
TOWER_COLS = 5
QWAK_ROWS = 5
QWAK_COLS = 5
QWAK_MINE_COUNTS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}
QWAK_START_COL = 2
QWAK_PAD_EMOJI_ID = "5395325195542078574"
QWAK_MINE_EMOJI_ID = "5469654973308476699"
QWAK_BOOM_EMOJI_ID = "5276032951342088188"
QWAK_SUCCESS_EMOJI_ID = "5427009714745517609"
QWAK_PAD_EMOJI = f'<tg-emoji emoji-id="{QWAK_PAD_EMOJI_ID}">🍀</tg-emoji>'
QWAK_MINE_EMOJI = f'<tg-emoji emoji-id="{QWAK_MINE_EMOJI_ID}">💣</tg-emoji>'
QWAK_BOOM_EMOJI = f'<tg-emoji emoji-id="{QWAK_BOOM_EMOJI_ID}">💥</tg-emoji>'
QWAK_SUCCESS_EMOJI = f'<tg-emoji emoji-id="{QWAK_SUCCESS_EMOJI_ID}">✅</tg-emoji>'
DIAMONDS_ROWS = 16
DIAMONDS_COLS = 3

event_participants = {}
event_message_id = None
event_chat_id = None
event_number = None
event_prize = None
event_active = False
event_started = False
event_timer_task = None
event_timeout_task = None
event_min_num = 1
event_max_num = 250

EMOJI_IDS_TO_CHECK = [
    "5206607081334906820", "5247011187308140698", "5255703720078879038",
    "5276032951342088188", "5280769763398671636", "5307594157739515229",
    "5309815458990433715", "5350612670435313545", "5372926953978341366",
    "5372981976804366741", "5386367538735104399", "5393194986252542669",
    "5418238674267556907", "5427009714745517609", "5431577498364158238",
    "5436040291507247633", "5436113877181941026", "5442983582882601962",
    "5465368548702446780", "5467671759274661866", "5469654973308476699",
    "5469785308386041323", "5471960722206366390", "5472212780952066876",
    "5472255352667904566", "5472283700884660912", "5836936408681421518",
    "5852868430952144622", "5881948563591666817", "5920090136627908485",
    "5809949600152296075", "5283080528818360566", "544528490978621387",
    "5361741454685256344", "5258203794772085854"
]


async def get_chat_members(chat_id):
    try:
        members = []
        async for member in bot.get_chat_members(chat_id):
            members.append(member.user.id)
        return members
    except Exception:
        return []


@_localized
async def check_expired_games_task():
    while True:
        try:
            now = datetime.now()
            expired_ids = []
            for gid, gdata in list(games.items()):
                if not gdata.get("game_over", False) and not gdata.get("settled", False) and not gdata.get("expired", False):
                    created_at = gdata.get("created_at")
                    if created_at and (now - created_at) > timedelta(hours=12):
                        expired_ids.append(gid)

            for gid in expired_ids:
                gdata = games.get(gid)
                if not gdata or gdata.get("settled", False) or gdata.get("expired", False):
                    continue

                gdata["game_over"] = True
                gdata["expired"] = True
                gdata["settled"] = True

                uid = gdata["owner_id"]
                bet = gdata.get("bet", 0)
                gtype = gdata.get("type", "mines")
                name_map = {"mines": _l('мины', user_id=uid), "tower": _l('башня', user_id=uid), "qwak": _l('квак', user_id=uid), "scratch": _l('скретч', user_id=uid), "diamonds": _l('алмазы', user_id=uid), "twentyone": "21", "gold": _l('золото', user_id=uid)}
                game_title = name_map.get(gtype, _l('мины', user_id=uid))

                if not gdata.get("demo_mode", False) and not is_demo_user(uid):
                    udata = get_user(uid)
                    update_user(uid, balance=udata["balance"] + bet)
                    dt_str = gdata.get("created_at_str", now.strftime("%d-%m-%Y %H:%M:%S"))
                    add_game_history(uid, gtype, bet, "expired", 0, dt_str)
                else:
                    dt_str = gdata.get("created_at_str", now.strftime("%d-%m-%Y %H:%M:%S"))
                remove_active_game_from_db(gid)

                msg_text = (
                    _lf('💾 Игра «{0}», начавшаяся {1}, была завершена из-за бездействия. <b>{2} mCoin были возвращены на баланс.</b>', (_fmt(_label(game_title, user_id=uid), '', -1), _fmt(dt_str, '', -1), _fmt(format_number(bet), '', -1)), user_id=uid)
                )

                try:
                    await bot.send_message(chat_id=uid, text=msg_text, parse_mode=ParseMode.HTML)
                except Exception:
                    pass

                if active_games.get(uid) == gid:
                    del active_games[uid]

        except Exception:
            pass
        await asyncio.sleep(60)


@_localized
async def show_catalog(message_or_callback, user_id, user_name, chat_id, is_group=False, edit=False):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    text = (
        f'{user_link}\n'
        f'<b><tg-emoji emoji-id="5309815458990433715">🎮</tg-emoji>{tr(user_id, "catalog_title")}\n'
        '<code>·····················</code></b>\n'
        f'<blockquote> <i>{tr(user_id, "catalog_hint")}</i></blockquote>'
    )

    keyboard_buttons = [
        [
            InlineKeyboardButton(
                text=tr(user_id, "catalog_fast"),
                callback_data="catalog_fast",
                style="primary",
                icon_custom_emoji_id="5449683594425410231"
            ),
            InlineKeyboardButton(
                text=tr(user_id, "catalog_modes"),
                callback_data="catalog_modes",
                style="primary",
                icon_custom_emoji_id="5361741454685256344"
            )
        ]
    ]

    if not is_group:
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=tr(user_id, "settings_back"),
                callback_data="back",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    if isinstance(message_or_callback, types.Message):
        msg = await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        if edit:
            try:
                msg = await message_or_callback.message.edit_text(
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            except Exception:
                msg = await message_or_callback.message.answer(
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
        else:
            msg = await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )

    key = get_chat_key(user_id, chat_id)
    if key not in user_messages:
        user_messages[key] = []
    if msg:
        _remember_message(user_messages, key, msg.message_id)


@_localized
async def show_fast_games_catalog(callback: types.CallbackQuery, user_id, user_name, chat_id, is_group=False):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    text = (
        f'{user_link}\n'
        f'<b><tg-emoji emoji-id="5449683594425410231">⚡</tg-emoji>{tr(user_id, "catalog_fast_title")}\n'
        '<code>·····················</code></b>\n'
        f'<blockquote> <i>{tr(user_id, "catalog_fast_hint")}</i></blockquote>'
    )

    keyboard_buttons = [
        [
            InlineKeyboardButton(text=_l('🎰 Слоты'), callback_data="info_slots", style="primary"),
            InlineKeyboardButton(text=_l('🧰 Сундук'), callback_data="info_chest", style="primary")
        ],
        [
            InlineKeyboardButton(text=_l('🪙 Монетка'), callback_data="info_coin", style="primary"),
            InlineKeyboardButton(text=_l('🎲 Кубик'), callback_data="info_dice", style="primary")
        ],
        [
            InlineKeyboardButton(text=_l('🎳 Боулинг'), callback_data="info_bowling", style="primary"),
            InlineKeyboardButton(text=_l('🎯 Дартс'), callback_data="info_darts", style="primary")
        ],
        [
            InlineKeyboardButton(text=_l('🏀 Баскетбол'), callback_data="info_basketball", style="primary"),
            InlineKeyboardButton(text=_l('⚽ Футбол'), callback_data="info_football", style="primary")
        ],
        [
            InlineKeyboardButton(text=_l('🚀 Краш'), callback_data="info_crash", style="primary"),
            InlineKeyboardButton(text=_l('🎣 Рыбалка'), callback_data="info_fishing", style="primary")
        ],
        [
            InlineKeyboardButton(text=_l('🎫 Скретч'), callback_data="info_scratch", style="primary")
        ],
        [
            InlineKeyboardButton(text=tr(user_id, "settings_back"), callback_data="catalog_main", icon_custom_emoji_id="5255703720078879038")
        ]
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        msg = await callback.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    except Exception:
        msg = await callback.message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    key = get_chat_key(user_id, chat_id)
    if key not in user_messages:
        user_messages[key] = []
    if msg:
        _remember_message(user_messages, key, msg.message_id)


@_localized
async def show_modes_games_catalog(callback: types.CallbackQuery, user_id, user_name, chat_id, is_group=False):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    text = (
        f'{user_link}\n'
        f'<b><tg-emoji emoji-id="5361741454685256344">🕹</tg-emoji>{tr(user_id, "catalog_modes_title")}\n'
        '<code>·····················</code></b>\n'
        f'<blockquote> <i>{tr(user_id, "catalog_modes_hint")}</i></blockquote>'
    )

    keyboard_buttons = [
        [
            InlineKeyboardButton(
                text=_l('Мины'),
                callback_data="mines",
                style="primary",
                icon_custom_emoji_id="5469654973308476699"
            ),
            InlineKeyboardButton(
                text=_l('🛕 Башня'),
                callback_data="tower",
                style="primary"
            )
        ],
        [
            InlineKeyboardButton(
                text=_l('Квак'),
                callback_data="qwak",
                style="primary",
                icon_custom_emoji_id=QWAK_PAD_EMOJI_ID
            ),
            InlineKeyboardButton(
                text=_l('Алмазы'),
                callback_data="diamonds",
                style="primary",
                icon_custom_emoji_id="5307594157739515229"
            )
        ],
        [
            InlineKeyboardButton(
                text=_l('🃏 21 (Очко)'),
                callback_data="info_twentyone",
                style="primary"
            ),
            InlineKeyboardButton(
                text=_l('🌼 Золото'),
                callback_data="gold",
                style="primary",
                icon_custom_emoji_id="5370731117588523522"
            )
        ],
        [
            InlineKeyboardButton(
                text=_l('🎱 Рулетка'),
                callback_data="info_roulette",
                style="primary"
            )
        ],
        [
            InlineKeyboardButton(
                text=tr(user_id, "settings_back"),
                callback_data="catalog_main",
                icon_custom_emoji_id="5255703720078879038"
            )
        ]
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    try:
        msg = await callback.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    except Exception:
        msg = await callback.message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    key = get_chat_key(user_id, chat_id)
    if key not in user_messages:
        user_messages[key] = []
    if msg:
        _remember_message(user_messages, key, msg.message_id)


async def _get_top_identity(user_id, settings):
    if settings.get("bot_nickname"):
        return settings["bot_nickname"], None
    cursor.execute("SELECT first_name, username FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        return row[0], row[1]
    if row and row[1] and not settings.get("hide_top_username"):
        return row[1], row[1]
    try:
        user = await bot.get_chat(user_id)
        save_username(user_id, user.username, user.first_name)
        return user.first_name or _l('Пользователь'), user.username
    except Exception:
        name = _l('Пользователь') if settings.get("hide_top_username") else get_user_display_name(user_id)
        return name, None


@_localized
async def show_top(message, chat_id=None):
    user_id = message.from_user.id

    if chat_id:
        add_chat_member(user_id, chat_id)
        top_users = get_top_users(10, chat_id)
        title = tr(user_id, "top_chat")
    else:
        top_users = get_top_users(10)
        title = tr(user_id, "top_world")

    if not top_users:
        await message.answer(f"<i>{tr(user_id, 'top_empty')}</i>", parse_mode=ParseMode.HTML)
        return

    rank_emojis = [
        '<tg-emoji emoji-id="5765089714717596171">🥇</tg-emoji>',
        '<tg-emoji emoji-id="5767304320114498155">🥈</tg-emoji>',
        '<tg-emoji emoji-id="5764928223947267454">🥉</tg-emoji>',
        '<tg-emoji emoji-id="5334644364280866007">🏅</tg-emoji>',
        '<tg-emoji emoji-id="5334644364280866007">🏅</tg-emoji>',
        '<tg-emoji emoji-id="5334644364280866007">🏅</tg-emoji>',
        '<tg-emoji emoji-id="5334644364280866007">🏅</tg-emoji>',
        '<tg-emoji emoji-id="5334644364280866007">🏅</tg-emoji>',
        '<tg-emoji emoji-id="5334644364280866007">🏅</tg-emoji>',
        '<tg-emoji emoji-id="5334644364280866007">🏅</tg-emoji>'
    ]

    text = f'<tg-emoji emoji-id="5280769763398671636">🏆</tg-emoji><b>{title}</b>\n\n'

    for i, (uid, balance) in enumerate(top_users):
        settings = get_user_settings(uid)
        raw_name, username = await _get_top_identity(uid, settings)
        if settings.get("bot_nickname"):
            raw_name = settings["bot_nickname"]
        elif username and not settings.get("hide_top_username"):
            raw_name = f"@{username}"
        clean_name = html.escape(str(raw_name))
        text += f'{rank_emojis[i]} {i+1}.  {clean_name} | <code>{format_number(balance)}</code> m¢\n'

    user_rank = get_user_rank(user_id, chat_id) if chat_id else get_user_rank(user_id)

    if user_rank > 0:
        user_data = get_user(user_id)

        if user_rank <= 10:
            caller_emoji = rank_emojis[user_rank - 1]
        else:
            caller_emoji = "🎖️"

        settings = get_user_settings(user_id)
        raw_name, username = await _get_top_identity(user_id, settings)
        if settings.get("bot_nickname"):
            raw_name = settings["bot_nickname"]
        elif username and not settings.get("hide_top_username"):
            raw_name = f"@{username}"
        clean_name = html.escape(str(raw_name))
        text += f'\n<blockquote>{user_rank}. {caller_emoji}  {clean_name} | <code>{format_number(user_data["balance"])}</code> mCoin</blockquote>'

    await message.answer(
        text=text,
        parse_mode=ParseMode.HTML
    )



def get_active_unplayed_games(user_id):
    result = []
    for gid, g in games.items():
        if g.get("owner_id") == user_id:
            if not g.get("game_over", False) and not g.get("settled", False) and not g.get("expired", False):
                if g.get("stage") in ["playing", "ready"]:
                    result.append((gid, g))
    return sorted(result, key=lambda x: x[0], reverse=True)


@_localized
async def show_recent_games_menu(message_or_callback, user_id, user_name, page=1):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    text = (
        _lf('{0}\n🕓 <b>НЕДАВНИЕ ИГРЫ</b>\n<code>·····················</code>\n<blockquote>ℹ️ Вы можете просмотреть свои недавние игры и продолжить запущенные. Если вы запускали игру более 12 часов назад, она завершилась, и ставка была возвращена на ваш баланс.</blockquote>', (_fmt(user_link, '', -1),))
    )

    unplayed = get_active_unplayed_games(user_id)
    per_page = 5
    total_pages = max(1, (len(unplayed) + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    start_idx = (page - 1) * per_page
    page_games = unplayed[start_idx:start_idx + per_page]

    keyboard_rows = []

    type_names = {
        "mines": _l('Мины'),
        "tower": _l('Башня'),
        "qwak": _l('Квак'),
        "scratch": _l('Скретч'),
        "diamonds": _l('Алмазы'),
        "twentyone": _l('21 (Очко)'),
        "gold": _l('Золото')
    }

    for gid, gdata in page_games:
        gtype = gdata.get("type", "mines")
        gname = type_names.get(gtype, _l('Мины'))
        bet_str = format_number(gdata.get("bet", 10))
        btn_text = f"{gname} • {bet_str} mCoin"
        keyboard_rows.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"resume_game_{gid}",
                style="success",
                icon_custom_emoji_id="5809949600152296075"
            )
        ])

    if total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"recent_page_{page - 1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"recent_page_{page + 1}"))
        if nav_buttons:
            keyboard_rows.append(nav_buttons)

    keyboard_rows.append([
        InlineKeyboardButton(
            text=_l('История игр'),
            callback_data="history_games_1",
            style="primary",
            icon_custom_emoji_id="5309815458990433715"
        ),
        InlineKeyboardButton(
            text=_l('Статистика'),
            callback_data="history_stats",
            style="primary",
            icon_custom_emoji_id="5431577498364158238"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@dp.message(Command("history", "история"))
@dp.message(_inline_filter(lambda message: message.text and message.text.lower() in ["история", "недавние игры", "игры история", "история игр"]))
@_localized
async def cmd_history(message: types.Message):
    await show_recent_games_menu(message, message.from_user.id, get_user_display_name(message.from_user.id, message.from_user.first_name), page=1)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("recent_page_")))
@_localized
async def process_recent_page(callback: types.CallbackQuery):
    await callback.answer()
    try:
        page = int(callback.data.split("_")[-1])
    except Exception:
        page = 1
    await show_recent_games_menu(callback, callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), page=page)


@dp.callback_query(_inline_filter(lambda c: c.data == "back_to_history_menu"))
@_localized
async def process_back_to_history_menu(callback: types.CallbackQuery):
    await callback.answer()
    await show_recent_games_menu(callback, callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), page=1)


@dp.callback_query(_inline_filter(lambda c: c.data == "history_stats"))
@_localized
async def process_history_stats(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    user_name = html.escape(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{user_name}</a>'

    stats = get_user_stats(user_id)

    text = (
        _lf('{0}\n<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji><b>СТАТИСТИКА ПО ИГРАМ</b>\n<code>·····················</code>\n<blockquote expandable>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> Мины: {1}\n<tg-emoji emoji-id="5283080528818360566">🚀</tg-emoji> Краш: {2}\n🛕 Башня: {3}\n🐸 Квак: {4}\n💠 Алмазы: {5}\n🌼 Золото: {6}\n🎰 Слоты: {7}\n🎳 Боулинг: {8}\n🎲 Кубик: {9}\n🪙 Монетка: {10}\n🧰 Сундук: {11}\n🎣 Рыбалка: {12}\n🎫 Скретч: {13}\n🎱 Рулетка: {14}\n🎯 Дартс: {15}\n🏀 Баскетбол: {16}\n⚽ Футбол: {17}\n🃏 21 (Очко): {18}\n<code>·····················</code>\n🕹 Сыграно: {19} игр\n</blockquote>', (_fmt(user_link, '', -1), _fmt(stats['mines'], '', -1), _fmt(stats['crash'], '', -1), _fmt(stats['tower'], '', -1), _fmt(stats.get('qwak', 0), '', -1), _fmt(stats['diamonds'], '', -1), _fmt(stats.get('gold', 0), '', -1), _fmt(stats.get('slots', 0), '', -1), _fmt(stats.get('bowling', 0), '', -1), _fmt(stats.get('dice', 0), '', -1), _fmt(stats.get('coin', 0), '', -1), _fmt(stats.get('chest', 0), '', -1), _fmt(stats.get('fishing', 0), '', -1), _fmt(stats.get('scratch', 0), '', -1), _fmt(stats.get('roulette', 0), '', -1), _fmt(stats.get('darts', 0), '', -1), _fmt(stats.get('basketball', 0), '', -1), _fmt(stats.get('football', 0), '', -1), _fmt(stats.get('twentyone', 0), '', -1), _fmt(stats['total'], '', -1)))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Назад'),
                    callback_data="back_to_history_menu",
                    icon_custom_emoji_id="5255703720078879038"
                )
            ]
        ]
    )

    try:
        await callback.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    except Exception:
        await callback.message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("history_games_")))
@_localized
async def process_history_games(callback: types.CallbackQuery):
    await callback.answer()
    try:
        page = int(callback.data.split("_")[-1])
    except Exception:
        page = 1

    user_id = callback.from_user.id
    user_name = html.escape(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{user_name}</a>'

    total_count = get_user_history_count(user_id)
    per_page = 5
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    offset = (page - 1) * per_page
    rows = get_user_history(user_id, limit=per_page, offset=offset)

    type_info = {
        "mines": ("💣", _l('Мины')),
        "tower": ("🛕", _l('Башня')),
        "qwak": ("🐸", _l('Квак')),
        "diamonds": ("💠", _l('Алмазы')),
        "gold": ("🌼", _l('Золото')),
        "crash": ("🚀", _l('Краш')),
        "slots": ("🎰", _l('Слоты')),
        "bowling": ("🎳", _l('Боулинг')),
        "dice": ("🎲", _l('Кубик')),
        "coin": ("🪙", _l('Монетка')),
        "chest": ("🧰", _l('Сундук')),
        "fishing": ("🎣", _l('Рыбалка')),
        "scratch": ("🎫", _l('Скретч')),
        "roulette": ("🎱", _l('Рулетка')),
        "darts": ("🎯", _l('Дартс')),
        "basketball": ("🏀", _l('Баскетбол')),
        "football": ("⚽", _l('Футбол')),
        "twentyone": ("🃏", _l('21 (Очко)'))
    }

    text = _lf('{0}\n🕓 <b>История игр:</b>\n\n', (_fmt(user_link, '', -1),))

    if not rows:
        text += _l('<i>История игр пуста. Сыграйте в любую игру!</i>\n\n')
    else:
        for idx, (gtype, bet, result, win_amount, dt_str) in enumerate(rows):
            icon, name = type_info.get(gtype, ("🎮", _l('Игра')))
            text += f'{icon} <b>{name}:</b> {dt_str}\n'
            text += _lf('💸 <b>Ставка:</b> {0} m¢\n', (_fmt(format_number(bet), '', -1),))
            if result == "win":
                text += _lf('✅ <b>Выигрыш:</b> {0} m¢\n', (_fmt(format_number(win_amount), '', -1),))
            elif result == "draw":
                text += _lf('🤝 <b>Ничья (возврат):</b> {0} m¢\n', (_fmt(format_number(win_amount), '', -1),))
            elif result == "expired":
                text += _l('💾 <b>Игра отменена (бездействие)</b>\n')
            else:
                text += _l('❌ <b>Игра проиграна!</b>\n')
            
            if idx < len(rows) - 1:
                text += '<code>·····················</code>\n'

        text += _lf('\n↗️ <i>Страница {0}/{1}</i>', (_fmt(page, '', -1), _fmt(total_pages, '', -1)))

    keyboard_rows = []
    nav_buttons = []

    if page > 5:
        nav_buttons.append(InlineKeyboardButton(text="⏮️ 5", callback_data=f"history_games_{page - 5}"))
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"history_games_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"history_games_{page + 1}"))
    if total_pages - page >= 5:
        nav_buttons.append(InlineKeyboardButton(text="⏩ 5", callback_data=f"history_games_{page + 5}"))

    if nav_buttons:
        keyboard_rows.append(nav_buttons)

    keyboard_rows.append([
        InlineKeyboardButton(
            text=_l('Назад'),
            callback_data="back_to_history_menu",
            icon_custom_emoji_id="5255703720078879038"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    try:
        await callback.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    except Exception:
        await callback.message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("resume_game_")))
@_localized
async def process_resume_game(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer(_l('Ошибка игры!'), show_alert=True)
        return

    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("settled", False) or game.get("expired", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    active_games[user_id] = game_id
    game["chat_id"] = callback.message.chat.id

    old_msg_id = game.get("message_id")
    if old_msg_id and old_msg_id != callback.message.message_id:
        try:
            await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=old_msg_id)
        except Exception:
            pass

    await callback.answer()

    gtype = game.get("type")
    if gtype == "mines":
        await show_mines_grid_from_callback(callback, user_id, game_id)
    elif gtype == "tower":
        await show_tower_grid_from_callback(callback, user_id, game_id)
    elif gtype == "qwak":
        await show_qwak_grid_from_callback(callback, user_id, game_id)
    elif gtype == "scratch":
        await show_scratch_grid_from_callback(callback, user_id, game_id)
    elif gtype == "diamonds":
        await show_diamonds_grid_from_callback(callback, user_id, game_id)
    elif gtype == "twentyone":
        await show_twentyone_from_callback(callback, user_id, game_id)
    elif gtype == "gold":
        await show_gold_grid_from_message(callback, user_id, game_id)
    else:
        await callback.answer(_l('Неизвестный тип игры!'), show_alert=True)


CHECKS_ACCESS_PRICE = 100000
CHECK_MAX_ACTIVATIONS = 1000
CHECK_MAX_AMOUNT = 10_000_000


def has_checks_access(user_id):
    try:
        cursor.execute("SELECT 1 FROM checks_access WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None
    except Exception:
        return False


def make_check_code():
    while True:
        code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:12]
        try:
            cursor.execute("SELECT 1 FROM mcoin_checks WHERE check_code = ?", (code,))
            if not cursor.fetchone():
                return code
        except Exception:
            return code


@_localized
async def show_checks_menu(message_or_callback, user_id, edit=False):
    chat = message_or_callback.message.chat if isinstance(message_or_callback, types.CallbackQuery) else message_or_callback.chat
    if chat.type != "private":
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.answer(_l('Раздел чеков работает только в личке.'), show_alert=True)
        else:
            await message_or_callback.answer(_l('<i>Раздел чеков работает только в личных сообщениях!</i>'), parse_mode=ParseMode.HTML)
        return

    access = has_checks_access(user_id)
    if access:
        text = (
            _l('<b>🧾 РАЗДЕЛ ЧЕКОВ</b>\n<code>·····················</code>\n<i>Доступ куплен навсегда. Создай чек на сумму за одну активацию и укажи количество получателей.</i>\n\n<code>/check 100к 5</code> — чек по 100 000 mCoin для 5 человек.')
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_l('➕ Создать чек'), callback_data="checks_create_help", style="success")],
            [InlineKeyboardButton(text=_l('📋 Мои чеки'), callback_data="checks_mine", style="primary")],
            [InlineKeyboardButton(text=_l('Назад'), callback_data="checks_back")],
        ])
    else:
        text = (
            _lf('<b>🧾 РАЗДЕЛ ЧЕКОВ</b>\n<code>·····················</code>\n<i>Откройте раздел за <b>{0} mCoin</b> один раз — доступ останется навсегда.</i>', (_fmt(format_number(CHECKS_ACCESS_PRICE), '', -1),))
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_l('🔓 Открыть за 100к'), callback_data="checks_buy", style="success")],
            [InlineKeyboardButton(text=_l('Назад'), callback_data="checks_back")],
        ])

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    elif edit:
        try:
            await message_or_callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except Exception:
            await message_or_callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await message_or_callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@_localized
async def activate_mcoin_check(message, code):
    user_id = message.from_user.id
    if message.chat.type != "private":
        await message.answer(_l('<i>Активация чеков работает только в личных сообщениях!</i>'), parse_mode=ParseMode.HTML)
        return
    code = (code or "").strip()
    try:
        cursor.execute('''
            SELECT creator_id, amount, remaining_activations, is_active
            FROM mcoin_checks WHERE check_code = ?
        ''', (code,))
        row = cursor.fetchone()
        if not row or not row[3] or int(row[2] or 0) <= 0:
            await message.answer(_l('<i>Чек не найден или уже полностью активирован.</i>'), parse_mode=ParseMode.HTML)
            return
        creator_id, amount, remaining, _ = row
        if int(creator_id) == user_id:
            await message.answer(_l('<i>Нельзя активировать собственный чек.</i>'), parse_mode=ParseMode.HTML)
            return
        cursor.execute("SELECT 1 FROM check_activations WHERE check_code = ? AND user_id = ?", (code, user_id))
        if cursor.fetchone():
            await message.answer(_l('<i>Вы уже активировали этот чек.</i>'), parse_mode=ParseMode.HTML)
            return

        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute(
            "INSERT INTO check_activations (check_code, user_id, activated_at) VALUES (?, ?, ?)",
            (code, user_id, now_str)
        )
        new_remaining = int(remaining) - 1
        cursor.execute(
            "UPDATE mcoin_checks SET remaining_activations = ?, is_active = ? WHERE check_code = ?",
            (new_remaining, 1 if new_remaining > 0 else 0, code)
        )
        user_data = get_user(user_id)
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (int(amount), user_id))
        conn.commit()
        await message.answer(
            _lf('<i>✅ Чек активирован!\nНачислено: <b>{0} mCoin</b>\nОсталось активаций: <b>{1}</b></i>', (_fmt(format_number(amount), '', -1), _fmt(new_remaining, '', -1))),
            parse_mode=ParseMode.HTML
        )
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        await message.answer(_lf('<i>Не удалось активировать чек: {0}</i>', (_fmt(html.escape(str(exc)), '', -1),)), parse_mode=ParseMode.HTML)


@dp.message(Command("check", "checks", "чек", "чеки"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r"^(?:чек|чеки|check|checks)(?:\s|$)", message.text.strip(), re.IGNORECASE)))
@_localized
async def cmd_checks(message: types.Message):
    if message.chat.type != "private":
        await message.answer(_l('<i>Раздел чеков работает только в личных сообщениях!</i>'), parse_mode=ParseMode.HTML)
        return
    args = (message.text or "").strip().split()[1:]
    if not args:
        await show_checks_menu(message, message.from_user.id)
        return
    if not has_checks_access(message.from_user.id):
        await show_checks_menu(message, message.from_user.id)
        return
    if len(args) > 2:
        await message.answer(_l('<i>Использование: <code>/check 100к 5</code></i>'), parse_mode=ParseMode.HTML)
        return
    amount = parse_amount(args[0])
    activations = int(args[1]) if len(args) == 2 and args[1].isdigit() else 1
    if amount is None or amount <= 0 or amount > CHECK_MAX_AMOUNT or activations < 1 or activations > CHECK_MAX_ACTIVATIONS:
        await message.answer(_l('<i>Сумма одной активации должна быть от 1 до <b>10kk mCoin</b>. Пример: <code>/check 100к 5</code></i>'), parse_mode=ParseMode.HTML)
        return
    total = int(amount) * activations
    user_data = get_user(message.from_user.id)
    if user_data["balance"] < total:
        await message.answer(
            _lf('<i>Недостаточно средств. Нужно зарезервировать <b>{0} mCoin</b>.</i>', (_fmt(format_number(total), '', -1),)),
            parse_mode=ParseMode.HTML
        )
        return
    code = make_check_code()
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (total, message.from_user.id))
        cursor.execute('''
            INSERT INTO mcoin_checks
                (check_code, creator_id, amount, total_activations, remaining_activations, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', (code, message.from_user.id, int(amount), activations, activations, now_str))
        conn.commit()
        link = f"https://t.me/{BOT_USERNAME}?start=check_{code}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_l('🎁 Активировать чек'), url=link)]
        ])
        await message.answer(
            _lf('<b>🧾 Чек создан!</b>\nСумма за активацию: <b>{0} mCoin</b>\nАктиваций: <b>{1}</b>\nЗарезервировано: <b>{2} mCoin</b>\n\nСсылка: <code>{3}</code>', (_fmt(format_number(amount), '', -1), _fmt(activations, '', -1), _fmt(format_number(total), '', -1), _fmt(html.escape(link), '', -1))),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        await message.answer(_lf('<i>Не удалось создать чек: {0}</i>', (_fmt(html.escape(str(exc)), '', -1),)), parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "checks_menu"))
@_localized
async def process_checks_menu(callback: types.CallbackQuery):
    await callback.answer()
    await show_checks_menu(callback, callback.from_user.id, edit=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "checks_buy"))
@_localized
async def process_checks_buy(callback: types.CallbackQuery):
    if callback.message.chat.type != "private":
        await callback.answer(_l('Раздел чеков работает только в личке.'), show_alert=True)
        return
    user_id = callback.from_user.id
    if has_checks_access(user_id):
        await show_checks_menu(callback, user_id, edit=True)
        return
    user_data = get_user(user_id)
    if user_data["balance"] < CHECKS_ACCESS_PRICE:
        await callback.answer(_l('Недостаточно mCoin для покупки доступа.'), show_alert=True)
        return
    try:
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (CHECKS_ACCESS_PRICE, user_id))
        cursor.execute(
            "INSERT INTO checks_access (user_id, purchased_at) VALUES (?, ?)",
            (user_id, datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
        )
        conn.commit()
        await callback.answer(_l('Раздел чеков открыт навсегда!'))
        await show_checks_menu(callback, user_id, edit=True)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        await callback.answer(_l('Ошибка при покупке доступа.'), show_alert=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "checks_create_help"))
@_localized
async def process_checks_create_help(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        _l('<b>➕ Создание чека</b>\n\nОтправь команду в личку:\n<code>/check сумма количество</code>\n\nНапример: <code>/check 100к 5</code>\n<i>С баланса сразу резервируется сумма всех активаций.</i>'),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_l('Назад'), callback_data="checks_menu")]
        ])
    )


@dp.callback_query(_inline_filter(lambda c: c.data == "checks_mine"))
@_localized
async def process_checks_mine(callback: types.CallbackQuery):
    await callback.answer()
    if callback.message.chat.type != "private":
        return
    cursor.execute('''
        SELECT check_code, amount, remaining_activations, total_activations
        FROM mcoin_checks WHERE creator_id = ? ORDER BY created_at DESC LIMIT 10
    ''', (callback.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        text = _l('<i>У вас пока нет созданных чеков.</i>')
    else:
        lines = [_l('<b>📋 Ваши чеки:</b>')]
        for code, amount, remaining, total in rows:
            status = _l('активен') if int(remaining or 0) > 0 else _l('завершён')
            lines.append(f"• <code>{html.escape(str(code))}</code> — {format_number(amount)} m¢, {remaining}/{total}, {status}")
        text = "\n".join(lines)
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_l('Назад'), callback_data="checks_menu")]
        ])
    )


@dp.callback_query(_inline_filter(lambda c: c.data == "checks_back"))
@_localized
async def process_checks_back(callback: types.CallbackQuery):
    await callback.answer()
    if callback.message.chat.type != "private":
        return
    try:
        await callback.message.edit_text(
            _l('<b>Привет! <tg-emoji emoji-id="5350612670435313545">👋</tg-emoji> Ты в Мины Бот — место, где время летит незаметно!</b>\n\n🎮 Много бесплатных игр без скачивания, прямо в Telegram.\n\nСоревнуйся с друзьями и прокачивай свои каналы и чаты. 🏆'),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_l('Играть'), callback_data="play", style="success", icon_custom_emoji_id="5350612670435313545")],
                [InlineKeyboardButton(text=_l('🧾 Чеки'), callback_data="checks_menu", style="primary")],
                [InlineKeyboardButton(text=_l('Добавить бота в чат'), url=f"https://t.me/{BOT_USERNAME}?startgroup=start", style="primary", icon_custom_emoji_id="5393194986252542669")],
            ])
        )
    except Exception:
        pass



@dp.message(Command("start"))
@_localized
async def cmd_start(message: types.Message):
    if message.chat.type in ["group", "supergroup"]:
        await message.answer(_l('<i>Эта команда работает только в личных сообщениях!</i>'), parse_mode=ParseMode.HTML)
        return

    user_id = message.from_user.id
    get_user(user_id)

    parts = message.text.split()
    if len(parts) > 1:
        payload = parts[1].strip()
        if payload.startswith("ref_"):
            try:
                referrer_id = int(payload.replace("ref_", ""))
                register_referral(referrer_id, user_id)
            except Exception:
                pass
        elif payload == "p2p":
            await show_p2p_main(message, user_id=user_id, first_name=get_user_display_name(message.from_user.id, message.from_user.first_name))
            return
        elif payload == "promote":
            promote_user_states.pop(user_id, None)
            await send_promote_main_menu(message.chat.id, user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
            return
        elif payload in ["earn", "earning"]:
            text, keyboard = build_earn_menu(user_id)
            await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            return
        elif payload.startswith("check_"):
            await activate_mcoin_check(message, payload[len("check_"):])
            return

    text = tr(message.from_user.id, "main_text")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(message.from_user.id, "main_play"),
                    callback_data="play",
                    style="success",
                    icon_custom_emoji_id="5350612670435313545"
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(message.from_user.id, "main_checks"),
                    callback_data="checks_menu",
                    style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(message.from_user.id, "main_add_chat"),
                    url=f"https://t.me/{BOT_USERNAME}?startgroup=start",
                    style="primary",
                    icon_custom_emoji_id="5393194986252542669"
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(message.from_user.id, "main_settings"),
                    callback_data="settings_open",
                    style="primary"
                )
            ]
        ]
    )

    photo_url = "https://iili.io/CPpNkSR.md.png"
    msg = await message.answer_photo(
        photo=photo_url,
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    key = get_chat_key(message.from_user.id, message.chat.id)
    if key not in user_messages:
        user_messages[key] = []
    _remember_message(user_messages, key, msg.message_id)


@dp.message(Command("add"))
@_localized
async def cmd_add(message: types.Message):
    user_id = message.from_user.id

    if user_id not in ADMINS or not admin_has_permission(user_id, "issue"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer(_l('<i>Использование: /add [сумма]\nИли в ответ на сообщение пользователя: /add [сумма]</i>'), parse_mode=ParseMode.HTML)
        return

    amount = parse_amount(args[1])
    if amount is None or amount < 0:
        await message.answer(_l('<i>Неверная сумма! Пример: 100, 1.4кк, 120кк</i>'), parse_mode=ParseMode.HTML)
        return

    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
        target_name = get_user_display_name(message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name)
    else:
        target_user_id = user_id
        target_name = None

    user_data = get_user(target_user_id)
    allowed, limit_error = reserve_admin_usage(user_id, "issue", amount)
    if not allowed:
        await message.reply(_lf('<i>{0}</i>', (_fmt(html.escape(limit_error or _l('Операция запрещена.')), '', -1),)), parse_mode=ParseMode.HTML)
        return
    new_balance = user_data["balance"] + amount

    if update_user(target_user_id, balance=new_balance):
        _admin_log(
            message.from_user,
            "add_balance",
            target_id=target_user_id,
            target_name=target_name,
            details={"amount": format_number(amount), "balance": format_number(new_balance), "currency": "mCoin"},
        )
        await message.reply(
            _lf('<i>✅ Successfully! На баланс пользователя {0} добавлено {1} mCoin\nТекущий баланс: {2} mCoin</i>', (_fmt(html.escape(get_user_display_name(target_user_id, target_name) if target_name is not None else _l('ваш')), '', -1), _fmt(format_number(amount), '', -1), _fmt(format_number(new_balance), '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(_l('<i>Ошибка базы данных!</i>'), parse_mode=ParseMode.HTML)


@dp.message(Command("set"))
@_localized
async def cmd_set(message: types.Message):
    user_id = message.from_user.id

    if user_id not in ADMINS or not admin_has_permission(user_id, "set"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer(_l('<i>Использование: /set [сумма]\nИли в ответ на сообщение пользователя: /set [сумма]</i>'), parse_mode=ParseMode.HTML)
        return

    amount = parse_amount(args[1])
    if amount is None or amount < 0:
        await message.answer(_l('<i>Неверная сумма! Пример: 100, 1.4кк, 120кк</i>'), parse_mode=ParseMode.HTML)
        return

    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
        target_name = get_user_display_name(message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name)
    else:
        target_user_id = user_id
        target_name = None

    target_data = get_user(target_user_id)
    increase = max(0, int(amount) - int(target_data.get("balance", 0) or 0))
    allowed, limit_error = reserve_admin_usage(user_id, "issue", increase)
    if not allowed:
        await message.reply(_lf('<i>{0}</i>', (_fmt(html.escape(limit_error or _l('Операция запрещена.')), '', -1),)), parse_mode=ParseMode.HTML)
        return
    if update_user(target_user_id, balance=amount):
        user_data = get_user(target_user_id)
        _admin_log(
            message.from_user,
            "zero_balance" if int(amount) == 0 else "set_balance",
            target_id=target_user_id,
            target_name=target_name,
            details={"balance": format_number(user_data["balance"]), "currency": "mCoin"},
        )
        await message.reply(
            _lf('<i>✅ Successfully! Баланс пользователя {0} установлен на {1} mCoin</i>', (_fmt(html.escape(get_user_display_name(target_user_id, target_name) if target_name is not None else _l('ваш')), '', -1), _fmt(format_number(user_data['balance']), '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(_l('<i>Ошибка базы данных!</i>'), parse_mode=ParseMode.HTML)


@_localized
def parse_record_field(field_str: str):
    if not field_str:
        return None, None
    f = field_str.lower().strip()
    if f in ["баланс", "balance", "max_balance", "макс", "максбаланс", "bal", "max", "б"]:
        return "max_balance", _l('Рекорд максимального баланса')
    if f in ["игры", "игры_колво", "games", "game", "игр", "и"]:
        return "games", _l('Сыграно игр')
    if f in ["слив", "проигрыш", "проигрыши", "lost", "проиграно", "lose", "с", "п"]:
        return "lost", _l('Проиграно m¢')
    return None, None


@dp.message(Command("setrec", "setrecord", "изменитьрекорд"))
@_localized
async def cmd_setrec(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    text = (message.text or "").strip()
    parts = text.split()

    target_user_id = None
    target_name = None
    field_arg = None
    val_arg = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or f"ID:{target_user_id}"
        if len(parts) >= 3:
            field_arg = parts[1]
            val_arg = parts[2]
        else:
            await message.reply(
                _l('<i>Использование в ответ на сообщение:\n/setrec &lt;тип&gt; &lt;значение&gt;\n\nТипы:\n• <code>баланс</code> (максимальный баланс)\n• <code>игры</code> (количество игр)\n• <code>слив</code> (сумма проигрышей)\n\nПример: <code>/setrec баланс 50кк</code> или <code>/setrec игры 500</code></i>'),
                parse_mode=ParseMode.HTML
            )
            return
    elif len(parts) >= 4:
        target_arg = parts[1]
        field_arg = parts[2]
        val_arg = parts[3]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.reply(_lf('<i>Пользователь @{0} не найден в базе бота!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = get_user_display_name(target_user_id)
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.reply(_lf('<i>Пользователь {0} не найден в базе бота!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        await message.reply(
            _l('<i>Использование:\n• <code>/setrec &lt;@user/ID&gt; &lt;тип&gt; &lt;значение&gt;</code>\n• ответом на сообщение: <code>/setrec &lt;тип&gt; &lt;значение&gt;</code>\n\nДоступные типы:\n• <code>баланс</code> (максимальный баланс)\n• <code>игры</code> (количество сыгранных игр)\n• <code>слив</code> (сумма проигрышей)\n\nПример: <code>/setrec @durov баланс 100кк</code></i>'),
            parse_mode=ParseMode.HTML
        )
        return

    col_name, col_title = parse_record_field(field_arg)
    if not col_name:
        await message.reply(
            _l('<i>Неизвестный тип рекорда! Доступны: <code>баланс</code>, <code>игры</code>, <code>слив</code></i>'),
            parse_mode=ParseMode.HTML
        )
        return

    amount = parse_amount(val_arg)
    if amount is None or amount < 0:
        await message.reply(_l('<i>Неверное значение! Пример: 100, 1.4кк, 500</i>'), parse_mode=ParseMode.HTML)
        return

    kwargs = {col_name: amount}
    if update_user(target_user_id, **kwargs):
        _admin_log(
            message.from_user,
            "set_record",
            target_id=target_user_id,
            target_name=target_name,
            details={"field": col_name, "value": format_number(amount)},
        )
        admin_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ'))
        admin_link = f'<a href="tg://user?id={user_id}">{admin_name}</a>'
        target_link = f'<a href="tg://user?id={target_user_id}">{html.escape(get_user_display_name(target_user_id, target_name))}</a>'
        await message.reply(
            _lf('<i>{0}, успешно обновлен рекорд для {1}!\n👑 <b>{2}:</b> {3}</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1), _fmt(_label(col_title), '', -1), _fmt(format_number(amount), '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(_l('<i>Ошибка при обновлении базы данных!</i>'), parse_mode=ParseMode.HTML)


@dp.message(Command("delrec", "delrecord", "resetrec", "удалитьрекорд", "сброситьрекорд"))
@_localized
async def cmd_delrec(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    text = (message.text or "").strip()
    parts = text.split()

    target_user_id = None
    target_name = None
    field_arg = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or f"ID:{target_user_id}"
        if len(parts) >= 2:
            field_arg = parts[1]
    elif len(parts) >= 2:
        target_arg = parts[1]
        if len(parts) >= 3:
            field_arg = parts[2]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.reply(_lf('<i>Пользователь @{0} не найден в базе бота!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = get_user_display_name(target_user_id)
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                col, _ = parse_record_field(target_arg)
                if col:
                    target_user_id = user_id
                    target_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ')
                    field_arg = target_arg
                else:
                    await message.reply(_lf('<i>Пользователь {0} не найден в базе бота!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                    return
    else:
        await message.reply(
            _l('<i>Использование:\n• <code>/delrec &lt;@user/ID&gt; [тип]</code> — сбросить рекорды пользователя\n• ответом на сообщение: <code>/delrec [тип]</code>\n\nТипы: <code>все</code> (по умолчанию) | <code>баланс</code> | <code>игры</code> | <code>слив</code>\nПример: <code>/delrec @username</code> или <code>/delrec @username баланс</code></i>'),
            parse_mode=ParseMode.HTML
        )
        return

    u_data = get_user(target_user_id)
    cur_balance = u_data.get("balance", 0)

    if not field_arg or field_arg.lower().strip() in ["все", "all", "всё"]:
        success = update_user(target_user_id, max_balance=cur_balance, games=0, lost=0)
        log_field = "all"
        desc = _lf('Все рекорды сброшены (Макс. баланс: {0} m¢, Игры: 0, Проиграно: 0)', (_fmt(format_number(cur_balance), '', -1),))
    else:
        col_name, col_title = parse_record_field(field_arg)
        if not col_name:
            await message.reply(
                _l('<i>Неизвестный тип рекорда! Доступны: <code>все</code>, <code>баланс</code>, <code>игры</code>, <code>слив</code></i>'),
                parse_mode=ParseMode.HTML
            )
            return
        val = cur_balance if col_name == "max_balance" else 0
        success = update_user(target_user_id, **{col_name: val})
        log_field = col_name
        desc = _lf('Рекорд «{0}» сброшен в {1}', (_fmt(_label(col_title), '', -1), _fmt(format_number(val), '', -1)))

    if success:
        _admin_log(
            message.from_user,
            "reset_record",
            target_id=target_user_id,
            target_name=target_name,
            details={"field": log_field},
        )
        admin_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ'))
        admin_link = f'<a href="tg://user?id={user_id}">{admin_name}</a>'
        target_link = f'<a href="tg://user?id={target_user_id}">{html.escape(get_user_display_name(target_user_id, target_name))}</a>'
        await message.reply(
            _lf('<i>{0}, для пользователя {1} успешно выполнено:\n🗑 {2} ✅</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1), _fmt(desc, '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(_l('<i>Ошибка при обновлении базы данных!</i>'), parse_mode=ParseMode.HTML)


@dp.message(Command("sna"))
@_localized
async def cmd_sna(message: types.Message):
    user_id = message.from_user.id

    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        cursor.execute("UPDATE users SET balance = 0")
        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM users")
        row = cursor.fetchone()
        total_users = row[0] if row else 0
        _admin_log(
            message.from_user,
            "reset_balances",
            all_users=True,
            details={"users": total_users, "currency": "mCoin"},
        )
        await message.reply(
            _lf('<i>✅ Successfully! Баланс всех игроков обнулен.\n👥 Всего пользователей: {0}</i>', (_fmt(total_users, '', -1),)),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.reply(_lf('<i>Ошибка базы данных: {0}</i>', (_fmt(html.escape(str(e)), '', -1),)), parse_mode=ParseMode.HTML)


@dp.message(Command("sn"))
@_localized
async def cmd_sn(message: types.Message):
    user_id = message.from_user.id

    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        cursor.execute("UPDATE users SET balance = 0, mp_balance = 0, mp_daily_transferred = 0, mp_daily_date = NULL, games = 0, lost = 0, bonus_time = NULL")
        cursor.execute("DELETE FROM games_history")
        cursor.execute("DELETE FROM transfers_history")
        cursor.execute("DELETE FROM mp_transfers_history")
        cursor.execute("DELETE FROM game_stats")
        cursor.execute("DELETE FROM active_games_state")
        cursor.execute("DELETE FROM promo_codes")
        cursor.execute("DELETE FROM promo_activations")
        cursor.execute("DELETE FROM top_bans")
        cursor.execute("DELETE FROM transfer_bans")
        _top_banned_users.clear()
        _transfer_banned_users.clear()
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM users")
        row = cursor.fetchone()
        total_users = row[0] if row else 0
        _admin_log(
            message.from_user,
            "reset_database",
            all_users=True,
            details={"users": total_users},
        )

        await message.reply(
            _lf('<i>✅ Successfully! База данных полностью очищена.\n👥 Сохранены только профили пользователей ({0} шт.).\n🗑 Балансы, статистика (сыграно/проиграно), история игр, переводов и промокоды удалены.</i>', (_fmt(total_users, '', -1),)),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.reply(_lf('<i>Ошибка базы данных: {0}</i>', (_fmt(html.escape(str(e)), '', -1),)), parse_mode=ParseMode.HTML)


@dp.message(Command("unbd", "унбд"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower().split()[0] in ["/unbd", "unbd", "унбд", "/унбд"]))
@_localized
async def cmd_unbd(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    text = (message.text or "").strip()
    parts = text.split()

    target_user_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        target_name = get_user_display_name(message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name) or f"ID:{target_user_id}"
    elif len(parts) > 1:
        target_arg = parts[1]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.reply(_lf('<i>Пользователь @{0} не найден в базе данных!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = get_user_display_name(target_user_id)
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.reply(_lf('<i>Пользователь {0} не найден в базе данных!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        await message.reply(_l('<i>Использование: /unbd &lt;id/@username&gt; или ответом на сообщение пользователя</i>'), parse_mode=ParseMode.HTML)
        return

    cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (target_user_id,))
    if not cursor.fetchone():
        cursor.execute("SELECT 1 FROM game_stats WHERE user_id = ?", (target_user_id,))
        if not cursor.fetchone():
            await message.reply(_lf('<i>Пользователь с ID {0} не найден в базе данных!</i>', (_fmt(target_user_id, '', -1),)), parse_mode=ParseMode.HTML)
            return

    try:
        cursor.execute("DELETE FROM users WHERE user_id = ?", (target_user_id,))
        cursor.execute("DELETE FROM game_stats WHERE user_id = ?", (target_user_id,))
        cursor.execute("DELETE FROM bans WHERE user_id = ?", (target_user_id,))
        cursor.execute("DELETE FROM top_bans WHERE user_id = ?", (target_user_id,))
        cursor.execute("DELETE FROM transfer_bans WHERE user_id = ?", (target_user_id,))
        cursor.execute("DELETE FROM promo_activations WHERE user_id = ?", (target_user_id,))
        cursor.execute("DELETE FROM games_history WHERE user_id = ?", (target_user_id,))
        cursor.execute("DELETE FROM chat_members WHERE user_id = ?", (target_user_id,))
        cursor.execute("DELETE FROM active_games_state WHERE owner_id = ?", (target_user_id,))
        conn.commit()

        for membership in tuple(_known_chat_members):
            if membership[0] == target_user_id:
                _known_chat_members.pop(membership, None)
        _known_usernames.pop(target_user_id, None)
        _known_names.pop(target_user_id, None)
        _identity_cache.pop(target_user_id, None)
        _banned_users_cache.pop(target_user_id, None)
        _top_banned_users.discard(target_user_id)
        _transfer_banned_users.discard(target_user_id)
        active_games.pop(target_user_id, None)

        clean_name = html.escape(get_user_display_name(target_user_id, target_name))
        _admin_log(
            message.from_user,
            "delete_user",
            target_id=target_user_id,
            target_name=target_name,
        )
        await message.reply(
            _lf('<i>✅ Successfully! Пользователь <b>{0}</b> (<code>{1}</code>) полностью удален из базы данных!</i>', (_fmt(clean_name, '', -1), _fmt(target_user_id, '', -1))),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.reply(_lf('<i>Ошибка при удалении пользователя: {0}</i>', (_fmt(html.escape(str(e)), '', -1),)), parse_mode=ParseMode.HTML)


def clean_promo_string(s):
    if not s:
        return ""
    s = s.strip()
    for q in ['"', "'", "«", "»", "“", "”", "`"]:
        s = s.strip(q)
    return s.strip()


@dp.message(Command("cprom"))
@_localized
async def cmd_cprom(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer(_l('<i>Использование: /cprom [название] [награда] [активации]\nПример: <code>/cprom Новый год 100кк 10</code> или <code>/cprom test 50кк</code></i>'), parse_mode=ParseMode.HTML)
        return

    activations = 1
    reward = None
    promo_name = ""

    if len(args) >= 4 and args[-1].isdigit():
        activations = int(args[-1])
        if activations <= 0:
            await message.answer(_l('<i>Количество активаций должно быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return
        reward = parse_amount(args[-2])
        if reward is None or reward <= 0:
            await message.answer(_l('<i>Неверная сумма награды! Пример: 100кк, 50000</i>'), parse_mode=ParseMode.HTML)
            return
        promo_name = clean_promo_string(" ".join(args[1:-2]))
    else:
        reward = parse_amount(args[-1])
        if reward is None or reward <= 0:
            await message.answer(_l('<i>Неверная сумма награды! Пример: 100кк, 50000</i>'), parse_mode=ParseMode.HTML)
            return
        promo_name = clean_promo_string(" ".join(args[1:-1]))
        activations = 1

    if not promo_name:
        await message.answer(_l('<i>Укажите название промокода!</i>'), parse_mode=ParseMode.HTML)
        return

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        cursor.execute('''
            INSERT INTO promo_codes (code, reward, total_activations, remaining_activations, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (code) DO UPDATE SET
                reward = EXCLUDED.reward,
                total_activations = EXCLUDED.total_activations,
                remaining_activations = EXCLUDED.remaining_activations,
                created_at = EXCLUDED.created_at
        ''', (promo_name, reward, activations, activations, now_str))
        conn.commit()
        _admin_log(
            message.from_user,
            "create_promo",
            details={"code": promo_name, "amount": format_number(reward), "currency": "mCoin", "activations": activations},
        )

        await message.reply(
            _lf('<i>✅ Промокод «<b>{0}</b>» успешно создан!\n💰 Награда: <b>{1}</b> mCoin\n👥 Количество активаций: <b>{2}</b></i>', (_fmt(html.escape(promo_name), '', -1), _fmt(format_number(reward), '', -1), _fmt(activations, '', -1))),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.reply(_lf('<i>Ошибка базы данных: {0}</i>', (_fmt(html.escape(str(e)), '', -1),)), parse_mode=ParseMode.HTML)


@dp.message(Command("listprom"))
@_localized
async def cmd_listprom(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        cursor.execute("DELETE FROM promo_codes WHERE remaining_activations <= 0")
        conn.commit()

        cursor.execute("SELECT code, reward, remaining_activations, total_activations FROM promo_codes ORDER BY created_at DESC")
        rows = cursor.fetchall()

        if not rows:
            await message.answer(_l('<i>Список доступных промокодов пуст.</i>'), parse_mode=ParseMode.HTML)
            return

        lines = [_l('<b>📋 Доступные промокоды:</b>\n')]
        for code, reward, rem, total in rows:
            lines.append(_lf('• «<code>{0}</code>» — {1} mCoin (Осталось: {2}/{3})', (_fmt(html.escape(code), '', -1), _fmt(format_number(reward), '', -1), _fmt(rem, '', -1), _fmt(total, '', -1))))

        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.answer(_lf('<i>Ошибка базы данных: {0}</i>', (_fmt(html.escape(str(e)), '', -1),)), parse_mode=ParseMode.HTML)


@dp.message(Command("em"))
@_localized
async def cmd_em(message: types.Message):
    user_id = message.from_user.id

    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    status_msg = await message.answer(_lf('⏳ Проверяю {0} emoji-id...', (_fmt(len(EMOJI_IDS_TO_CHECK), '', -1),)))

    good_ids = []
    bad_ids = []

    for emoji_id in EMOJI_IDS_TO_CHECK:
        try:
            probe = await message.answer(
                f'<tg-emoji emoji-id="{emoji_id}">✅</tg-emoji>',
                parse_mode=ParseMode.HTML
            )
            good_ids.append(emoji_id)
            try:
                await probe.delete()
            except Exception:
                pass
        except TelegramBadRequest:
            bad_ids.append(emoji_id)
        await asyncio.sleep(0.05)

    report = _lf('✅ Рабочих: {0}/{1}\n', (_fmt(len(good_ids), '', -1), _fmt(len(EMOJI_IDS_TO_CHECK), '', -1)))
    if bad_ids:
        report += _l('<i>Битые ID (DOCUMENT_INVALID):\n</i>') + "\n".join(f"<code>{i}</code>" for i in bad_ids)
    else:
        report += _l('<i>Битых не найдено.</i>')

    await status_msg.edit_text(report, parse_mode=ParseMode.HTML)


@dp.message(Command("event"))
@_localized
async def cmd_event(message: types.Message):
    user_id = message.from_user.id

    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    global event_active, event_started, event_number, event_prize, event_participants, event_message_id, event_chat_id, event_timer_task, event_timeout_task, event_min_num, event_max_num

    if event_active:
        await message.answer(_l('<i>Ивент уже запущен!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()

    if len(args) < 5:
        await message.answer(_l('<i>Использование: /event [min] [max] [приз] [участники]\nПример: /event 1 250 250kk 5</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        min_num = int(args[1])
        max_num = int(args[2])
        if min_num < 1:
            await message.answer(_l('<i>Минимальное число должно быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return
        if max_num <= min_num:
            await message.answer(_l('<i>Максимальное число должно быть больше минимального!</i>'), parse_mode=ParseMode.HTML)
            return
        if max_num > 1000000:
            await message.answer(_l('<i>Максимальное число не может превышать 1,000,000!</i>'), parse_mode=ParseMode.HTML)
            return
        prize = parse_amount(args[3])
        if prize is None or prize <= 0:
            await message.answer(_l('<i>Неверная сумма приза!</i>'), parse_mode=ParseMode.HTML)
            return
        max_participants = int(args[4])
        if max_participants < 1:
            await message.answer(_l('<i>Должен быть хотя бы 1 участник!</i>'), parse_mode=ParseMode.HTML)
            return
    except ValueError:
        await message.answer(_l('<i>Неверный формат! Пример: /event 1 250 250kk 5</i>'), parse_mode=ParseMode.HTML)
        return

    event_min_num = min_num
    event_max_num = max_num
    event_number = random.randint(min_num, max_num)
    event_prize = prize
    event_participants = {}
    event_active = True
    event_started = False
    event_chat_id = message.chat.id

    text = (
        _lf('<b><tg-emoji emoji-id="5467671759274661866">🤩</tg-emoji> Ивент на {0} начался!</b>\n\n<tg-emoji emoji-id="5372926953978341366">👥</tg-emoji> Участники: пока нет\n<tg-emoji emoji-id="5386367538735104399">⌛</tg-emoji> До начала розыгрыша 60 сек.\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Для участия нажми кнопку ниже.', (_fmt(format_number(prize), '', -1),))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Участвовать'),
                    callback_data="event_join",
                    style="primary",
                    icon_custom_emoji_id="5920090136627908485"
                )
            ]
        ]
    )

    msg = await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    event_message_id = msg.message_id
    _admin_log(
        message.from_user,
        "event",
        details={"amount": format_number(prize), "currency": "mCoin", "users": max_participants, "value": f"{min_num}-{max_num}"},
    )

    await bot.pin_chat_message(chat_id=message.chat.id, message_id=msg.message_id)

    if event_timer_task:
        event_timer_task.cancel()

    if event_timeout_task:
        event_timeout_task.cancel()

    event_timer_task = asyncio.create_task(event_timer(message.chat.id, msg.message_id))


async def _event_participant_links():
    links = []
    for uid in tuple(event_participants):
        name = get_user_display_name(uid)
        if name == f"ID:{uid}":
            try:
                user = await bot.get_chat(uid)
                name = get_user_display_name(uid, user.first_name) or _l('Пользователь')
                if user.first_name:
                    _cache_put(_known_names, uid, user.first_name)
            except Exception:
                name = _l('Пользователь')
        links.append(f'<a href="tg://user?id={uid}">{html.escape(name)}</a>')
    return links


@_localized
async def event_timer(chat_id, message_id):
    global event_active, event_started, event_participants, event_timeout_task

    for i in range(60, -1, -1):
        if not event_active:
            return

        if i == 0:
            if len(event_participants) < 1:
                await bot.edit_message_text(
                    _l('<i>Ивент отменен! Недостаточно участников.</i>'),
                    chat_id=chat_id,
                    message_id=message_id
                )
                await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
                event_active = False
                return

            event_started = True

            participants_list = []
            participants_list = await _event_participant_links()

            text = (
                _lf('<tg-emoji emoji-id="5852868430952144622">🔥</tg-emoji> Конкурс начался!\n\n<tg-emoji emoji-id="5372926953978341366">👥</tg-emoji> Участники: {0}\n\nУ каждого участника будет по 3 попытки чтобы отгадать нужное число!\nЧтобы испытать свою удачи напиши <code>/i число</code>\n\n⏰ У вас есть 10 минут!', (_fmt(', '.join(participants_list), '', -1),))
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=_l('Участвовать'),
                            callback_data="event_join",
                            style="primary",
                            icon_custom_emoji_id="5920090136627908485"
                        )
                    ]
                ]
            )

            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )

            event_timeout_task = asyncio.create_task(event_timeout(chat_id, message_id))
            return

        participants_count = len(event_participants)
        try:
            await bot.edit_message_text(
                _lf('<b><tg-emoji emoji-id="5467671759274661866">🤩</tg-emoji> Ивент на {0} начался!</b>\n\n<tg-emoji emoji-id="5372926953978341366">👥</tg-emoji> Участники: {1} чел.\n<tg-emoji emoji-id="5386367538735104399">⌛</tg-emoji> До начала розыгрыша {2} сек.\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Для участия нажми кнопку ниже.', (_fmt(format_number(event_prize), '', -1), _fmt(participants_count, '', -1), _fmt(i, '', -1))),
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=_l('Участвовать'),
                                callback_data="event_join",
                                style="primary",
                                icon_custom_emoji_id="5920090136627908485"
                            )
                        ]
                    ]
                )
            )
        except Exception:
            pass

        await asyncio.sleep(1)


@_localized
async def event_timeout(chat_id, message_id):
    global event_active, event_started, event_number, event_participants

    await asyncio.sleep(600)

    if not event_active or not event_started:
        return

    event_active = False
    event_started = False

    await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)

    participants_list = []
    participants_list = await _event_participant_links()

    text = (
        _lf('⏰ <b>Время вышло!</b>\n\nЗагаданное число было: <code>{0}</code>\n\n<tg-emoji emoji-id="5372926953978341366">👥</tg-emoji> Участники: {1}\n\n<i>Никто не угадал число. Ивент завершен!</i>', (_fmt(event_number, '', -1), _fmt(', '.join(participants_list), '', -1)))
    )

    await bot.edit_message_text(
        text=text,
        chat_id=chat_id,
        message_id=message_id,
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(_inline_filter(lambda c: c.data == "event_join"))
@_localized
async def process_event_join(callback: types.CallbackQuery):
    global event_active, event_started, event_participants

    if not event_active:
        await callback.answer(_l('Ивент не активен!'), show_alert=True)
        return

    if event_started:
        await callback.answer(_l('Розыгрыш уже начался!'), show_alert=True)
        return

    user_id = callback.from_user.id

    if user_id in event_participants:
        await callback.answer(_l('Вы уже участвуете в розыгрыше!'), show_alert=True)
        return

    event_participants[user_id] = 3
    await callback.answer(_l('✅ Вы стали участником розыгрыша!'))

    participants_list = []
    participants_list = await _event_participant_links()

    try:
        await callback.message.edit_text(
            _lf('<b><tg-emoji emoji-id="5467671759274661866">🤩</tg-emoji> Ивент на {0} начался!</b>\n\n<tg-emoji emoji-id="5372926953978341366">👥</tg-emoji> Участники: {1}\n<tg-emoji emoji-id="5386367538735104399">⌛</tg-emoji> До начала розыгрыша ... сек.\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Для участия нажми кнопку ниже.', (_fmt(format_number(event_prize), '', -1), _fmt(', '.join(participants_list), '', -1))),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=_l('Участвовать'),
                            callback_data="event_join",
                            style="primary",
                            icon_custom_emoji_id="5920090136627908485"
                        )
                    ]
                ]
            )
        )
    except Exception:
        pass


@dp.message(_inline_filter(lambda message: message.text and message.text.startswith("/i ")))
@_localized
async def cmd_i(message: types.Message):
    global event_active, event_started, event_number, event_prize, event_participants, event_min_num, event_max_num

    if not event_active or not event_started:
        await message.answer(_l('<i>Конкурс окончен. Ожидайте новый.</i>'), parse_mode=ParseMode.HTML)
        return

    user_id = message.from_user.id

    if user_id not in event_participants:
        await message.delete()
        return

    if event_participants[user_id] <= 0:
        await message.reply(_l('<i>У вас закончились попытки!</i>'), parse_mode=ParseMode.HTML)
        await message.delete()
        return

    try:
        guess = int(message.text.split()[1])
    except (ValueError, IndexError):
        await message.reply(_lf('<i>Введите число от {0} до {1}! Пример: /i 50</i>', (_fmt(event_min_num, '', -1), _fmt(event_max_num, '', -1))), parse_mode=ParseMode.HTML)
        await message.delete()
        return

    if guess < event_min_num or guess > event_max_num:
        await message.reply(_lf('<i>Число должно быть от {0} до {1}!</i>', (_fmt(event_min_num, '', -1), _fmt(event_max_num, '', -1))), parse_mode=ParseMode.HTML)
        await message.delete()
        return

    event_participants[user_id] -= 1

    if guess == event_number:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + event_prize)

        await message.reply(
            _lf('<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji> <a href="tg://user?id={0}">{1}</a> <b>угадал загаданное число и получил {2} mCoin!\nЗагаданное число было: <code>{3}</code></b>', (_fmt(user_id, '', -1), _fmt(html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок')), '', -1), _fmt(format_number(event_prize), '', -1), _fmt(event_number, '', -1))),
            parse_mode=ParseMode.HTML
        )

        await bot.unpin_chat_message(chat_id=message.chat.id, message_id=event_message_id)
        event_active = False

        results_text = _l('📊 Результаты:\n')
        for uid, attempts in event_participants.items():
            try:
                user = await bot.get_chat(uid)
                name = get_user_display_name(user.id, user.first_name)
            except Exception:
                name = _l('Пользователь')
            clean_p_name = html.escape(str(name))
            results_text += _lf('<a href="tg://user?id={0}">{1}</a>: {2} попыток\n', (_fmt(uid, '', -1), _fmt(clean_p_name, '', -1), _fmt(3 - attempts, '', -1)))

        await message.answer(
            results_text,
            parse_mode=ParseMode.HTML
        )
        return

    if event_participants[user_id] == 0:
        await message.reply(
            _lf('<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji> <b>Вы не отгадали число!</b>\nВы истратили все попытки!', ()),
            parse_mode=ParseMode.HTML
        )
        await message.delete()
        return

    await message.reply(
        _lf('<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji> <b>Вы не отгадали число!</b>\nОставшиеся попытки: <code>{0}</code>', (_fmt(event_participants[user_id], '', -1),)),
        parse_mode=ParseMode.HTML
    )
    await message.delete()


@dp.message(Command("top"))
@dp.message(_inline_filter(lambda message: message.text and message.text.lower() in ["топ", "топ игроков", "мировой топ"]))
@_localized
async def cmd_top(message: types.Message):
    await show_top(message)


@dp.message(Command("top_chat", "topchat"))
@dp.message(_inline_filter(lambda message: message.text and message.text.lower() in ["топ чата", "топ ч", "топ чат", "топ беседы", "топбеседы"]))
@_localized
async def cmd_top_chat(message: types.Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer(_l('<i>Эта команда работает только в беседах!</i>'), parse_mode=ParseMode.HTML)
        return
    add_chat_member(message.from_user.id, message.chat.id)
    await show_top(message, message.chat.id)


@_localized
async def show_records(message: types.Message):
    async def get_plain_user_name(uid: int):
        settings = get_user_settings(uid)
        raw_name, _ = await _get_top_identity(uid, settings)
        return html.escape(str(raw_name))

    try:
        cursor.execute('''
            SELECT user_id, max_balance FROM users 
            WHERE user_id NOT IN (SELECT user_id FROM top_bans)
            ORDER BY max_balance DESC LIMIT 1
        ''')
        max_bal_row = cursor.fetchone()

        cursor.execute('''
            SELECT user_id, games FROM users 
            WHERE user_id NOT IN (SELECT user_id FROM top_bans)
            ORDER BY games DESC LIMIT 1
        ''')
        max_games_row = cursor.fetchone()

        cursor.execute('''
            SELECT user_id, lost FROM users 
            WHERE user_id NOT IN (SELECT user_id FROM top_bans)
            ORDER BY lost DESC LIMIT 1
        ''')
        max_lost_row = cursor.fetchone()
    except Exception:
        max_bal_row = None
        max_games_row = None
        max_lost_row = None

    if max_bal_row and max_bal_row[1] is not None:
        bal_user_name = await get_plain_user_name(max_bal_row[0])
        bal_text = f'— {bal_user_name} {format_number(max_bal_row[1])} m¢'
    else:
        bal_text = _l('— Нет данных')

    if max_games_row and max_games_row[1] is not None:
        games_user_name = await get_plain_user_name(max_games_row[0])
        games_text = _lf('— {0} сыграно {1} игр.', (_fmt(games_user_name, '', -1), _fmt(format_number(max_games_row[1]), '', -1)))
    else:
        games_text = _l('— сыграно 0 игр.')

    if max_lost_row and max_lost_row[1] is not None:
        lost_user_name = await get_plain_user_name(max_lost_row[0])
        lost_text = _lf('— {0} проиграно {1} m¢', (_fmt(lost_user_name, '', -1), _fmt(format_number(max_lost_row[1]), '', -1)))
    else:
        lost_text = _l('— проиграно 0 m¢')

    text = (
        _lf('<tg-emoji emoji-id="5767161061480340249">👑</tg-emoji> <b>Рекорды бота</b>\n\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Самый большой баланс:\n{0}\n\n<tg-emoji emoji-id="5309815458990433715">🎮</tg-emoji> Игроман бота\n{1}\n\n<tg-emoji emoji-id="5442983582882601962">🗿</tg-emoji> «Везунчик» бота\n{2}', (_fmt(bal_text, '', -1), _fmt(games_text, '', -1), _fmt(lost_text, '', -1)))
    )

    await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@dp.message(Command("records", "record", "рекорды", "рекорд"))
@dp.message(_inline_filter(lambda message: message.text and message.text.lower().strip() in [
    "рекорды", "рекорд", "топ рекорды", "топ рекордов", "топ рекорд", "records", "/records", "/рекорды", "records_top"
]))
@_localized
async def cmd_records(message: types.Message):
    await show_records(message)


@dp.message(Command("game", "games"))
@dp.message(_inline_filter(lambda message: message.text and message.text.lower() in ["игры", "игра", "каталог"]))
@_localized
async def cmd_game(message: types.Message):
    is_group = message.chat.type in ["group", "supergroup"]
    await show_catalog(message, message.from_user.id, get_user_display_name(message.from_user.id, message.from_user.first_name), message.chat.id, is_group)



@dp.message(Command("mines"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(мины|mines)\s*', message.text, re.IGNORECASE)))
@_localized
async def cmd_mines(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_mines_info(message, user_id)
        return

    unplayed = get_active_unplayed_games(user_id)
    if unplayed:
        await message.answer(_l('<i>У вас уже есть игра! Закончите или доиграйте активную игру.</i>'), parse_mode=ParseMode.HTML)
        return

    args = parts[1].strip().split()
    user_data = get_user(user_id)

    try:
        if len(args) == 1:
            bet = resolve_bet_amount(args[0], user_data["balance"])
            if bet is None:
                await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
                return
            mine_count = 1
        elif len(args) >= 2:
            bet = resolve_bet_amount(args[0], user_data["balance"])
            if bet is None:
                await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
                return
            mine_count = int(args[1])
            if mine_count < 1 or mine_count > 6:
                await message.answer(_l('<i>Количество мин должно быть от 1 до 6!</i>'), parse_mode=ParseMode.HTML)
                return
        else:
            await show_mines_info(message, user_id)
            return

        if bet < 1:
            if user_data["balance"] < 1:
                await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
            else:
                await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return

        if bet > 250000000 and not is_admin_unlimited_bet(user_id):
            await message.answer(_l('<i>Максимальная ставка: 250kk m¢!</i>'), parse_mode=ParseMode.HTML)
            return

        if user_data["balance"] < bet:
            await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
            return

        await start_mines_game_from_command(message, user_id, chat_id, bet, mine_count)

    except ValueError:
        await show_mines_info(message, user_id)



@dp.message(Command("tower"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(башня|tower)\s*', message.text, re.IGNORECASE)))
@_localized
async def cmd_tower(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_tower_info(message, user_id)
        return

    unplayed = get_active_unplayed_games(user_id)
    if unplayed:
        await message.answer(_l('<i>У вас уже есть игра! Закончите или доиграйте активную игру.</i>'), parse_mode=ParseMode.HTML)
        return

    args = parts[1].strip().split()
    user_data = get_user(user_id)

    try:
        if len(args) == 1:
            bet = resolve_bet_amount(args[0], user_data["balance"])
            if bet is None:
                await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
                return
            mine_count = 1
        elif len(args) >= 2:
            bet = resolve_bet_amount(args[0], user_data["balance"])
            if bet is None:
                await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
                return
            mine_count = int(args[1])
            if mine_count < 1 or mine_count > 4:
                await message.answer(_l('<i>Количество мин должно быть от 1 до 4!</i>'), parse_mode=ParseMode.HTML)
                return
        else:
            await show_tower_info(message, user_id)
            return

        if bet < 1:
            if user_data["balance"] < 1:
                await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
            else:
                await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return

        if bet > 250000000 and not is_admin_unlimited_bet(user_id):
            await message.answer(_l('<i>Максимальная ставка: 250kk m¢!</i>'), parse_mode=ParseMode.HTML)
            return

        if user_data["balance"] < bet:
            await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
            return

        await start_tower_game_from_command(message, user_id, chat_id, bet, mine_count)

    except ValueError:
        await show_tower_info(message, user_id)



@dp.message(Command("qwak", "квак", "frog"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(квак|qwak|frog|лягушка)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_qwak(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_qwak_info(message, user_id)
        return

    unplayed = get_active_unplayed_games(user_id)
    if unplayed:
        await message.answer(_l('<i>У вас уже есть игра! Закончите или доиграйте активную игру.</i>'), parse_mode=ParseMode.HTML)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_qwak_info(message, user_id)
        return
    bet_str = tokens[0]
    user_data = get_user(user_id)

    try:
        bet = resolve_bet_amount(bet_str, user_data["balance"])
        if bet is None:
            await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
            return

        if bet < 1:
            if user_data["balance"] < 1:
                await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
            else:
                await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return

        if bet > 300000000 and not is_admin_unlimited_bet(user_id):
            await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
            return

        if user_data["balance"] < bet:
            await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
            return

        await start_qwak_game_from_command(message, user_id, chat_id, bet)

    except ValueError:
        await show_qwak_info(message, user_id)



@dp.message(Command("diamond", "diamonds"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(алмазы|алмаз|diamond|diamonds)\s*', message.text, re.IGNORECASE)))
@_localized
async def cmd_diamonds(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_diamonds_info(message, user_id)
        return

    unplayed = get_active_unplayed_games(user_id)
    if unplayed:
        await message.answer(_l('<i>У вас уже есть игра! Закончите или доиграйте активную игру.</i>'), parse_mode=ParseMode.HTML)
        return

    args = parts[1].strip().split()
    user_data = get_user(user_id)

    try:
        if len(args) == 1:
            bet = resolve_bet_amount(args[0], user_data["balance"])
            if bet is None:
                await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
                return
            mine_count = 1
        elif len(args) >= 2:
            bet = resolve_bet_amount(args[0], user_data["balance"])
            if bet is None:
                await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
                return
            mine_count = int(args[1])
            if mine_count < 1 or mine_count > 2:
                await message.answer(_l('<i>Количество мин должно быть 1 или 2!</i>'), parse_mode=ParseMode.HTML)
                return
        else:
            await show_diamonds_info(message, user_id)
            return

        if bet < 1:
            if user_data["balance"] < 1:
                await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
            else:
                await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return

        if bet > 250000000 and not is_admin_unlimited_bet(user_id):
            await message.answer(_l('<i>Максимальная ставка: 250kk m¢!</i>'), parse_mode=ParseMode.HTML)
            return

        if user_data["balance"] < bet:
            await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
            return

        await start_diamonds_game_from_command(message, user_id, chat_id, bet, mine_count)

    except ValueError:
        await show_diamonds_info(message, user_id)



@_localized
async def show_gold_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Золото — это игра, в которой необходимо угадать, где спрятано золото. Вам нужно открывать по одной ячейке с золотом на каждом из 12 уровней.\n📊 Лимиты:\nRTP: ~100%\nМакс. множитель: х4096\nМакс. ставка: 200kk m¢\nМакс. выигрыш: 1kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>💰 /gold [ставка]</u></b>\n\nПример: <code>/gold 100</code>\nПример: <code>золото 100</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_modes",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@dp.message(Command("gold", "золото", "голд"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(золото|gold|голд)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_gold(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_gold_info(message, user_id)
        return

    unplayed = get_active_unplayed_games(user_id)
    if unplayed:
        await message.answer(_l('<i>У вас уже есть игра! Закончите или доиграйте активную игру.</i>'), parse_mode=ParseMode.HTML)
        return

    bet_str = parts[1].strip()
    user_data = get_user(user_id)

    try:
        bet = resolve_bet_amount(bet_str, user_data["balance"])
        if bet is None:
            await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
            return

        if bet < 1:
            if user_data["balance"] < 1:
                await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
            else:
                await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return

        if bet > 200000000 and not is_admin_unlimited_bet(user_id):
            await message.answer(_l('<i>Максимальная ставка: 200kk m¢!</i>'), parse_mode=ParseMode.HTML)
            return

        if user_data["balance"] < bet:
            await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
            return

        await start_gold_game_from_command(message, user_id, chat_id, bet)

    except ValueError:
        await show_gold_info(message, user_id)



@dp.message(Command("21", "очко", "ochko", "twentyone"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(21|очко|ochko)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_twentyone(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_twentyone_info(message, user_id)
        return

    unplayed = get_active_unplayed_games(user_id)
    if unplayed:
        await message.answer(_l('<i>У вас уже есть игра! Закончите или доиграйте активную игру.</i>'), parse_mode=ParseMode.HTML)
        return

    bet_str = parts[1].strip()
    user_data = get_user(user_id)

    try:
        bet = resolve_bet_amount(bet_str, user_data["balance"])
        if bet is None:
            await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, вб, пол</i>'), parse_mode=ParseMode.HTML)
            return

        if bet < 1:
            if user_data["balance"] < 1:
                await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
            else:
                await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return

        if bet > 500000000 and not is_admin_unlimited_bet(user_id):
            await message.answer(_l('<i>Максимальная ставка: 500kk m¢!</i>'), parse_mode=ParseMode.HTML)
            return

        if user_data["balance"] < bet:
            await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
            return

        await start_twentyone_game_from_command(message, user_id, chat_id, bet)

    except ValueError:
        await show_twentyone_info(message, user_id)



CRASH_STICKER_ID = "CAACAgIAAxkBAAERvEdqhKGsSq0k-jQQ4fTpDTbyWVntowACGoAAAq1smEp3pQH6UfFOqz0E"


@_localized
async def process_crash_round(message: types.Message, user_id: int, bet: int, target_mult: float, user_first_name: str = None):
    sticker_msg = None
    try:
        sticker_msg = await message.answer_sticker(CRASH_STICKER_ID)
    except Exception:
        pass

    await asyncio.sleep(2)

    if sticker_msg:
        try:
            await sticker_msg.delete()
        except Exception:
            pass

    r = secrets.SystemRandom().random()
    if r >= 0.97:
        crash_point = 1.00
    else:
        crash_point = 0.97 / (1.0 - r)

    if DEMO_GAME_CONTEXT.get() or is_demo_user(user_id):
        crash_point = max(1.0, float(target_mult))
    crash_point = round(crash_point, 2)
    if crash_point < 1.00:
        crash_point = 1.00
    elif crash_point > 100000.00:
        crash_point = 100000.00

    if crash_point == int(crash_point):
        crash_point_str = f"{int(crash_point)}"
    else:
        crash_point_str = f"{crash_point:.2f}".rstrip('0').rstrip('.')

    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))

    current_data = get_user(user_id)

    if DEMO_GAME_CONTEXT.get() or is_demo_user(user_id) or target_mult <= crash_point:
        win_amount = int(bet * target_mult)
        if win_amount > 2000000000 and not is_admin_unlimited_bet(user_id):
            win_amount = 2000000000
        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "crash", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<blockquote> <tg-emoji emoji-id="5283080528818360566">🚀</tg-emoji>Ракета упала на x<b>{1}</b><tg-emoji emoji-id="5244837092042750681">📈</tg-emoji>\n\n<tg-emoji emoji-id="5427009714745517609">✅</tg-emoji> Ты <b>выиграл! Твой выигрыш составил <code>{2}</code> m¢</b> </blockquote>', (_fmt(user_link, '', -1), _fmt(crash_point_str, '', -1), _fmt(format_number(win_amount), '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "crash", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<blockquote> <tg-emoji emoji-id="5283080528818360566">🚀</tg-emoji>Ракета упала на x<b>{1}</b><tg-emoji emoji-id="5246762912428603768">📉</tg-emoji>\n\n<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji> Ты <b>проиграл <code>{2}</code> m¢</b> </blockquote>', (_fmt(user_link, '', -1), _fmt(crash_point_str, '', -1), _fmt(format_number(bet), '', -1)))
        )

    await message.answer(
        text=response_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@dp.message(Command("crash", "краш"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(краш|crash|кр)\s*', message.text, re.IGNORECASE)))
@_localized
async def cmd_crash(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_crash_info(message, user_id)
        return

    args = parts[1].strip().split()

    if len(args) < 2:
        await show_crash_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(args[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 200000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 200kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    target_mult = parse_multiplier(args[1])
    if target_mult is None or target_mult < 1.01 or target_mult > 100000:
        await message.answer(_l('<i>Множитель должен быть от x1.01 до x100k! Пример: 1.1, 4, 100к</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    asyncio.create_task(process_crash_round(message, user_id, bet, target_mult, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name)))



@_localized
async def process_slots_outcome(message: types.Message, dice_msg: types.Message, user_id: int, bet: int, user_first_name: str = None):
    await asyncio.sleep(2.7)

    val = (dice_msg.dice.value - 1) if (dice_msg and dice_msg.dice) else 0
    reel1 = val & 3
    reel2 = (val >> 2) & 3
    reel3 = (val >> 4) & 3

    symbols = {0: "🅱️", 1: "🍒", 2: "🍋", 3: "7️⃣"}
    combo_str = f"{symbols.get(reel1, '❓')}{symbols.get(reel2, '❓')}{symbols.get(reel3, '❓')}"

    is_win = DEMO_GAME_CONTEXT.get() or (reel1 == reel2 == reel3)

    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)

    if is_win:
        win_mult = 15.5
        win_amount = int(bet * win_mult)
        if win_amount > 3000000000 and not is_admin_unlimited_bet(user_id):
            win_amount = 3000000000

        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "slots", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Слоты · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n💰 <b>Выигрыш:</b> х15.5 / {2} m¢\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Выпало: {3} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(format_number(win_amount), '', -1), _fmt(combo_str, '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "slots", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5276032951342088188">💥</tg-emoji><b>Слоты · Проигрыш!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Выпало: {2} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(combo_str, '', -1)))
        )

    await message.answer(
        text=response_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@dp.message(Command("slots", "slot"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(слоты|слот|slots|slot)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_slots(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_slots_info(message, user_id)
        return

    args = parts[1].strip().split()
    if not args:
        await show_slots_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(args[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        dice_msg = await message.answer_dice(emoji="🎰")
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await message.answer(_l('<i>Ошибка запуска слотов! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return

    asyncio.create_task(process_slots_outcome(message, dice_msg, user_id, bet, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name)))



@_localized
def parse_bowling_choice(choice_text: str):
    choice_text = _canonical_choice(choice_text, (('Страйк (6 кеглей)', 'strike'), ('Мимо (0 кеглей)', 'miss'), ('1 кегля', '1'), ('3 кегли', '3'), ('4 кегли', '4'), ('5 кеглей', '5')))
    t = choice_text.lower().strip()
    if t in ["страйк", "strike", "страйк!", "все", "всё", "all", "6", "6 кеглей", "6кеглей"]:
        return 6, _l('Страйк (6 кеглей)')
    elif t in ["мимо", "miss", "промах", "ни одной", "0", "0 кеглей", "0кеглей"]:
        return 1, _l('Мимо (0 кеглей)')
    elif t in ["1", "1 кегля", "1 кеглю", "1 кегли", "1кегля", "1кеглю"]:
        return 2, _l('1 кегля')
    elif t in ["3", "3 кегли", "3 кеглей", "3кегли"]:
        return 3, _l('3 кегли')
    elif t in ["4", "4 кегли", "4 кеглей", "4кегли"]:
        return 4, _l('4 кегли')
    elif t in ["5", "5 кеглей", "5 кегли", "5кеглей"]:
        return 5, _l('5 кеглей')
    elif t in ["2", "2 кегли", "2 кеглей", "2кегли"]:
        return 3, _l('3 кегли')
    return None, None


@_localized
def get_bowling_choice_keyboard(bet: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('1 кегля (х5.8)'), callback_data=f"bwl_{bet}_2", style="primary"),
                InlineKeyboardButton(text=_l('3 кегли (х5.8)'), callback_data=f"bwl_{bet}_3", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('4 кегли (х5.8)'), callback_data=f"bwl_{bet}_4", style="primary"),
                InlineKeyboardButton(text=_l('5 кеглей (х5.8)'), callback_data=f"bwl_{bet}_5", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('Страйк (6 кеглей) (х5.8)'), callback_data=f"bwl_{bet}_6", style="primary"),
                InlineKeyboardButton(text=_l('Мимо (0 кеглей) (х5.8)'), callback_data=f"bwl_{bet}_1", style="primary"),
            ]
        ]
    )


@_localized
async def process_bowling_outcome(message: types.Message, dice_msg: types.Message, user_id: int, bet: int, target_choice_code: int, target_choice_name: str, user_first_name: str = None):
    await asyncio.sleep(2.7)

    val = dice_msg.dice.value if (dice_msg and dice_msg.dice) else 1

    outcome_names = {
        1: _l('Мимо (0 кеглей)'),
        2: _l('1 кегля'),
        3: _l('3 кегли'),
        4: _l('4 кегли'),
        5: _l('5 кеглей'),
        6: _l('Страйк (6 кеглей)')
    }
    outcome_str = outcome_names.get(val, _lf('{0} кеглей', (_fmt(val, '', -1),)))

    is_win = DEMO_GAME_CONTEXT.get() or (val == target_choice_code)

    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)

    if is_win:
        win_mult = 5.8
        win_amount = int(bet * win_mult)
        if win_amount > 1740000000 and not is_admin_unlimited_bet(user_id):
            win_amount = 1740000000

        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "bowling", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Боулинг · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n💰 <b>Выигрыш:</b> х5.8 / {3} m¢\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {4} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(target_choice_name), '', -1), _fmt(format_number(win_amount), '', -1), _fmt(outcome_str, '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "bowling", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji><b> Боулинг · Проигрыш!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {3} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(target_choice_name), '', -1), _fmt(outcome_str, '', -1)))
        )

    try:
        await message.answer(
            text=response_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        pass


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("bwl_")))
@_localized
async def process_bowling_choice_callback(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass
    parts = callback.data.split("_")
    if len(parts) < 3:
        return
    try:
        bet = int(parts[1])
        target_code = int(parts[2])
    except ValueError:
        return

    user_id = callback.from_user.id
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await callback.message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await callback.message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    target_names = {
        1: _l('Мимо (0 кеглей)'),
        2: _l('1 кегля'),
        3: _l('3 кегли'),
        4: _l('4 кегли'),
        5: _l('5 кеглей'),
        6: _l('Страйк (6 кеглей)')
    }
    target_name = target_names.get(target_code, _lf('{0} кеглей', (_fmt(target_code, '', -1),)))

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        dice_msg = await callback.message.answer_dice(emoji="🎳")
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await callback.message.answer(_l('<i>Ошибка запуска боулинга! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return

    asyncio.create_task(process_bowling_outcome(callback.message, dice_msg, user_id, bet, target_code, target_name, user_first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name)))


@dp.message(Command("bowling", "боулинг", "бо"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(боулинг|bowling|бо)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_bowling(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_bowling_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_bowling_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if len(tokens) >= 2:
        choice_raw = " ".join(tokens[1:])
        target_code, target_name = parse_bowling_choice(choice_raw)
        if target_code is not None:
            if not update_user(user_id, balance=user_data["balance"] - bet):
                await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
                return
            try:
                dice_msg = await message.answer_dice(emoji="🎳")
            except Exception:
                user_data = get_user(user_id)
                update_user(user_id, balance=user_data["balance"] + bet)
                await message.answer(_l('<i>Ошибка запуска боулинга! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
                return
            asyncio.create_task(process_bowling_outcome(message, dice_msg, user_id, bet, target_code, target_name, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name)))
            return

    user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
    prompt_text = (
        _lf('{0}\n🎳 <b>Боулинг · Выберите итог:</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n\n<blockquote><i>Укажите, сколько кеглей собьет бросок:</i></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )
    await message.answer(
        text=prompt_text,
        reply_markup=get_bowling_choice_keyboard(bet),
        parse_mode=ParseMode.HTML
    )



DICE_CHOICES = {
    "n1": ("1", 5.8),
    "n2": ("2", 5.8),
    "n3": ("3", 5.8),
    "n4": ("4", 5.8),
    "n5": ("5", 5.8),
    "n6": ("6", 5.8),
    "gt3": ("Больше 3-х", 1.97),
    "lt3": ("Меньше 3-х", 2.32),
    "eq3": ("Равно 3", 5.8),
    "even": ("Чёт", 2.23),
    "odd": ("Нечёт", 2.23),
}


def normalize_dice_choice_text(choice_text: str) -> str:
    return re.sub(r"\s+", " ", (choice_text or "").lower().replace("ё", "е").replace("-", " ").strip())


@_localized
def parse_dice_choice(choice_text: str):
    choice_text = _canonical_choice(choice_text, (('Равно 3', '=3'), ('Больше 3-х', '>3'), ('Меньше 3-х', '<3'), ('Чёт', 'even'), ('Нечёт', 'odd')))
    t = normalize_dice_choice_text(choice_text)
    compact = t.replace(" ", "")

    if compact in {"1", "один", "единица", "число1", "на1"}:
        return "n1", "1", 5.8
    if compact in {"2", "два", "двойка", "число2", "на2"}:
        return "n2", "2", 5.8
    if compact in {"3", "три", "тройка", "число3", "на3"}:
        return "n3", "3", 5.8
    if compact in {"4", "четыре", "четверка", "число4", "на4"}:
        return "n4", "4", 5.8
    if compact in {"5", "пять", "пятерка", "число5", "на5"}:
        return "n5", "5", 5.8
    if compact in {"6", "шесть", "шестерка", "число6", "на6"}:
        return "n6", "6", 5.8

    if compact in {"=3", "равно3", "ровно3", "равнотрем", "равнотри", "только3"} or t.startswith("равно") or t.startswith("ровно"):
        return "eq3", _l('Равно 3'), 5.8
    if compact in {">3", "больше3", "больше3х", "больше3x", "большетрех", "большетри", "бол3", "б3"} or t.startswith("больше"):
        return "gt3", _l('Больше 3-х'), 1.97
    if compact in {"<3", "меньше3", "меньше3х", "меньше3x", "меньшетрех", "меньшетри", "менше3", "меншьше3", "м3"} or t.startswith("меньше") or t.startswith("менше") or t.startswith("меншьше"):
        return "lt3", _l('Меньше 3-х'), 2.32
    if compact in {"нечет", "нечетное", "нечетный", "нечетная", "odd", "н", "неч"}:
        return "odd", _l('Нечёт'), 2.23
    if compact in {"чет", "четное", "четный", "четная", "even", "ч"}:
        return "even", _l('Чёт'), 2.23

    return None, None, None


def is_dice_choice_win(choice_code: str, value: int) -> bool:
    if choice_code and choice_code.startswith("n") and choice_code[1:].isdigit():
        return value == int(choice_code[1:])
    if choice_code == "gt3":
        return value > 3
    if choice_code == "lt3":
        return value < 3
    if choice_code == "eq3":
        return value == 3
    if choice_code == "even":
        return value % 2 == 0
    if choice_code == "odd":
        return value % 2 == 1
    return False


@_localized
def get_dice_choice_keyboard(bet: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 x5.8", callback_data=f"dice_{bet}_n1", style="primary"),
                InlineKeyboardButton(text="2 x5.8", callback_data=f"dice_{bet}_n2", style="primary"),
            ],
            [
                InlineKeyboardButton(text="3 x5.8", callback_data=f"dice_{bet}_n3", style="primary"),
                InlineKeyboardButton(text="4 x5.8", callback_data=f"dice_{bet}_n4", style="primary"),
            ],
            [
                InlineKeyboardButton(text="5 x5.8", callback_data=f"dice_{bet}_n5", style="primary"),
                InlineKeyboardButton(text="6 x5.8", callback_data=f"dice_{bet}_n6", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('Больше 3 x1.97'), callback_data=f"dice_{bet}_gt3", style="primary"),
                InlineKeyboardButton(text=_l('Меньше 3 x2.32'), callback_data=f"dice_{bet}_lt3", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('Равно 3 x5.8'), callback_data=f"dice_{bet}_eq3", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('Чёт x2.23'), callback_data=f"dice_{bet}_even", style="primary"),
                InlineKeyboardButton(text=_l('Нечёт x2.23'), callback_data=f"dice_{bet}_odd", style="primary"),
            ]
        ]
    )


@_localized
async def start_dice_game(message: types.Message, user_id: int, bet: int, choice_code: str, choice_name: str, multiplier: float, user_first_name: str = None):
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return False

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return False

    try:
        dice_msg = await message.answer_dice(emoji="🎲")
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await message.answer(_l('<i>Ошибка запуска кубика! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return False

    asyncio.create_task(process_dice_outcome(message, dice_msg, user_id, bet, choice_code, choice_name, multiplier, user_first_name=user_first_name))
    return True


@_localized
async def process_dice_outcome(message: types.Message, dice_msg: types.Message, user_id: int, bet: int, choice_code: str, choice_name: str, multiplier: float, user_first_name: str = None):
    await asyncio.sleep(2.7)

    val = dice_msg.dice.value if (dice_msg and dice_msg.dice) else 1
    outcome_str = _lf('Выпало {0}', (_fmt(val, '', -1),))
    is_win = DEMO_GAME_CONTEXT.get() or is_dice_choice_win(choice_code, val)

    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)

    if is_win:
        win_amount = int(bet * multiplier)
        if win_amount > 1740000000 and not is_admin_unlimited_bet(user_id):
            win_amount = 1740000000

        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "dice", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Кубик · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n💰 <b>Выигрыш:</b> х{3} / {4} m¢\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {5} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(choice_name), '', -1), _fmt(multiplier, f'g', -1), _fmt(format_number(win_amount), '', -1), _fmt(outcome_str, '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "dice", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji><b> Кубик · Проигрыш!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {3} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(choice_name), '', -1), _fmt(outcome_str, '', -1)))
        )

    try:
        await message.answer(
            text=response_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        pass


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("dice_")))
@_localized
async def process_dice_choice_callback(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass

    parts = callback.data.split("_")
    if len(parts) < 3:
        return
    try:
        bet = int(parts[1])
    except ValueError:
        return
    choice_code = parts[2]
    meta = DICE_CHOICES.get(choice_code)
    if not meta:
        return
    choice_name, multiplier = meta

    try:
        await callback.message.delete()
    except Exception:
        pass

    await start_dice_game(callback.message, callback.from_user.id, bet, choice_code, choice_name, multiplier, user_first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name))


@dp.message(Command("dice", "кубик", "куб"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(кубик|dice|куб)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_dice(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)
    if len(parts) == 1:
        await show_dice_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_dice_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if len(tokens) >= 2:
        choice_raw = " ".join(tokens[1:])
        choice_code, choice_name, multiplier = parse_dice_choice(choice_raw)
        if choice_code is not None:
            await start_dice_game(message, user_id, bet, choice_code, choice_name, multiplier, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name))
            return

    user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
    prompt_text = (
        _lf('{0}\n☘️ <b>Кубик · выбери режим!</b>\n<code>·····················</code>\n🎲 <b>Ставка:</b> {1} m¢\n\n<b>Ставка на число x5.8 🎲</b>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )
    await message.answer(
        text=prompt_text,
        reply_markup=get_dice_choice_keyboard(bet),
        parse_mode=ParseMode.HTML
    )



COIN_MULTIPLIER = 1.97
COIN_STICKERS = {
    "tails": "CAACAgIAAxkBAAEHTf9qu3HnfS_vkf6D1I2GUxmjAyb6bwAC_4EAAvBP8EgU_3ladadb9T0E",
    "heads": "CAACAgIAAxkBAAEHTgNqu3ICSiGQ6ZlpVhEvLE0k6kuzYQACynsAAuTt8Uj_xptHkCyoDT0E",
}
COIN_NAMES = {
    "heads": "Орёл",
    "tails": "Решка",
}


@_localized
def parse_coin_choice(choice_text: str):
    choice_text = _canonical_choice(choice_text, (('Орёл', 'heads'), ('Решка', 'tails')))
    t = re.sub(r"\s+", " ", (choice_text or "").lower().replace("ё", "е").strip())
    compact = t.replace(" ", "")
    if compact in {"о", "орел", "орёл", "orel", "heads", "head", "h", "eagle"}:
        return "heads", _l('Орёл'), COIN_MULTIPLIER
    if compact in {"р", "решка", "reshka", "tails", "tail", "t"}:
        return "tails", _l('Решка'), COIN_MULTIPLIER
    return None, None, None


@_localized
def get_coin_choice_keyboard(bet: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('🦅 Орёл - x1.97'), callback_data=f"coinbet_{bet}_heads", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('💎 Решка - x1.97'), callback_data=f"coinbet_{bet}_tails", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('Отменить ❌'), callback_data="coin_cancel", style="danger"),
            ]
        ]
    )


@_localized
async def start_coin_game(message: types.Message, user_id: int, bet: int, choice_code: str, choice_name: str, multiplier: float, user_first_name: str = None):
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return False

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return False

    result_code = "heads" if secrets.randbelow(2) == 0 else "tails"
    sticker_id = COIN_STICKERS[result_code]

    try:
        await bot.send_sticker(chat_id=message.chat.id, sticker=sticker_id)
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await message.answer(_l('<i>Ошибка запуска монетки! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return False

    asyncio.create_task(process_coin_outcome(message, user_id, bet, choice_code, choice_name, multiplier, result_code, user_first_name=user_first_name))
    return True


@_localized
async def process_coin_outcome(message: types.Message, user_id: int, bet: int, choice_code: str, choice_name: str, multiplier: float, result_code: str, user_first_name: str = None):
    await asyncio.sleep(5)

    result_name = COIN_NAMES.get(result_code, _l('Орёл'))
    is_win = DEMO_GAME_CONTEXT.get() or (choice_code == result_code)
    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)

    if is_win:
        win_amount = int(bet * multiplier)
        if win_amount > 1740000000 and not is_admin_unlimited_bet(user_id):
            win_amount = 1740000000

        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "coin", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Монетка · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🪙 <b>Выбрано:</b> {2}\n💰 <b>Выигрыш:</b> х{3} / {4} m¢\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {5} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(choice_name), '', -1), _fmt(multiplier, f'g', -1), _fmt(format_number(win_amount), '', -1), _fmt(_label(result_name), '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "coin", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji><b> Монетка · Проигрыш!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🪙 <b>Выбрано:</b> {2}\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {3} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(choice_name), '', -1), _fmt(_label(result_name), '', -1)))
        )

    try:
        await message.answer(
            text=response_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        pass


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("coinbet_")))
@_localized
async def process_coin_choice_callback(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass

    parts = callback.data.split("_")
    if len(parts) < 3:
        return
    try:
        bet = int(parts[1])
    except ValueError:
        return
    choice_code = parts[2]
    if choice_code not in COIN_NAMES:
        return

    choice_name = COIN_NAMES[choice_code]
    try:
        await callback.message.delete()
    except Exception:
        pass

    await start_coin_game(callback.message, callback.from_user.id, bet, choice_code, choice_name, COIN_MULTIPLIER, user_first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name))


@dp.callback_query(_inline_filter(lambda c: c.data == "coin_cancel"))
@_localized
async def process_coin_cancel(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer(_l('Игра отменена'))


@dp.message(Command("coin", "монета", "монетка"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(монета|монетка|coin)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_coin(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)
    if len(parts) == 1:
        await show_coin_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_coin_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if len(tokens) >= 2:
        choice_raw = " ".join(tokens[1:])
        choice_code, choice_name, multiplier = parse_coin_choice(choice_raw)
        if choice_code is not None:
            await start_coin_game(message, user_id, bet, choice_code, choice_name, multiplier, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name))
            return

    user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
    prompt_text = (
        _lf('{0}\n🪙 <b>Монета • выбери сторону!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )
    await message.answer(
        text=prompt_text,
        reply_markup=get_coin_choice_keyboard(bet),
        parse_mode=ParseMode.HTML
    )



FISHING_OUTCOMES = [
    {
        "code": "fish",
        "name": "Рыба 🐟",
        "multiplier": 2.0,
        "sticker": "CAACAgIAAxkBAAEHUi9qvOJWemjPB2eDvSO5xZKf-Ke0kQACVZkAAo5q-UkND0F9df8D5j0E",
        "note": "🎣 <i>Улов: Рыба 🐟</i>",
    },
    {
        "code": "escaped",
        "name": "Рыба сорвалась",
        "multiplier": 0.0,
        "sticker": "CAACAgIAAxkBAAEHUjFqvOJYuR_grueiKE-H6gtZsAYOwQACaZcAAhz7-UkFt2fJFMGxBz0E",
        "note": "😭 <i>Рыба сорвалась!</i>",
    },
    {
        "code": "can_small",
        "name": "Банка 🥫",
        "multiplier": 0.08,
        "sticker": "CAACAgIAAxkBAAEHUjNqvOJgvyeSPcdAr3g47ciUNi8NDAACapMAAtvC-Enhzo-Vz2DBsz0E",
        "note": "🎣 <i>Улов: Банка 🥫</i>",
    },
    {
        "code": "can_big",
        "name": "Банка 🥫",
        "multiplier": 0.5,
        "sticker": "CAACAgIAAxkBAAEHUjVqvOJkJL2B5T_4rB3loRrUFOeWRwACG5gAAtnW-UmGRTlvWJBZlT0E",
        "note": "🎣 <i>Улов: Банка 🥫</i>",
    },
]


@_localized
async def start_fishing_game(message: types.Message, user_id: int, bet: int, user_first_name: str = None):
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return False

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return False

    outcome = FISHING_OUTCOMES[0] if DEMO_GAME_CONTEXT.get() else secrets.choice(FISHING_OUTCOMES)
    try:
        await bot.send_sticker(chat_id=message.chat.id, sticker=outcome["sticker"])
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await message.answer(_l('<i>Ошибка запуска рыбалки! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return False

    asyncio.create_task(process_fishing_outcome(message, user_id, bet, outcome, user_first_name=user_first_name))
    return True


@_localized
async def process_fishing_outcome(message: types.Message, user_id: int, bet: int, outcome: dict, user_first_name: str = None):
    await asyncio.sleep(3)

    multiplier = float(outcome.get("multiplier", 0))
    win_amount = int(bet * multiplier)
    is_win = DEMO_GAME_CONTEXT.get() or multiplier > 0
    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)

    if is_win:
        update_user(user_id, balance=current_data["balance"] + win_amount, games=current_data["games"] + 1)
        add_game_history(user_id, "fishing", bet, "win", win_amount)
        title = _l('🎣<b>Рыбалка · Победа!</b><tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>')
    else:
        update_user(user_id, games=current_data["games"] + 1, lost=current_data["lost"] + bet)
        add_game_history(user_id, "fishing", bet, "lose", 0)
        title = _l('😔<b>Рыбалка · Проигрыш!</b>')

    result_text = (
        _lf('{0}\n{1}\n<code>·····················</code>\n🎲 <b>Ставка:</b> {2} m¢\n💰 <b>Выигрыш:</b> x{3} / {4} m¢\n<blockquote>{5}</blockquote>', (_fmt(user_link, '', -1), _fmt(title, '', -1), _fmt(format_number(bet), '', -1), _fmt(multiplier, f'g', -1), _fmt(format_number(win_amount), '', -1), _fmt(_label(outcome.get('note', '')), '', -1)))
    )

    try:
        await message.answer(text=result_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass


@dp.message(Command("fishing", "fish", "рыбалка", "рыба"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(рыбалка|рыба|fishing|fish)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_fishing(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_fishing_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_fishing_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    await start_fishing_game(message, user_id, bet, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name))



CHEST_CELLS_COUNT = 9
CHEST_PRIZES = [3.0, 1.0, 1.0]


@_localized
def get_chest_choice_keyboard(user_id: int, bet: int):
    rows = []
    for start in range(0, CHEST_CELLS_COUNT, 3):
        rows.append([
            InlineKeyboardButton(text="🧰", callback_data=f"chest_pick:{user_id}:{bet}:{idx}")
            for idx in range(start, start + 3)
        ])
    rows.append([InlineKeyboardButton(text=_l('Отменить ❌'), callback_data=f"chest_cancel:{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_chest_reveal_keyboard(prize_cells: dict, picked_idx: int):
    rows = []
    for start in range(0, CHEST_CELLS_COUNT, 3):
        row = []
        for idx in range(start, start + 3):
            multiplier = prize_cells.get(idx, 0)
            if idx == picked_idx:
                text = f"✅ x{multiplier:g}" if multiplier else "✅ x0"
            elif multiplier:
                text = f"🏛 x{multiplier:g}"
            else:
                text = "💥 x0"
            row.append(InlineKeyboardButton(text=text, callback_data="noop_chest"))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@_localized
def chest_prompt_text(user_id: int, user_first_name: str, bet: int):
    user_link = get_user_mention(user_id, user_first_name)
    return (
        _lf('{0}\n🧰<b>Сундук · выбери ящик!</b>\n<code>·····················</code>\n🎲 <b>Ставка:</b> {1} m¢', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )


def build_chest_prize_cells():
    cells = list(range(CHEST_CELLS_COUNT))
    secrets.SystemRandom().shuffle(cells)
    return {cell: multiplier for cell, multiplier in zip(cells, CHEST_PRIZES)}


@_localized
async def show_chest_menu(message: types.Message, user_id: int, bet: int, user_first_name: str = None):
    await message.answer(
        text=chest_prompt_text(user_id, user_first_name or _l('Игрок'), bet),
        reply_markup=get_chest_choice_keyboard(user_id, bet),
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("chest_cancel:")))
@_localized
async def process_chest_cancel(callback: types.CallbackQuery):
    try:
        owner_id = int(callback.data.split(":", 1)[1])
    except Exception:
        owner_id = 0
    if callback.from_user.id != owner_id:
        await callback.answer(_l('Это не твоя игра'), show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer(_l('Игра отменена'))


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("chest_pick:")))
@_localized
async def process_chest_pick(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    try:
        owner_id = int(parts[1])
        bet = int(parts[2])
        picked_idx = int(parts[3])
    except Exception:
        return

    if callback.from_user.id != owner_id:
        await callback.answer(_l('Это не твоя игра'), show_alert=True)
        return

    user_id = callback.from_user.id
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await callback.answer(_lf('Недостаточно средств! Баланс: {0} mCoin', (_fmt(format_number(user_data['balance']), '', -1),)), show_alert=True)
        return

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await callback.answer(_l('Ошибка списания средств'), show_alert=True)
        return

    prize_cells = build_chest_prize_cells()
    multiplier = prize_cells.get(picked_idx, 0)
    if DEMO_GAME_CONTEXT.get():
        multiplier = max(CHEST_PRIZES)
    is_win = DEMO_GAME_CONTEXT.get() or multiplier > 0
    win_amount = int(bet * multiplier)
    current_data = get_user(user_id)

    if is_win:
        update_user(user_id, balance=current_data["balance"] + win_amount, games=current_data["games"] + 1)
        add_game_history(user_id, "chest", bet, "win", win_amount)
        result_title = _l('🥳<b>Сундук · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>')
        result_note = _lf('🎁 <i>В сундуке найден приз x{0}!</i>', (_fmt(multiplier, f'g', -1),))
    else:
        update_user(user_id, games=current_data["games"] + 1, lost=current_data["lost"] + bet)
        add_game_history(user_id, "chest", bet, "lose", 0)
        result_title = _l('😔<b>Сундук · Проигрыш!</b>')
        result_note = _l('😭 <i>Сундук пустой!</i>')

    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    result_text = (
        _lf('{0}\n{1}\n<code>·····················</code>\n🎲 <b>Ставка:</b> {2} m¢\n🎲 <b>Выпало:</b> x{3}\n<blockquote>{4}</blockquote>', (_fmt(user_link, '', -1), _fmt(result_title, '', -1), _fmt(format_number(bet), '', -1), _fmt(multiplier, f'g', -1), _fmt(result_note, '', -1)))
    )

    try:
        await callback.message.edit_text(
            text=result_text,
            reply_markup=get_chest_reveal_keyboard(prize_cells, picked_idx),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await callback.message.answer(
            text=result_text,
            reply_markup=get_chest_reveal_keyboard(prize_cells, picked_idx),
            parse_mode=ParseMode.HTML
        )

    await callback.answer()


@dp.message(Command("chest", "сундук", "сунд"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(сундук|chest|сунд)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_chest(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_chest_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_chest_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    await show_chest_menu(message, user_id, bet, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name))



SCRATCH_CELLS_COUNT = 6
SCRATCH_MAX_BET = 300000000
SCRATCH_HIDDEN_EMOJI_ID = "5436113877181941026"
SCRATCH_DIAMOND_EMOJI_ID = "5307594157739515229"
SCRATCH_MONEY_EMOJI_ID = "5472212780952066876"
SCRATCH_PAD_EMOJI_ID = QWAK_PAD_EMOJI_ID
SCRATCH_SYMBOLS = ["cherry", "diamond", "seven", "money", "web", "clover"]
SCRATCH_SYMBOL_META = {
    "cherry": {"button": "🍒", "label": "Вишня", "emoji": "🍒", "icon_id": None},
    "diamond": {"button": " ", "label": "Алмаз", "emoji": '<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji>', "icon_id": SCRATCH_DIAMOND_EMOJI_ID},
    "seven": {"button": "7️⃣", "label": "Семёрка", "emoji": "7️⃣", "icon_id": None},
    "money": {"button": " ", "label": "Мешок", "emoji": "💰", "icon_id": SCRATCH_MONEY_EMOJI_ID},
    "web": {"button": "🕸", "label": "Паутина", "emoji": "🕸", "icon_id": None},
    "clover": {"button": " ", "label": "Клевер", "emoji": QWAK_PAD_EMOJI, "icon_id": SCRATCH_PAD_EMOJI_ID},
}


def generate_scratch_symbols():
    rng = secrets.SystemRandom()
    return [rng.choice(SCRATCH_SYMBOLS) for _ in range(SCRATCH_CELLS_COUNT)]


@_localized
def get_scratch_multiplier(symbols):
    diamond_count = sum(1 for s in symbols if s == "diamond")
    cherry_count = sum(1 for s in symbols if s == "cherry")
    if diamond_count >= 3:
        return 10.0, _l('3 алмаза'), _l('<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <i>Выпало 3 алмаза!</i>')
    if cherry_count >= 3:
        return 2.0, _l('3 вишни'), _l('🍒 <i>Выпало 3 вишни!</i>')
    return 0.0, _l('нет совпадений'), _l('😔 <i>Совпадений не хватило.</i>')


def scratch_symbols_line(symbols):
    return " ".join(SCRATCH_SYMBOL_META.get(sym, {}).get("emoji", "❔") for sym in symbols)


def scratch_button_for_symbol(symbol, callback_data):
    meta = SCRATCH_SYMBOL_META.get(symbol, {})
    kwargs = {"text": meta.get("button", "❔"), "callback_data": callback_data}
    icon_id = meta.get("icon_id")
    if icon_id:
        kwargs["icon_custom_emoji_id"] = icon_id
    return InlineKeyboardButton(**kwargs)


@_localized
def get_scratch_keyboard(game_id: int, symbols: list, revealed: set, settled: bool = False):
    rows = []
    for start in range(0, SCRATCH_CELLS_COUNT, 3):
        row = []
        for idx in range(start, start + 3):
            if idx in revealed or settled:
                row.append(scratch_button_for_symbol(symbols[idx], f"scratch_noop_{game_id}"))
            else:
                row.append(InlineKeyboardButton(text=" ", callback_data=f"scratch_cell_{game_id}_{idx}", icon_custom_emoji_id=SCRATCH_HIDDEN_EMOJI_ID))
        rows.append(row)

    if not settled:
        rows.append([
            InlineKeyboardButton(text=_l('🚀 Открыть все сразу'), callback_data=f"scratch_openall_{game_id}", style="primary")
        ])
        if not revealed:
            rows.append([
                InlineKeyboardButton(text=_l('Отменить ❌'), callback_data=f"scratch_cancel_{game_id}", style="danger")
            ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@_localized
def build_scratch_text(user_id: int, user_name: str, game: dict, settled: bool = False):
    user_name = get_user_display_name(user_id, user_name)
    user_link = get_user_mention(user_id, user_name or _l('Игрок'))
    bet = game.get("bet", 0)
    symbols = list(game.get("mine_positions", []))
    revealed = game.get("revealed", set())
    multiplier, combo_name, note = get_scratch_multiplier(symbols)
    win_amount = int(bet * multiplier)

    if settled:
        if multiplier > 0:
            title = _l('<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Скретч · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>')
            win_line = _lf('💰 <b>Выигрыш:</b> x{0} / {1} m¢\n', (_fmt(multiplier, f'g', -1), _fmt(format_number(win_amount), '', -1)))
        else:
            title = _l('<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji><b>Скретч · Проигрыш!</b>')
            win_line = ''
        return (
            _lf('{0}\n{1}\n<code>·····················</code>\n🎲 <b>Ставка:</b> {2} m¢\n{3}<blockquote>{4}\n{5}</blockquote>', (_fmt(user_link, '', -1), _fmt(title, '', -1), _fmt(format_number(bet), '', -1), _fmt(win_line, '', -1), _fmt(note, '', -1), _fmt(scratch_symbols_line(symbols), '', -1)))
        )

    if revealed:
        title = _l('<b>🎫 Скретч · игра идёт!</b>')
        extra = _lf('\n<blockquote>Открыто: {0} из {1}</blockquote>', (_fmt(len(revealed), '', -1), _fmt(SCRATCH_CELLS_COUNT, '', -1)))
    else:
        title = _l('<b>🎫 Скретч · начни игру!</b>')
        extra = ''
    return (
        _lf('{0}\n{1}\n<code>·····················</code>\n🎲 <b>Ставка:</b> {2} m¢{3}', (_fmt(user_link, '', -1), _fmt(title, '', -1), _fmt(format_number(bet), '', -1), _fmt(extra, '', -1)))
    )


def settle_scratch_game(game_id: int, user_id: int):
    game = games.get(game_id)
    if not game or game.get("settled", False):
        return
    symbols = list(game.get("mine_positions", []))
    bet = int(game.get("bet", 0))
    multiplier, _, _ = get_scratch_multiplier(symbols)
    win_amount = int(bet * multiplier)
    current_data = get_user(user_id)
    game["game_over"] = True
    game["won"] = multiplier > 0
    game["settled"] = True
    game["revealed"] = set(range(SCRATCH_CELLS_COUNT))
    game["level"] = SCRATCH_CELLS_COUNT
    if multiplier > 0:
        update_user(user_id, balance=current_data["balance"] + win_amount, games=current_data["games"] + 1)
        add_game_history(user_id, "scratch", bet, "win", win_amount, game.get("created_at_str"))
    else:
        update_user(user_id, games=current_data["games"] + 1, lost=current_data["lost"] + bet)
        add_game_history(user_id, "scratch", bet, "lose", 0, game.get("created_at_str"))
    if active_games.get(user_id) == game_id:
        del active_games[user_id]
    remove_active_game_from_db(game_id)


@_localized
async def start_scratch_game_from_command(message, user_id, chat_id, bet):
    key = get_chat_key(user_id, chat_id)
    if key in user_messages:
        await _delete_messages(chat_id, user_messages[key], bot)
        user_messages[key] = []

    user_data = get_user(user_id)
    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    game_id = get_next_game_id()
    now = datetime.now()
    game_data = {
        "type": "scratch",
        "stage": "playing",
        "bet": bet,
        "mine_count": 0,
        "mine_positions": (["diamond", "diamond", "diamond", "cherry", "cherry", "cherry"] if DEMO_GAME_CONTEXT.get() else generate_scratch_symbols()),
        "revealed": set(),
        "level": 0,
        "game_over": False,
        "won": False,
        "exploded_mine": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "cashed_out": False,
        "bet_placed": False,
        "moves_count": 0,
        "created_at": now,
        "created_at_str": now.strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }
    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)
    await show_scratch_grid_from_message(message, user_id, game_id)


@_localized
async def show_scratch_grid_from_message(message, user_id, game_id, settled=False):
    game = games.get(game_id)
    if not game:
        await message.answer(_l('<i>Игра не найдена!</i>'), parse_mode=ParseMode.HTML)
        return
    if game.get("owner_id") != user_id:
        return

    is_settled = settled or game.get("settled", False) or game.get("game_over", False)
    text = build_scratch_text(user_id, get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок'), game, settled=is_settled)
    keyboard = get_scratch_keyboard(game_id, list(game.get("mine_positions", [])), game.get("revealed", set()), settled=is_settled)
    try:
        msg = await message.edit_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        game["is_edited"] = True
    except Exception:
        msg = await message.answer(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        game["is_edited"] = False
    game["message_id"] = msg.message_id
    key = get_chat_key(user_id, game.get("chat_id"))
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)


@_localized
async def show_scratch_grid_from_callback(callback, user_id, game_id, settled=False):
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return
    if game.get("owner_id") != user_id:
        return

    is_settled = settled or game.get("settled", False) or game.get("game_over", False)
    text = build_scratch_text(user_id, get_user_display_name(user_id, callback.from_user.first_name) or _l('Игрок'), game, settled=is_settled)
    keyboard = get_scratch_keyboard(game_id, list(game.get("mine_positions", [])), game.get("revealed", set()), settled=is_settled)
    try:
        msg = await callback.message.edit_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        game["is_edited"] = True
    except Exception:
        msg = await callback.message.answer(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        game["is_edited"] = False
    game["message_id"] = msg.message_id
    key = get_chat_key(user_id, game.get("chat_id"))
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("scratch_cell_")))
@_localized
async def process_scratch_cell(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 3:
        return
    try:
        game_id = int(parts[-2])
        idx = int(parts[-1])
    except Exception:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return
    if game.get("owner_id") != user_id:
        await callback.answer(_l('Это не твоя игра'), show_alert=True)
        return
    if game.get("settled") or game.get("game_over"):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return
    if idx < 0 or idx >= SCRATCH_CELLS_COUNT:
        await callback.answer(_l('Ошибка клетки'), show_alert=True)
        return
    if game.get("is_processing"):
        await callback.answer()
        return

    game["is_processing"] = True
    try:
        await callback.answer()
        game.setdefault("revealed", set()).add(idx)
        game["level"] = len(game["revealed"])
        game["moves_count"] = len(game["revealed"])
        game["bet_placed"] = True
        if len(game["revealed"]) >= SCRATCH_CELLS_COUNT:
            settle_scratch_game(game_id, user_id)
            await show_scratch_grid_from_callback(callback, user_id, game_id, settled=True)
        else:
            save_active_game_to_db(game_id, game)
            await show_scratch_grid_from_callback(callback, user_id, game_id)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("scratch_openall_")))
@_localized
async def process_scratch_openall(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return
    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return
    if game.get("owner_id") != user_id:
        await callback.answer(_l('Это не твоя игра'), show_alert=True)
        return
    if game.get("settled") or game.get("game_over"):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return
    if game.get("is_processing"):
        await callback.answer()
        return
    game["is_processing"] = True
    try:
        await callback.answer()
        game["revealed"] = set(range(SCRATCH_CELLS_COUNT))
        game["level"] = SCRATCH_CELLS_COUNT
        game["moves_count"] = SCRATCH_CELLS_COUNT
        game["bet_placed"] = True
        settle_scratch_game(game_id, user_id)
        await show_scratch_grid_from_callback(callback, user_id, game_id, settled=True)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("scratch_cancel_")))
@_localized
async def process_scratch_cancel(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except Exception:
        return
    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return
    if game.get("owner_id") != user_id:
        await callback.answer(_l('Это не твоя игра'), show_alert=True)
        return
    if game.get("revealed") or game.get("bet_placed") or game.get("settled"):
        await callback.answer(_l('Нельзя отменить начатую игру'), show_alert=True)
        return
    user_data = get_user(user_id)
    update_user(user_id, balance=user_data["balance"] + int(game.get("bet", 0)))
    if active_games.get(user_id) == game_id:
        del active_games[user_id]
    if game_id in games:
        del games[game_id]
    remove_active_game_from_db(game_id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer(_l('Игра отменена'))


@dp.message(Command("scratch", "скретч", "скретчка"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(скретч|scratch|скретчка)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_scratch(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    parts = re.split(r'\s+', text, maxsplit=1)
    if len(parts) == 1:
        await show_scratch_info(message, user_id)
        return

    unplayed = get_active_unplayed_games(user_id)
    if unplayed:
        await message.answer(_l('<i>У вас уже есть игра! Закончите или доиграйте активную игру.</i>'), parse_mode=ParseMode.HTML)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_scratch_info(message, user_id)
        return
    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return
    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return
    if bet > SCRATCH_MAX_BET and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return
    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return
    await start_scratch_game_from_command(message, user_id, chat_id, bet)



ROULETTE_RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
ROULETTE_BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
ROULETTE_BLOCKS = [
    (1, 2, 4, 5), (2, 3, 5, 6), (4, 5, 7, 8),
    (5, 6, 8, 9), (7, 8, 10, 11), (8, 9, 11, 12),
    (10, 11, 13, 14), (11, 12, 14, 15), (13, 14, 16, 17),
    (14, 15, 17, 18), (16, 17, 19, 20), (17, 18, 20, 21),
    (19, 20, 22, 23), (20, 21, 23, 24), (22, 23, 25, 26),
    (23, 24, 26, 27), (25, 26, 28, 29), (26, 27, 29, 30),
    (28, 29, 31, 32), (29, 30, 32, 33), (31, 32, 34, 35),
    (32, 33, 35, 36),
]
ROULETTE_STREETS = [tuple(range(start, start + 3)) for start in range(1, 35, 3)]
ROULETTE_STICKERS = {
    0: "CAACAgIAAxkBAAEHTh5qu3cfevNVqvyCNn4gf8lRvYUSGwACIIMAAtJnqEhLTE5iB7xvrD0E",
    1: "CAACAgIAAxkBAAEHTiBqu3chi-gHDhMDLVQCIfypAAEwFJAAAqx6AAL3zqlI_dO0ZWZjJYs9BA",
    2: "CAACAgIAAxkBAAEHTiJqu3cjKWpWT1cL54xuNP2jWC6m5QACf3sAApR6qEhFDrGjoS582j0E",
    3: "CAACAgIAAxkBAAEHTiRqu3ckZLOcxJxPfrqBujV_Sgwu7AACMnoAAlQLqUjJbZ887c092D0E",
    4: "CAACAgIAAxkBAAEHTiZqu3cmojZ2OAYxFOB_Wn1urGCZIwACtYEAAvDMqUj9fMCMellbqj0E",
    5: "CAACAgIAAxkBAAEHTihqu3cnBy1UDihRwvOgy2j-HzRSJgAC838AArVvqUioI8rW4yItHz0E",
    6: "CAACAgIAAxkBAAEHTipqu3cpnu9bW0C6qRLC98gULyHZYgACgYQAAovsqUhQW86W-I_mPz0E",
    7: "CAACAgIAAxkBAAEHTixqu3cqX8zBtYEDwyhMdw1SCNONcwACxHoAAhPbqUg1ZnJlsBMZgT0E",
    8: "CAACAgIAAxkBAAEHTi5qu3csrnz4ThyS7PkWacXsWOs7XQACpXoAAmnuqUh4BH7Z1VXJxj0E",
    9: "CAACAgIAAxkBAAEHTjBqu3ct-Uofdx2q4pTi7SnoLbiTzwACAXwAAjCZqUimI96B2e1K_j0E",
    10: "CAACAgIAAxkBAAEHTjJqu3cvKt8QxfGPiz-UBpm1QtU8_wACrXQAAtDaqEiYkYYV5svlBz0E",
    11: "CAACAgIAAxkBAAEHTjZqu3cxPgr69pXLQdmu1zCC4GcwpgACwYAAAhnroUh-neuxtS5Hjj0E",
    12: "CAACAgIAAxkBAAEHTjhqu3cxVa79Gy4439Fvxa4MZqW2hwACEYEAAv35qUjEZH4gmSj4Xj0E",
    13: "CAACAgIAAxkBAAEHTjpqu3c0C7Hg66IfPHiQhIRR1hzI-gACnYcAAhE0qUjg1NZVHxYr-j0E",
    14: "CAACAgIAAxkBAAEHTjxqu3c1MsxdnevffgLLMFUgOhfqqQAC4HwAAiXMqEiSZcye_FqAxD0E",
    15: "CAACAgIAAxkBAAEHTj5qu3c4v1KjTLeeGQU3Xq0wFQomfgACiYIAApZkqEhzNOStDy91Uj0E",
    16: "CAACAgIAAxkBAAEHTkBqu3c6HCZ0EMAkPEClcx2kB4bYeQACin8AAtRrqEiEvy3wQV3Y8D0E",
    17: "CAACAgIAAxkBAAEHTkJqu3c7KezwPsTBqKEaamp9K9qYTgACG4AAAjoMqEiHSbFUVopsjj0E",
    18: "CAACAgIAAxkBAAEHTkRqu3c9UI4F848TC2SH46UFDImwPgACBIUAAhc7qUg7iVbilHE-Dj0E",
    19: "CAACAgIAAxkBAAEHTkZqu3c-Izc-G4UMwRkCL2KYUo0xngACCXsAAiPrqEiVa46gH0ht8z0E",
    20: "CAACAgIAAxkBAAEHT2Fqu-Fu0OFBkv5bzP2405HEi7KQKQACV30AAtSCqEjx8T5LDBRfAAE9BA",
    21: "CAACAgIAAxkBAAEHT2Nqu-F5o9jvU3pGbh_77LMZ6nQKhgAC8XMAApLKqUiWIB4RwVPkSj0E",
    22: "CAACAgIAAxkBAAEHT2Vqu-GA66LLyzeHrbttn_ZN0OL_RgADgAACEDioSGDO-khlMDVfPQQ",
    23: "CAACAgIAAxkBAAEHT2lqu-GIOFpesF5JO8b-8SN2BtYKfgAC73sAAvNVoEhOV-r7DSDuRz0E",
    24: "CAACAgIAAxkBAAEHT2tqu-GL43989w-9wRhB6XQEDt9U-wACMnkAApA1qUgpf_GBbzbfpz0E",
    25: "CAACAgIAAxkBAAEHT21qu-GdWHcv_L9yj0gmXOE2YkSUawAC6YAAAvrkqUhhmfV03w6ONj0E",
    26: "CAACAgIAAxkBAAEHT3tqu-GpNVyd5WaLkI1fvZ2JY7_2VgACrH4AArvtqUiW88zR8qQ3DT0E",
    27: "CAACAgIAAxkBAAEHT39qu-G-6grqB0ijw8q0z8EN9QwlUwACi4oAAtdlqUho_doj7o8U0z0E",
    28: "CAACAgIAAxkBAAEHT4Fqu-HKF5blRSnGQ2lFHR_IQl-GYgACY34AAja6qUga8bRJcYBl1D0E",
    29: "CAACAgIAAxkBAAEHT4Vqu-HhSGziYVzsTSML4lxOmiPXzgACVYcAAijdqUhZH7Px1HPDXD0E",
    30: "CAACAgIAAxkBAAEHT4dqu-HsZTVAuTlJIkvIxh0hmXcuEwACFXsAAnA5qEgRMB0nmnZjoD0E",
    31: "CAACAgIAAxkBAAEHT4lqu-Hv5z8MZEPkZkOz8EUj4n9EawACYH0AAnljqUjSRuWFxaxoRz0E",
    32: "CAACAgIAAxkBAAEHT4tqu-HwUFRZOqSABxEudYnab3DBXQAC3oAAAo8dqUh-TxjbgP7mAAE9BA",
    33: "CAACAgIAAxkBAAEHT41qu-H8RemJxKP_gY-FaEP9Ua2H_QAC_oEAAguDqEhbqBw_U8NFTT0E",
    34: "CAACAgIAAxkBAAEHT49qu-H_LtwaF9DeD62V7CC0NaI7qgACNn8AAn54qEhq5n18sxAU3z0E",
    35: "CAACAgIAAxkBAAEHT5Fqu-IEspLMjcCYByHcKd14BBqLWQACf4QAAkfTqEiSJWZ7vZJx6D0E",
    36: "CAACAgIAAxkBAAEHT5Nqu-IGry42uSi6QCgudarHp3DFHQAC1IAAAlb-qEjt46mkcorGWz0E",
}


def roulette_photo_path():
    candidates = [
        os.path.join(BASE_DIR, "roulete.png"),
        os.path.join(BASE_DIR, "roulette.png"),
        os.path.join(BASE_DIR, "uploads", "roulete.png"),
        os.path.join(BASE_DIR, "uploads", "roulette.png"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


@_localized
def roulette_prompt_text(user_id: int, user_first_name: str, bet: int) -> str:
    user_link = get_user_mention(user_id, user_first_name)
    return (
        _lf('{0}\n🎱 <b>Рулетка · выбери режим!</b>\n<code>·····················</code>\n🎲 <b>Ставка:</b> {1} m¢', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )


def roulette_pick_button(text: str, bet: int, code: str, style: str = "primary"):
    return InlineKeyboardButton(text=text, callback_data=f"roul_pick:{bet}:{code}", style=style)


def roulette_nav_button(text: str, bet: int, page: str, style: str = "primary"):
    return InlineKeyboardButton(text=text, callback_data=f"roul_menu:{bet}:{page}", style=style)


@_localized
def get_roulette_main_keyboard(bet: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [roulette_nav_button(_l('Ставка на число x35 ⚪'), bet, "numbers")],
            [
                roulette_pick_button(_l('🔴 Красный x1.97'), bet, "red"),
                roulette_pick_button(_l('⚫ Чёрный x1.97'), bet, "black"),
            ],
            [
                roulette_pick_button(_l('⚖️ Чётный x1.97'), bet, "even"),
                roulette_pick_button(_l('🔰 Нечётный x1.97'), bet, "odd"),
            ],
            [
                roulette_pick_button("1️⃣ 1-12 x2.9", bet, "dozen1"),
                roulette_pick_button("2️⃣ 13-24 x2.9", bet, "dozen2"),
                roulette_pick_button("3️⃣ 25-36 x2.9", bet, "dozen3"),
            ],
            [
                roulette_pick_button(_l('1️⃣ ряд x2.9'), bet, "row1"),
                roulette_pick_button(_l('2️⃣ ряд x2.9'), bet, "row2"),
                roulette_pick_button(_l('3️⃣ ряд x2.9'), bet, "row3"),
            ],
            [
                roulette_pick_button(_l('🔽 малые x1.97'), bet, "low"),
                roulette_pick_button(_l('🔼 большие x1.97'), bet, "high"),
            ],
            [
                roulette_nav_button(_l('🔳 Блоки x8.7'), bet, "blocks1"),
                roulette_nav_button(_l('3️⃣ Стрит x11.6'), bet, "streets"),
            ],
        ]
    )


@_localized
def get_roulette_numbers_keyboard(bet: int):
    rows = [[roulette_pick_button(_l('🟢 Зеро (0)'), bet, "n0")]]
    for start in range(1, 37, 6):
        rows.append([roulette_pick_button(str(n), bet, f"n{n}") for n in range(start, min(start + 6, 37))])
    rows.append([roulette_nav_button(_l('◀️ назад'), bet, "main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@_localized
def get_roulette_blocks_keyboard(bet: int, page: int = 1):
    blocks = ROULETTE_BLOCKS[:12] if page == 1 else ROULETTE_BLOCKS[12:]
    rows = []
    for i in range(0, len(blocks), 3):
        row = []
        for block in blocks[i:i + 3]:
            label = ",".join(map(str, block))
            code = "b" + "-".join(map(str, block))
            row.append(roulette_pick_button(label, bet, code))
        rows.append(row)
    if page == 1:
        rows.append([roulette_nav_button("▶️", bet, "blocks2")])
    else:
        rows.append([roulette_nav_button("◀️", bet, "blocks1")])
        rows.append([roulette_nav_button(_l('◀️ назад'), bet, "main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@_localized
def get_roulette_streets_keyboard(bet: int):
    rows = []
    for i in range(0, len(ROULETTE_STREETS), 3):
        row = []
        for street in ROULETTE_STREETS[i:i + 3]:
            label = f"{street[0]}-{street[-1]}"
            row.append(roulette_pick_button(label, bet, f"s{street[0]}"))
        rows.append(row)
    rows.append([roulette_nav_button(_l('◀️ назад'), bet, "main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_roulette_keyboard(bet: int, page: str = "main"):
    if page == "numbers":
        return get_roulette_numbers_keyboard(bet)
    if page == "blocks1":
        return get_roulette_blocks_keyboard(bet, 1)
    if page == "blocks2":
        return get_roulette_blocks_keyboard(bet, 2)
    if page == "streets":
        return get_roulette_streets_keyboard(bet)
    return get_roulette_main_keyboard(bet)


@_localized
def roulette_choice_meta(code: str):
    code = str(code or "")
    if code.startswith("n") and code[1:].isdigit():
        n = int(code[1:])
        if 0 <= n <= 36:
            return (_l('Зеро (0)') if n == 0 else str(n)), 35.0, {n}
    if code == "red":
        return _l('Красный'), 1.97, set(ROULETTE_RED_NUMBERS)
    if code == "black":
        return _l('Чёрный'), 1.97, set(ROULETTE_BLACK_NUMBERS)
    if code == "even":
        return _l('Чётный'), 1.97, {n for n in range(1, 37) if n % 2 == 0}
    if code == "odd":
        return _l('Нечётный'), 1.97, {n for n in range(1, 37) if n % 2 == 1}
    if code == "low":
        return _l('Малые (1-18)'), 1.97, set(range(1, 19))
    if code == "high":
        return _l('Большие (19-36)'), 1.97, set(range(19, 37))
    if code in {"dozen1", "dozen2", "dozen3"}:
        idx = int(code[-1])
        start = (idx - 1) * 12 + 1
        end = idx * 12
        return f"{start}-{end}", 2.9, set(range(start, end + 1))
    if code in {"row1", "row2", "row3"}:
        idx = int(code[-1])
        return _lf('{0} ряд', (_fmt(idx, '', -1),)), 2.9, set(range(idx, 37, 3))
    if code.startswith("s") and code[1:].isdigit():
        start = int(code[1:])
        street = tuple(range(start, start + 3))
        if street in ROULETTE_STREETS:
            return f"{start}-{start + 2}", 11.6, set(street)
    if code.startswith("b"):
        try:
            nums = tuple(int(x) for x in code[1:].split("-"))
        except Exception:
            nums = ()
        if nums in ROULETTE_BLOCKS:
            return ",".join(map(str, nums)), 8.7, set(nums)
    return None, None, None


def normalize_roulette_choice_text(choice_text: str) -> str:
    return re.sub(r"\s+", " ", (choice_text or "").lower().replace("ё", "е").strip())


def parse_roulette_choice(choice_text: str):
    choice_text = _canonical_choice(choice_text, (('Красный', 'red'), ('Чёрный', 'black'), ('Чётный', 'even'), ('Нечётный', 'odd'), ('Малые (1-18)', 'low'), ('Большие (19-36)', 'high'), ('Зеро (0)', 'zero')))
    t = normalize_roulette_choice_text(choice_text)
    compact = t.replace(" ", "")
    aliases = {
        "к": "red", "красный": "red", "красное": "red", "красная": "red", "red": "red", "r": "red",
        "ч": "black", "черный": "black", "черное": "black", "черная": "black", "black": "black", "b": "black",
        "чет": "even", "четный": "even", "четное": "even", "четная": "even", "even": "even",
        "н": "odd", "нечет": "odd", "нечетный": "odd", "нечетное": "odd", "нечетная": "odd", "odd": "odd",
        "малые": "low", "малое": "low", "мал": "low", "м": "low", "low": "low", "1-18": "low", "1to18": "low",
        "большие": "high", "большое": "high", "бол": "high", "high": "high", "19-36": "high", "19to36": "high",
        "1-12": "dozen1", "112": "dozen1", "перваядюжина": "dozen1", "1дюжина": "dozen1",
        "13-24": "dozen2", "1324": "dozen2", "втораядюжина": "dozen2", "2дюжина": "dozen2",
        "25-36": "dozen3", "2536": "dozen3", "третьядюжина": "dozen3", "3дюжина": "dozen3",
        "1ряд": "row1", "ряд1": "row1", "1р": "row1", "row1": "row1", "1қатар": "row1",
        "2ряд": "row2", "ряд2": "row2", "2р": "row2", "row2": "row2", "2қатар": "row2",
        "3ряд": "row3", "ряд3": "row3", "3р": "row3", "row3": "row3", "3қатар": "row3",
        "зеро": "n0", "zero": "n0", "ноль": "n0",
    }
    if compact in aliases:
        code = aliases[compact]
        name, mult, numbers = roulette_choice_meta(code)
        return code, name, mult, numbers

    if compact.isdigit():
        n = int(compact)
        if 0 <= n <= 36:
            code = f"n{n}"
            name, mult, numbers = roulette_choice_meta(code)
            return code, name, mult, numbers

    m = re.match(r"^(\d{1,2})\s*[-–—]\s*(\d{1,2})$", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a == 1 and b == 12:
            return ("dozen1",) + roulette_choice_meta("dozen1")
        if a == 13 and b == 24:
            return ("dozen2",) + roulette_choice_meta("dozen2")
        if a == 25 and b == 36:
            return ("dozen3",) + roulette_choice_meta("dozen3")
        if a == 1 and b == 18:
            return ("low",) + roulette_choice_meta("low")
        if a == 19 and b == 36:
            return ("high",) + roulette_choice_meta("high")
        street = tuple(range(a, b + 1))
        if len(street) == 3 and street in ROULETTE_STREETS:
            code = f"s{a}"
            return (code,) + roulette_choice_meta(code)

    if re.fullmatch(r"\d{1,2}([,; ]+\d{1,2})+", t):
        nums = tuple(int(x) for x in re.findall(r"\d{1,2}", t))
        if len(nums) == 1 and 0 <= nums[0] <= 36:
            code = f"n{nums[0]}"
            return (code,) + roulette_choice_meta(code)
        if len(nums) == 3 and nums in ROULETTE_STREETS:
            code = f"s{nums[0]}"
            return (code,) + roulette_choice_meta(code)
        if len(nums) == 4 and nums in ROULETTE_BLOCKS:
            code = "b" + "-".join(map(str, nums))
            return (code,) + roulette_choice_meta(code)

    return None, None, None, None


@_localized
def roulette_result_label(result: int) -> str:
    if result == 0:
        return _l('🟢 Зеро (0)')
    if result in ROULETTE_RED_NUMBERS:
        return f"🔴 {result}"
    return f"⚫ {result}"


async def send_or_edit_roulette_menu(target, user_id: int, user_first_name: str, bet: int, page: str = "main", edit: bool = False):
    text = roulette_prompt_text(user_id, user_first_name, bet)
    keyboard = get_roulette_keyboard(bet, page)
    photo_path = roulette_photo_path()

    if edit:
        message = target.message
        if getattr(message, "photo", None):
            try:
                await message.edit_caption(caption=text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                return
            except Exception:
                pass
        try:
            await message.edit_text(text=text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            await message.answer(text=text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return

    if photo_path:
        try:
            await target.answer_photo(
                photo=FSInputFile(photo_path),
                caption=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            return
        except Exception as e:
            logging.warning(f"Failed to send roulette photo {photo_path}: {e}")
    await target.answer(text=text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@_localized
async def start_roulette_game(message: types.Message, user_id: int, bet: int, choice_code: str, choice_name: str, multiplier: float, win_numbers: set, user_first_name: str = None):
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return False

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return False

    result = secrets.randbelow(37)
    sticker_id = ROULETTE_STICKERS.get(result)
    try:
        if sticker_id:
            await bot.send_sticker(chat_id=message.chat.id, sticker=sticker_id)
        else:
            await message.answer(_lf('🎱 Выпало: {0}', (_fmt(roulette_result_label(result), '', -1),)), parse_mode=ParseMode.HTML)
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await message.answer(_l('<i>Ошибка запуска рулетки! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return False

    asyncio.create_task(process_roulette_outcome(message, user_id, bet, choice_code, choice_name, multiplier, win_numbers, result, user_first_name=user_first_name))
    return True


@_localized
async def process_roulette_outcome(message: types.Message, user_id: int, bet: int, choice_code: str, choice_name: str, multiplier: float, win_numbers: set, result: int, user_first_name: str = None):
    await asyncio.sleep(3.5)

    is_win = DEMO_GAME_CONTEXT.get() or result in win_numbers
    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)
    result_text = roulette_result_label(result)

    if is_win:
        win_amount = int(bet * multiplier)
        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "roulette", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Рулетка · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎱 <b>Выбрано:</b> {2}\n💰 <b>Выигрыш:</b> х{3} / {4} m¢\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {5} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(choice_name), '', -1), _fmt(multiplier, f'g', -1), _fmt(format_number(win_amount), '', -1), _fmt(result_text, '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "roulette", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji><b> Рулетка · Проигрыш!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎱 <b>Выбрано:</b> {2}\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {3} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(choice_name), '', -1), _fmt(result_text, '', -1)))
        )

    try:
        await message.answer(text=response_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("roul_menu:")))
@_localized
async def process_roulette_menu_callback(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        return
    try:
        bet = int(parts[1])
    except Exception:
        return
    page = parts[2]
    await send_or_edit_roulette_menu(callback, callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), bet, page=page, edit=True)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("roul_pick:")))
@_localized
async def process_roulette_pick_callback(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        return
    try:
        bet = int(parts[1])
    except Exception:
        return
    code = parts[2]
    choice_name, multiplier, win_numbers = roulette_choice_meta(code)
    if choice_name is None:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await start_roulette_game(callback.message, callback.from_user.id, bet, code, choice_name, multiplier, win_numbers, user_first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name))


@dp.message(Command("roulette", "рулетка", "рул"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(рулетка|roulette|рул)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_roulette(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)
    if len(parts) == 1:
        await show_roulette_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_roulette_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if len(tokens) >= 2:
        choice_raw = " ".join(tokens[1:])
        code, choice_name, multiplier, win_numbers = parse_roulette_choice(choice_raw)
        if code is not None:
            await start_roulette_game(message, user_id, bet, code, choice_name, multiplier, win_numbers, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name))
            return
        await message.answer(_l('<i>Не понял исход. Примеры: <code>рулетка 100 ч</code>, <code>рулетка 100 1</code>, <code>рулетка 100 1,2,3</code></i>'), parse_mode=ParseMode.HTML)
        return

    await send_or_edit_roulette_menu(message, user_id, get_user_display_name(message.from_user.id, message.from_user.first_name), bet, page="main", edit=False)



@_localized
def parse_darts_choice(choice_text: str):
    choice_text = _canonical_choice(choice_text, (('Красное', 'red'), ('Белое', 'white'), ('Центр', 'center'), ('Мимо', 'miss')))
    t = choice_text.lower().strip()
    if t in ["красное", "красный", "красная", "red", "к", "крас"]:
        return "red", _l('🔴 Красное'), 1.94
    elif t in ["белое", "белый", "белая", "white", "б", "бел"]:
        return "white", _l('⚪️ Белое'), 2.9
    elif t in ["центр", "яблочко", "булзай", "center", "bullseye", "ц", "в центр"]:
        return "center", _l('🎯 Центр'), 5.8
    elif t in ["мимо", "промах", "miss", "м"]:
        return "miss", _l('😯 Мимо'), 5.8
    return None, None, None


@_localized
def get_darts_choice_keyboard(bet: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('🔴 Красное (х1.94)'), callback_data=f"darts_{bet}_red", style="primary"),
                InlineKeyboardButton(text=_l('⚪️ Белое (х2.9)'), callback_data=f"darts_{bet}_white", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('🎯 Центр (х5.8)'), callback_data=f"darts_{bet}_center", style="primary"),
                InlineKeyboardButton(text=_l('😯 Мимо (х5.8)'), callback_data=f"darts_{bet}_miss", style="primary"),
            ]
        ]
    )


@_localized
async def process_darts_outcome(message: types.Message, dice_msg: types.Message, user_id: int, bet: int, target_choice_code: str, target_choice_name: str, win_mult: float, user_first_name: str = None):
    await asyncio.sleep(2.7)

    val = dice_msg.dice.value if (dice_msg and dice_msg.dice) else 1

    outcome_names = {
        1: _l('😯 Мимо'),
        2: _l('🔴 Красное кольцо'),
        3: _l('⚪️ Белое кольцо'),
        4: _l('🔴 Красное кольцо'),
        5: _l('⚪️ Белое кольцо'),
        6: _l('🎯 Центр (Яблочко)')
    }
    outcome_str = outcome_names.get(val, _lf('Сектор {0}', (_fmt(val, '', -1),)))

    is_win = False
    if target_choice_code == "red" and val in [2, 4, 6]:
        is_win = True
    elif target_choice_code == "white" and val in [3, 5]:
        is_win = True
    elif target_choice_code == "center" and val == 6:
        is_win = True
    elif target_choice_code == "miss" and val == 1:
        is_win = True
    is_win = DEMO_GAME_CONTEXT.get() or is_win

    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)

    if is_win:
        win_amount = int(bet * win_mult)
        if win_amount > 1740000000 and not is_admin_unlimited_bet(user_id):
            win_amount = 1740000000

        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "darts", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Дартс · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n💰 <b>Выигрыш:</b> х{3} / {4} m¢\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {5} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(target_choice_name), '', -1), _fmt(win_mult, '', -1), _fmt(format_number(win_amount), '', -1), _fmt(outcome_str, '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "darts", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji><b> Дартс · Проигрыш!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {3} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(target_choice_name), '', -1), _fmt(outcome_str, '', -1)))
        )

    await message.answer(
        text=response_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("darts_")))
@_localized
async def process_darts_choice_callback(callback: types.CallbackQuery):
    await callback.answer()
    parts = callback.data.split("_")
    if len(parts) < 3:
        return
    try:
        bet = int(parts[1])
        target_code = parts[2]
    except ValueError:
        return

    code_map = {
        "red": (_l('🔴 Красное'), 1.94),
        "white": (_l('⚪️ Белое'), 2.9),
        "center": (_l('🎯 Центр'), 5.8),
        "miss": (_l('😯 Мимо'), 5.8)
    }
    if target_code not in code_map:
        return
    target_name, win_mult = code_map[target_code]

    user_id = callback.from_user.id
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await callback.message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await callback.message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        dice_msg = await callback.message.answer_dice(emoji="🎯")
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await callback.message.answer(_l('<i>Ошибка запуска дартса! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return

    asyncio.create_task(process_darts_outcome(callback.message, dice_msg, user_id, bet, target_code, target_name, win_mult, user_first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name)))


@dp.message(Command("darts", "дартс", "дс", "dart"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(дартс|darts|дс|dart)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_darts(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_darts_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_darts_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if len(tokens) >= 2:
        choice_raw = " ".join(tokens[1:])
        target_code, target_name, win_mult = parse_darts_choice(choice_raw)
        if target_code is not None:
            if not update_user(user_id, balance=user_data["balance"] - bet):
                await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
                return
            try:
                dice_msg = await message.answer_dice(emoji="🎯")
            except Exception:
                user_data = get_user(user_id)
                update_user(user_id, balance=user_data["balance"] + bet)
                await message.answer(_l('<i>Ошибка запуска дартса! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
                return
            asyncio.create_task(process_darts_outcome(message, dice_msg, user_id, bet, target_code, target_name, win_mult, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name)))
            return

    user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
    prompt_text = (
        _lf('{0}\n🎯 <b>Дартс · выбери исход!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n\n🔰 <b>Коэффициенты:</b>\n🔴 Красное (х1.94)\n⚪️ Белое (х2.9)\n🎯 Центр (х5.8)\n😯 Мимо (х5.8)', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )
    await message.answer(
        text=prompt_text,
        reply_markup=get_darts_choice_keyboard(bet),
        parse_mode=ParseMode.HTML
    )



@_localized
def parse_basketball_choice(choice_text: str):
    choice_text = _canonical_choice(choice_text, (('Попадание', 'hit'), ('Мимо', 'miss'), ('Застрял мяч', 'stuck')))
    t = choice_text.lower().strip()
    if t in ["попадание", "попал", "гол", "hit", "score", "п", "г", "в корзину", "1"]:
        return "hit", _l('🏀 Попадание'), 2.4
    elif t in ["мимо", "промах", "miss", "м", "0"]:
        return "miss", _l('💨 Мимо'), 2.4
    elif t in ["застрял", "застрял мяч", "дужка", "stuck", "з"]:
        return "stuck", _l('🛑 Застрял мяч'), 4.8
    return None, None, None


@_localized
def get_basketball_choice_keyboard(bet: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('🏀 Попадание (х2.4)'), callback_data=f"bb_{bet}_hit", style="primary"),
                InlineKeyboardButton(text=_l('💨 Мимо (х2.4)'), callback_data=f"bb_{bet}_miss", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('🛑 Застрял мяч (х4.8)'), callback_data=f"bb_{bet}_stuck", style="primary"),
            ]
        ]
    )


@_localized
async def process_basketball_outcome(message: types.Message, dice_msg: types.Message, user_id: int, bet: int, target_choice_code: str, target_choice_name: str, win_mult: float, user_first_name: str = None):
    await asyncio.sleep(2.7)

    val = dice_msg.dice.value if (dice_msg and dice_msg.dice) else 1

    outcome_names = {
        1: _l('💨 Мимо'),
        2: _l('💨 Отскок мимо'),
        3: _l('🛑 Застрял мяч'),
        4: _l('🏀 Попадание!'),
        5: _l('🏀 Чистое попадание!')
    }
    outcome_str = outcome_names.get(val, _l('Мимо'))

    is_win = False
    if target_choice_code == "hit" and val in [4, 5]:
        is_win = True
    elif target_choice_code == "miss" and val in [1, 2]:
        is_win = True
    elif target_choice_code == "stuck" and val == 3:
        is_win = True
    is_win = DEMO_GAME_CONTEXT.get() or is_win

    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)

    if is_win:
        win_amount = int(bet * win_mult)
        if win_amount > 1440000000 and not is_admin_unlimited_bet(user_id):
            win_amount = 1440000000

        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "basketball", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Баскетбол · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n💰 <b>Выигрыш:</b> х{3} / {4} m¢\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {5} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(target_choice_name), '', -1), _fmt(win_mult, '', -1), _fmt(format_number(win_amount), '', -1), _fmt(outcome_str, '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "basketball", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji><b> Баскетбол · Проигрыш!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {3} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(target_choice_name), '', -1), _fmt(outcome_str, '', -1)))
        )

    await message.answer(
        text=response_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("bb_")))
@_localized
async def process_basketball_choice_callback(callback: types.CallbackQuery):
    await callback.answer()
    parts = callback.data.split("_")
    if len(parts) < 3:
        return
    try:
        bet = int(parts[1])
        target_code = parts[2]
    except ValueError:
        return

    code_map = {
        "hit": (_l('🏀 Попадание'), 2.4),
        "miss": (_l('💨 Мимо'), 2.4),
        "stuck": (_l('🛑 Застрял мяч'), 4.8)
    }
    if target_code not in code_map:
        return
    target_name, win_mult = code_map[target_code]

    user_id = callback.from_user.id
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await callback.message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await callback.message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        dice_msg = await callback.message.answer_dice(emoji="🏀")
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await callback.message.answer(_l('<i>Ошибка запуска баскетбола! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return

    asyncio.create_task(process_basketball_outcome(callback.message, dice_msg, user_id, bet, target_code, target_name, win_mult, user_first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name)))


@dp.message(Command("basketball", "баскетбол", "баскет", "бс", "бк"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(баскетбол|basketball|баскет|бс|бк)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_basketball(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_basketball_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_basketball_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if len(tokens) >= 2:
        choice_raw = " ".join(tokens[1:])
        target_code, target_name, win_mult = parse_basketball_choice(choice_raw)
        if target_code is not None:
            if not update_user(user_id, balance=user_data["balance"] - bet):
                await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
                return
            try:
                dice_msg = await message.answer_dice(emoji="🏀")
            except Exception:
                user_data = get_user(user_id)
                update_user(user_id, balance=user_data["balance"] + bet)
                await message.answer(_l('<i>Ошибка запуска баскетбола! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
                return
            asyncio.create_task(process_basketball_outcome(message, dice_msg, user_id, bet, target_code, target_name, win_mult, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name)))
            return

    user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
    prompt_text = (
        _lf('{0}\n🏀 <b>Баскетбол · выбери исход!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n\n🔰 <b>Коэффициенты:</b>\n🏀 Попадание (х2.4)\n💨 Мимо (х2.4)\n🛑 Застрял мяч (х4.8)', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )
    await message.answer(
        text=prompt_text,
        reply_markup=get_basketball_choice_keyboard(bet),
        parse_mode=ParseMode.HTML
    )



@_localized
def parse_football_choice(choice_text: str):
    choice_text = _canonical_choice(choice_text, (('Гол', 'goal'), ('Мимо', 'miss')))
    t = choice_text.lower().strip()
    if t in ["гол", "попадание", "забил", "goal", "г", "1"]:
        return "goal", _l('⚽️ Гол'), 1.6
    elif t in ["мимо", "промах", "штанга", "miss", "м", "0"]:
        return "miss", _l('💨 Мимо'), 2.4
    return None, None, None


@_localized
def get_football_choice_keyboard(bet: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('⚽️ Гол (х1.6)'), callback_data=f"fb_{bet}_goal", style="primary"),
                InlineKeyboardButton(text=_l('💨 Мимо (х2.4)'), callback_data=f"fb_{bet}_miss", style="primary"),
            ]
        ]
    )


@_localized
async def process_football_outcome(message: types.Message, dice_msg: types.Message, user_id: int, bet: int, target_choice_code: str, target_choice_name: str, win_mult: float, user_first_name: str = None):
    await asyncio.sleep(2.7)

    val = dice_msg.dice.value if (dice_msg and dice_msg.dice) else 1

    outcome_names = {
        1: _l('💨 Мимо ворот'),
        2: _l('🥅 Штанга / Мимо'),
        3: _l('⚽️ Гол!'),
        4: _l('⚽️ Гол в девятку!'),
        5: _l('⚽️ Гол!')
    }
    outcome_str = outcome_names.get(val, _l('Мимо'))

    is_win = False
    if target_choice_code == "goal" and val in [3, 4, 5]:
        is_win = True
    elif target_choice_code == "miss" and val in [1, 2]:
        is_win = True
    is_win = DEMO_GAME_CONTEXT.get() or is_win

    user_link = get_user_mention(user_id, user_first_name or (get_user_display_name(message.from_user.id, message.from_user.first_name) if message and message.from_user and get_user_display_name(message.from_user.id, message.from_user.first_name) != "Мины Бот" else None))
    current_data = get_user(user_id)

    if is_win:
        win_amount = int(bet * win_mult)
        if win_amount > 720000000 and not is_admin_unlimited_bet(user_id):
            win_amount = 720000000

        new_balance = current_data["balance"] + win_amount
        new_games = current_data["games"] + 1

        update_user(user_id, balance=new_balance, games=new_games)
        add_game_history(user_id, "football", bet, "win", win_amount)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Футбол · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n💰 <b>Выигрыш:</b> х{3} / {4} m¢\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {5} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(target_choice_name), '', -1), _fmt(win_mult, '', -1), _fmt(format_number(win_amount), '', -1), _fmt(outcome_str, '', -1)))
        )
    else:
        new_games = current_data["games"] + 1
        new_lost = current_data["lost"] + bet

        update_user(user_id, games=new_games, lost=new_lost)
        add_game_history(user_id, "football", bet, "lose", 0)

        response_text = (
            _lf('{0}\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji><b> Футбол · Проигрыш!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n🎲 <b>Выбрано:</b> {2}\n<code>············</code>\n<blockquote> <tg-emoji emoji-id="5258203794772085854">⚡️</tg-emoji> Итог: {3} </blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(_label(target_choice_name), '', -1), _fmt(outcome_str, '', -1)))
        )

    await message.answer(
        text=response_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("fb_")))
@_localized
async def process_football_choice_callback(callback: types.CallbackQuery):
    await callback.answer()
    parts = callback.data.split("_")
    if len(parts) < 3:
        return
    try:
        bet = int(parts[1])
        target_code = parts[2]
    except ValueError:
        return

    code_map = {
        "goal": (_l('⚽️ Гол'), 1.6),
        "miss": (_l('💨 Мимо'), 2.4)
    }
    if target_code not in code_map:
        return
    target_name, win_mult = code_map[target_code]

    user_id = callback.from_user.id
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await callback.message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if not update_user(user_id, balance=user_data["balance"] - bet):
        await callback.message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        dice_msg = await callback.message.answer_dice(emoji="⚽")
    except Exception:
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + bet)
        await callback.message.answer(_l('<i>Ошибка запуска футбола! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
        return

    asyncio.create_task(process_football_outcome(callback.message, dice_msg, user_id, bet, target_code, target_name, win_mult, user_first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name)))


@dp.message(Command("football", "футбол", "фб"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(футбол|football|фб)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_football(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    parts = re.split(r'\s+', text, maxsplit=1)

    if len(parts) == 1:
        await show_football_info(message, user_id)
        return

    tokens = parts[1].strip().split()
    if not tokens:
        await show_football_info(message, user_id)
        return

    user_data = get_user(user_id)
    bet = resolve_bet_amount(tokens[0], user_data["balance"])
    if bet is None:
        await message.answer(_l('<i>Неверный формат суммы! Пример: 100, 1.4кк, 120кк, все, пол</i>'), parse_mode=ParseMode.HTML)
        return

    if bet < 1:
        if user_data["balance"] < 1:
            await message.answer(_l('<i>Ваш баланс равен 0! Пополните баланс чтобы играть.</i>'), parse_mode=ParseMode.HTML)
        else:
            await message.answer(_l('<i>Ставка должна быть больше 0!</i>'), parse_mode=ParseMode.HTML)
        return

    if bet > 300000000 and not is_admin_unlimited_bet(user_id):
        await message.answer(_l('<i>Максимальная ставка: 300kk m¢!</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < bet:
        await message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    if len(tokens) >= 2:
        choice_raw = " ".join(tokens[1:])
        target_code, target_name, win_mult = parse_football_choice(choice_raw)
        if target_code is not None:
            if not update_user(user_id, balance=user_data["balance"] - bet):
                await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
                return
            try:
                dice_msg = await message.answer_dice(emoji="⚽")
            except Exception:
                user_data = get_user(user_id)
                update_user(user_id, balance=user_data["balance"] + bet)
                await message.answer(_l('<i>Ошибка запуска футбола! Ставка возвращена.</i>'), parse_mode=ParseMode.HTML)
                return
            asyncio.create_task(process_football_outcome(message, dice_msg, user_id, bet, target_code, target_name, win_mult, user_first_name=get_user_display_name(message.from_user.id, message.from_user.first_name)))
            return

    user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
    prompt_text = (
        _lf('{0}\n⚽️ <b>Футбол · выбери исход!</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n\n🔰 <b>Коэффициенты:</b>\n⚽️ Гол (х1.6)\n💨 Мимо (х2.4)', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )
    await message.answer(
        text=prompt_text,
        reply_markup=get_football_choice_keyboard(bet),
        parse_mode=ParseMode.HTML
    )



@dp.message(Command("promo", "промо"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^(промо|promo)\b', message.text, re.IGNORECASE)))
@_localized
async def cmd_promo(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    user_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{user_name}</a>'

    parts = re.split(r'\s+', text, maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            _lf('<i>{0}, ты не ввел промокод <tg-emoji emoji-id="5474493399996308572">😏</tg-emoji></i>', (_fmt(user_link, '', -1),)),
            parse_mode=ParseMode.HTML
        )
        return

    code_input = clean_promo_string(parts[1])

    try:
        cursor.execute("SELECT code, reward, remaining_activations FROM promo_codes WHERE code = ?", (code_input,))
        promo = cursor.fetchone()

        if not promo or promo[2] <= 0:
            cursor.execute("DELETE FROM promo_codes WHERE remaining_activations <= 0")
            conn.commit()
            await message.reply(
                _lf('<i>{0}, такого промокода не существует! <tg-emoji emoji-id="5371074117971745503">🤡</tg-emoji></i>', (_fmt(user_link, '', -1),)),
                parse_mode=ParseMode.HTML
            )
            return

        real_code, reward, remaining = promo

        cursor.execute("SELECT 1 FROM promo_activations WHERE code = ? AND user_id = ?", (real_code, user_id))
        if cursor.fetchone():
            await message.reply(
                _lf('<i>{0}, ты уже активировал этот промокод!</i>', (_fmt(user_link, '', -1),)),
                parse_mode=ParseMode.HTML
            )
            return

        new_remaining = remaining - 1
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        cursor.execute("INSERT INTO promo_activations (code, user_id, activated_at) VALUES (?, ?, ?) ON CONFLICT (code, user_id) DO NOTHING", (real_code, user_id, now_str))

        if new_remaining <= 0:
            cursor.execute("DELETE FROM promo_codes WHERE code = ?", (real_code,))
        else:
            cursor.execute("UPDATE promo_codes SET remaining_activations = ? WHERE code = ?", (new_remaining, real_code))
        conn.commit()

        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + reward)

        await message.reply(
            _lf('<i>{0}, ты успешно активировал промокод «{1}» и получил {2} mCoin</i>', (_fmt(user_link, '', -1), _fmt(html.escape(real_code), '', -1), _fmt(format_number(reward), '', -1))),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.reply(_lf('<i>Ошибка при активации промокода: {0}</i>', (_fmt(html.escape(str(e)), '', -1),)), parse_mode=ParseMode.HTML)



@dp.message(_inline_filter(lambda message: message.text and message.text.lower() in ["б", "баланс", "бал"]))
@_localized
async def cmd_balance(message: types.Message):
    user_id = message.from_user.id

    user_data = get_user(user_id)

    if not user_data:
        await message.answer(f"<i>{tr(user_id, 'balance_error')}</i>", parse_mode=ParseMode.HTML)
        return

    balance = user_data["balance"]
    games_count = user_data["games"]
    lost = user_data["lost"]

    text = (
        f'<i><tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> {tr(user_id, "balance_title")}: {format_number(balance)} mCoin\n'
        '<code>·····················</code>\n'
        f'<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> {tr(user_id, "balance_games")}: {games_count}\n'
        f'<tg-emoji emoji-id="5442983582882601962">🗿</tg-emoji> {tr(user_id, "balance_lost")}: {format_number(lost)}</i>'
    )

    if message.chat.type in ["group", "supergroup"]:
        await message.reply(
            text=text,
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            text=text,
            parse_mode=ParseMode.HTML
        )


@dp.message(_inline_filter(lambda message: message.text and message.text.lower() == "бонус" and message.chat.type in ["group", "supergroup"]))
@_localized
async def cmd_bonus(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user(user_id)

    if not user_data:
        await message.reply(_l('<i>Ошибка получения данных!</i>'), parse_mode=ParseMode.HTML)
        return

    try:
        user_info = await bot.get_chat(user_id)
        description = user_info.bio or ""
    except Exception:
        description = ""

    if f"@{BOT_USERNAME}" not in description and BOT_USERNAME not in description:
        text = (
            _lf('<i>Чтобы получить бонус, нужно выполнить некие условия.\n<code>·····················</code>\nНужно добавить юзернейм бота в свое описание.\nДля продолжения нажмите ниже.</i>', ())
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Проверить'),
                        callback_data="check_bonus",
                        style="success",
                        icon_custom_emoji_id="5465368548702446780"
                    ),
                    InlineKeyboardButton(
                        text=_l('Туториал'),
                        callback_data="bonus_tutorial",
                        style="primary",
                        icon_custom_emoji_id="5471960722206366390"
                    )
                ]
            ]
        )

        await message.reply(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
        return

    if user_data["bonus_time"]:
        try:
            last_bonus = datetime.fromisoformat(user_data["bonus_time"])
            if datetime.now() - last_bonus < timedelta(hours=6):
                time_left = timedelta(hours=6) - (datetime.now() - last_bonus)
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)
                await message.reply(_lf('<i>Бонус можно получить только раз в 6 часов. Осталось: {0}ч {1}м</i>', (_fmt(hours, '', -1), _fmt(minutes, '', -1))), parse_mode=ParseMode.HTML)
                return
        except Exception:
            pass

    bonus = random.randint(70000, 100000)
    if update_user(user_id, balance=user_data["balance"] + bonus, bonus_time=datetime.now().isoformat()):
        try:
            asyncio.create_task(activate_referral_if_needed(user_id))
        except Exception:
            pass
        await message.reply(
            _lf('<i>🎉 Поздравляем! Вы получили бонус {0} mCoin!\nТекущий баланс: {1} mCoin</i>', (_fmt(format_number(bonus), '', -1), _fmt(format_number(user_data['balance'] + bonus), '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(_l('<i>Ошибка при начислении бонуса!</i>'), parse_mode=ParseMode.HTML)



@_localized
async def show_mines_info(message, user_id):
    user_link = _lf('<a href="tg://user?id={0}">{1}</a>', (_fmt(user_id, '', -1), _fmt(html.escape(get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок')), '', -1)))

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Мины — это игра, в которой вам нужно угадать пустые ячейки. Чем больше ячеек вы откроете, тем больше получите mCoin!\n📊 Лимиты:\nRTP: ~97%\nМакс. множитель: х5,044,291\nМакс. ставка: 250kk m¢\nМакс. выигрыш: 2kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u><tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> /mines [ставка] [мины (1-6)]</u></b>\n\nПример: <code>/mines 100 6</code>\nПример: <code>Мины 1.4кк</code>', (_fmt(user_link, '', -1),))
    )

    await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@_localized
async def show_tower_info(message, user_id):
    user_link = _lf('<a href="tg://user?id={0}">{1}</a>', (_fmt(user_id, '', -1), _fmt(html.escape(get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок')), '', -1)))

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Башня — это игра, в которой нужно избежать мин и добраться до вершины.\n📊 Лимиты:\nRTP: ~97%\nМакс. множитель: х1,894,531\nМакс. ставка: 250kk m¢\nМакс. выигрыш: 2kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🛕 /tower [ставка] [мины (1-4)]</u></b>\n\nПример: <code>/tower 100 4</code>\nПример: <code>Башня 1.4кк</code>', (_fmt(user_link, '', -1),))
    )

    await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@_localized
async def show_qwak_info(message, user_id):
    user_link = _lf('<a href="tg://user?id={0}">{1}</a>', (_fmt(user_id, '', -1), _fmt(html.escape(get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок')), '', -1)))

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Квак — режим как башня: нужно прыгать по кувшинкам и не попасть на мину. Всего 5 этажей.\nМины по этажам фиксированные:\n1 этаж — 0 мин\n2 этаж — 1 мина\n3 этаж — 2 мины\n4 этаж — 3 мины\n5 этаж — 4 мины\n\n📊 Множители:\n1.00x / 1.21x / 2.00x / 5.05x / 25.25x\n\nЛимиты:\nМакс. ставка: 300kk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>{1} /qwak [ставка]</u></b>\n\nПример: <code>/qwak 100</code>\nПример: <code>квак 100</code>', (_fmt(user_link, '', -1), _fmt(QWAK_PAD_EMOJI, '', -1)))
    )

    await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@_localized
async def show_diamonds_info(message, user_id):
    user_link = _lf('<a href="tg://user?id={0}">{1}</a>', (_fmt(user_id, '', -1), _fmt(html.escape(get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок')), '', -1)))

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Алмазная лихорадка — это игра, в которой необходимо угадать, в какой ячейке спрятан алмаз. Вам нужно открывать по одной ячейке на каждом из 16 уровней, чтобы найти алмаз.\n📊 Лимиты:\nRTP: ~97%\nМакс. множитель: х41,755,319\nМакс. ставка: 250kk m¢\nМакс. выигрыш: 2kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u><tg-emoji emoji-id="5307594157739515229">💠</tg-emoji> /diamond [ставка] [мины 1-2]</u></b>\n\nПример: <code>/diamond 100 2</code>\nПример: <code>алмазы 100</code>', (_fmt(user_link, '', -1),))
    )

    await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@_localized
async def show_twentyone_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> 21 (Очко) — карточная игра, в которой цель игрока — набрать сумму очков ближе к 21, чем у дилера, не превышая это число. Карты от 2 до 10 считаются по номиналу, валет даёт 2 очка, дама — 3 очка, король — 4 очка, туз — 11 или 1, в зависимости от ситуации. Если сумма больше 21 — перебор.\n📊 Лимиты:\nRTP: ~97%\nМакс. множитель: х1.97\nМакс. ставка: 500kk m¢\nМакс. выигрыш: 1kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u><tg-emoji emoji-id="5395325195542078574">🍀</tg-emoji> /21 [ставка]</u></b>\n\nПример: <code>/21 100</code>\nПример: <code>очко 100</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_modes",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@dp.callback_query(_inline_filter(lambda c: c.data == "info_twentyone"))
@_localized
async def process_info_twentyone(callback: types.CallbackQuery):
    await callback.answer()
    await show_twentyone_info(callback, callback.from_user.id, is_callback=True)


@_localized
async def show_crash_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Краш — это игра, в которой нужно выбрать множитель от x1.01 до x100k. Бот случайно останавливается от x1 до x100k.\n📊 Лимиты:\nRTP: ~97%\nМакс. множитель: х100,000\nМакс. ставка: 200kk m¢\nМакс. выигрыш: 2kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>📈 /crash [ставка] [1.01-100к]</u></b>\n\nПример: <code>/crash 100 1.1</code>\nПример: <code>краш 100 4</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@_localized
async def show_slots_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Слоты — это игра, где цель выбить три одинаковых символа на барабанах, запустив их вращение.\n📊 Лимиты:\nRTP: ~97%\nМакс. множитель: х15.5\nМакс. ставка: 300kk m¢\nМакс. выигрыш: 3kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🎰 /slots [ставка]</u></b>\n\nПример: <code>/slots 100</code>\nПример: <code>слоты 100</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@_localized
async def show_bowling_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Боулинг — это игра, в которой вам нужно сбить кегли, чтобы получить максимальный множитель.\n📊 Лимиты:\nRTP: ~97%\nМакс. множитель: х5.8\nМакс. ставка: 300kk m¢\nМакс. выигрыш: 1.74kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🎳 /bowling [ставка]</u></b>\n\nПример: <code>/bowling 100</code>\nПример: <code>боулинг 100</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@_localized
async def show_dice_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Кубик — быстрая игра на Telegram-кубике 🎲. Выберите точное число или исход броска.\n📊 Множители:\n1 / 2 / 3 / 4 / 5 / 6 — х5.8\nБольше 3-х — х1.97\nМеньше 3-х — х2.32\nРавно 3 — х5.8\nЧёт / Нечёт — х2.23\n\nЛимиты:\nМакс. ставка: 300kk m¢\nМакс. выигрыш: 1.74kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🎲 /dice [ставка] [исход]</u></b>\n\nПример: <code>/dice 100 чёт</code>\nПример: <code>кубик 100 больше 3</code>\nПример: <code>кубик 100</code> — выбрать исход кнопками', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@_localized
async def show_coin_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Монетка — быстрая игра Орёл/Решка. Выберите сторону, бот подбросит монету стикером и через 5 секунд покажет итог.\n📊 Множители:\nОрёл — х1.97\nРешка — х1.97\n\nЛимиты:\nМакс. ставка: 300kk m¢\nМакс. выигрыш: 1.74kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🪙 /coin [ставка] [орёл/решка]</u></b>\n\nПример: <code>/coin 100 орёл</code>\nПример: <code>монета 100 р</code>\nПример: <code>монета 100</code> — выбрать сторону кнопками', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@_localized
async def show_roulette_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Рулетка — режим игры с 37 числами: 0-36. Выберите число, цвет, ряд, дюжину, блок или стрит.\n📊 Множители:\nЧисло — х35\nКрасный / Чёрный / Чёт / Нечёт / Малые / Большие — х1.97\nДюжины и ряды — х2.9\nБлоки — х8.7\nСтрит — х11.6\n\nЛимиты:\nМакс. ставка: 300kk m¢\nМакс. выигрыш: 10.5kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🎱 /roulette [ставка] [исход]</u></b>\n\nПример: <code>рулетка 100 ч</code> — чёрный\nПример: <code>рулетка 1кк 1,2,3</code> — стрит\nПример: <code>рулетка пол</code> — выбрать исход кнопками', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_modes",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@_localized
async def show_chest_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Сундук — быстрая игра, где нужно выбрать один из 9 ящиков.\nВ одном ящике лежит приз x3, в двух ящиках — x1, остальные пустые x0.\n\n📊 Лимиты:\nМакс. множитель: х3\nМакс. ставка: 300kk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🧰 /chest [ставка]</u></b>\n\nПример: <code>/chest 100</code>\nПример: <code>сундук 10</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@_localized
async def show_scratch_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Скретч — быстрая лотерейка на 6 ячеек. Открывайте клетки по одной или сразу всё поле.\n📊 Комбинации:\n3 вишни — х2\n3 алмаза — х10\n\nЛимиты:\nМакс. ставка: 300kk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🎫 /scratch [ставка]</u></b>\n\nПример: <code>/scratch 100</code>\nПример: <code>скретч 100</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
    else:
        try:
            await message_or_callback.message.edit_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        except Exception:
            await message_or_callback.message.answer(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)


@_localized
async def show_fishing_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Рыбалка — быстрая игра: забросьте удочку и получите случайный улов.\n📊 Исходы:\nРыба — х2\nРыба сорвалась — х0\nБанка — х0.08\nБанка — х0.5\n\nЛимиты:\nМакс. ставка: 300kk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🎣 /fishing [ставка]</u></b>\n\nПример: <code>/fishing 100</code>\nПример: <code>рыбалка 10</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )



@dp.callback_query(_inline_filter(lambda c: c.data == "catalog_main"))
@_localized
async def process_catalog_main(callback: types.CallbackQuery):
    await callback.answer()
    is_group = callback.message.chat.type in ["group", "supergroup"]
    await show_catalog(callback, callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), callback.message.chat.id, is_group, edit=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "catalog_fast"))
@_localized
async def process_catalog_fast(callback: types.CallbackQuery):
    await callback.answer()
    is_group = callback.message.chat.type in ["group", "supergroup"]
    await show_fast_games_catalog(callback, callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), callback.message.chat.id, is_group)


@dp.callback_query(_inline_filter(lambda c: c.data == "catalog_modes"))
@_localized
async def process_catalog_modes(callback: types.CallbackQuery):
    await callback.answer()
    is_group = callback.message.chat.type in ["group", "supergroup"]
    await show_modes_games_catalog(callback, callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), callback.message.chat.id, is_group)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_slots"))
@_localized
async def process_info_slots(callback: types.CallbackQuery):
    await callback.answer()
    await show_slots_info(callback, callback.from_user.id, is_callback=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_chest"))
@_localized
async def process_info_chest(callback: types.CallbackQuery):
    await callback.answer()
    await show_chest_info(callback, callback.from_user.id, is_callback=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_fishing"))
@_localized
async def process_info_fishing(callback: types.CallbackQuery):
    await callback.answer()
    await show_fishing_info(callback, callback.from_user.id, is_callback=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_scratch"))
@_localized
async def process_info_scratch(callback: types.CallbackQuery):
    await callback.answer()
    await show_scratch_info(callback, callback.from_user.id, is_callback=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_bowling"))
@_localized
async def process_info_bowling(callback: types.CallbackQuery):
    await callback.answer()
    await show_bowling_info(callback, callback.from_user.id, is_callback=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_dice"))
@_localized
async def process_info_dice(callback: types.CallbackQuery):
    await callback.answer()
    await show_dice_info(callback, callback.from_user.id, is_callback=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_coin"))
@_localized
async def process_info_coin(callback: types.CallbackQuery):
    await callback.answer()
    await show_coin_info(callback, callback.from_user.id, is_callback=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_roulette"))
@_localized
async def process_info_roulette(callback: types.CallbackQuery):
    await callback.answer()
    await show_roulette_info(callback, callback.from_user.id, is_callback=True)


@_localized
async def show_darts_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Дартс — это игра, в которой нужно попасть в центр мишени, чтобы получить максимальный множитель.\n📊 Лимиты:\nRTP: ~97%\nМакс. множитель: х5.8\nМакс. ставка: 300kk m¢\nМакс. выигрыш: 1.74kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🎯 /darts [ставка]</u></b>\n\nПример: <code>/darts 100</code>\nПример: <code>дартс 100 мимо</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@dp.callback_query(_inline_filter(lambda c: c.data == "info_darts"))
@_localized
async def process_info_darts(callback: types.CallbackQuery):
    await callback.answer()
    await show_darts_info(callback, callback.from_user.id, is_callback=True)


@_localized
async def show_basketball_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Баскетбол — это игра, где нужно попасть в кольцо, чтобы получить максимальный множитель.\n📊 Лимиты:\nRTP: ~96%\nМакс. множитель: х4.8\nМакс. ставка: 300kk m¢\nМакс. выигрыш: 1.44kkk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>🏀 /basketball [ставка]</u></b>\n\nПример: <code>/basketball 100</code>\nПример: <code>баскетбол 100</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@dp.callback_query(_inline_filter(lambda c: c.data == "info_basketball"))
@_localized
async def process_info_basketball(callback: types.CallbackQuery):
    await callback.answer()
    await show_basketball_info(callback, callback.from_user.id, is_callback=True)


@_localized
async def show_football_info(message_or_callback, user_id, is_callback=False):
    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        user_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        user_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(user_name)}</a>'

    text = (
        _lf('<blockquote expandable><i><tg-emoji emoji-id="5307594157739515229">ℹ️</tg-emoji> Футбол — это игра, в которой нужно предсказать, попадет ли мяч в ворота или пролетит мимо, чтобы получить выигрыш.\n📊 Лимиты:\nRTP: ~96%\nМакс. множитель: х2.4\nМакс. ставка: 300kk m¢\nМакс. выигрыш: 720kk m¢</i></blockquote>\n\n<i><tg-emoji emoji-id="5372981976804366741">🤖</tg-emoji> {0}, чтобы начать игру, используй команду:</i>\n\n<b><u>⚽️ /football [ставка] [гол/мимо]</u></b>\n\nПример: <code>/football 100</code>\nПример: <code>футбол 100 гол</code>', (_fmt(user_link, '', -1),))
    )

    keyboard = None
    if is_callback:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data="catalog_fast",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )

    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    else:
        try:
            await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )


@dp.callback_query(_inline_filter(lambda c: c.data == "info_football"))
@_localized
async def process_info_football(callback: types.CallbackQuery):
    await callback.answer()
    await show_football_info(callback, callback.from_user.id, is_callback=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "info_crash"))
@_localized
async def process_info_crash(callback: types.CallbackQuery):
    await callback.answer()
    await show_crash_info(callback, callback.from_user.id, is_callback=True)



@_localized
async def start_mines_game_from_command(message, user_id, chat_id, bet, mine_count):
    key = get_chat_key(user_id, chat_id)
    if key in user_messages:
        await _delete_messages(chat_id, user_messages[key], bot)
        user_messages[key] = []

    game_id = get_next_game_id()

    user_data = get_user(user_id)
    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    now = datetime.now()
    game_data = {
        "type": "mines",
        "stage": "playing",
        "bet": bet,
        "mine_count": mine_count,
        "mine_positions": generate_mines(mine_count),
        "revealed": set(),
        "level": 0,
        "game_over": False,
        "won": False,
        "exploded_mine": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "cashed_out": False,
        "bet_placed": False,
        "moves_count": 0,
        "created_at": now,
        "created_at_str": now.strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    await show_mines_grid_from_message(message, user_id, game_id)


@_localized
async def show_mines_grid_from_message(message, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        await message.answer(_l('<i>Игра не найдена!</i>'), parse_mode=ParseMode.HTML)
        return

    if game["owner_id"] != user_id:
        return

    mine_count = game["mine_count"]
    bet = game["bet"]
    revealed = game["revealed"]
    mine_positions = game["mine_positions"]
    level = game["level"]
    exploded_mine = game.get("exploded_mine")

    user_link = _lf('<a href="tg://user?id={0}">{1}</a>', (_fmt(user_id, '', -1), _fmt(html.escape(get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок')), '', -1)))
    multiplier = get_multiplier(mine_count, level)
    win_amount = int(bet * multiplier)

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + bet)
            add_game_history(user_id, "mines", bet, "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "mines", bet, "win", win_amount, game.get("created_at_str"))

    if game_over and exploded_mine is not None:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5469785308386041323">💥</tg-emoji> <b>Мины · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Открыто:</b> {3} из {4}\n\n<blockquote><i><tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji>Мог забрать: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢</i></blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(len(revealed) - 1, '', -1), _fmt(TOTAL_CELLS - mine_count, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    elif won:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Мины · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Открыто:</b> {3} из {4}\n\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Выигрыш: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(len(revealed), '', -1), _fmt(TOTAL_CELLS - mine_count, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    else:
        multiplier = get_multiplier(mine_count, level)

        if level == 0:
            text = (
                _lf('{0}\n<b><tg-emoji emoji-id="5247011187308140698">🧨</tg-emoji>Мины • начни игру!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(get_multiplier(mine_count, level + 1), f'.2f', -1)))
            )
        else:
            win_amount = int(bet * multiplier)
            next_multiplier = get_multiplier(mine_count, level + 1)
            text = (
                _lf('{0}\n<b><tg-emoji emoji-id="5307594157739515229">💎</tg-emoji>Мины • игра идёт.</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji><b>Выигрыш:</b> <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x / {4} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1), _fmt(next_multiplier, f'.2f', -1)))
            )

    grid_buttons = []
    for row in range(GRID_SIZE):
        row_buttons = []
        for col in range(GRID_SIZE):
            idx = row * GRID_SIZE + col

            if game_over or won:
                if idx == exploded_mine:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5276032951342088188"
                        )
                    )
                elif idx in mine_positions:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5469654973308476699"
                        )
                    )
                elif idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💎",
                            callback_data=f"noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"noop_{game_id}",
                            icon_custom_emoji_id="5436113877181941026"
                        )
                    )
            else:
                if idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💎",
                            callback_data=f"noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"cell_{game_id}_{idx}",
                            icon_custom_emoji_id="5436113877181941026"
                        )
                    )
        grid_buttons.append(row_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=grid_buttons)

    if game_over or won:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_game_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])
    else:
        if len(revealed) > 0:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=_l('Забрать выигрыш'),
                    callback_data=f"cashout_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5427009714745517609"
                )
            ])
        else:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=_l('Назад'),
                    callback_data=f"exit_game_{game_id}",
                    icon_custom_emoji_id="5255703720078879038"
                )
            ])

    msg = None
    try:
        msg = await message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = True
    except Exception:
        msg = await message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = False

    game["message_id"] = msg.message_id

    key = get_chat_key(user_id, game["chat_id"])
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)



@_localized
async def start_tower_game_from_command(message, user_id, chat_id, bet, mine_count):
    key = get_chat_key(user_id, chat_id)
    if key in user_messages:
        await _delete_messages(chat_id, user_messages[key], bot)
        user_messages[key] = []

    game_id = get_next_game_id()

    user_data = get_user(user_id)
    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    now = datetime.now()
    game_data = {
        "type": "tower",
        "stage": "playing",
        "bet": bet,
        "mine_count": mine_count,
        "mine_positions": generate_tower_mines(mine_count),
        "revealed": set(),
        "level": 0,
        "game_over": False,
        "won": False,
        "exploded_mine": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "cashed_out": False,
        "bet_placed": False,
        "moves_count": 0,
        "created_at": now,
        "created_at_str": now.strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    await show_tower_grid_from_message(message, user_id, game_id)


@_localized
async def show_tower_grid_from_message(message, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        await message.answer(_l('<i>Игра не найдена!</i>'), parse_mode=ParseMode.HTML)
        return

    if game["owner_id"] != user_id:
        return

    mine_count = game["mine_count"]
    bet = game["bet"]
    revealed = game["revealed"]
    mine_positions = game["mine_positions"]
    level = game["level"]
    exploded_mine = game.get("exploded_mine")
    hide_demo_mines = bool(game.get("demo_mode") or DEMO_GAME_CONTEXT.get())

    user_link = _lf('<a href="tg://user?id={0}">{1}</a>', (_fmt(user_id, '', -1), _fmt(html.escape(get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок')), '', -1)))
    multiplier = get_tower_multiplier(mine_count, level)
    win_amount = int(bet * multiplier)

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + bet)
            add_game_history(user_id, "tower", bet, "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "tower", bet, "win", win_amount, game.get("created_at_str"))

    if game_over and exploded_mine is not None:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5469785308386041323">💥</tg-emoji> <b>Башня · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<blockquote><i><tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji>Мог забрать: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢</i></blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(TOWER_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    elif won:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Башня · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Выигрыш: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(TOWER_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    else:
        if level == 0:
            text = (
                _lf('{0}\n<b>🛕Башня · начни игру!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(get_tower_multiplier(mine_count, level + 1), f'.2f', -1)))
            )
        else:
            text = (
                _lf('{0}\n<b>🛕Башня · игра идёт.</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(TOWER_ROWS, '', -1), _fmt(get_tower_multiplier(mine_count, level + 1), f'.2f', -1)))
            )

    grid_buttons = []

    display_max_row = min(level, TOWER_ROWS - 1)
    for row in range(display_max_row, -1, -1):
        row_buttons = []
        for col in range(TOWER_COLS):
            idx = row * TOWER_COLS + col
            if game_over or won:
                if idx == exploded_mine:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"tower_noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5276032951342088188"
                        )
                    )
                elif not hide_demo_mines and col in mine_positions[row]:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"tower_noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5469654973308476699"
                        )
                    )
                elif idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💎",
                            callback_data=f"tower_noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"tower_noop_{game_id}",
                            icon_custom_emoji_id="5436113877181941026"
                        )
                    )
            else:
                if idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💎",
                            callback_data=f"tower_noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    if row == level:
                        row_buttons.append(
                            InlineKeyboardButton(
                                text=" ",
                                callback_data=f"tower_cell_{game_id}_{row}_{col}",
                                icon_custom_emoji_id="5436113877181941026"
                            )
                        )
                    else:
                        row_buttons.append(
                            InlineKeyboardButton(
                                text=" ",
                                callback_data=f"tower_noop_{game_id}",
                                icon_custom_emoji_id="5436113877181941026"
                            )
                        )
        grid_buttons.append(row_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=grid_buttons)

    if game_over or won:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_tower_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])
    else:
        if level > 0:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=_l('Забрать выигрыш'),
                    callback_data=f"tower_cashout_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5427009714745517609"
                )
            ])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_tower_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])

    msg = None
    try:
        msg = await message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = True
    except Exception:
        msg = await message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = False

    game["message_id"] = msg.message_id

    key = get_chat_key(user_id, game["chat_id"])
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)



def get_qwak_next_multiplier(level: int):
    if level >= QWAK_ROWS:
        return get_qwak_multiplier(level)
    return get_qwak_multiplier(level + 1)


def get_qwak_current_col(game: dict):
    level = int(game.get("level", 1) or 1)
    current_row = max(0, min(QWAK_ROWS - 1, level - 1))
    for idx in game.get("revealed", set()):
        try:
            idx = int(idx)
        except Exception:
            continue
        if idx // QWAK_COLS == current_row:
            return idx % QWAK_COLS
    return QWAK_START_COL


@_localized
def build_qwak_view(user_id: int, user_name: str, game_id: int, game: dict, game_over=False, won=False):
    user_name = get_user_display_name(user_id, user_name)
    bet = game["bet"]
    revealed = game.get("revealed", set())
    mine_positions = game.get("mine_positions", generate_qwak_mines())
    level = int(game.get("level", 1) or 1)
    exploded_mine = game.get("exploded_mine")

    clean_user_name = html.escape(user_name or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{clean_user_name}</a>'
    multiplier = get_qwak_multiplier(level)
    win_amount = int(bet * multiplier)
    next_mult = get_qwak_next_multiplier(level)
    next_win = int(bet * next_mult)

    if game_over and exploded_mine is not None:
        title = _l('<tg-emoji emoji-id="5469785308386041323">💥</tg-emoji> <b>Квак · Проигрыш!</b>')
        body = (
            _lf('<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {0} m¢\n{1} <b>Этаж:</b> {2} из {3}\n\n<blockquote><i><tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji>Мог забрать: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{4}x / {5} m¢</i></blockquote>', (_fmt(format_number(bet), '', -1), _fmt(QWAK_PAD_EMOJI, '', -1), _fmt(min(level, QWAK_ROWS), '', -1), _fmt(QWAK_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    elif won:
        title = _l('<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Квак · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>')
        body = (
            _lf('<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {0} m¢\n{1} <b>Этаж:</b> {2} из {3}\n\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Выигрыш: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{4}x / {5} m¢', (_fmt(format_number(bet), '', -1), _fmt(QWAK_PAD_EMOJI, '', -1), _fmt(min(level, QWAK_ROWS), '', -1), _fmt(QWAK_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    else:
        title = _lf('{0}<b>Квак · начни игру!</b>', (_fmt(QWAK_PAD_EMOJI, '', -1),)) if level <= 1 else _lf('{0}<b>Квак · игра идёт.</b>', (_fmt(QWAK_PAD_EMOJI, '', -1),))
        body = (
            _lf('<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {0} m¢\n{1} <b>Этаж:</b> {2} из {3}\n<blockquote>{4} Сл. кувшин: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢</blockquote>', (_fmt(format_number(bet), '', -1), _fmt(QWAK_PAD_EMOJI, '', -1), _fmt(level, '', -1), _fmt(QWAK_ROWS, '', -1), _fmt(QWAK_PAD_EMOJI, '', -1), _fmt(next_mult, f'.2f', -1), _fmt(format_number(next_win), '', -1)))
        )

    text = (
        f'{user_link}\n'
        f'{title}\n'
        '<code>·····················</code>\n'
        f'{body}'
    )

    grid_buttons = []
    current_col = get_qwak_current_col(game)
    for row in range(QWAK_ROWS - 1, -1, -1):
        row_buttons = []
        for col in range(QWAK_COLS):
            idx = row * QWAK_COLS + col
            text_btn = " "
            callback_data = f"qwak_noop_{game_id}"
            style = None
            icon_id = QWAK_PAD_EMOJI_ID

            if game_over or won:
                if idx == exploded_mine:
                    icon_id = QWAK_BOOM_EMOJI_ID
                    style = "danger"
                elif col in mine_positions[row]:
                    icon_id = QWAK_MINE_EMOJI_ID
                    style = "danger"
                elif idx in revealed:
                    if row == max(0, min(QWAK_ROWS - 1, level - 1)) and col == current_col:
                        text_btn = "🐸"
                        icon_id = QWAK_PAD_EMOJI_ID
                    else:
                        icon_id = QWAK_SUCCESS_EMOJI_ID
                    style = "success"
                else:
                    icon_id = QWAK_PAD_EMOJI_ID
            else:
                if row < level:
                    if idx in revealed and row == level - 1 and col == current_col:
                        text_btn = "🐸"
                        icon_id = QWAK_PAD_EMOJI_ID
                        style = "success"
                    elif idx in revealed:
                        icon_id = QWAK_SUCCESS_EMOJI_ID
                        style = "success"
                    else:
                        text_btn = "▪️"
                        icon_id = None
                elif row == level:
                    icon_id = QWAK_PAD_EMOJI_ID
                    callback_data = f"qwak_cell_{game_id}_{row}_{col}"
                else:
                    icon_id = QWAK_PAD_EMOJI_ID

            kwargs = {"text": text_btn, "callback_data": callback_data}
            if style:
                kwargs["style"] = style
            if icon_id:
                kwargs["icon_custom_emoji_id"] = icon_id
            row_buttons.append(InlineKeyboardButton(**kwargs))
        grid_buttons.append(row_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=grid_buttons)
    if game_over or won:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=_l('Назад'), callback_data=f"exit_qwak_{game_id}", icon_custom_emoji_id="5255703720078879038")
        ])
    else:
        if level > 1:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=_l('Забрать выигрыш'), callback_data=f"qwak_cashout_{game_id}", style="success", icon_custom_emoji_id="5427009714745517609")
            ])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=_l('Назад'), callback_data=f"exit_qwak_{game_id}", icon_custom_emoji_id="5255703720078879038")
        ])
    return text, keyboard


@_localized
async def start_qwak_game_from_command(message, user_id, chat_id, bet):
    key = get_chat_key(user_id, chat_id)
    if key in user_messages:
        await _delete_messages(chat_id, user_messages[key], bot)
        user_messages[key] = []

    game_id = get_next_game_id()

    user_data = get_user(user_id)
    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    now = datetime.now()
    game_data = {
        "type": "qwak",
        "stage": "playing",
        "bet": bet,
        "mine_count": 0,
        "mine_positions": generate_qwak_mines(),
        "revealed": {QWAK_START_COL},
        "level": 1,
        "game_over": False,
        "won": False,
        "exploded_mine": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "cashed_out": False,
        "bet_placed": False,
        "moves_count": 0,
        "created_at": now,
        "created_at_str": now.strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    await show_qwak_grid_from_message(message, user_id, game_id)


@_localized
async def show_qwak_grid_from_message(message, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        await message.answer(_l('<i>Игра не найдена!</i>'), parse_mode=ParseMode.HTML)
        return

    if game["owner_id"] != user_id:
        return

    level = int(game.get("level", 1) or 1)
    multiplier = get_qwak_multiplier(level)
    win_amount = int(game["bet"] * multiplier)
    exploded_mine = game.get("exploded_mine")

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + game["bet"])
            add_game_history(user_id, "qwak", game["bet"], "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "qwak", game["bet"], "win", win_amount, game.get("created_at_str"))

    text, keyboard = build_qwak_view(user_id, get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок'), game_id, game, game_over=game_over, won=won)

    msg = None
    try:
        msg = await message.edit_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        game["is_edited"] = True
    except Exception:
        msg = await message.answer(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        game["is_edited"] = False

    game["message_id"] = msg.message_id
    key = get_chat_key(user_id, game["chat_id"])
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)


@_localized
async def show_qwak_grid_from_callback(callback, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        return

    level = int(game.get("level", 1) or 1)
    multiplier = get_qwak_multiplier(level)
    win_amount = int(game["bet"] * multiplier)
    exploded_mine = game.get("exploded_mine")

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + game["bet"])
            add_game_history(user_id, "qwak", game["bet"], "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "qwak", game["bet"], "win", win_amount, game.get("created_at_str"))

    text, keyboard = build_qwak_view(user_id, get_user_display_name(user_id, callback.from_user.first_name) or _l('Игрок'), game_id, game, game_over=game_over, won=won)

    msg = None
    try:
        msg = await callback.message.edit_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        game["is_edited"] = True
    except Exception:
        msg = await callback.message.answer(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True)
        game["is_edited"] = False

    game["message_id"] = msg.message_id
    key = get_chat_key(user_id, game["chat_id"])
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)



@_localized
async def start_diamonds_game_from_command(message, user_id, chat_id, bet, mine_count):
    key = get_chat_key(user_id, chat_id)
    if key in user_messages:
        await _delete_messages(chat_id, user_messages[key], bot)
        user_messages[key] = []

    game_id = get_next_game_id()

    user_data = get_user(user_id)
    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    now = datetime.now()
    game_data = {
        "type": "diamonds",
        "stage": "playing",
        "bet": bet,
        "mine_count": mine_count,
        "mine_positions": generate_diamonds_mines(mine_count),
        "revealed": set(),
        "level": 0,
        "game_over": False,
        "won": False,
        "exploded_mine": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "cashed_out": False,
        "bet_placed": False,
        "moves_count": 0,
        "created_at": now,
        "created_at_str": now.strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    await show_diamonds_grid_from_message(message, user_id, game_id)


@_localized
async def show_diamonds_grid_from_message(message, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        await message.answer(_l('<i>Игра не найдена!</i>'), parse_mode=ParseMode.HTML)
        return

    if game["owner_id"] != user_id:
        return

    mine_count = game["mine_count"]
    bet = game["bet"]
    revealed = game["revealed"]
    mine_positions = game["mine_positions"]
    level = game["level"]
    exploded_mine = game.get("exploded_mine")

    user_link = _lf('<a href="tg://user?id={0}">{1}</a>', (_fmt(user_id, '', -1), _fmt(html.escape(get_user_display_name(user_id, message.from_user.first_name) or _l('Игрок')), '', -1)))
    multiplier = get_diamonds_multiplier(mine_count, level)
    win_amount = int(bet * multiplier)

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + bet)
            add_game_history(user_id, "diamonds", bet, "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "diamonds", bet, "win", win_amount, game.get("created_at_str"))

    if game_over and exploded_mine is not None:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5469785308386041323">💥</tg-emoji> <b>Алмазы · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<blockquote><i><tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji>Мог забрать: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢</i></blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(DIAMONDS_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    elif won:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Алмазы · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Выигрыш: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(DIAMONDS_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    else:
        if level == 0:
            text = (
                _lf('{0}\n<b><tg-emoji emoji-id="5307594157739515229">💠</tg-emoji>Алмазы · начни игру!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(get_diamonds_multiplier(mine_count, level + 1), f'.2f', -1)))
            )
        else:
            win_amount = int(bet * multiplier)
            next_multiplier = get_diamonds_multiplier(mine_count, level + 1)
            text = (
                _lf('{0}\n<b><tg-emoji emoji-id="5307594157739515229">💠</tg-emoji>Алмазы · игра идёт!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji><b>Выигрыш:</b> <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x / {4} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1), _fmt(next_multiplier, f'.2f', -1)))
            )

    grid_buttons = []

    for row in range(0, level + 1 if not (game_over or won) else min(level + 1, DIAMONDS_ROWS)):
        row_buttons = []
        for col in range(DIAMONDS_COLS):
            idx = row * DIAMONDS_COLS + col
            if game_over or won:
                if idx == exploded_mine:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"diamonds_noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5276032951342088188"
                        )
                    )
                elif col in mine_positions[row]:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"diamonds_noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5469654973308476699"
                        )
                    )
                elif idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💠",
                            callback_data=f"diamonds_noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"diamonds_noop_{game_id}",
                            icon_custom_emoji_id="5436113877181941026"
                        )
                    )
            else:
                if idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💠",
                            callback_data=f"diamonds_noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    if row == level:
                        row_buttons.append(
                            InlineKeyboardButton(
                                text=" ",
                                callback_data=f"diamonds_cell_{game_id}_{row}_{col}",
                                icon_custom_emoji_id="5436113877181941026"
                            )
                        )
                    else:
                        row_buttons.append(
                            InlineKeyboardButton(
                                text=" ",
                                callback_data=f"diamonds_noop_{game_id}",
                                icon_custom_emoji_id="5436113877181941026"
                            )
                        )
        grid_buttons.append(row_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=grid_buttons)

    if game_over or won:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_diamonds_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])
    else:
        if level > 0:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=_l('Забрать выигрыш'),
                    callback_data=f"diamonds_cashout_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5427009714745517609"
                )
            ])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_diamonds_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])

    msg = None
    try:
        msg = await message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = True
    except Exception:
        msg = await message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = False

    game["message_id"] = msg.message_id

    key = get_chat_key(user_id, game["chat_id"])
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)



@dp.callback_query(_inline_filter(lambda c: c.data == "tower"))
@_localized
async def process_tower_start(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    key = get_chat_key(user_id, chat_id)
    if key in game_messages:
        await _delete_messages(chat_id, game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=chat_id, message_id=callback.message.message_id)
    except Exception:
        pass

    game_id = get_next_game_id()

    game_data = {
        "type": "tower_select",
        "stage": "select_mines",
        "bet": 10,
        "mine_count": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "moves_count": 0,
        "created_at": datetime.now(),
        "created_at_str": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    clean_user_name = html.escape(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{clean_user_name}</a>'

    text = (
        _lf('{0}\n🛕<b>Башня · выбери количество мин!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: 10 m¢', (_fmt(user_link, '', -1),))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣", callback_data=f"tower_count_{game_id}_1"),
                InlineKeyboardButton(text="2️⃣", callback_data=f"tower_count_{game_id}_2"),
                InlineKeyboardButton(text="3️⃣", callback_data=f"tower_count_{game_id}_3"),
                InlineKeyboardButton(text="4️⃣", callback_data=f"tower_count_{game_id}_4")
            ],
            [
                InlineKeyboardButton(
                    text=_l('Назад'),
                    callback_data=f"tower_back_to_catalog_{game_id}",
                    icon_custom_emoji_id="5255703720078879038"
                )
            ]
        ]
    )

    msg = await callback.message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

    games[game_id]["message_id"] = msg.message_id

    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("tower_count_")))
@_localized
async def process_tower_count(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-2])
        count = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("stage") != "select_mines":
        await callback.answer(_l('Выберите количество мин!'), show_alert=True)
        return

    await callback.answer()

    now = datetime.now()
    game["mine_count"] = count
    game["stage"] = "playing"
    game["type"] = "tower"
    game["mine_positions"] = generate_tower_mines(count)
    game["revealed"] = set()
    game["level"] = 0
    game["game_over"] = False
    game["won"] = False
    game["exploded_mine"] = None
    game["cashed_out"] = False
    game["bet_placed"] = False
    game["moves_count"] = 0
    game["created_at"] = now
    game["created_at_str"] = now.strftime("%d-%m-%Y %H:%M:%S")
    game["settled"] = False
    game["expired"] = False
    save_active_game_to_db(game_id, game)

    key = get_chat_key(user_id, game["chat_id"])
    if key in game_messages:
        await _delete_messages(game["chat_id"], game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=game["chat_id"], message_id=callback.message.message_id)
    except Exception:
        pass

    await show_tower_grid_from_callback(callback, user_id, game_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("tower_cell_")))
@_localized
async def process_tower_cell_click(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 4:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-3])
        target_row = int(data[-2])
        cell_idx = int(data[-1])
    except (ValueError, IndexError):
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["stage"] != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    current_level = game["level"]
    if target_row != current_level:
        await callback.answer()
        return

    global_idx = current_level * TOWER_COLS + cell_idx

    if global_idx in game["revealed"]:
        await callback.answer(_l('Эта клетка уже открыта!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True

    try:
        await callback.answer()

        demo_round = bool(game.get("demo_mode") or DEMO_GAME_CONTEXT.get())
        if demo_round:
            safe_cells = game["mine_positions"][current_level]
            if isinstance(safe_cells, set):
                safe_cells.discard(cell_idx)
            else:
                safe_cells = set(safe_cells or [])
                safe_cells.discard(cell_idx)
                game["mine_positions"][current_level] = safe_cells
        is_mine = (not demo_round) and cell_idx in game["mine_positions"][current_level]

        game["revealed"].add(global_idx)
        game["level"] += 1
        game["moves_count"] = game.get("moves_count", 0) + 1
        game["bet_placed"] = True

        if is_mine:
            game["game_over"] = True
            game["exploded_mine"] = global_idx
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_tower_grid_from_callback(callback, user_id, game_id, game_over=True)
            return

        if game["level"] >= TOWER_ROWS:
            game["game_over"] = True
            game["won"] = True
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_tower_grid_from_callback(callback, user_id, game_id, won=True)
            return

        save_active_game_to_db(game_id, game)
        await show_tower_grid_from_callback(callback, user_id, game_id)
    finally:
        game["is_processing"] = False


@_localized
async def show_tower_grid_from_callback(callback, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        return

    mine_count = game["mine_count"]
    bet = game["bet"]
    revealed = game["revealed"]
    mine_positions = game["mine_positions"]
    level = game["level"]
    exploded_mine = game.get("exploded_mine")
    hide_demo_mines = bool(game.get("demo_mode") or DEMO_GAME_CONTEXT.get())

    clean_user_name = html.escape(get_user_display_name(user_id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{clean_user_name}</a>'
    multiplier = get_tower_multiplier(mine_count, level)
    win_amount = int(bet * multiplier)

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + bet)
            add_game_history(user_id, "tower", bet, "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "tower", bet, "win", win_amount, game.get("created_at_str"))

    if game_over and exploded_mine is not None:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5469785308386041323">💥</tg-emoji> <b>Башня · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<blockquote><i><tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji>Мог забрать: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢</i></blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(TOWER_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    elif won:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Башня · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Выигрыш: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(TOWER_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    else:
        if level == 0:
            text = (
                _lf('{0}\n<b>🛕Башня · начни игру!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(get_tower_multiplier(mine_count, level + 1), f'.2f', -1)))
            )
        else:
            text = (
                _lf('{0}\n<b>🛕Башня · игра идёт.</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(TOWER_ROWS, '', -1), _fmt(get_tower_multiplier(mine_count, level + 1), f'.2f', -1)))
            )

    grid_buttons = []

    display_max_row = min(level, TOWER_ROWS - 1)
    for row in range(display_max_row, -1, -1):
        row_buttons = []
        for col in range(TOWER_COLS):
            idx = row * TOWER_COLS + col
            if game_over or won:
                if idx == exploded_mine:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"tower_noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5276032951342088188"
                        )
                    )
                elif not hide_demo_mines and col in mine_positions[row]:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"tower_noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5469654973308476699"
                        )
                    )
                elif idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💎",
                            callback_data=f"tower_noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"tower_noop_{game_id}",
                            icon_custom_emoji_id="5436113877181941026"
                        )
                    )
            else:
                if idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💎",
                            callback_data=f"tower_noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    if row == level:
                        row_buttons.append(
                            InlineKeyboardButton(
                                text=" ",
                                callback_data=f"tower_cell_{game_id}_{row}_{col}",
                                icon_custom_emoji_id="5436113877181941026"
                            )
                        )
                    else:
                        row_buttons.append(
                            InlineKeyboardButton(
                                text=" ",
                                callback_data=f"tower_noop_{game_id}",
                                icon_custom_emoji_id="5436113877181941026"
                            )
                        )
        grid_buttons.append(row_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=grid_buttons)

    if game_over or won:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_tower_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])
    else:
        if level > 0:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=_l('Забрать выигрыш'),
                    callback_data=f"tower_cashout_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5427009714745517609"
                )
            ])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_tower_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])

    msg = None
    try:
        msg = await callback.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = True
    except Exception:
        msg = await callback.message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = False

    game["message_id"] = msg.message_id

    key = get_chat_key(user_id, game["chat_id"])
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("tower_cashout_")))
@_localized
async def process_tower_cashout(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена!'), show_alert=True)
        return

    if game.get("stage") != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    if game["level"] == 0:
        await callback.answer(_l('Откройте хотя бы одну клетку!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True

    try:
        await callback.answer()

        game["game_over"] = True
        game["won"] = True
        game["cashed_out"] = True
        if user_id in active_games and active_games.get(user_id) == game_id:
            del active_games[user_id]
        remove_active_game_from_db(game_id)

        await show_tower_grid_from_callback(callback, user_id, game_id, won=True)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("exit_tower_")))
@_localized
async def process_exit_tower(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[2])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game.get("bet_placed", False) or len(game.get("revealed", set())) > 0 or game.get("level", 0) > 0:
        await callback.answer(_l('Нельзя отменить начатую игру! Нажмите «Забрать выигрыш».'), show_alert=True)
        return

    key = f"exit_{user_id}_{game_id}"
    current_time = datetime.now().timestamp()

    if key in exit_confirm:
        if current_time - exit_confirm[key] < 10:
            user_data = get_user(user_id)
            update_user(user_id, balance=user_data["balance"] + game["bet"])

            try:
                await callback.bot.delete_message(chat_id=game["chat_id"], message_id=game["message_id"])
            except Exception:
                pass

            if game_id in games:
                del games[game_id]
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            if key in exit_confirm:
                del exit_confirm[key]
            remove_active_game_from_db(game_id)

            await callback.message.edit_text(
                _lf('<i>✅ Игра отменена. Ставка {0} mCoin возвращена на баланс.</i>', (_fmt(format_number(game['bet']), '', -1),)),
                parse_mode=ParseMode.HTML
            )

            await callback.answer(_l('Игра отменена!'))
            return
        else:
            del exit_confirm[key]

    exit_confirm[key] = current_time
    await callback.answer(_l('⚠️ Если вы хотите отменить игру, нажмите ещё раз на кнопку назад.'), show_alert=True)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("tower_back_to_catalog_")))
@_localized
async def process_tower_back_to_catalog(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if game and game["owner_id"] == user_id:
        if game_id in games:
            del games[game_id]
        if user_id in active_games and active_games.get(user_id) == game_id:
            del active_games[user_id]
        remove_active_game_from_db(game_id)

    await callback.answer()

    key = get_chat_key(user_id, callback.message.chat.id)
    if key in game_messages:
        await _delete_messages(callback.message.chat.id, game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    except Exception:
        pass

    is_group = callback.message.chat.type in ["group", "supergroup"]
    await show_catalog(callback, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), callback.message.chat.id, is_group)



@dp.callback_query(_inline_filter(lambda c: c.data == "qwak"))
@_localized
async def process_qwak_start(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    bet = 10
    user_data = get_user(user_id)
    if user_data["balance"] < bet:
        await callback.message.answer(_lf('<i>Недостаточно средств! Ваш баланс: {0} mCoin</i>', (_fmt(format_number(user_data['balance']), '', -1),)), parse_mode=ParseMode.HTML)
        return

    key = get_chat_key(user_id, chat_id)
    if key in game_messages:
        await _delete_messages(chat_id, game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=chat_id, message_id=callback.message.message_id)
    except Exception:
        pass

    await start_qwak_game_from_command(callback.message, user_id, chat_id, bet)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("qwak_cell_")))
@_localized
async def process_qwak_cell_click(callback: types.CallbackQuery):
    data = callback.data.split("_")
    if len(data) < 4:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-3])
        target_row = int(data[-2])
        cell_idx = int(data[-1])
    except (ValueError, IndexError):
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game.get("stage") != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    current_level = int(game.get("level", 1) or 1)
    if target_row != current_level:
        await callback.answer()
        return

    global_idx = current_level * QWAK_COLS + cell_idx
    if global_idx in game.get("revealed", set()):
        await callback.answer(_l('Эта клетка уже открыта!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True
    try:
        await callback.answer()

        is_mine = (not DEMO_GAME_CONTEXT.get()) and cell_idx in game["mine_positions"][current_level]
        game.setdefault("revealed", set()).add(global_idx)
        game["level"] = current_level + 1
        game["moves_count"] = game.get("moves_count", 0) + 1
        game["bet_placed"] = True

        if is_mine:
            game["game_over"] = True
            game["exploded_mine"] = global_idx
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_qwak_grid_from_callback(callback, user_id, game_id, game_over=True)
            return

        if game["level"] >= QWAK_ROWS:
            game["game_over"] = True
            game["won"] = True
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_qwak_grid_from_callback(callback, user_id, game_id, won=True)
            return

        save_active_game_to_db(game_id, game)
        await show_qwak_grid_from_callback(callback, user_id, game_id)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("qwak_cashout_")))
@_localized
async def process_qwak_cashout(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена!'), show_alert=True)
        return

    if game.get("stage") != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    if int(game.get("level", 1) or 1) <= 1:
        await callback.answer(_l('Сделайте хотя бы один прыжок!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True
    try:
        await callback.answer()
        game["game_over"] = True
        game["won"] = True
        game["cashed_out"] = True
        if user_id in active_games and active_games.get(user_id) == game_id:
            del active_games[user_id]
        remove_active_game_from_db(game_id)
        await show_qwak_grid_from_callback(callback, user_id, game_id, won=True)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("exit_qwak_")))
@_localized
async def process_exit_qwak(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False) or game.get("settled", False):
        try:
            await callback.message.delete()
        except Exception:
            pass
        if game_id in games:
            del games[game_id]
        await callback.answer()
        return

    if game.get("bet_placed", False) or int(game.get("level", 1) or 1) > 1:
        await callback.answer(_l('Нельзя отменить начатую игру! Нажмите «Забрать выигрыш».'), show_alert=True)
        return

    key = f"exit_qwak_{user_id}_{game_id}"
    current_time = datetime.now().timestamp()
    if key in exit_confirm:
        if current_time - exit_confirm[key] < 10:
            user_data = get_user(user_id)
            update_user(user_id, balance=user_data["balance"] + game["bet"])
            try:
                await callback.bot.delete_message(chat_id=game["chat_id"], message_id=game.get("message_id") or callback.message.message_id)
            except Exception:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
            if game_id in games:
                del games[game_id]
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            if key in exit_confirm:
                del exit_confirm[key]
            remove_active_game_from_db(game_id)
            await callback.answer(_l('Игра отменена!'))
            return
        else:
            del exit_confirm[key]

    exit_confirm[key] = current_time
    await callback.answer(_l('⚠️ Если вы хотите отменить игру, нажмите ещё раз на кнопку назад.'), show_alert=True)



@dp.callback_query(_inline_filter(lambda c: c.data.startswith("cell_")))
@_localized
async def process_cell_click(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[1])
        cell_idx = int(data[2])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["stage"] != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    if cell_idx in game["revealed"]:
        await callback.answer(_l('Эта клетка уже открыта!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True

    try:
        await callback.answer()

        game["revealed"].add(cell_idx)
        game["level"] += 1
        game["moves_count"] = game.get("moves_count", 0) + 1
        game["bet_placed"] = True

        if (not DEMO_GAME_CONTEXT.get()) and cell_idx in game["mine_positions"]:
            game["game_over"] = True
            game["exploded_mine"] = cell_idx
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_mines_grid_from_callback(callback, user_id, game_id, game_over=True)
            return

        if len(game["revealed"]) == TOTAL_CELLS - game["mine_count"]:
            game["game_over"] = True
            game["won"] = True
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_mines_grid_from_callback(callback, user_id, game_id, won=True)
            return

        save_active_game_to_db(game_id, game)
        await show_mines_grid_from_callback(callback, user_id, game_id)
    finally:
        game["is_processing"] = False


@_localized
async def show_mines_grid_from_callback(callback, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        return

    mine_count = game["mine_count"]
    bet = game["bet"]
    revealed = game["revealed"]
    mine_positions = game["mine_positions"]
    level = game["level"]
    exploded_mine = game.get("exploded_mine")

    clean_user_name = html.escape(get_user_display_name(user_id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{clean_user_name}</a>'
    multiplier = get_multiplier(mine_count, level)
    win_amount = int(bet * multiplier)

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + bet)
            add_game_history(user_id, "mines", bet, "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "mines", bet, "win", win_amount, game.get("created_at_str"))

    if game_over and exploded_mine is not None:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5469785308386041323">💥</tg-emoji> <b>Мины · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Открыто:</b> {3} из {4}\n\n<blockquote><i><tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji>Мог забрать: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢</i></blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(len(revealed) - 1, '', -1), _fmt(TOTAL_CELLS - mine_count, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    elif won:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Мины · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Открыто:</b> {3} из {4}\n\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Выигрыш: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(len(revealed), '', -1), _fmt(TOTAL_CELLS - mine_count, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    else:
        multiplier = get_multiplier(mine_count, level)

        if level == 0:
            text = (
                _lf('{0}\n<b><tg-emoji emoji-id="5247011187308140698">🧨</tg-emoji>Мины • начни игру!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(get_multiplier(mine_count, level + 1), f'.2f', -1)))
            )
        else:
            win_amount = int(bet * multiplier)
            next_multiplier = get_multiplier(mine_count, level + 1)
            text = (
                _lf('{0}\n<b><tg-emoji emoji-id="5307594157739515229">💎</tg-emoji>Мины • игра идёт.</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji><b>Выигрыш:</b> <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x / {4} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1), _fmt(next_multiplier, f'.2f', -1)))
            )

    grid_buttons = []
    for row in range(GRID_SIZE):
        row_buttons = []
        for col in range(GRID_SIZE):
            idx = row * GRID_SIZE + col

            if game_over or won:
                if idx == exploded_mine:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5276032951342088188"
                        )
                    )
                elif idx in mine_positions:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5469654973308476699"
                        )
                    )
                elif idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💎",
                            callback_data=f"noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"noop_{game_id}",
                            icon_custom_emoji_id="5436113877181941026"
                        )
                    )
            else:
                if idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💎",
                            callback_data=f"noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"cell_{game_id}_{idx}",
                            icon_custom_emoji_id="5436113877181941026"
                        )
                    )
        grid_buttons.append(row_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=grid_buttons)

    if game_over or won:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_game_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])
    else:
        if len(revealed) > 0:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=_l('Забрать выигрыш'),
                    callback_data=f"cashout_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5427009714745517609"
                )
            ])
        else:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=_l('Назад'),
                    callback_data=f"exit_game_{game_id}",
                    icon_custom_emoji_id="5255703720078879038"
                )
            ])

    msg = None
    try:
        msg = await callback.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = True
    except Exception:
        msg = await callback.message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = False

    game["message_id"] = msg.message_id

    key = get_chat_key(user_id, game["chat_id"])
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("cashout_")))
@_localized
async def process_cashout(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 2:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена!'), show_alert=True)
        return

    if game.get("stage") != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    if len(game["revealed"]) == 0:
        await callback.answer(_l('Откройте хотя бы одну клетку!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True

    try:
        await callback.answer()

        game["game_over"] = True
        game["won"] = True
        game["cashed_out"] = True
        if user_id in active_games and active_games.get(user_id) == game_id:
            del active_games[user_id]
        remove_active_game_from_db(game_id)

        await show_mines_grid_from_callback(callback, user_id, game_id, won=True)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("exit_game_")))
@_localized
async def process_exit_game(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[2])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game.get("bet_placed", False) or len(game.get("revealed", set())) > 0 or game.get("level", 0) > 0:
        await callback.answer(_l('Нельзя отменить начатую игру! Нажмите «Забрать выигрыш».'), show_alert=True)
        return

    key = f"exit_{user_id}_{game_id}"
    current_time = datetime.now().timestamp()

    if key in exit_confirm:
        if current_time - exit_confirm[key] < 10:
            user_data = get_user(user_id)
            update_user(user_id, balance=user_data["balance"] + game["bet"])

            try:
                await callback.bot.delete_message(chat_id=game["chat_id"], message_id=game["message_id"])
            except Exception:
                pass

            if game_id in games:
                del games[game_id]
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            if key in exit_confirm:
                del exit_confirm[key]
            remove_active_game_from_db(game_id)

            await callback.message.edit_text(
                _lf('<i>✅ Игра отменена. Ставка {0} mCoin возвращена на баланс.</i>', (_fmt(format_number(game['bet']), '', -1),)),
                parse_mode=ParseMode.HTML
            )

            await callback.answer(_l('Игра отменена!'))
            return
        else:
            del exit_confirm[key]

    exit_confirm[key] = current_time
    await callback.answer(_l('⚠️ Если вы хотите отменить игру, нажмите ещё раз на кнопку назад.'), show_alert=True)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("mines_count_")))
@_localized
async def process_mines_count(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-2])
        count = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("stage") != "select_mines":
        await callback.answer(_l('Выберите количество мин!'), show_alert=True)
        return

    await callback.answer()

    now = datetime.now()
    game["mine_count"] = count
    game["stage"] = "playing"
    game["type"] = "mines"
    game["mine_positions"] = generate_mines(count)
    game["revealed"] = set()
    game["level"] = 0
    game["game_over"] = False
    game["won"] = False
    game["exploded_mine"] = None
    game["cashed_out"] = False
    game["bet_placed"] = False
    game["moves_count"] = 0
    game["created_at"] = now
    game["created_at_str"] = now.strftime("%d-%m-%Y %H:%M:%S")
    game["settled"] = False
    game["expired"] = False
    save_active_game_to_db(game_id, game)

    key = get_chat_key(user_id, game["chat_id"])
    if key in game_messages:
        await _delete_messages(game["chat_id"], game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=game["chat_id"], message_id=callback.message.message_id)
    except Exception:
        pass

    await show_mines_grid_from_callback(callback, user_id, game_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("back_to_catalog_")))
@_localized
async def process_back_to_catalog_from_select(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if game and game["owner_id"] == user_id:
        if game_id in games:
            del games[game_id]
        if user_id in active_games and active_games.get(user_id) == game_id:
            del active_games[user_id]
        remove_active_game_from_db(game_id)

    await callback.answer()

    key = get_chat_key(user_id, callback.message.chat.id)
    if key in game_messages:
        await _delete_messages(callback.message.chat.id, game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    except Exception:
        pass

    is_group = callback.message.chat.type in ["group", "supergroup"]
    await show_catalog(callback, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), callback.message.chat.id, is_group)


@dp.callback_query(_inline_filter(lambda c: c.data == "mines"))
@_localized
async def process_mines_start(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    key = get_chat_key(user_id, chat_id)
    if key in game_messages:
        await _delete_messages(chat_id, game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=chat_id, message_id=callback.message.message_id)
    except Exception:
        pass

    game_id = get_next_game_id()

    game_data = {
        "type": "mines_select",
        "stage": "select_mines",
        "bet": 10,
        "mine_count": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "moves_count": 0,
        "created_at": datetime.now(),
        "created_at_str": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    clean_user_name = html.escape(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{clean_user_name}</a>'

    text = (
        _lf('{0}\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji><b>Мины • выбери мины!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: 10 m¢', (_fmt(user_link, '', -1),))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣", callback_data=f"mines_count_{game_id}_1"),
                InlineKeyboardButton(text="2️⃣", callback_data=f"mines_count_{game_id}_2"),
                InlineKeyboardButton(text="3️⃣", callback_data=f"mines_count_{game_id}_3")
            ],
            [
                InlineKeyboardButton(text="4️⃣", callback_data=f"mines_count_{game_id}_4"),
                InlineKeyboardButton(text="5️⃣", callback_data=f"mines_count_{game_id}_5"),
                InlineKeyboardButton(text="6️⃣", callback_data=f"mines_count_{game_id}_6")
            ],
            [
                InlineKeyboardButton(
                    text=_l('Назад'),
                    callback_data=f"back_to_catalog_{game_id}",
                    icon_custom_emoji_id="5255703720078879038"
                )
            ]
        ]
    )

    msg = await callback.message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

    games[game_id]["message_id"] = msg.message_id

    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)



@dp.callback_query(_inline_filter(lambda c: c.data == "diamonds"))
@_localized
async def process_diamonds_start(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    key = get_chat_key(user_id, chat_id)
    if key in game_messages:
        await _delete_messages(chat_id, game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=chat_id, message_id=callback.message.message_id)
    except Exception:
        pass

    game_id = get_next_game_id()

    game_data = {
        "type": "diamonds_select",
        "stage": "select_mines",
        "bet": 10,
        "mine_count": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "moves_count": 0,
        "created_at": datetime.now(),
        "created_at_str": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    clean_user_name = html.escape(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{clean_user_name}</a>'

    text = (
        _lf('{0}\n<tg-emoji emoji-id="5307594157739515229">💠</tg-emoji> <b>Алмазы · выбери количество мин!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: 10 m¢', (_fmt(user_link, '', -1),))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣", callback_data=f"diamonds_count_{game_id}_1"),
                InlineKeyboardButton(text="2️⃣", callback_data=f"diamonds_count_{game_id}_2")
            ],
            [
                InlineKeyboardButton(
                    text=_l('Назад'),
                    callback_data=f"diamonds_back_to_catalog_{game_id}",
                    icon_custom_emoji_id="5255703720078879038"
                )
            ]
        ]
    )

    msg = await callback.message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

    games[game_id]["message_id"] = msg.message_id

    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("diamonds_count_")))
@_localized
async def process_diamonds_count(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-2])
        count = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("stage") != "select_mines":
        await callback.answer(_l('Выберите количество мин!'), show_alert=True)
        return

    await callback.answer()

    now = datetime.now()
    game["mine_count"] = count
    game["stage"] = "playing"
    game["type"] = "diamonds"
    game["mine_positions"] = generate_diamonds_mines(count)
    game["revealed"] = set()
    game["level"] = 0
    game["game_over"] = False
    game["won"] = False
    game["exploded_mine"] = None
    game["cashed_out"] = False
    game["bet_placed"] = False
    game["moves_count"] = 0
    game["created_at"] = now
    game["created_at_str"] = now.strftime("%d-%m-%Y %H:%M:%S")
    game["settled"] = False
    game["expired"] = False
    save_active_game_to_db(game_id, game)

    key = get_chat_key(user_id, game["chat_id"])
    if key in game_messages:
        await _delete_messages(game["chat_id"], game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=game["chat_id"], message_id=callback.message.message_id)
    except Exception:
        pass

    await show_diamonds_grid_from_callback(callback, user_id, game_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("diamonds_cell_")))
@_localized
async def process_diamonds_cell_click(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 4:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-3])
        target_row = int(data[-2])
        cell_idx = int(data[-1])
    except (ValueError, IndexError):
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["stage"] != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    current_level = game["level"]
    if target_row != current_level:
        await callback.answer()
        return

    global_idx = current_level * DIAMONDS_COLS + cell_idx

    if global_idx in game["revealed"]:
        await callback.answer(_l('Эта клетка уже открыта!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True

    try:
        await callback.answer()

        is_mine = (not DEMO_GAME_CONTEXT.get()) and cell_idx in game["mine_positions"][current_level]

        game["revealed"].add(global_idx)
        game["level"] += 1
        game["moves_count"] = game.get("moves_count", 0) + 1
        game["bet_placed"] = True

        if is_mine:
            game["game_over"] = True
            game["exploded_mine"] = global_idx
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_diamonds_grid_from_callback(callback, user_id, game_id, game_over=True)
            return

        if game["level"] >= DIAMONDS_ROWS:
            game["game_over"] = True
            game["won"] = True
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_diamonds_grid_from_callback(callback, user_id, game_id, won=True)
            return

        save_active_game_to_db(game_id, game)
        await show_diamonds_grid_from_callback(callback, user_id, game_id)
    finally:
        game["is_processing"] = False


@_localized
async def show_diamonds_grid_from_callback(callback, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        return

    mine_count = game["mine_count"]
    bet = game["bet"]
    revealed = game["revealed"]
    mine_positions = game["mine_positions"]
    level = game["level"]
    exploded_mine = game.get("exploded_mine")

    clean_user_name = html.escape(get_user_display_name(user_id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{clean_user_name}</a>'
    multiplier = get_diamonds_multiplier(mine_count, level)
    win_amount = int(bet * multiplier)

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + bet)
            add_game_history(user_id, "diamonds", bet, "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "diamonds", bet, "win", win_amount, game.get("created_at_str"))

    if game_over and exploded_mine is not None:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5469785308386041323">💥</tg-emoji> <b>Алмазы · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<blockquote><i><tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji>Мог забрать: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢</i></blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(DIAMONDS_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    elif won:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Алмазы · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> <b>Уровень:</b> {3} из {4}\n\n<tg-emoji emoji-id="5472212780952066876">🤑</tg-emoji> Выигрыш: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x / {6} m¢', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(DIAMONDS_ROWS, '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1)))
        )
    else:
        if level == 0:
            text = (
                _lf('{0}\n<b><tg-emoji emoji-id="5307594157739515229">💠</tg-emoji>Алмазы · начни игру!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(get_diamonds_multiplier(mine_count, level + 1), f'.2f', -1)))
            )
        else:
            win_amount = int(bet * multiplier)
            next_multiplier = get_diamonds_multiplier(mine_count, level + 1)
            text = (
                _lf('{0}\n<b><tg-emoji emoji-id="5307594157739515229">💠</tg-emoji>Алмазы · игра идёт!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji> <b>Мин:</b> {1}\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji><b>Ставка</b>: {2} m¢\n<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji><b>Выигрыш:</b> <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{3}x / {4} m¢\n\n<blockquote>Следующий множитель: <tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>{5}x</blockquote>', (_fmt(user_link, '', -1), _fmt(mine_count, '', -1), _fmt(format_number(bet), '', -1), _fmt(multiplier, f'.2f', -1), _fmt(format_number(win_amount), '', -1), _fmt(next_multiplier, f'.2f', -1)))
            )

    grid_buttons = []

    for row in range(0, level + 1 if not (game_over or won) else min(level + 1, DIAMONDS_ROWS)):
        row_buttons = []
        for col in range(DIAMONDS_COLS):
            idx = row * DIAMONDS_COLS + col
            if game_over or won:
                if idx == exploded_mine:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"diamonds_noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5276032951342088188"
                        )
                    )
                elif col in mine_positions[row]:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"diamonds_noop_{game_id}",
                            style="danger",
                            icon_custom_emoji_id="5469654973308476699"
                        )
                    )
                elif idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💠",
                            callback_data=f"diamonds_noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"diamonds_noop_{game_id}",
                            icon_custom_emoji_id="5436113877181941026"
                        )
                    )
            else:
                if idx in revealed:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text="💠",
                            callback_data=f"diamonds_noop_{game_id}",
                            style="success"
                        )
                    )
                else:
                    if row == level:
                        row_buttons.append(
                            InlineKeyboardButton(
                                text=" ",
                                callback_data=f"diamonds_cell_{game_id}_{row}_{col}",
                                icon_custom_emoji_id="5436113877181941026"
                            )
                        )
                    else:
                        row_buttons.append(
                            InlineKeyboardButton(
                                text=" ",
                                callback_data=f"diamonds_noop_{game_id}",
                                icon_custom_emoji_id="5436113877181941026"
                            )
                        )
        grid_buttons.append(row_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=grid_buttons)

    if game_over or won:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_diamonds_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])
    else:
        if level > 0:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=_l('Забрать выигрыш'),
                    callback_data=f"diamonds_cashout_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5427009714745517609"
                )
            ])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_diamonds_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])

    msg = None
    try:
        msg = await callback.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = True
    except Exception:
        msg = await callback.message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = False

    game["message_id"] = msg.message_id

    key = get_chat_key(user_id, game["chat_id"])
    if key not in game_messages:
        game_messages[key] = []
    _remember_message(game_messages, key, msg.message_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("diamonds_cashout_")))
@_localized
async def process_diamonds_cashout(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена!'), show_alert=True)
        return

    if game.get("stage") != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    if game["level"] == 0:
        await callback.answer(_l('Откройте хотя бы одну клетку!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True

    try:
        await callback.answer()

        game["game_over"] = True
        game["won"] = True
        game["cashed_out"] = True
        if user_id in active_games and active_games.get(user_id) == game_id:
            del active_games[user_id]
        remove_active_game_from_db(game_id)

        await show_diamonds_grid_from_callback(callback, user_id, game_id, won=True)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("exit_diamonds_")))
@_localized
async def process_exit_diamonds(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[2])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game.get("bet_placed", False) or len(game.get("revealed", set())) > 0 or game.get("level", 0) > 0:
        await callback.answer(_l('Нельзя отменить начатую игру! Нажмите «Забрать выигрыш».'), show_alert=True)
        return

    key = f"exit_{user_id}_{game_id}"
    current_time = datetime.now().timestamp()

    if key in exit_confirm:
        if current_time - exit_confirm[key] < 10:
            user_data = get_user(user_id)
            update_user(user_id, balance=user_data["balance"] + game["bet"])

            try:
                await callback.bot.delete_message(chat_id=game["chat_id"], message_id=game["message_id"])
            except Exception:
                pass

            if game_id in games:
                del games[game_id]
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            if key in exit_confirm:
                del exit_confirm[key]
            remove_active_game_from_db(game_id)

            await callback.message.edit_text(
                _lf('<i>✅ Игра отменена. Ставка {0} mCoin возвращена на баланс.</i>', (_fmt(format_number(game['bet']), '', -1),)),
                parse_mode=ParseMode.HTML
            )

            await callback.answer(_l('Игра отменена!'))
            return
        else:
            del exit_confirm[key]

    exit_confirm[key] = current_time
    await callback.answer(_l('⚠️ Если вы хотите отменить игру, нажмите ещё раз на кнопку назад.'), show_alert=True)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("diamonds_back_to_catalog_")))
@_localized
async def process_diamonds_back_to_catalog(callback: types.CallbackQuery):
    data = callback.data.split("_")

    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[-1])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id

    game = games.get(game_id)
    if game and game["owner_id"] == user_id:
        if game_id in games:
            del games[game_id]
        if user_id in active_games and active_games.get(user_id) == game_id:
            del active_games[user_id]
        remove_active_game_from_db(game_id)

    await callback.answer()

    key = get_chat_key(user_id, callback.message.chat.id)
    if key in game_messages:
        await _delete_messages(callback.message.chat.id, game_messages[key], callback.bot)
        game_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    except Exception:
        pass

    is_group = callback.message.chat.type in ["group", "supergroup"]
    await show_catalog(callback, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), callback.message.chat.id, is_group)



@_localized
async def start_gold_game_from_command(message, user_id, chat_id, bet):
    key = get_chat_key(user_id, chat_id)
    if key in user_messages:
        await _delete_messages(chat_id, user_messages[key], bot)
        user_messages[key] = []

    game_id = get_next_game_id()

    user_data = get_user(user_id)
    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    now = datetime.now()
    mine_positions = [secrets.SystemRandom().randint(0, 1) for _ in range(12)]
    game_data = {
        "type": "gold",
        "stage": "playing",
        "bet": bet,
        "mine_positions": mine_positions,
        "revealed": {},
        "level": 0,
        "game_over": False,
        "won": False,
        "exploded_mine": None,
        "owner_id": user_id,
        "chat_id": chat_id,
        "cashed_out": False,
        "bet_placed": False,
        "moves_count": 0,
        "created_at": now,
        "created_at_str": now.strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "is_edited": False
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    await show_gold_grid_from_message(message, user_id, game_id)


def build_gold_board_text(game, bet, level, game_over, won, exploded_mine):
    rows_text = []
    for lvl_idx in range(GOLD_ROWS - 1, -1, -1):
        mult = GOLD_MULTIPLIERS[lvl_idx + 1]
        amt_str = f"{format_number(bet * mult)} m¢ ({mult}x)"
        mine_col = game["mine_positions"][lvl_idx]

        if not (game_over or won):
            if lvl_idx < level:
                chosen = game["revealed"].get(lvl_idx)
                c0 = "💰" if chosen == 0 else GOLD_Q_EMOJI
                c1 = "💰" if chosen == 1 else GOLD_Q_EMOJI
            else:
                c0 = GOLD_Q_EMOJI
                c1 = GOLD_Q_EMOJI
        elif game_over and exploded_mine is not None:
            if lvl_idx < level:
                chosen = game["revealed"].get(lvl_idx)
                c0 = "💰" if chosen == 0 else "🧨"
                c1 = "💰" if chosen == 1 else "🧨"
            elif lvl_idx == level:
                if mine_col == 0:
                    c0 = GOLD_BOOM_EMOJI
                    c1 = "💸"
                else:
                    c0 = "💸"
                    c1 = GOLD_BOOM_EMOJI
            else:
                c0 = "🧨" if mine_col == 0 else "💸"
                c1 = "🧨" if mine_col == 1 else "💸"
        else:
            if lvl_idx < level:
                chosen = game["revealed"].get(lvl_idx)
                c0 = "💰" if chosen == 0 else "🧨"
                c1 = "💰" if chosen == 1 else "🧨"
            else:
                c0 = "🧨" if mine_col == 0 else "💸"
                c1 = "🧨" if mine_col == 1 else "💸"

        rows_text.append(f"| {c0}| {c1}| {amt_str}")

    return "\n".join(rows_text)


@_localized
async def show_gold_grid_from_message(message_or_callback, user_id, game_id, game_over=False, won=False):
    game = games.get(game_id)
    if not game:
        return

    if game["owner_id"] != user_id:
        return

    bet = game["bet"]
    level = game["level"]
    exploded_mine = game.get("exploded_mine")

    if hasattr(message_or_callback, "from_user") and message_or_callback.from_user:
        raw_name = get_user_display_name(user_id, message_or_callback.from_user.first_name) or _l('Игрок')
    else:
        raw_name = _l('Игрок')
    user_link = f'<a href="tg://user?id={user_id}">{html.escape(raw_name)}</a>'

    current_mult = GOLD_MULTIPLIERS.get(level, 1) if level > 0 else 1
    raw_win_amount = int(bet * current_mult) if level > 0 else 0
    win_amount = raw_win_amount if is_admin_unlimited_bet(user_id) else min(1000000000, raw_win_amount)

    if (game_over or won) and not game.get("settled", False):
        game["settled"] = True
        if game_over and exploded_mine is not None:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + bet)
            add_game_history(user_id, "gold", bet, "lose", 0, game.get("created_at_str"))
        elif won:
            user_data = get_user(user_id)
            update_user(user_id, games=user_data["games"] + 1, balance=user_data["balance"] + win_amount)
            add_game_history(user_id, "gold", bet, "win", win_amount, game.get("created_at_str"))

    board_text = build_gold_board_text(game, bet, level, game_over, won, exploded_mine)

    if game_over and exploded_mine is not None:
        text = (
            _lf('{0}\n💥 <b>Золото · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji> <b>Ставка:</b> {1} m¢\n⚜️ <b>Пройдено:</b> {2} из 12\n\n{3}', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(board_text, '', -1)))
        )
    elif won:
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji><b>Золото · Победа!</b> <tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>\n<code>·····················</code>\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji> <b>Ставка:</b> {1} m¢\n⚜️ <b>Пройдено:</b> {2} из 12\n<tg-emoji emoji-id="5375296873982604963">💰</tg-emoji><b>Выигрыш:</b> х{3} / {4} m¢\n\n{5}', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(level, '', -1), _fmt(current_mult, '', -1), _fmt(format_number(win_amount), '', -1), _fmt(board_text, '', -1)))
        )
    else:
        if level == 0:
            text = (
                _lf('{0}\n <tg-emoji emoji-id="5370731117588523522">🌼</tg-emoji><b>Золото · начни игру!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji> <b>Ставка:</b> {1} m¢\n\n{2}', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(board_text, '', -1)))
            )
        else:
            text = (
                _lf('{0}\n <tg-emoji emoji-id="5472010685560921607">🖥</tg-emoji><b>Золото · игра идёт.</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5881948563591666817">💸</tg-emoji> <b>Ставка:</b> {1} m¢\n <tg-emoji emoji-id="5375296873982604963">💰</tg-emoji><b>Выигрыш:</b> х{2} / {3} m¢\n\n{4}', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(current_mult, '', -1), _fmt(format_number(win_amount), '', -1), _fmt(board_text, '', -1)))
            )

    keyboard = None
    if not (game_over or won):
        row1 = [
            InlineKeyboardButton(
                text=" ",
                callback_data=f"gold_cell_{game_id}_{level}_0",
                style="primary",
                icon_custom_emoji_id="5436113877181941026"
            ),
            InlineKeyboardButton(
                text=" ",
                callback_data=f"gold_cell_{game_id}_{level}_1",
                style="primary",
                icon_custom_emoji_id="5436113877181941026"
            )
        ]
        buttons = [row1]
        if level > 0:
            buttons.append([
                InlineKeyboardButton(
                    text=_lf('Забрать {0} m¢', (_fmt(format_number(win_amount), '', -1),)),
                    callback_data=f"gold_cashout_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5427009714745517609"
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text=_l('Назад'),
                callback_data=f"exit_gold_{game_id}",
                icon_custom_emoji_id="5255703720078879038"
            )
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    msg = None
    if isinstance(message_or_callback, types.CallbackQuery):
        try:
            msg = await message_or_callback.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            game["is_edited"] = True
        except Exception:
            msg = await message_or_callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            game["is_edited"] = False
    else:
        msg = await message_or_callback.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        game["is_edited"] = False

    if msg:
        game["message_id"] = msg.message_id
        key = get_chat_key(user_id, game["chat_id"])
        if key not in game_messages:
            game_messages[key] = []
        _remember_message(game_messages, key, msg.message_id)



@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("gold_cell_")))
@_localized
async def process_gold_cell(callback: types.CallbackQuery):
    data = callback.data.split("_")
    if len(data) < 5:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[2])
        target_row = int(data[3])
        cell_idx = int(data[4])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game.get("stage") != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    current_level = game["level"]
    if target_row != current_level:
        await callback.answer()
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True
    try:
        await callback.answer()
        mine_col = game["mine_positions"][current_level]
        is_mine = (not DEMO_GAME_CONTEXT.get()) and (cell_idx == mine_col)

        if is_mine:
            game["game_over"] = True
            game["exploded_mine"] = (current_level, cell_idx)
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_gold_grid_from_message(callback, user_id, game_id, game_over=True)
            return

        game["revealed"][current_level] = cell_idx
        game["level"] += 1
        game["moves_count"] = game.get("moves_count", 0) + 1
        game["bet_placed"] = True

        if game["level"] >= GOLD_ROWS:
            game["game_over"] = True
            game["won"] = True
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            remove_active_game_from_db(game_id)
            await show_gold_grid_from_message(callback, user_id, game_id, won=True)
            return

        save_active_game_to_db(game_id, game)
        await show_gold_grid_from_message(callback, user_id, game_id)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("gold_cashout_")))
@_localized
async def process_gold_cashout(callback: types.CallbackQuery):
    data = callback.data.split("_")
    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[2])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена!'), show_alert=True)
        return

    if game.get("stage") != "playing":
        await callback.answer(_l('Игра неактивна!'), show_alert=True)
        return

    if game["level"] == 0:
        await callback.answer(_l('Пройдите хотя бы один уровень!'), show_alert=True)
        return

    if game.get("is_processing", False):
        await callback.answer()
        return

    game["is_processing"] = True
    try:
        await callback.answer()
        game["game_over"] = True
        game["won"] = True
        game["cashed_out"] = True
        if user_id in active_games and active_games.get(user_id) == game_id:
            del active_games[user_id]
        remove_active_game_from_db(game_id)

        await show_gold_grid_from_message(callback, user_id, game_id, won=True)
    finally:
        game["is_processing"] = False


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("exit_gold_")))
@_localized
async def process_exit_gold(callback: types.CallbackQuery):
    data = callback.data.split("_")
    if len(data) < 3:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    try:
        game_id = int(data[2])
    except ValueError:
        await callback.answer(_l('Ошибка! Попробуйте заново.'), show_alert=True)
        return

    user_id = callback.from_user.id
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("game_over", False) or game.get("won", False) or game.get("cashed_out", False):
        await callback.answer(_l('Игра уже завершена.'), show_alert=True)
        return

    if game.get("level", 0) > 0:
        await callback.answer(_l('Нельзя отменить начатую игру! Нажмите «Забрать выигрыш».'), show_alert=True)
        return

    key = f"exit_{user_id}_{game_id}"
    current_time = datetime.now().timestamp()

    if key in exit_confirm:
        if current_time - exit_confirm[key] < 10:
            user_data = get_user(user_id)
            update_user(user_id, balance=user_data["balance"] + game["bet"])

            try:
                await callback.bot.delete_message(chat_id=game["chat_id"], message_id=game["message_id"])
            except Exception:
                pass

            if game_id in games:
                del games[game_id]
            if user_id in active_games and active_games.get(user_id) == game_id:
                del active_games[user_id]
            if key in exit_confirm:
                del exit_confirm[key]
            remove_active_game_from_db(game_id)

            await callback.message.edit_text(
                _lf('<i>✅ Игра отменена. Ставка {0} mCoin возвращена на баланс.</i>', (_fmt(format_number(game['bet']), '', -1),)),
                parse_mode=ParseMode.HTML
            )
            await callback.answer(_l('Игра отменена!'))
            return
        else:
            del exit_confirm[key]

    exit_confirm[key] = current_time
    await callback.answer(_l('⚠️ Если вы хотите отменить игру, нажмите ещё раз на кнопку назад.'), show_alert=True)


@dp.callback_query(_inline_filter(lambda c: c.data in ["gold", "info_gold"]))
@_localized
async def process_gold_info_callback(callback: types.CallbackQuery):
    await callback.answer()
    await show_gold_info(callback, callback.from_user.id, is_callback=True)



RANKS_21 = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
SUITS_21 = ['♠️', '♥️', '♦️', '♣️']


def create_deck_21():
    deck = [(r, s) for r in RANKS_21 for s in SUITS_21]
    secrets.SystemRandom().shuffle(deck)
    return deck


def calculate_21_score(cards):
    if not cards:
        return 0
    if len(cards) == 2 and cards[0][0] == 'A' and cards[1][0] == 'A':
        return 21
    total = 0
    aces = 0
    for rank, _ in cards:
        if rank in ['2', '3', '4', '5', '6', '7', '8', '9', '10']:
            total += int(rank)
        elif rank == 'J':
            total += 2
        elif rank == 'Q':
            total += 3
        elif rank == 'K':
            total += 4
        elif rank == 'A':
            total += 11
            aces += 1
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def format_21_cards(cards):
    cards_str = " • ".join(f"{r}{s}" for r, s in cards)
    score = calculate_21_score(cards)
    return f"{cards_str} | {score}"


@_localized
async def start_twentyone_game_from_command(message, user_id, chat_id, bet):
    key = get_chat_key(user_id, chat_id)
    if key in user_messages:
        await _delete_messages(chat_id, user_messages[key], bot)
        user_messages[key] = []

    if user_id in active_games:
        old_game_id = active_games[user_id]
        old_game = games.get(old_game_id)
        if old_game and not old_game.get("settled", False) and not old_game.get("game_over", False):
            if old_game.get("stage") == "ready":
                cur_u = get_user(user_id)
                update_user(user_id, balance=cur_u["balance"] + old_game.get("bet", 0))
            remove_active_game_from_db(old_game_id)
            if old_game_id in games:
                del games[old_game_id]

    user_data = get_user(user_id)
    if not update_user(user_id, balance=user_data["balance"] - bet):
        await message.answer(_l('<i>Ошибка списания средств!</i>'), parse_mode=ParseMode.HTML)
        return

    game_id = get_next_game_id()
    now = datetime.now()
    user_first_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок')

    game_data = {
        "type": "twentyone",
        "stage": "ready",
        "bet": bet,
        "deck": create_deck_21(),
        "player_cards": [],
        "dealer_cards": [],
        "owner_id": user_id,
        "chat_id": chat_id,
        "game_over": False,
        "won": False,
        "created_at": now,
        "created_at_str": now.strftime("%d-%m-%Y %H:%M:%S"),
        "settled": False,
        "expired": False,
        "message_id": None,
        "user_first_name": user_first_name
    }

    games[game_id] = game_data
    active_games[user_id] = game_id
    save_active_game_to_db(game_id, game_data)

    user_link = get_user_mention(user_id, user_first_name)

    text = (
        _lf('{0}\n<tg-emoji emoji-id="5395325195542078574">🍀</tg-emoji>21 · начни игру!\n<code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji><b>Ставка:</b> {1} m¢', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Запустить'),
                    callback_data=f"to_start_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5809949600152296075"
                ),
                InlineKeyboardButton(
                    text=_l('Назад'),
                    callback_data=f"to_cancel_{game_id}",
                    icon_custom_emoji_id="5255703720078879038"
                )
            ]
        ]
    )

    msg = await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )
    game_data["message_id"] = msg.message_id
    if key not in user_messages:
        user_messages[key] = []
    _remember_message(user_messages, key, msg.message_id)


@_localized
async def show_twentyone_from_callback(callback: types.CallbackQuery, user_id: int, game_id: int):
    game = games.get(game_id)
    if not game:
        await callback.answer(_l('Игра не найдена!'), show_alert=True)
        return

    if game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    bet = game["bet"]
    user_first_name = game.get("user_first_name") or get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок')
    user_link = get_user_mention(user_id, user_first_name)
    stage = game.get("stage", "ready")

    if stage == "ready":
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5395325195542078574">🍀</tg-emoji>21 · начни игру!\n<code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji><b>Ставка:</b> {1} m¢', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1)))
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Запустить'),
                        callback_data=f"to_start_{game_id}",
                        style="success",
                        icon_custom_emoji_id="5809949600152296075"
                    ),
                    InlineKeyboardButton(
                        text=_l('Назад'),
                        callback_data=f"to_cancel_{game_id}",
                        icon_custom_emoji_id="5255703720078879038"
                    )
                ]
            ]
        )
    else:
        dealer_cards = game.get("dealer_cards", [])
        player_cards = game.get("player_cards", [])
        dealer_str = format_21_cards(dealer_cards)
        player_str = format_21_cards(player_cards)
        text = (
            _lf('{0}\n♠️<b> 21 · игра идёт.</b> <code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji> Ставка: {1} m¢\n\n🤵♂ Дилер: \n<blockquote>{2}</blockquote>\n<code>············</code>\n🫵 Ты: \n<blockquote>{3}</blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1)))
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('СТОП'),
                        callback_data=f"to_stand_{game_id}",
                        style="danger",
                        icon_custom_emoji_id="5445350865776941647"
                    ),
                    InlineKeyboardButton(
                        text=_l('ЕЩЁ'),
                        callback_data=f"to_hit_{game_id}",
                        style="success",
                        icon_custom_emoji_id="5809949600152296075"
                    )
                ]
            ]
        )

    msg = None
    try:
        msg = await callback.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    except Exception:
        try:
            msg = await callback.message.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            pass

    if msg:
        game["message_id"] = msg.message_id


@_localized
async def update_twentyone_game_view(message_obj, user_id, game_id, user_first_name="Игрок"):
    game = games.get(game_id)
    if not game:
        return

    bet = game["bet"]
    user_link = get_user_mention(user_id, game.get("user_first_name") or user_first_name)

    dealer_cards = game["dealer_cards"]
    player_cards = game["player_cards"]

    dealer_str = format_21_cards(dealer_cards)
    player_str = format_21_cards(player_cards)

    text = (
        _lf('{0}\n♠️<b> 21 · игра идёт.</b> <code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji> Ставка: {1} m¢\n\n🤵♂ Дилер: \n<blockquote>{2}</blockquote>\n<code>············</code>\n🫵 Ты: \n<blockquote>{3}</blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1)))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('СТОП'),
                    callback_data=f"to_stand_{game_id}",
                    style="danger",
                    icon_custom_emoji_id="5445350865776941647"
                ),
                InlineKeyboardButton(
                    text=_l('ЕЩЁ'),
                    callback_data=f"to_hit_{game_id}",
                    style="success",
                    icon_custom_emoji_id="5809949600152296075"
                )
            ]
        ]
    )

    msg = None
    try:
        msg = await message_obj.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    except Exception:
        try:
            msg = await message_obj.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        except Exception:
            pass

    if msg:
        game["message_id"] = msg.message_id


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("to_start_")))
@_localized
async def process_twentyone_start(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    game = games.get(game_id)
    user_id = callback.from_user.id
    if not game or game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("stage") != "ready":
        await callback.answer()
        return

    game["stage"] = "playing"
    if get_user_display_name(callback.from_user.id, callback.from_user.first_name):
        game["user_first_name"] = get_user_display_name(callback.from_user.id, callback.from_user.first_name)
    deck = game["deck"]
    game["player_cards"] = [deck.pop(), deck.pop()]
    game["dealer_cards"] = [deck.pop(), deck.pop()]

    dealer_score = calculate_21_score(game["dealer_cards"])
    player_score = calculate_21_score(game["player_cards"])
    bet = game["bet"]
    user_data = get_user(user_id)

    if dealer_score == 21 and not DEMO_GAME_CONTEXT.get():
        game["settled"] = True
        game["game_over"] = True
        await callback.answer()

        if active_games.get(user_id) == game_id:
            del active_games[user_id]
        if game_id in games:
            del games[game_id]
        remove_active_game_from_db(game_id)

        user_link = get_user_mention(user_id, game.get("user_first_name") or get_user_display_name(callback.from_user.id, callback.from_user.first_name))
        dealer_str = format_21_cards(game["dealer_cards"])
        player_str = format_21_cards(game["player_cards"])

        if player_score == 21:
            update_user(user_id, balance=user_data["balance"] + bet, games=user_data["games"] + 1)
            add_game_history(user_id, "twentyone", bet, "draw", bet, game.get("created_at_str"))

            text = (
                _lf('{0}\n🤝 <b>21 · Ничья!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji>  Ставка: {1} m¢\n\n🤵♂ Дилер:\n<blockquote>{2}</blockquote>\n<code>············</code>\n🫵 Ты:\n<blockquote>{3}</blockquote>\n\n<i>🤝 Ничья! У обоих 21. Ставка возвращена на баланс.</i>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1)))
            )
        else:
            update_user(user_id, lost=user_data["lost"] + bet, games=user_data["games"] + 1)
            add_game_history(user_id, "twentyone", bet, "lose", 0, game.get("created_at_str"))

            text = (
                _lf('{0}\n<tg-emoji emoji-id="5213090867044162716">😭</tg-emoji> <b>21 · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji>  Ставка: {1} m¢\n\n🤵♂ Дилер:\n<blockquote>{2}</blockquote>\n<code>············</code>\n🫵 Ты:\n<blockquote>{3}</blockquote>\n\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji> <i>Не повезло! У дилера 21.</i>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1)))
            )

        try:
            await callback.message.edit_text(text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            pass
        return

    save_active_game_to_db(game_id, game)

    await callback.answer()
    await update_twentyone_game_view(callback.message, user_id, game_id, game.get("user_first_name"))


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("to_hit_")))
@_localized
async def process_twentyone_hit(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    game = games.get(game_id)
    user_id = callback.from_user.id
    if not game or game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("stage") != "playing" or game.get("settled", False):
        await callback.answer()
        return

    if not game["deck"]:
        game["deck"] = create_deck_21()
    new_card = game["deck"].pop()
    game["player_cards"].append(new_card)

    player_score = calculate_21_score(game["player_cards"])
    await callback.answer()

    if player_score > 21 and not DEMO_GAME_CONTEXT.get():
        game["settled"] = True
        game["game_over"] = True
        game["won"] = False
        bet = game["bet"]
        user_data = get_user(user_id)
        update_user(user_id, games=user_data["games"] + 1, lost=user_data["lost"] + bet)
        add_game_history(user_id, "twentyone", bet, "lose", 0, game.get("created_at_str"))

        if active_games.get(user_id) == game_id:
            del active_games[user_id]
        if game_id in games:
            del games[game_id]
        remove_active_game_from_db(game_id)

        user_link = get_user_mention(user_id, game.get("user_first_name") or get_user_display_name(callback.from_user.id, callback.from_user.first_name))
        dealer_str = format_21_cards(game["dealer_cards"])
        player_str = format_21_cards(game["player_cards"])

        text = (
            _lf('{0}\n<tg-emoji emoji-id="5213090867044162716">😭</tg-emoji> <b>21 · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji>  Ставка: {1} m¢\n\n🤵♂ Дилер:\n<blockquote>{2}</blockquote>\n<code>············</code>\n🫵 Ты:\n<blockquote>{3}</blockquote>\n\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji> <i>Не повезло! У вас перебор ({4}).</i>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1), _fmt(player_score, '', -1)))
        )

        try:
            await callback.message.edit_text(text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            pass
    else:
        save_active_game_to_db(game_id, game)
        await update_twentyone_game_view(callback.message, user_id, game_id, game.get("user_first_name"))


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("to_stand_")))
@_localized
async def process_twentyone_stand(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    game = games.get(game_id)
    user_id = callback.from_user.id
    if not game or game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("stage") != "playing" or game.get("settled", False):
        await callback.answer()
        return

    game["settled"] = True
    game["game_over"] = True
    await callback.answer()

    dealer_cards = game["dealer_cards"]
    deck = game["deck"]
    while calculate_21_score(dealer_cards) < 17:
        if not deck:
            deck = create_deck_21()
        dealer_cards.append(deck.pop())

    dealer_score = calculate_21_score(dealer_cards)
    player_score = calculate_21_score(game["player_cards"])
    bet = game["bet"]
    user_data = get_user(user_id)

    user_link = get_user_mention(user_id, game.get("user_first_name") or get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    dealer_str = format_21_cards(dealer_cards)
    player_str = format_21_cards(game["player_cards"])
    if DEMO_GAME_CONTEXT.get():
        dealer_score = -1

    if active_games.get(user_id) == game_id:
        del active_games[user_id]
    if game_id in games:
        del games[game_id]
    remove_active_game_from_db(game_id)

    if dealer_score > 21:
        win_amount = int(bet * 1.97) if is_admin_unlimited_bet(user_id) else min(int(bet * 1.97), 1000000000)
        update_user(user_id, balance=user_data["balance"] + win_amount, games=user_data["games"] + 1)
        add_game_history(user_id, "twentyone", bet, "win", win_amount, game.get("created_at_str"))

        text = (
            _lf('{0}\n🤯 <b>21 · Победа! ✅</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n💰 <b>Выигрыш: </b>x1,97 / {2} m¢\n\n🤵♂ Дилер:\n<blockquote>{3}</blockquote>\n<code>············</code>\n🫵 Ты:\n<blockquote>{4}</blockquote>\n\n<i>🎉 Ты победил! У дилера перебор.</i>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(format_number(win_amount), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1)))
        )
    elif player_score > dealer_score:
        win_amount = int(bet * 1.97) if is_admin_unlimited_bet(user_id) else min(int(bet * 1.97), 1000000000)
        update_user(user_id, balance=user_data["balance"] + win_amount, games=user_data["games"] + 1)
        add_game_history(user_id, "twentyone", bet, "win", win_amount, game.get("created_at_str"))

        text = (
            _lf('{0}\n🤯 <b>21 · Победа! ✅</b>\n<code>·····················</code>\n💸 <b>Ставка:</b> {1} m¢\n💰 <b>Выигрыш: </b>x1,97 / {2} m¢\n\n🤵♂ Дилер:\n<blockquote>{3}</blockquote>\n<code>············</code>\n🫵 Ты:\n<blockquote>{4}</blockquote>\n\n<i>🎉 Ты победил! У тебя {5} против {6} у дилера.</i>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(format_number(win_amount), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1), _fmt(player_score, '', -1), _fmt(dealer_score, '', -1)))
        )
    elif player_score == dealer_score:
        update_user(user_id, balance=user_data["balance"] + bet, games=user_data["games"] + 1)
        add_game_history(user_id, "twentyone", bet, "draw", bet, game.get("created_at_str"))

        text = (
            _lf('{0}\n🤝 <b>21 · Ничья!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji>  Ставка: {1} m¢\n\n🤵♂ Дилер:\n<blockquote>{2}</blockquote>\n<code>············</code>\n🫵 Ты:\n<blockquote>{3}</blockquote>\n\n<i>🤝 Ничья! Ставка возвращена на баланс.</i>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1)))
        )
    else:
        update_user(user_id, lost=user_data["lost"] + bet, games=user_data["games"] + 1)
        add_game_history(user_id, "twentyone", bet, "lose", 0, game.get("created_at_str"))

        text = (
            _lf('{0}\n<tg-emoji emoji-id="5213090867044162716">😭</tg-emoji> <b>21 · Проигрыш!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5224257782013769471">💰</tg-emoji>  Ставка: {1} m¢\n\n🤵♂ Дилер:\n<blockquote>{2}</blockquote>\n<code>············</code>\n🫵 Ты:\n<blockquote>{3}</blockquote>\n\n<tg-emoji emoji-id="5472255352667904566">😔</tg-emoji> <i>Не повезло! У дилера {4}.</i>', (_fmt(user_link, '', -1), _fmt(format_number(bet), '', -1), _fmt(dealer_str, '', -1), _fmt(player_str, '', -1), _fmt(dealer_score, '', -1)))
        )

    try:
        await callback.message.edit_text(text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("to_cancel_")))
@_localized
async def process_twentyone_cancel(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    game = games.get(game_id)
    user_id = callback.from_user.id
    if not game or game["owner_id"] != user_id:
        await callback.answer(_l('Это не ваша игра!'), show_alert=True)
        return

    if game.get("stage") == "ready" and not game.get("settled", False):
        game["settled"] = True
        game["game_over"] = True
        user_data = get_user(user_id)
        update_user(user_id, balance=user_data["balance"] + game["bet"])
        if active_games.get(user_id) == game_id:
            del active_games[user_id]
        if game_id in games:
            del games[game_id]
        remove_active_game_from_db(game_id)
        await callback.answer(_l('Игра отменена. Ставка возвращена.'))
        try:
            await callback.message.edit_text(_l('<i>Игра отменена. Ставка возвращена на баланс.</i>'), parse_mode=ParseMode.HTML)
        except Exception:
            pass
    else:
        await callback.answer(_l('Игру нельзя отменить во время раунда!'), show_alert=True)



@dp.callback_query(_inline_filter(lambda c: c.data == "play"))
@_localized
async def process_play(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    key = get_chat_key(user_id, callback.message.chat.id)
    if key in user_messages:
        await _delete_messages(callback.message.chat.id, user_messages[key], callback.bot)
        user_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    except Exception:
        pass

    is_group = callback.message.chat.type in ["group", "supergroup"]
    await show_catalog(callback, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), callback.message.chat.id, is_group)


@dp.callback_query(_inline_filter(lambda c: c.data == "back"))
@_localized
async def process_back(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    key = get_chat_key(user_id, chat_id)
    if key in user_messages:
        await _delete_messages(chat_id, user_messages[key], callback.bot)
        user_messages[key] = []

    try:
        await callback.bot.delete_message(chat_id=chat_id, message_id=callback.message.message_id)
    except Exception:
        pass

    text = (
        _l('<b>Привет! <tg-emoji emoji-id="5350612670435313545">👋</tg-emoji> Ты в Мины Бот — место, где время летит незаметно!</b>\n\n🎮 Много бесплатных игр без скачивания, прямо в Telegram.\n\nСоревнуйся с друзьями и прокачивай свои каналы и чаты. 🏆')
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Играть'),
                    callback_data="play",
                    style="success",
                    icon_custom_emoji_id="5350612670435313545"
                )
            ],
            [
                InlineKeyboardButton(
                    text=_l('🧾 Чеки'),
                    callback_data="checks_menu",
                    style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text=_l('Добавить бота в чат'),
                    url=f"https://t.me/{BOT_USERNAME}?startgroup=start",
                    style="primary",
                    icon_custom_emoji_id="5393194986252542669"
                )
            ]
        ]
    )

    photo_url = "https://iili.io/CPpNkSR.md.png"
    msg = await callback.message.answer_photo(
        photo=photo_url,
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    if key not in user_messages:
        user_messages[key] = []
    _remember_message(user_messages, key, msg.message_id)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("noop_") or c.data.startswith("tower_noop_") or c.data.startswith("qwak_noop_") or c.data.startswith("scratch_noop_") or c.data.startswith("diamonds_noop_")))
@_localized
async def process_noop(callback: types.CallbackQuery):
    try:
        game_id = int(callback.data.split("_")[-1])
        game = games.get(game_id)
        if game and not game.get("game_over", False) and not game.get("settled", False) and not game.get("expired", False):
            await callback.answer()
            return
    except Exception:
        pass
    await callback.answer(_l('Игра завершена.'))


@dp.callback_query(_inline_filter(lambda c: c.data == "check_bonus"))
@_localized
async def process_check_bonus(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    user_data = get_user(user_id)

    if not user_data:
        await callback.answer(_l('Ошибка получения данных!'), show_alert=True)
        return

    try:
        user_info = await bot.get_chat(user_id)
        description = user_info.bio or ""
    except Exception:
        description = ""

    if f"@{BOT_USERNAME}" not in description and BOT_USERNAME not in description:
        await callback.answer(_l('Не все условия выполнены.'), show_alert=True)
        return

    if user_data["bonus_time"]:
        try:
            last_bonus = datetime.fromisoformat(user_data["bonus_time"])
            if datetime.now() - last_bonus < timedelta(hours=6):
                time_left = timedelta(hours=6) - (datetime.now() - last_bonus)
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)
                await callback.answer(_lf('Бонус можно получить только раз в 6 часов. Осталось: {0}ч {1}м', (_fmt(hours, '', -1), _fmt(minutes, '', -1))), show_alert=True)
                return
        except Exception:
            pass

    bonus = random.randint(70000, 100000)
    if update_user(user_id, balance=user_data["balance"] + bonus, bonus_time=datetime.now().isoformat()):
        try:
            asyncio.create_task(activate_referral_if_needed(user_id))
        except Exception:
            pass
        await callback.message.edit_text(
            _lf('<i>🎉 Поздравляем! Вы получили бонус {0} mCoin!\nТекущий баланс: {1} mCoin</i>', (_fmt(format_number(bonus), '', -1), _fmt(format_number(user_data['balance'] + bonus), '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer(_l('Ошибка при начислении бонуса!'), show_alert=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "bonus_tutorial"))
@_localized
async def process_bonus_tutorial(callback: types.CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    clean_user_name = html.escape(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{clean_user_name}</a>'

    text = (
        _lf('{0}, бонус получить достаточно просто, нужно просто добавить юзернейм бота - <code>@{1}</code> в описание профиля.', (_fmt(user_link, '', -1), _fmt(BOT_USERNAME, '', -1)))
    )

    photo_url = "https://iili.io/CiK2iKJ.md.png"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Продолжить'),
                    callback_data="bonus_continue"
                )
            ]
        ]
    )

    await callback.message.delete()

    await callback.message.answer_photo(
        photo=photo_url,
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


@dp.callback_query(_inline_filter(lambda c: c.data == "bonus_continue"))
@_localized
async def process_bonus_continue(callback: types.CallbackQuery):
    await callback.answer()

    photo_url = "https://iili.io/CidJB9e.md.jpg"

    await callback.message.delete()

    await callback.message.answer_photo(
        photo=photo_url,
        caption=_l('Выполните так как на фото'),
        parse_mode=ParseMode.HTML
    )



@db_transaction
def _apply_mcoin_transfer(sender_id, receiver_id, amount, commission):
    if amount <= 0 or commission < 0 or commission > amount or sender_id == receiver_id:
        return False
    credited = amount - commission
    try:
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?", (amount, sender_id, amount))
        if cursor.rowcount != 1:
            return False
        cursor.execute("UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ?", (credited, credited, receiver_id))
        if cursor.rowcount != 1:
            return False
        cursor.execute("INSERT INTO transfers_history (sender_id, receiver_id, amount, commission, created_at) VALUES (?, ?, ?, ?, ?)", (sender_id, receiver_id, credited, commission, datetime.now().strftime("%d.%m.%Y %H:%M:%S")))
        return True
    except sqlite3.Error:
        logging.exception("Could not apply mCoin transfer")
        return False


@db_transaction
def _apply_mp_transfer(sender_id, receiver_id, amount, today):
    if amount <= 0 or sender_id == receiver_id:
        return False
    try:
        if int(sender_id) == UNRESTRICTED_OWNER_ID:
            cursor.execute(
                """
                UPDATE users SET mp_balance = mp_balance - ?,
                    mp_daily_transferred = CASE WHEN mp_daily_date = ? THEN COALESCE(mp_daily_transferred, 0) + ? ELSE ? END,
                    mp_daily_date = ?
                WHERE user_id = ? AND mp_balance >= ?
                """,
                (amount, today, amount, amount, today, sender_id, amount),
            )
        else:
            cursor.execute(
                """
            UPDATE users SET mp_balance = mp_balance - ?,
                mp_daily_transferred = CASE WHEN mp_daily_date = ? THEN COALESCE(mp_daily_transferred, 0) + ? ELSE ? END,
                mp_daily_date = ?
            WHERE user_id = ? AND mp_balance >= ?
                AND CASE WHEN mp_daily_date = ? THEN COALESCE(mp_daily_transferred, 0) ELSE 0 END + ? <= 1000
            """,
                (amount, today, amount, amount, today, sender_id, amount, today, amount),
            )
        if cursor.rowcount != 1:
            return False
        cursor.execute("UPDATE users SET mp_balance = mp_balance + ? WHERE user_id = ?", (amount, receiver_id))
        if cursor.rowcount != 1:
            return False
        cursor.execute("INSERT INTO mp_transfers_history (sender_id, receiver_id, amount, created_at) VALUES (?, ?, ?, ?)", (sender_id, receiver_id, amount, datetime.now().strftime("%d.%m.%Y %H:%M:%S")))
        return True
    except sqlite3.Error:
        logging.exception("Could not apply MP transfer")
        return False


def _transfer_comment_block(comment, user_id):
    if not comment:
        return ""
    return _lf('\n<blockquote> <tg-emoji emoji-id="5465300082628763143">💬</tg-emoji> Комментарий: {0}</blockquote>', (_fmt(html.escape(comment), '', -1),), user_id=user_id)


@dp.message(Command("transfer"))
@dp.message(_inline_filter(lambda message: message.text and (
    message.text.lower().startswith("дать") or
    message.text.lower().startswith("пер") or
    message.text.strip().lower() == "transfer" or
    message.text.strip().lower().startswith("transfer ")
)))
@_localized
async def cmd_transfer(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user(user_id)

    if is_admin(user_id) and not admin_has_permission(user_id, "transfer"):
        await message.reply(_l('<i>Владельцем отключено право на передачи.</i>'), parse_mode=ParseMode.HTML)
        return

    if is_transfer_banned(user_id):
        await message.reply(_l('<i>Вам заблокированы переводы! 🚫</i>'), parse_mode=ParseMode.HTML)
        return

    text = message.text.strip()

    parts = text.split()
    if len(parts) < 2 and not message.reply_to_message:
        await message.reply(
            _l('<i>Укажите сумму и получателя!\nПример: ответом на сообщение <code>дать 10кк</code> или <code>дать 10кк @username</code></i>'),
            parse_mode=ParseMode.HTML
        )
        return

    cmd = parts[0].lower()
    if cmd not in ["дать", "пер", "transfer"] and _message_command_name(message) != "transfer":
        return

    args_parts = parts[1:]

    target_user_id = None
    target_name = None
    amount = None
    comment = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Игрок')
        if args_parts:
            amt = resolve_bet_amount(args_parts[0], user_data["balance"])
            if amt is not None:
                amount = amt
                if len(args_parts) > 1:
                    comment = " ".join(args_parts[1:]).strip()
            else:
                amount = parse_amount(" ".join(args_parts))
    else:
        username_part = None
        amount_tokens = []

        for part in args_parts:
            if part.startswith("@") and not username_part:
                username_part = part.lstrip("@")
            else:
                amount_tokens.append(part)

        if username_part:
            found = get_user_by_username(username_part)
            if not found:
                await message.reply(
                    _lf('<i>Игрок @{0} не найден в базе бота. Он должен хотя бы раз написать боту.</i>', (_fmt(username_part, '', -1),)),
                    parse_mode=ParseMode.HTML
                )
                return
            target_user_id = found["user_id"]
            target_name = f"@{username_part}"

            if amount_tokens:
                amt = resolve_bet_amount(amount_tokens[0], user_data["balance"])
                if amt is not None:
                    amount = amt
                    if len(amount_tokens) > 1:
                        comment = " ".join(amount_tokens[1:]).strip()
                else:
                    amount = parse_amount(" ".join(amount_tokens))
        else:
            await message.reply(
                _l('<i>Укажите получателя!\nНапишите в ответ на сообщение игрока: <code>дать 10кк</code> или укажите юзернейм: <code>дать 10кк @username</code></i>'),
                parse_mode=ParseMode.HTML
            )
            return

    if amount is None or amount <= 0:
        await message.reply(_l('<i>Неверная сумма! Пример: <code>дать 10кк</code></i>'), parse_mode=ParseMode.HTML)
        return

    if target_user_id == user_id:
        await message.reply(_l('<i>Нельзя переводить самому себе!</i>'), parse_mode=ParseMode.HTML)
        return

    if is_transfer_banned(target_user_id):
        await message.reply(_l('<i>Этому пользователю заблокированы переводы! 🚫</i>'), parse_mode=ParseMode.HTML)
        return

    if user_data["balance"] < amount:
        await message.reply(
            _lf('<i>Недостаточно средств!\n<tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> Баланс: <b>{0} m¢</b></i>', (_fmt(format_number(user_data['balance']), '', -1),)),
            parse_mode=ParseMode.HTML
        )
        return

    allowed, limit_error = reserve_admin_usage(user_id, "transfer", amount)
    if not allowed:
        await message.reply(_lf('<i>{0}</i>', (_fmt(html.escape(limit_error or _l('Операция запрещена.')), '', -1),)), parse_mode=ParseMode.HTML)
        return

    commission = int(amount * 0.1)
    amount_after_commission = amount - commission

    sender_balance_before = user_data["balance"]
    receiver_data = get_user(target_user_id)
    receiver_balance_before = receiver_data["balance"]

    new_sender_balance = sender_balance_before - amount
    new_receiver_balance = receiver_balance_before + amount_after_commission
    if not _apply_mcoin_transfer(user_id, target_user_id, amount, commission):
        await message.reply(_l('<i>Не удалось выполнить перевод. Средства не списаны.</i>'), parse_mode=ParseMode.HTML)
        return

    if is_admin(user_id):
        _admin_log(
            message.from_user,
            "transfer_mcoin",
            target_id=target_user_id,
            target_name=target_name,
            details={"amount": format_number(amount), "balance": format_number(new_sender_balance), "currency": "mCoin"},
        )

    sender_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок'))
    sender_link = f'<a href="tg://user?id={user_id}">{sender_name}</a>'
    clean_target_name = html.escape(get_user_display_name(target_user_id, target_name))
    target_link = f'<a href="tg://user?id={target_user_id}">{clean_target_name}</a>'

    comment_block = _transfer_comment_block(comment, user_id)

    sender_msg = (
        _lf('<tg-emoji emoji-id="5472250091332993630">💳</tg-emoji> {0} передал(-а) <b>{1} m¢</b> игроку {2}.\n<blockquote> <tg-emoji emoji-id="5287231198098117669">💰</tg-emoji>Комиссия: {3} m¢</blockquote>{4}\n<code>·····················</code>\n<tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> Баланс: <s>{5}</s> → <b>{6} m¢</b>', (_fmt(sender_link, '', -1), _fmt(format_number(amount_after_commission), '', -1), _fmt(target_link, '', -1), _fmt(format_number(commission), '', -1), _fmt(comment_block, '', -1), _fmt(format_number(sender_balance_before), '', -1), _fmt(format_number(new_sender_balance), '', -1)))
    )

    await message.reply(sender_msg, parse_mode=ParseMode.HTML)

    try:
        receiver_msg = (
            _lf('<tg-emoji emoji-id="5472250091332993630">💳</tg-emoji> {0} передал(-а) вам <b>{1} m¢</b>{2}\n<code>·····················</code>\n<tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> Баланс: {3} → <b>{4} m¢</b>', (_fmt(sender_link, '', -1), _fmt(format_number(amount_after_commission), '', -1), _fmt(_transfer_comment_block(comment, target_user_id), '', -1), _fmt(format_number(receiver_balance_before), '', -1), _fmt(format_number(new_receiver_balance), '', -1)), user_id=target_user_id)
        )
        await bot.send_message(
            chat_id=target_user_id,
            text=receiver_msg,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass



@dp.message(Command("point", "points", "mp", "поинт", "поинты"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower() in ["поинт", "поинты", "point", "points", "/point", "/points", "мп", "/mp", "mp"]))
@_localized
async def cmd_point(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user(user_id)
    mp_balance = user_data.get("mp_balance", 0) or 0
    rem_limit = get_user_mp_limit(user_data, user_id)
    rem_limit_str = "∞" if rem_limit is None else format_number(rem_limit)

    text = (
        _lf('💎 Баланс: {0} MP\n<code>·····················</code>\n<blockquote>Лимит: {1} MP/д.</blockquote>', (_fmt(format_number(mp_balance), '', -1), _fmt(rem_limit_str, '', -1)))
    )

    if message.chat.type in ["group", "supergroup"]:
        await message.reply(text, parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("send", "mpsend", "sendmp"))
@dp.message(_inline_filter(lambda message: message.text and (
    message.text.strip().lower() == "/send" or
    message.text.strip().lower() == "send" or
    message.text.strip().lower().startswith("/send ") or
    message.text.strip().lower().startswith("send ")
)))
@_localized
async def cmd_send_mp(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user(user_id)
    sender_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок'))
    sender_link = f'<a href="tg://user?id={user_id}">{sender_name}</a>'

    help_text = (
        _lf('{0}, ты не ввел сколько MPOINT хочешь перевести!\nКомиссия на перевод - 0%\n<blockquote>Пример: /send сумма «в ответ» </blockquote>\n<blockquote>Пример: /send 10 6025818386</blockquote>\n<blockquote>Пример: /send 10 @username</blockquote>', (_fmt(sender_link, '', -1),))
    )

    if is_transfer_banned(user_id):
        await message.reply(_l('<i>Вам заблокированы переводы! 🚫</i>'), parse_mode=ParseMode.HTML)
        return

    text = message.text.strip()
    parts = text.split()

    target_user_id = None
    target_name = None
    amount = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Игрок')
        if len(parts) >= 2:
            amount = parse_amount(parts[1])
        else:
            await message.reply(help_text, parse_mode=ParseMode.HTML)
            return
    else:
        if len(parts) < 2:
            await message.reply(help_text, parse_mode=ParseMode.HTML)
            return
        elif len(parts) == 2:
            await message.reply(help_text, parse_mode=ParseMode.HTML)
            return
        else:
            arg1 = parts[1]
            arg2 = parts[2]

            parsed_amt1 = parse_amount(arg1)
            parsed_amt2 = parse_amount(arg2)

            if parsed_amt1 is not None and not (arg1.isdigit() and len(arg1) >= 8 and parsed_amt2 is not None):
                amount = parsed_amt1
                target_arg = arg2
            elif parsed_amt2 is not None:
                amount = parsed_amt2
                target_arg = arg1
            else:
                await message.reply(help_text, parse_mode=ParseMode.HTML)
                return

            if target_arg.startswith("@"):
                uname = target_arg.lstrip("@")
                found = get_user_by_username(uname)
                if not found:
                    await message.reply(
                        _lf('<i>Игрок @{0} не найден в базе бота. Он должен хотя бы раз написать боту.</i>', (_fmt(uname, '', -1),)),
                        parse_mode=ParseMode.HTML
                    )
                    return
                target_user_id = found["user_id"]
                target_name = f"@{uname}"
            elif target_arg.isdigit():
                target_user_id = int(target_arg)
                target_name = get_user_display_name(target_user_id)
            else:
                found = get_user_by_username(target_arg)
                if found:
                    target_user_id = found["user_id"]
                    target_name = f"@{target_arg}"
                else:
                    await message.reply(
                        _lf('<i>Игрок {0} не найден в базе бота.</i>', (_fmt(target_arg, '', -1),)),
                        parse_mode=ParseMode.HTML
                    )
                    return

    if amount is None or amount <= 0:
        await message.reply(help_text, parse_mode=ParseMode.HTML)
        return

    if target_user_id == user_id:
        await message.reply(_l('<i>Нельзя переводить самому себе!</i>'), parse_mode=ParseMode.HTML)
        return

    if is_transfer_banned(target_user_id):
        await message.reply(_l('<i>Этому пользователю заблокированы переводы! 🚫</i>'), parse_mode=ParseMode.HTML)
        return

    sender_mp = user_data.get("mp_balance", 0) or 0
    if sender_mp < amount:
        await message.reply(
            _lf('<i>Недостаточно средств!\n💎 Баланс: <b>{0} MP</b></i>', (_fmt(format_number(sender_mp), '', -1),)),
            parse_mode=ParseMode.HTML
        )
        return

    rem_limit = get_user_mp_limit(user_data, user_id)
    if rem_limit is not None and amount > rem_limit:
        await message.reply(
            _lf('<i>Превышен суточный лимит переводов!\n📮 Доступно сегодня: <b>{0} MP/д.</b></i>', (_fmt(format_number(rem_limit), '', -1),)),
            parse_mode=ParseMode.HTML
        )
        return

    get_user(target_user_id)

    confirm_token = secrets.token_hex(8)
    mp_pending_transfers[confirm_token] = {
        "sender_id": user_id,
        "receiver_id": target_user_id,
        "amount": amount,
        "target_name": target_name,
        "chat_id": message.chat.id
    }

    target_display = html.escape(get_user_display_name(target_user_id, target_name))
    target_link = f'<a href="tg://user?id={target_user_id}">{target_display}</a>'

    confirm_text = (
        _lf('❓ {0}, точно хочешь перевести <b>{1} MP </b>игроку {2}?', (_fmt(sender_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(target_link, '', -1)))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Да ✅'),
                    callback_data=f"mp_yes_{confirm_token}",
                    style="success"
                ),
                InlineKeyboardButton(
                    text=_l('Нет 💢'),
                    callback_data=f"mp_no_{confirm_token}",
                    style="danger"
                )
            ]
        ]
    )

    await message.reply(
        text=confirm_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("mp_no_")))
@_localized
async def process_mp_no(callback: types.CallbackQuery):
    token = callback.data.split("_")[-1]
    transfer = mp_pending_transfers.get(token)
    if transfer and callback.from_user.id != transfer["sender_id"]:
        await callback.answer(_l('Это действие не для вас!'), show_alert=True)
        return

    mp_pending_transfers.pop(token, None)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("mp_yes_")))
@_localized
async def process_mp_yes(callback: types.CallbackQuery):
    token = callback.data.split("_")[-1]
    transfer = mp_pending_transfers.get(token)
    if not transfer:
        await callback.answer(_l('Перевод устарел или уже выполнен!'), show_alert=True)
        return

    if callback.from_user.id != transfer["sender_id"]:
        await callback.answer(_l('Это действие не для вас!'), show_alert=True)
        return

    sender_id = transfer["sender_id"]
    receiver_id = transfer["receiver_id"]
    amount = transfer["amount"]

    sender_data = get_user(sender_id)
    receiver_data = get_user(receiver_id)

    sender_mp_before = sender_data.get("mp_balance", 0) or 0
    if sender_mp_before < amount:
        await callback.answer(_l('Недостаточно MP на балансе!'), show_alert=True)
        return

    rem_limit = get_user_mp_limit(sender_data, sender_id)
    if rem_limit is not None and amount > rem_limit:
        await callback.answer(_l('Превышен суточный лимит переводов!'), show_alert=True)
        return

    if is_transfer_banned(sender_id) or is_transfer_banned(receiver_id):
        await callback.answer(_l('Переводы заблокированы!'), show_alert=True)
        return

    allowed, limit_error = reserve_admin_usage(sender_id, "mp_transfer", amount)
    if not allowed:
        await callback.answer(limit_error or _l('Операция запрещена.'), show_alert=True)
        return

    sender_mp_after = sender_mp_before - amount
    receiver_mp_before = receiver_data.get("mp_balance", 0) or 0
    receiver_mp_after = receiver_mp_before + amount

    today_str = get_msk_today_str()
    if sender_data.get("mp_daily_date") != today_str:
        new_daily_transferred = amount
    else:
        new_daily_transferred = (sender_data.get("mp_daily_transferred", 0) or 0) + amount

    new_rem_limit = None if rem_limit is None else max(0, 1000 - new_daily_transferred)
    new_rem_limit_str = "∞" if new_rem_limit is None else format_number(new_rem_limit)

    if not _apply_mp_transfer(sender_id, receiver_id, amount, today_str):
        await callback.answer(_l('Не удалось выполнить перевод. Средства не списаны.'), show_alert=True)
        return
    mp_pending_transfers.pop(token, None)
    if is_admin(sender_id):
        _admin_log(
            callback.from_user,
            "transfer_mp",
            target_id=receiver_id,
            target_name=transfer.get("target_name"),
            details={"amount": format_number(amount), "balance": format_number(sender_mp_after), "currency": "MP"},
        )

    sender_name = html.escape(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок'))
    sender_link = f'<a href="tg://user?id={sender_id}">{sender_name}</a>'
    target_raw_name = transfer.get("target_name") or get_user_display_name(receiver_id)
    target_name = html.escape(get_user_display_name(receiver_id, target_raw_name))
    target_link = f'<a href="tg://user?id={receiver_id}">{target_name}</a>'

    success_msg = (
        _lf('🔹 {0} перевел(-а) <b>{1} MP </b> {2}. \n<blockquote>📮 Лимит: {3} MP</blockquote>\n<code>·····················</code>\n💎 Баланс: <s>{4}</s> → {5} MP', (_fmt(sender_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(target_link, '', -1), _fmt(new_rem_limit_str, '', -1), _fmt(format_number(sender_mp_before), '', -1), _fmt(format_number(sender_mp_after), '', -1)))
    )

    try:
        await callback.message.edit_text(
            text=success_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=None
        )
    except Exception:
        pass

    await callback.answer(_l('Перевод выполнен!'))

    try:
        receiver_pm = _lf('✅ Поступил перевод в размере {0} MP от {1}.', (_fmt(format_number(amount), '', -1), _fmt(sender_link, '', -1)), user_id=receiver_id)
        await bot.send_message(
            chat_id=receiver_id,
            text=receiver_pm,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


@dp.message(Command("addmp"))
@_localized
async def cmd_addmp(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]
    if not args:
        await message.answer(_l('<i>Использование: /addmp [сумма] или в ответ на сообщение</i>'), parse_mode=ParseMode.HTML)
        return

    amount = parse_amount(args[0])
    if amount is None:
        await message.answer(_l('<i>Неверная сумма!</i>'), parse_mode=ParseMode.HTML)
        return

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        target_name = get_user_display_name(message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name)
    elif len(args) > 1:
        target_arg = args[1]
        if target_arg.startswith("@"):
            found = get_user_by_username(target_arg.lstrip("@"))
            if not found:
                await message.answer(_l('<i>Пользователь не найден!</i>'), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = target_arg
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = f"ID:{target_user_id}"
        else:
            found = get_user_by_username(target_arg)
            if not found:
                await message.answer(_l('<i>Пользователь не найден!</i>'), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{target_arg}"
    else:
        target_user_id = user_id
        target_name = None

    allowed, limit_error = reserve_admin_usage(user_id, "mp_issue", amount)
    if not allowed:
        await message.reply(_lf('<i>{0}</i>', (_fmt(html.escape(limit_error or _l('Операция запрещена.')), '', -1),)), parse_mode=ParseMode.HTML)
        return

    u_data = get_user(target_user_id)
    new_bal = u_data.get("mp_balance", 0) + amount
    if update_user(target_user_id, mp_balance=new_bal):
        _admin_log(
            message.from_user,
            "add_mp",
            target_id=target_user_id,
            target_name=target_name,
            details={"amount": format_number(amount), "balance": format_number(new_bal), "currency": "MP"},
        )
        await message.reply(
            _lf('<i>✅ На баланс {0} добавлено <b>{1} MP</b>\n💎 Текущий баланс: <b>{2} MP</b></i>', (_fmt(html.escape(get_user_display_name(target_user_id, target_name) if target_name is not None else _l('ваш')), '', -1), _fmt(format_number(amount), '', -1), _fmt(format_number(new_bal), '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(_l('<i>Ошибка базы данных!</i>'), parse_mode=ParseMode.HTML)


@dp.message(Command("setmp"))
@_localized
async def cmd_setmp(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS or not admin_has_permission(user_id, "set"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]
    if not args:
        await message.answer(_l('<i>Использование: /setmp [сумма] или в ответ на сообщение</i>'), parse_mode=ParseMode.HTML)
        return

    amount = parse_amount(args[0])
    if amount is None or amount < 0:
        await message.answer(_l('<i>Неверная сумма!</i>'), parse_mode=ParseMode.HTML)
        return

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        target_name = get_user_display_name(message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name)
    elif len(args) > 1:
        target_arg = args[1]
        if target_arg.startswith("@"):
            found = get_user_by_username(target_arg.lstrip("@"))
            if not found:
                await message.answer(_l('<i>Пользователь не найден!</i>'), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = target_arg
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = f"ID:{target_user_id}"
        else:
            found = get_user_by_username(target_arg)
            if not found:
                await message.answer(_l('<i>Пользователь не найден!</i>'), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{target_arg}"
    else:
        target_user_id = user_id
        target_name = None

    get_user(target_user_id)
    if update_user(target_user_id, mp_balance=amount):
        _admin_log(
            message.from_user,
            "zero_mp" if int(amount) == 0 else "set_mp",
            target_id=target_user_id,
            target_name=target_name,
            details={"balance": format_number(amount), "currency": "MP"},
        )
        await message.reply(
            _lf('<i>✅ Баланс MP {0} установлен на <b>{1} MP</b></i>', (_fmt(html.escape(get_user_display_name(target_user_id, target_name) if target_name is not None else _l('ваш')), '', -1), _fmt(format_number(amount), '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(_l('<i>Ошибка базы данных!</i>'), parse_mode=ParseMode.HTML)



giveaways = {}
active_giveaways = {}
giveaway_counter = 0


@dp.message(_inline_filter(lambda message: message.text and (
    message.text.lower().startswith("раздача") or
    message.text.lower().startswith("/раздача") or
    message.text.lower().startswith("роздача") or
    message.text.lower().startswith("/giveaway") or
    message.text.strip().lower() == "giveaway" or
    message.text.strip().lower().startswith("giveaway ")
)))
@_localized
async def cmd_giveaway(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            _l('<i>Использование: раздача [сумма] [акт]\nПример: <code>раздача 10кк 10</code></i>'),
            parse_mode=ParseMode.HTML
        )
        return

    amount = parse_amount(args[1])
    if amount is None or amount <= 0:
        await message.answer(_l('<i>Неверная сумма! Пример: <code>раздача 10кк 10</code></i>'), parse_mode=ParseMode.HTML)
        return

    try:
        activations = int(args[2])
        if activations <= 0:
            await message.answer(_l('<i>Количество активаций должно быть больше 0!</i>'), parse_mode=ParseMode.HTML)
            return
    except ValueError:
        await message.answer(_l('<i>Количество активаций должно быть числом! Пример: <code>раздача 10кк 10</code></i>'), parse_mode=ParseMode.HTML)
        return

    global giveaway_counter
    giveaway_counter += 1
    gid = giveaway_counter
    chat_id = message.chat.id

    old_gid = active_giveaways.get(chat_id)
    if old_gid and old_gid in giveaways:
        giveaways[old_gid]["is_active"] = False

    giveaways[gid] = {
        "chat_id": chat_id,
        "amount": amount,
        "total_activations": activations,
        "remaining_activations": activations,
        "claimed_users": set(),
        "is_active": True,
        "message_id": None
    }
    active_giveaways[chat_id] = gid

    text = (
        _lf('<tg-emoji emoji-id="5287231198098117669">💰</tg-emoji>Новая раздача на <b>{0}</b> акт.\nСумма награды: <b>{1} m¢</b>\n\n<i>Чтобы забрать награду, нажми на кнопку ниже!</i>', (_fmt(activations, '', -1), _fmt(format_number(amount), '', -1)))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Взять'),
                    callback_data=f"giveaway_claim_{gid}",
                    style="success",
                    icon_custom_emoji_id="5278467510604160626"
                )
            ]
        ]
    )

    msg = await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    giveaways[gid]["message_id"] = msg.message_id
    _admin_log(
        message.from_user,
        "giveaway",
        details={"amount": format_number(amount), "currency": "mCoin", "activations": activations},
    )

    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception:
        pass


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("giveaway_claim_")))
@_localized
async def process_giveaway_claim(callback: types.CallbackQuery):
    try:
        gid = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    giveaway = giveaways.get(gid)
    if not giveaway:
        try:
            await callback.answer(_l('Эта раздача устарела!'), show_alert=True)
        except Exception:
            pass
        return

    current_gid = active_giveaways.get(chat_id)
    if current_gid != gid or not giveaway["is_active"]:
        try:
            await callback.answer(_l('Эта раздача устарела!'), show_alert=True)
        except Exception:
            pass
        return

    if user_id in giveaway["claimed_users"]:
        try:
            await callback.answer(_l('Вы уже забрали эту награду!'), show_alert=True)
        except Exception:
            pass
        return

    if giveaway["remaining_activations"] <= 0:
        try:
            await callback.answer(_l('Раздача окончена! Активации закончились.'), show_alert=True)
        except Exception:
            pass
        return

    giveaway["remaining_activations"] -= 1
    giveaway["claimed_users"].add(user_id)

    amount = giveaway["amount"]
    user_data = get_user(user_id)
    update_user(user_id, balance=user_data["balance"] + amount)

    user_name = html.escape(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок'))
    user_link = f'<a href="tg://user?id={user_id}">{user_name}</a>'

    try:
        await callback.message.reply(
            _lf('<i>{0}, вы получили <b>{1} m¢</b>!</i>', (_fmt(user_link, '', -1), _fmt(format_number(amount), '', -1))),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    try:
        await callback.answer(_lf('Вы получили {0} m¢!', (_fmt(format_number(amount), '', -1),)))
    except Exception:
        pass

    if giveaway["remaining_activations"] <= 0:
        giveaway["is_active"] = False
        try:
            finished_text = (
                _lf('<tg-emoji emoji-id="5287231198098117669">💰</tg-emoji><b>Раздача окончена!</b>\nСумма награды: <b>{0} m¢</b>\nВсе {1} активаций были забраны.', (_fmt(format_number(amount), '', -1), _fmt(giveaway['total_activations'], '', -1)))
            )
            await callback.message.edit_text(
                text=finished_text,
                parse_mode=ParseMode.HTML,
                reply_markup=None
            )
        except Exception:
            pass




def _demo_keyboard(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=tr(user_id, "demo_enable"), callback_data="demo_on", style="success"),
            InlineKeyboardButton(text=tr(user_id, "demo_disable"), callback_data="demo_off", style="danger"),
        ]
    ])


def _set_demo_mode(user_id, enabled):
    try:
        if enabled:
            initialize_demo_balance(user_id)
            cursor.execute(
                "INSERT INTO demo_modes (user_id, enabled, updated_at) VALUES (?, 1, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET enabled = 1, updated_at = excluded.updated_at",
                (user_id, datetime.now().isoformat())
            )
        else:
            cursor.execute("DELETE FROM demo_modes WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    except Exception:
        return False


async def _send_demo_status(target, user_id, edit=False):
    enabled = is_demo_user(user_id)
    status = tr(user_id, "demo_on" if enabled else "demo_off")
    text = (
        f"{tr(user_id, 'demo_title')}\n"
        f"{tr(user_id, 'demo_status', status=status)}\n"
        f"{tr(user_id, 'demo_balance', balance=format_number(get_demo_balance(user_id)))}\n\n"
        f"{tr(user_id, 'demo_description')}"
    )
    if edit:
        await target.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_demo_keyboard(user_id))
    else:
        await target.answer(text, parse_mode=ParseMode.HTML, reply_markup=_demo_keyboard(user_id))


@dp.message(Command("demo", "демо"))
@_localized
async def cmd_demo(message: types.Message):
    user_id = message.from_user.id
    if message.chat.type != "private":
        await message.answer(f"<i>{tr(user_id, 'demo_only_private')}</i>", parse_mode=ParseMode.HTML)
        return
    args = (message.text or "").split()[1:]
    if args and args[0].lower() in ("on", "вкл", "включить", "1"):
        _set_demo_mode(user_id, True)
    elif args and args[0].lower() in ("off", "выкл", "выключить", "0"):
        _set_demo_mode(user_id, False)
    await _send_demo_status(message, user_id)


@dp.callback_query(_inline_filter(lambda c: c.data in ("demo_on", "demo_off")))
@_localized
async def process_demo_toggle(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if callback.message and callback.message.chat.type != "private":
        await callback.answer(tr(user_id, "demo_only_private"), show_alert=True)
        return
    enabled = callback.data == "demo_on"
    if not _set_demo_mode(user_id, enabled):
        await callback.answer(_l('Не удалось сохранить режим.'), show_alert=True)
        return
    await _send_demo_status(callback.message, user_id, edit=True)
    await callback.answer(tr(user_id, "demo_on" if enabled else "demo_off"))


settings_nickname_pending = set()


def _settings_keyboard(user_id):
    settings = get_user_settings(user_id)
    language = settings.get("language", "ru")
    demo_enabled = is_demo_user(user_id)
    hide_enabled = bool(settings.get("hide_top_username"))
    demo_status = tr(user_id, "settings_demo_on" if demo_enabled else "settings_demo_off")
    hide_status = tr(user_id, "settings_hide_yes" if hide_enabled else "settings_hide_no")
    nickname = settings.get("bot_nickname") or tr(user_id, "settings_nickname_empty")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{tr(user_id, 'settings_language')}: {LANGUAGE_NAMES.get(language, language)}", callback_data="settings_languages", style="primary")],
        [
            InlineKeyboardButton(text=f"{tr(user_id, 'settings_demo')}: {demo_status}", callback_data="settings_demo_off" if demo_enabled else "settings_demo_on", style="danger" if demo_enabled else "success"),
            InlineKeyboardButton(text=tr(user_id, "settings_demo_balance"), callback_data="settings_demo_info", style="primary"),
        ],
        [InlineKeyboardButton(text=f"{tr(user_id, 'settings_nickname')}: {str(nickname)}", callback_data="settings_nickname", style="primary")],
        [InlineKeyboardButton(text=tr(user_id, "settings_clear_name"), callback_data="settings_clear_nickname", style="danger")],
        [InlineKeyboardButton(text=f"{tr(user_id, 'settings_hide_top')}: {hide_status}", callback_data="settings_hide_top", style="primary")],
        [InlineKeyboardButton(text=tr(user_id, "settings_back"), callback_data="settings_back")],
    ])


def _settings_text(user_id):
    settings = get_user_settings(user_id)
    language = settings.get("language", "ru")
    demo_enabled = is_demo_user(user_id)
    nickname = settings.get("bot_nickname") or tr(user_id, "settings_nickname_empty")
    hide_status = tr(user_id, "settings_hide_yes" if settings.get("hide_top_username") else "settings_hide_no")
    demo_status = tr(user_id, "settings_demo_on" if demo_enabled else "settings_demo_off")
    return (
        f"{tr(user_id, 'settings_title')}\n\n"
        f"{tr(user_id, 'settings_language')}: <b>{html.escape(LANGUAGE_NAMES.get(language, language))}</b>\n"
        f"{tr(user_id, 'settings_demo')}: <b>{demo_status}</b>\n"
        f"{tr(user_id, 'settings_demo_balance')}: <b>{format_number(get_demo_balance(user_id))} m¢</b>\n"
        f"{tr(user_id, 'settings_nickname')}: <b>{html.escape(str(nickname))}</b>\n"
        f"{tr(user_id, 'settings_hide_top')}: <b>{hide_status}</b>\n\n"
        f"{tr(user_id, 'demo_description')}"
    )


def _language_keyboard(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Русский", callback_data="settings_lang_ru"),
            InlineKeyboardButton(text="English", callback_data="settings_lang_en"),
        ],
        [
            InlineKeyboardButton(text="Українська", callback_data="settings_lang_uk"),
            InlineKeyboardButton(text="Қазақша", callback_data="settings_lang_kk"),
        ],
        [InlineKeyboardButton(text=tr(user_id, "settings_back"), callback_data="settings_open")],
    ])


def _language_text(user_id):
    language = get_user_language(user_id)
    return (
        f"{tr(user_id, 'language_title')}\n"
        f"{tr(user_id, 'language_current', language=html.escape(LANGUAGE_NAMES.get(language, language)))}\n\n"
        f"{tr(user_id, 'language_prompt')}"
    )


async def _show_settings(target, user_id, edit=False):
    text = _settings_text(user_id)
    markup = _settings_keyboard(user_id)
    if edit:
        try:
            await target.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception:
            await target.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await target.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


@dp.message(Command("language", "lang", "язык"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower().split()[0] in ("/language", "/lang", "/язык", "язык", "language")))
@_localized
async def cmd_language(message: types.Message):
    user_id = int(message.from_user.id)
    parts = (message.text or "").strip().split()
    if len(parts) > 1:
        raw_lang = parts[1].strip().lower()
        if raw_lang in LANGUAGE_NAMES or raw_lang in ("ua", "kz"):
            selected = _telegram_language(raw_lang)
            set_user_settings(user_id, language=selected)
    await message.answer(
        _language_text(user_id),
        parse_mode=ParseMode.HTML,
        reply_markup=_language_keyboard(user_id),
    )


@dp.message(Command("settings", "настройки"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower() in ("настройки", "/настройки", "/settings")))
@_localized
async def cmd_settings(message: types.Message):
    if message.chat.type != "private":
        await message.answer(f"<i>{tr(message.from_user.id, 'settings_private_only')}</i>", parse_mode=ParseMode.HTML)
        return
    await _show_settings(message, int(message.from_user.id))


async def _handle_settings_callback(callback: types.CallbackQuery):
    user_id = int(callback.from_user.id)
    data = str(callback.data or "")
    if data.startswith("settings_lang_"):
        language = data.rsplit("_", 1)[-1]
        if language in LANGUAGE_NAMES:
            set_user_settings(user_id, language=language)
        if callback.message and callback.message.chat.type == "private":
            await _show_settings(callback.message, user_id, edit=True)
        elif callback.message:
            try:
                await callback.message.edit_text(
                    _language_text(user_id),
                    parse_mode=ParseMode.HTML,
                    reply_markup=_language_keyboard(user_id),
                )
            except Exception:
                pass
        await callback.answer(tr(user_id, "settings_language_saved"))
        return
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer(tr(user_id, "settings_private_only"), show_alert=True)
        return
    if data == "settings_open":
        await _show_settings(callback.message, user_id, edit=True)
    elif data == "settings_languages":
        await callback.message.edit_text(
            _language_text(user_id),
            parse_mode=ParseMode.HTML,
            reply_markup=_language_keyboard(user_id),
        )
    elif data in ("settings_demo_on", "settings_demo_off"):
        _set_demo_mode(user_id, data.endswith("_on"))
        await _show_settings(callback.message, user_id, edit=True)
    elif data == "settings_demo_info":
        await callback.answer(f"{format_number(get_demo_balance(user_id))} m¢", show_alert=True)
        return
    elif data == "settings_hide_top":
        current = get_user_settings(user_id)
        set_user_settings(user_id, hide_top_username=not current.get("hide_top_username"))
        await _show_settings(callback.message, user_id, edit=True)
    elif data == "settings_nickname":
        settings_nickname_pending.add(user_id)
        await callback.message.answer(tr(user_id, "settings_name_prompt"), parse_mode=ParseMode.HTML)
    elif data == "settings_clear_nickname":
        set_user_settings(user_id, bot_nickname=None)
        await _show_settings(callback.message, user_id, edit=True)
    elif data == "settings_back":
        try:
            await callback.message.delete()
        except Exception:
            pass
    await callback.answer()


@dp.callback_query(_inline_filter(lambda callback: bool(callback.data and (callback.data == "settings_open" or callback.data.startswith("settings_")))))
@_localized
async def process_settings_callback(callback: types.CallbackQuery):
    await _handle_settings_callback(callback)



def _settings_pending_filter(message):
    return bool(message.from_user and message.chat and message.chat.type == "private" and message.from_user.id in settings_nickname_pending)


async def _handle_settings_text(message: types.Message):
    user_id = int(message.from_user.id)
    settings_nickname_pending.discard(user_id)
    value = (message.text or "").strip()
    if value.lower() in {"сброс", "сбросить", "reset", "clear", "тазалау", "скинути", "очистити"}:
        set_user_settings(user_id, bot_nickname=None)
        await message.answer(tr(user_id, "settings_name_cleared"), parse_mode=ParseMode.HTML)
    elif not 2 <= len(value) <= 32 or "\n" in value:
        await message.answer(tr(user_id, "settings_name_invalid"), parse_mode=ParseMode.HTML)
    else:
        set_user_settings(user_id, bot_nickname=value)
        await message.answer(tr(user_id, "settings_name_saved"), parse_mode=ParseMode.HTML)
    await _show_settings(message, user_id)



def resolve_user_id_argument(raw):
    raw = (raw or "").strip()
    if raw.isdigit():
        return int(raw)
    found = get_user_by_username(raw.lstrip("@"))
    return found["user_id"] if found else None


@dp.message(Command("owners", "owner", "овнеры", "овнер"))
@_localized
async def cmd_owners(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return
    owners_text = ", ".join(f"<code>{uid}</code>" for uid in sorted(OWNER_IDS))
    await message.answer(
        _lf('<b>👑 Owners</b>\n{0}\n\nАдминистраторов: <b>{1}</b>\nЛимит 0 означает безлимит. Изменять лимиты и права могут только owners.', (_fmt(owners_text, '', -1), _fmt(len(ADMINS), '', -1))),
        parse_mode=ParseMode.HTML
    )


admin_control_selections = {}
admin_limit_sessions = {}


def _admin_control_ids(owner_id):
    return sorted({int(uid) for uid in admin_control_selections.get(owner_id, set()) if uid in ADMINS and not is_owner(uid)})


@_localized
def _admin_control_keyboard(owner_id):
    selected = set(_admin_control_ids(owner_id))
    rows = []
    for admin_id in ADMINS:
        if is_owner(admin_id):
            rows.append([InlineKeyboardButton(text=f"👑 {admin_id} · {_l('Владелец')}", callback_data="admctl_noop", style="primary")])
        else:
            mark = "✅" if admin_id in selected else "⬜"
            rows.append([InlineKeyboardButton(text=f"{mark} {admin_id}", callback_data=f"admctl_sel_{admin_id}", style="primary")])
    rows.extend([
        [
            InlineKeyboardButton(text=_l('Выбрать всех'), callback_data="admctl_sel_all", style="primary"),
            InlineKeyboardButton(text=_l('Снять выбор'), callback_data="admctl_sel_clear", style="danger"),
        ],
        [InlineKeyboardButton(text=_lf('Настроить выбранных ({0})', (_fmt(len(selected), '', -1),)), callback_data="admctl_actions", style="success")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@_localized
def _admin_control_text(owner_id):
    selected = _admin_control_ids(owner_id)
    return (
        _lf('<b>🛡 Контроль администраторов</b>\nВыберите одного или сразу нескольких обычных администраторов. Owners не ограничиваются и отображаются отдельно.\n\nВыбрано: <b>{0}</b>\nПосле выбора можно массово включить или отключить права. Лимиты задаются командами <code>/adminlimit</code> — их можно применять к списку ID через запятую.', (_fmt(len(selected), '', -1),))
    )


@_localized
def _admin_action_keyboard(owner_id):
    selected = _admin_control_ids(owner_id)
    if not selected:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('← К выбору администраторов'), callback_data="admctl_back", style="primary")]])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_l('✅ Бан разрешить'), callback_data="admctl_perm_ban_1", style="success"),
            InlineKeyboardButton(text=_l('⛔ Бан запретить'), callback_data="admctl_perm_ban_0", style="danger"),
        ],
        [
            InlineKeyboardButton(text=_l('✅ Передачи разрешить'), callback_data="admctl_perm_transfer_1", style="success"),
            InlineKeyboardButton(text=_l('⛔ Передачи запретить'), callback_data="admctl_perm_transfer_0", style="danger"),
        ],
        [
            InlineKeyboardButton(text=_l('✅ Выдачу разрешить'), callback_data="admctl_perm_issue_1", style="success"),
            InlineKeyboardButton(text=_l('⛔ Выдачу запретить'), callback_data="admctl_perm_issue_0", style="danger"),
        ],
        [
            InlineKeyboardButton(text=_l('✅ Set разрешить'), callback_data="admctl_perm_set_1", style="success"),
            InlineKeyboardButton(text=_l('⛔ Set запретить'), callback_data="admctl_perm_set_0", style="danger"),
        ],
        [
            InlineKeyboardButton(text=_l('✅ MP-переводы разрешить'), callback_data="admctl_perm_mp_transfer_1", style="success"),
            InlineKeyboardButton(text=_l('⛔ MP-переводы запретить'), callback_data="admctl_perm_mp_transfer_0", style="danger"),
        ],
        [
            InlineKeyboardButton(text=_l('✅ MP-выдачу разрешить'), callback_data="admctl_perm_mp_issue_1", style="success"),
            InlineKeyboardButton(text=_l('⛔ MP-выдачу запретить'), callback_data="admctl_perm_mp_issue_0", style="danger"),
        ],
        [InlineKeyboardButton(text=_l('📊 Изменить лимиты'), callback_data="admctl_limit_start", style="primary")],
        [InlineKeyboardButton(text=_l('← Назад к выбору'), callback_data="admctl_back", style="primary")],
    ])


@dp.message(Command("adminlist", "списокадминов", "админы"))
@_localized
async def cmd_admin_list(message: types.Message):
    if not is_owner(message.from_user.id):
        await message.answer(_l('<i>Только owners могут просматривать настройки администраторов.</i>'), parse_mode=ParseMode.HTML)
        return
    lines = [_l('<b>🛡 Настройки администраторов</b>')]
    for admin_id in ADMINS:
        control = get_admin_control(admin_id)
        role = "👑 " + _l('Владелец') if is_owner(admin_id) else _l('Администратор')
        perms = []
        for key, label in (("can_ban", _l('бан')), ("can_transfer", _l('передачи')), ("can_issue", _l('выдача')), ("can_set", _l('установка')), ("can_mp_transfer", _l('MP-передачи')), ("can_mp_issue", _l('MP-выдача'))):
            if control.get(key):
                perms.append(label)
        lines.append(
            _lf('\n• <code>{0}</code> — {1}\n  mCoin передача: {2}/д.\n  mCoin выдача: {3}/д.\n  MP передача: {4}/д.\n  MP выдача: {5}/д.\n  права: {6}', (_fmt(admin_id, '', -1), _fmt(role, '', -1), _fmt(format_number(control.get('transfer_limit', 0)) if control.get('transfer_limit', 0) else '∞', '', -1), _fmt(format_number(control.get('issue_limit', 0)) if control.get('issue_limit', 0) else '∞', '', -1), _fmt(format_number(control.get('mp_transfer_limit', 0)) if control.get('mp_transfer_limit', 0) else '∞', '', -1), _fmt(format_number(control.get('mp_issue_limit', 0)) if control.get('mp_issue_limit', 0) else '∞', '', -1), _fmt(', '.join(perms) if perms else _l('нет'), '', -1)))
        )
    await message.answer("".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_l('⚙️ Контролировать администраторов'), callback_data="admctl_open", style="primary")]
    ]))


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("admctl_")))
@_localized
async def process_admin_control_callback(callback: types.CallbackQuery):
    owner_id = callback.from_user.id
    if not is_owner(owner_id):
        await callback.answer(_l('Только owners могут управлять администраторами.'), show_alert=True)
        return
    data = callback.data
    selected = admin_control_selections.setdefault(owner_id, set())
    if data == "admctl_open":
        await callback.message.edit_text(_admin_control_text(owner_id), parse_mode=ParseMode.HTML, reply_markup=_admin_control_keyboard(owner_id))
    elif data == "admctl_sel_all":
        selected.clear()
        selected.update(uid for uid in ADMINS if not is_owner(uid))
        await callback.message.edit_reply_markup(reply_markup=_admin_control_keyboard(owner_id))
    elif data == "admctl_sel_clear":
        selected.clear()
        await callback.message.edit_reply_markup(reply_markup=_admin_control_keyboard(owner_id))
    elif data.startswith("admctl_sel_"):
        raw_id = data[len("admctl_sel_"):]
        if raw_id.isdigit() and int(raw_id) in ADMINS and not is_owner(int(raw_id)):
            admin_id = int(raw_id)
            if admin_id in selected:
                selected.remove(admin_id)
            else:
                selected.add(admin_id)
        await callback.message.edit_reply_markup(reply_markup=_admin_control_keyboard(owner_id))
    elif data == "admctl_actions":
        targets = _admin_control_ids(owner_id)
        if not targets:
            await callback.answer(_l('Сначала выберите хотя бы одного администратора.'), show_alert=True)
            return
        await callback.message.edit_text(
            _lf('<b>⚙️ Массовое управление</b>\nВыбрано администраторов: <code>{0}</code>\n\nНажмите действие — оно применится ко всем выбранным. Лимиты можно назначить командой из отдельной кнопки.', (_fmt(', '.join((str(x) for x in targets)), '', -1),)),
            parse_mode=ParseMode.HTML,
            reply_markup=_admin_action_keyboard(owner_id)
        )
    elif data.startswith("admctl_perm_"):
        payload = data[len("admctl_perm_"):]
        permission, flag = payload.rsplit("_", 1) if "_" in payload else ("", "")
        if flag in ("0", "1") and permission in _ADMIN_PERMISSION_COLUMNS:
            enabled = flag == "1"
            targets = _admin_control_ids(owner_id)
            done = 0
            for admin_id in targets:
                if set_admin_permission(admin_id, permission, enabled, owner_id):
                    done += 1
                    _admin_log(
                        callback.from_user,
                        "admin_permission",
                        target_id=admin_id,
                        details={"permission": permission, "enabled": enabled},
                    )
            await callback.message.edit_text(
                _lf('<b>✅ Готово</b>\nПраво <b>{0}</b> {1} для {2} администраторов.', (_fmt(html.escape(permission), '', -1), _fmt(_l('разрешено') if enabled else _l('запрещено'), '', -1), _fmt(done, '', -1))),
                parse_mode=ParseMode.HTML,
                reply_markup=_admin_action_keyboard(owner_id)
            )
    elif data in ("admctl_limit_help", "admctl_limit_start"):
        targets = _admin_control_ids(owner_id)
        if not targets:
            await callback.answer(_l('Сначала выберите администраторов.'), show_alert=True)
            return
        admin_limit_sessions[owner_id] = {"targets": targets, "kind": None}
        await callback.message.edit_text(
            _lf('<b>📊 Изменение суточных лимитов</b>\nВыбраны: <code>{0}</code>\nВыберите тип операции, затем отправьте сумму. 0 — безлимит.', (_fmt(', '.join((str(x) for x in targets)), '', -1),)),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=_l('mCoin передачи'), callback_data="admctl_limit_kind_transfer", style="primary"),
                    InlineKeyboardButton(text=_l('mCoin выдача'), callback_data="admctl_limit_kind_issue", style="primary"),
                ],
                [
                    InlineKeyboardButton(text=_l('MP передачи'), callback_data="admctl_limit_kind_mp_transfer", style="primary"),
                    InlineKeyboardButton(text=_l('MP выдача'), callback_data="admctl_limit_kind_mp_issue", style="primary"),
                ],
                [
                    InlineKeyboardButton(text=_l('Оба mCoin'), callback_data="admctl_limit_kind_both", style="primary"),
                    InlineKeyboardButton(text=_l('Все операции'), callback_data="admctl_limit_kind_all", style="primary"),
                ],
                [InlineKeyboardButton(text=_l('← Назад'), callback_data="admctl_back", style="primary")],
            ])
        )
    elif data.startswith("admctl_limit_kind_"):
        kind = data[len("admctl_limit_kind_"):]
        session = admin_limit_sessions.get(owner_id)
        if not session or kind not in ("transfer", "issue", "mp_transfer", "mp_issue", "both", "all"):
            await callback.answer(_l('Сессия устарела.'), show_alert=True)
            return
        session["kind"] = kind
        await callback.message.edit_text(
            _lf('<b>Введите сумму лимита</b>\nТип: <code>{0}</code>\nПример: <code>10кк</code>. Для снятия лимита отправьте <code>0</code>.', (_fmt(html.escape(kind), '', -1),)),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_l('← Назад к выбору типа'), callback_data="admctl_limit_start", style="primary")],
            ])
        )
    elif data == "admctl_back":
        await callback.message.edit_text(_admin_control_text(owner_id), parse_mode=ParseMode.HTML, reply_markup=_admin_control_keyboard(owner_id))
    await callback.answer()


@dp.message(_inline_filter(lambda message: message.from_user and message.from_user.id in admin_limit_sessions and message.text))
@_localized
async def process_admin_limit_input(message: types.Message):
    owner_id = message.from_user.id
    if not is_owner(owner_id):
        admin_limit_sessions.pop(owner_id, None)
        return
    session = admin_limit_sessions.get(owner_id) or {}
    kind = session.get("kind")
    if not kind:
        return
    raw_amount = (message.text or "").strip().lower()
    if raw_amount in ("0", "off", "нет", "безлимит", "unlimited", "∞"):
        amount = 0
    else:
        amount = parse_amount(raw_amount)
        if amount is None or amount < 0:
            await message.reply(_l('<i>Неверная сумма. Отправьте число, например <code>10кк</code>, или <code>0</code>.</i>'), parse_mode=ParseMode.HTML)
            return
    changed = []
    for uid in session.get("targets", []):
        if set_admin_limit(uid, kind, amount, owner_id):
            changed.append(uid)
            _admin_log(
                message.from_user,
                "admin_limit",
                target_id=uid,
                details={"kind": kind, "value": "∞" if not amount else format_number(amount)},
            )
    admin_limit_sessions.pop(owner_id, None)
    if not changed:
        await message.reply(_l('<i>Ошибка базы данных!</i>'), parse_mode=ParseMode.HTML)
        return
    await message.reply(
        _lf('<i>✅ Лимит <b>{0}</b> для <code>{1}</code>: <b>{2}</b> в сутки.</i>', (_fmt(html.escape(kind), '', -1), _fmt(', '.join((str(x) for x in changed)), '', -1), _fmt(format_number(amount) if amount else _l('безлимит'), '', -1))),
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("adminlimit", "админлимит", "admin_limit"))
@_localized
async def cmd_admin_limit(message: types.Message):
    if not is_owner(message.from_user.id):
        await message.answer(_l('<i>Только owners могут назначать лимиты.</i>'), parse_mode=ParseMode.HTML)
        return
    args = (message.text or "").split()[1:]
    if len(args) < 2:
        await message.answer(
            _l('<i>Использование:\n<code>/adminlimit ID[,ID] transfer 10кк</code> — mCoin передача\n<code>/adminlimit ID[,ID] issue 10кк</code> — mCoin выдача\n<code>/adminlimit ID[,ID] mp_transfer 1000</code> — MP передача\n<code>/adminlimit ID[,ID] mp_issue 1000</code> — MP выдача\n<code>both</code> — оба mCoin, <code>all</code> — все четыре, 0 — безлимит.</i>'),
            parse_mode=ParseMode.HTML
        )
        return
    target_ids = []
    for raw_id in args[0].split(","):
        target_id = resolve_user_id_argument(raw_id)
        if target_id is None or target_id not in ADMINS or is_owner(target_id):
            await message.answer(_l('<i>Укажите ID обычных администраторов, не owners.</i>'), parse_mode=ParseMode.HTML)
            return
        target_ids.append(target_id)
    if len(args) == 2:
        kind, raw_amount = "both", args[1]
    else:
        kind, raw_amount = args[1].lower(), args[2]
    kind = {
        "передача": "transfer", "перевод": "transfer", "выдача": "issue", "add": "issue", "оба": "both",
        "mptransfer": "mp_transfer", "mp-передача": "mp_transfer", "mpвыдача": "mp_issue", "mpissue": "mp_issue",
        "mp-оба": "mp_both", "все": "all"
    }.get(kind, kind)
    if kind not in ("transfer", "issue", "both", "mp_transfer", "mp_issue", "mp_both", "all"):
        await message.answer(_l('<i>Тип: transfer, issue, both, mp_transfer, mp_issue, mp_both или all.</i>'), parse_mode=ParseMode.HTML)
        return
    if raw_amount.lower() in ("0", "off", "нет", "безлимит", "unlimited", "∞"):
        amount = 0
    else:
        amount = parse_amount(raw_amount)
        if amount is None or amount < 0:
            await message.answer(_l('<i>Неверная сумма лимита.</i>'), parse_mode=ParseMode.HTML)
            return
    changed = []
    for uid in target_ids:
        if set_admin_limit(uid, kind, amount, message.from_user.id):
            changed.append(uid)
            _admin_log(
                message.from_user,
                "admin_limit",
                target_id=uid,
                details={"kind": kind, "value": "∞" if not amount else format_number(amount)},
            )
    if not changed:
        await message.answer(_l('<i>Ошибка базы данных!</i>'), parse_mode=ParseMode.HTML)
        return
    title = {"transfer": _l('mCoin передачи'), "issue": _l('mCoin выдачи'), "both": _l('mCoin передачи и выдачи'), "mp_transfer": _l('MP передачи'), "mp_issue": _l('MP выдачи'), "mp_both": _l('MP передачи и выдачи'), "all": _l('все операции')}[kind]
    await message.answer(
        _lf('<i>✅ Для {0} администраторов (<code>{1}</code>) установлен лимит {2}: <b>{3}</b> в сутки.</i>', (_fmt(len(changed), '', -1), _fmt(', '.join((str(x) for x in changed)), '', -1), _fmt(title, '', -1), _fmt(format_number(amount) if amount else _l('безлимит'), '', -1))),
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("adminperm", "админправа", "adminrights"))
@_localized
async def cmd_admin_permission(message: types.Message):
    if not is_owner(message.from_user.id):
        await message.answer(_l('<i>Только owners могут изменять права администраторов.</i>'), parse_mode=ParseMode.HTML)
        return
    args = (message.text or "").split()[1:]
    if len(args) < 3:
        await message.answer(
            _l('<i>Использование: <code>/adminperm ID[,ID] право on/off</code>\nПрава: <code>ban</code>, <code>transfer</code>, <code>issue</code>, <code>set</code>, <code>mp_transfer</code>, <code>mp_issue</code>.</i>'),
            parse_mode=ParseMode.HTML
        )
        return
    target_ids = []
    for raw_id in args[0].split(","):
        target_id = resolve_user_id_argument(raw_id)
        if target_id is None or target_id not in ADMINS or is_owner(target_id):
            await message.answer(_l('<i>Укажите ID обычных администраторов, не owners.</i>'), parse_mode=ParseMode.HTML)
            return
        target_ids.append(target_id)
    permission = {"бан": "ban", "передачи": "transfer", "выдача": "issue", "добавление": "issue", "установка": "set", "мп_передачи": "mp_transfer", "mp-передачи": "mp_transfer", "mp_transfer": "mp_transfer", "мп_выдача": "mp_issue", "mp-выдача": "mp_issue", "mp_issue": "mp_issue"}.get(args[1].lower(), args[1].lower())
    if permission not in _ADMIN_PERMISSION_COLUMNS:
        await message.answer(_l('<i>Неизвестное право. Доступны: ban, transfer, issue, set, mp_transfer, mp_issue.</i>'), parse_mode=ParseMode.HTML)
        return
    if args[2].lower() not in ("on", "1", "да", "yes", "вкл", "разрешить", "off", "0", "нет", "no", "выкл", "запретить"):
        await message.answer(_l('<i>Укажите on или off.</i>'), parse_mode=ParseMode.HTML)
        return
    enabled = args[2].lower() in ("on", "1", "да", "yes", "вкл", "разрешить")
    changed = []
    for uid in target_ids:
        if set_admin_permission(uid, permission, enabled, message.from_user.id):
            changed.append(uid)
            _admin_log(
                message.from_user,
                "admin_permission",
                target_id=uid,
                details={"permission": permission, "enabled": enabled},
            )
    if not changed:
        await message.answer(_l('<i>Ошибка базы данных!</i>'), parse_mode=ParseMode.HTML)
        return
    await message.answer(
        _lf('<i>✅ Право <b>{0}</b> {1} для <code>{2}</code>.</i>', (_fmt(html.escape(permission), '', -1), _fmt(_l('разрешено') if enabled else _l('запрещено'), '', -1), _fmt(', '.join((str(x) for x in changed)), '', -1))),
        parse_mode=ParseMode.HTML
    )



@dp.message(Command("ban", "бан"))
@_localized
async def cmd_ban(message: types.Message):
    user_id = message.from_user.id
    if not admin_has_permission(user_id, "ban"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]

    target_user_id = None
    target_name = None
    reason = _l('Не указана')
    duration_str = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Пользователь')

        if len(args) == 0:
            await message.answer(_l('<i>Использование: /ban &lt;причина&gt; &lt;время&gt;\nПример: <code>/ban спам 1ч</code> или <code>/ban нг</code></i>'), parse_mode=ParseMode.HTML)
            return
        elif len(args) == 1:
            duration_str = args[0]
        else:
            duration_str = args[-1]
            reason = " ".join(args[:-1])
    else:
        if len(args) < 2:
            await message.answer(_l('<i>Использование: /ban &lt;username/id&gt; &lt;причина&gt; &lt;время&gt;\nПример: <code>/ban @username спам 1ч</code> или <code>/ban @username нг</code></i>'), parse_mode=ParseMode.HTML)
            return

        target_arg = args[0]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.answer(_lf('<i>Пользователь @{0} не найден в базе бота!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = f"ID:{target_user_id}"
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.answer(_lf('<i>Пользователь {0} не найден!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return

        if len(args) == 2:
            duration_str = args[1]
        else:
            duration_str = args[-1]
            reason = " ".join(args[1:-1])

    if target_user_id == user_id:
        await message.answer(_l('<i>Вы не можете забанить самого себя!</i>'), parse_mode=ParseMode.HTML)
        return

    if int(target_user_id) == UNRESTRICTED_OWNER_ID:
        await message.answer(_l('<i>Нельзя забанить администратора!</i>'), parse_mode=ParseMode.HTML)
        return

    if target_user_id in ADMINS and int(user_id) != UNRESTRICTED_OWNER_ID:
        await message.answer(_l('<i>Нельзя забанить администратора!</i>'), parse_mode=ParseMode.HTML)
        return

    delta, is_permanent = parse_ban_duration(duration_str)

    if not is_permanent:
        if delta is None:
            await message.answer(_l('<i>Неверный формат времени! Пример: <code>5мин</code>, <code>1ч</code>, <code>24ч</code>, <code>7д</code>, <code>нг</code></i>'), parse_mode=ParseMode.HTML)
            return
        if delta < timedelta(minutes=5):
            await message.answer(_l('<i>Минимальный бан — 5 минут!</i>'), parse_mode=ParseMode.HTML)
            return
        until_dt = datetime.now() + delta
        until_text = until_dt.strftime("%d/%m/%Y")
    else:
        until_dt = None
        until_text = _l('навсегда')

    if ban_user(target_user_id, reason, until_dt, is_permanent):
        _admin_log(
            message.from_user,
            "ban",
            target_id=target_user_id,
            target_name=target_name,
            details={"reason": reason, "until": until_text},
        )
        admin_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ'))
        admin_link = f'<a href="tg://user?id={user_id}">{admin_name}</a>'
        target_link = f'<a href="tg://user?id={target_user_id}">{html.escape(get_user_display_name(target_user_id, target_name))}</a>'

        if is_permanent:
            await message.answer(
                _lf('<i>{0}, пользователь {1} успешно забанен навсегда по причине: {2}</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1), _fmt(reason, '', -1))),
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer(
                _lf('<i>{0}, пользователь {1} успешно забанен до {2} по причине: {3}</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1), _fmt(until_text, '', -1), _fmt(reason, '', -1))),
                parse_mode=ParseMode.HTML
            )
    else:
        await message.answer(_l('<i>Ошибка при блокировке пользователя!</i>'), parse_mode=ParseMode.HTML)


@dp.message(Command("unban", "разбан"))
@_localized
async def cmd_unban(message: types.Message):
    user_id = message.from_user.id
    if not admin_has_permission(user_id, "ban"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]
    target_user_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Пользователь')
    elif args:
        target_arg = args[0]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.answer(_lf('<i>Пользователь @{0} не найден!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = f"ID:{target_user_id}"
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.answer(_lf('<i>Пользователь {0} не найден!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        await message.answer(_l('<i>Использование: /unban <username/id> или в ответ на сообщение</i>'), parse_mode=ParseMode.HTML)
        return

    if unban_user(target_user_id):
        _admin_log(
            message.from_user,
            "unban",
            target_id=target_user_id,
            target_name=target_name,
        )
        admin_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ'))
        admin_link = f'<a href="tg://user?id={user_id}">{admin_name}</a>'
        target_link = f'<a href="tg://user?id={target_user_id}">{html.escape(get_user_display_name(target_user_id, target_name))}</a>'
        await message.answer(
            _lf('<i>{0}, пользователь {1} успешно разбанен.</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1))),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(_l('<i>Ошибка при разбане пользователя!</i>'), parse_mode=ParseMode.HTML)



@dp.message(Command("tban"))
@_localized
async def cmd_tban(message: types.Message):
    user_id = message.from_user.id
    if not admin_has_permission(user_id, "ban"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]
    target_user_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Пользователь')
    elif args:
        target_arg = args[0]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.answer(_lf('<i>Пользователь @{0} не найден в базе бота!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = get_user_display_name(target_user_id)
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.answer(_lf('<i>Пользователь {0} не найден!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        target_user_id = user_id
        target_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Администратор')

    if not ban_user_top(target_user_id):
        await message.answer(_l('<i>Ошибка при блокировке пользователя!</i>'), parse_mode=ParseMode.HTML)
        return
    _admin_log(
        message.from_user,
        "top_ban",
        target_id=target_user_id,
        target_name=target_name,
    )
    admin_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ'))
    admin_link = f'<a href="tg://user?id={user_id}">{admin_name}</a>'
    target_link = f'<a href="tg://user?id={target_user_id}">{html.escape(get_user_display_name(target_user_id, target_name))}</a>'

    await message.answer(
        _lf('<i>{0}, пользователь {1} успешно заблокирован в топе! 🚫</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1))),
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("untban", "untopban"))
@_localized
async def cmd_untban(message: types.Message):
    user_id = message.from_user.id
    if not admin_has_permission(user_id, "ban"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]
    target_user_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Пользователь')
    elif args:
        target_arg = args[0]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.answer(_lf('<i>Пользователь @{0} не найден!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = get_user_display_name(target_user_id)
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.answer(_lf('<i>Пользователь {0} не найден!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        target_user_id = user_id
        target_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Администратор')

    if not unban_user_top(target_user_id):
        await message.answer(_l('<i>Ошибка при разбане пользователя!</i>'), parse_mode=ParseMode.HTML)
        return
    _admin_log(
        message.from_user,
        "top_unban",
        target_id=target_user_id,
        target_name=target_name,
    )
    admin_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ'))
    admin_link = f'<a href="tg://user?id={user_id}">{admin_name}</a>'
    target_link = f'<a href="tg://user?id={target_user_id}">{html.escape(get_user_display_name(target_user_id, target_name))}</a>'

    await message.answer(
        _lf('<i>{0}, пользователь {1} успешно разблокирован в топе! ✅</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1))),
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("trban"))
@_localized
async def cmd_trban(message: types.Message):
    user_id = message.from_user.id
    if not admin_has_permission(user_id, "ban"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]
    target_user_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Пользователь')
    elif args:
        target_arg = args[0]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.answer(_lf('<i>Пользователь @{0} не найден в базе бота!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = get_user_display_name(target_user_id)
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.answer(_lf('<i>Пользователь {0} не найден!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        target_user_id = user_id
        target_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Администратор')

    if not ban_user_transfers(target_user_id):
        await message.answer(_l('<i>Ошибка при блокировке пользователя!</i>'), parse_mode=ParseMode.HTML)
        return
    _admin_log(
        message.from_user,
        "transfer_ban",
        target_id=target_user_id,
        target_name=target_name,
    )
    admin_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ'))
    admin_link = f'<a href="tg://user?id={user_id}">{admin_name}</a>'
    target_link = f'<a href="tg://user?id={target_user_id}">{html.escape(get_user_display_name(target_user_id, target_name))}</a>'

    await message.answer(
        _lf('<i>{0}, пользователю {1} успешно заблокированы переводы! 🚫</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1))),
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("untrban"))
@_localized
async def cmd_untrban(message: types.Message):
    user_id = message.from_user.id
    if not admin_has_permission(user_id, "ban"):
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]
    target_user_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Пользователь')
    elif args:
        target_arg = args[0]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.answer(_lf('<i>Пользователь @{0} не найден!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = get_user_display_name(target_user_id)
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.answer(_lf('<i>Пользователь {0} не найден!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        target_user_id = user_id
        target_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Администратор')

    if not unban_user_transfers(target_user_id):
        await message.answer(_l('<i>Ошибка при разбане пользователя!</i>'), parse_mode=ParseMode.HTML)
        return
    _admin_log(
        message.from_user,
        "transfer_unban",
        target_id=target_user_id,
        target_name=target_name,
    )
    admin_name = html.escape(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Админ'))
    admin_link = f'<a href="tg://user?id={user_id}">{admin_name}</a>'
    target_link = f'<a href="tg://user?id={target_user_id}">{html.escape(get_user_display_name(target_user_id, target_name))}</a>'

    await message.answer(
        _lf('<i>{0}, пользователю {1} успешно разблокированы переводы! ✅</i>', (_fmt(admin_link, '', -1), _fmt(target_link, '', -1))),
        parse_mode=ParseMode.HTML
    )



@dp.message(Command("get", "гет"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower().split()[0] in ["гет", "get", "/get", "/гет"]))
@_localized
async def cmd_get(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    text = (message.text or "").strip()
    parts = text.split()

    target_user_id = None
    target_user_name = None
    target_username = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_user_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Игрок')
        target_username = target_user.username
    elif len(parts) > 1:
        arg = parts[1]
        if arg.startswith("@"):
            uname = arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.reply(_lf('<i>Пользователь @{0} не найден в базе бота!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_username = uname
            target_user_name = f"@{uname}"
        elif arg.isdigit():
            target_user_id = int(arg)
            target_user_name = get_user_display_name(target_user_id)
            target_username = target_user_name.lstrip("@") if target_user_name.startswith("@") else None
        else:
            found = get_user_by_username(arg)
            if found:
                target_user_id = found["user_id"]
                target_username = arg
                target_user_name = f"@{arg}"
            else:
                await message.reply(_lf('<i>Пользователь {0} не найден в базе бота!</i>', (_fmt(arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        target_user_id = user_id
        target_user_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок')
        target_username = message.from_user.username

    u_data = get_user(target_user_id)
    balance = u_data.get("balance", 0)
    reg_date = u_data.get("registered_at")
    if not reg_date:
        try:
            cursor.execute('SELECT created_at FROM games_history WHERE user_id = ? ORDER BY id ASC LIMIT 1', (target_user_id,))
            first_game = cursor.fetchone()
            if first_game and first_game[0]:
                reg_date = first_game[0]
            else:
                reg_date = _l('Неизвестно')
        except Exception:
            reg_date = _l('Неизвестно')

    ban_info = check_user_ban(target_user_id)
    if ban_info:
        ban_status = _lf('🚫 <b>Заблокирован</b>\n<blockquote>Причина: {0}\nСрок: {1}</blockquote>', (_fmt(ban_info['reason'], '', -1), _fmt(_l('Навсегда') if ban_info.get('is_perm') else ban_info['until_str'], '', -1)))
    else:
        ban_status = _l('✅ <b>Активен (не заблокирован)</b>')

    top_ban_status = _l('🚫 <b>Заблокирован в топе</b>') if is_top_banned(target_user_id) else _l('✅ <b>В топе доступен</b>')
    tr_ban_status = _l('🚫 <b>Переводы заблокированы</b>') if is_transfer_banned(target_user_id) else _l('✅ <b>Переводы доступны</b>')

    last_game = get_last_game(target_user_id)
    game_names = {
        "mines": ("💣", _l('Мины')),
        "tower": ("🛕", _l('Башня')),
        "qwak": ("🐸", _l('Квак')),
        "diamonds": ("💠", _l('Алмазы')),
        "crash": ("🚀", _l('Краш')),
        "slots": ("🎰", _l('Слоты')),
        "bowling": ("🎳", _l('Боулинг')),
        "dice": ("🎲", _l('Кубик')),
        "coin": ("🪙", _l('Монетка')),
        "chest": ("🧰", _l('Сундук')),
        "fishing": ("🎣", _l('Рыбалка')),
        "scratch": ("🎫", _l('Скретч')),
        "roulette": ("🎱", _l('Рулетка')),
        "darts": ("🎯", _l('Дартс')),
        "basketball": ("🏀", _l('Баскетбол')),
        "football": ("⚽", _l('Футбол')),
        "twentyone": ("🃏", _l('21 (Очко)'))
    }
    if last_game:
        gicon, gname = game_names.get(last_game["game_type"], ("🎮", last_game["game_type"]))
        if last_game["result"] == "win":
            res_str = _lf('✅ Выигрыш (<b>+{0} m¢</b>)', (_fmt(format_number(last_game['win_amount']), '', -1),))
        elif last_game["result"] == "draw":
            res_str = _lf('🤝 Ничья (<b>{0} m¢</b>)', (_fmt(format_number(last_game['win_amount']), '', -1),))
        elif last_game["result"] == "expired":
            res_str = _l('💾 Отменена (таймаут)')
        else:
            res_str = _l('❌ Проигрыш')
        last_game_str = (
            _lf('{0} <b>{1}</b> | <i>{2}</i>\n<blockquote>Ставка: <b>{3} m¢</b>\nРезультат: {4}</blockquote>', (_fmt(gicon, '', -1), _fmt(gname, '', -1), _fmt(last_game['created_at'], '', -1), _fmt(format_number(last_game['bet']), '', -1), _fmt(res_str, '', -1)))
        )
    else:
        last_game_str = _l('<blockquote><i>Нет сыгранных игр</i></blockquote>')

    clean_target_name = html.escape(get_user_display_name(target_user_id, target_user_name))
    if target_username:
        clean_target_uname = html.escape(str(target_username))
        user_mention = f'<a href="tg://user?id={target_user_id}">{clean_target_name}</a> (@{clean_target_uname})'
    else:
        user_mention = f'<a href="tg://user?id={target_user_id}">{clean_target_name}</a>'

    mp_balance = u_data.get("mp_balance", 0) or 0
    mp_limit = get_user_mp_limit(u_data, target_user_id)
    mp_limit_str = "∞" if mp_limit is None else format_number(mp_limit)

    max_bal = u_data.get("max_balance") if u_data.get("max_balance") is not None else balance
    games_count = u_data.get("games", 0) or 0
    lost_amount = u_data.get("lost", 0) or 0

    info_text = (
        _lf('<tg-emoji emoji-id="5465665476971471368">👤</tg-emoji> <b>Информация о пользователе:</b>\n<blockquote>Игрок: {0}\nID: <code>{1}</code></blockquote>\n<code>·····················</code>\n<tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> <b>Баланс:</b> <b>{2} m¢</b>\n💎 <b>MP Баланс:</b> <b>{3} MP</b> (Лимит: {4}/д.)\n📅 <b>Регистрация:</b> <i>{5}</i>\n👑 <b>Рекорды:</b>\n<blockquote>• Макс. баланс: <b>{6} m¢</b>\n• Сыграно игр: <b>{7}</b>\n• Проиграно: <b>{8} m¢</b></blockquote>\n🛡 <b>Статус бана:</b> {9}\n🏆 <b>Статус топа:</b> {10}\n💳 <b>Статус переводов:</b> {11}\n<code>·····················</code>\n🕹 <b>Последняя игра:</b>\n{12}', (_fmt(user_mention, '', -1), _fmt(target_user_id, '', -1), _fmt(format_number(balance), '', -1), _fmt(format_number(mp_balance), '', -1), _fmt(mp_limit_str, '', -1), _fmt(reg_date, '', -1), _fmt(format_number(max_bal), '', -1), _fmt(format_number(games_count), '', -1), _fmt(format_number(lost_amount), '', -1), _fmt(ban_status, '', -1), _fmt(top_ban_status, '', -1), _fmt(tr_ban_status, '', -1), _fmt(last_game_str, '', -1)))
    )

    get_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('🗑 Сбросить рекорды'),
                    callback_data=f"adm_reset_rec_{target_user_id}"
                ),
                InlineKeyboardButton(
                    text=_l('📜 История переводов'),
                    callback_data=f"thist_{target_user_id}_1"
                )
            ]
        ]
    )

    await message.reply(info_text, reply_markup=get_keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("adm_reset_rec_")))
@_localized
async def process_adm_reset_rec(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer(_l('У вас нет прав администратора!'), show_alert=True)
        return

    try:
        target_user_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer(_l('Ошибка пользователя!'), show_alert=True)
        return

    u_data = get_user(target_user_id)
    cur_bal = u_data.get("balance", 0)
    if not update_user(target_user_id, max_balance=cur_bal, games=0, lost=0):
        await callback.answer(_l('Ошибка базы данных!'), show_alert=True)
        return
    _admin_log(
        callback.from_user,
        "reset_record",
        target_id=target_user_id,
        details={"field": "all"},
    )
    await callback.answer(_l('✅ Рекорды пользователя успешно сброшены!'), show_alert=True)
    target_name = get_user_display_name(target_user_id)
    try:
        await callback.message.reply(
            _lf('<i>✅ Рекорды пользователя <b>{0}</b> (<code>{1}</code>) сброшены!\n• Макс. баланс: {2} m¢\n• Сыграно игр: 0\n• Проиграно: 0 m¢</i>', (_fmt(html.escape(get_user_display_name(target_user_id, target_name)), '', -1), _fmt(target_user_id, '', -1), _fmt(format_number(cur_bal), '', -1))),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass



@_localized
def build_thistory_message(target_user_id, target_name, page=1):
    total_count = get_user_transfers_count(target_user_id)
    per_page = 5
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    offset = (page - 1) * per_page
    rows = get_user_transfers(target_user_id, limit=per_page, offset=offset)

    clean_target_name = html.escape(get_user_display_name(target_user_id, target_name))
    target_link = f'<a href="tg://user?id={target_user_id}">{clean_target_name}</a>'
    text = (
        _lf('💳 <b>История переводов:</b> {0} (<code>{1}</code>)\n<code>·····················</code>\n', (_fmt(target_link, '', -1), _fmt(target_user_id, '', -1)))
    )

    if not rows:
        text += _l('<i>Переводов не найдено.</i>\n')
    else:
        for idx, (tid, sender_id, receiver_id, amount, commission, dt_str) in enumerate(rows):
            if sender_id == target_user_id:
                other_name = html.escape(get_user_display_name(receiver_id))
                other_link = f'<a href="tg://user?id={receiver_id}">{other_name}</a>'
                text += (
                    _lf('📤 <b>Перевод игроку:</b> {0}\n<blockquote>💰 Сумма: <b>{1} m¢</b> (ком.: {2} m¢)\n📅 Дата: <i>{3}</i></blockquote>\n', (_fmt(other_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(format_number(commission), '', -1), _fmt(dt_str, '', -1)))
                )
            else:
                other_name = html.escape(get_user_display_name(sender_id))
                other_link = f'<a href="tg://user?id={sender_id}">{other_name}</a>'
                text += (
                    _lf('📥 <b>Получено от:</b> {0}\n<blockquote>💰 Сумма: <b>{1} m¢</b>\n📅 Дата: <i>{2}</i></blockquote>\n', (_fmt(other_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(dt_str, '', -1)))
                )
            if idx < len(rows) - 1:
                text += '<code>·····················</code>\n'

        text += _lf('\n↗️ <i>Страница {0}/{1} (Всего: {2})</i>', (_fmt(page, '', -1), _fmt(total_pages, '', -1), _fmt(total_count, '', -1)))

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"thist_{target_user_id}_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"thist_{target_user_id}_{page + 1}"))

    keyboard_rows = []
    if nav_buttons:
        keyboard_rows.append(nav_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows) if keyboard_rows else None
    return text, keyboard


@dp.message(Command("thistory", "th", "история_переводов"))
@_localized
async def cmd_thistory(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.answer(_l('<i>У вас нет прав для этой команды!</i>'), parse_mode=ParseMode.HTML)
        return

    args = message.text.split()[1:]
    target_user_id = None
    target_name = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = get_user_display_name(target_user.id, target_user.first_name) or _l('Пользователь')
    elif args:
        target_arg = args[0]
        if target_arg.startswith("@"):
            uname = target_arg.lstrip("@")
            found = get_user_by_username(uname)
            if not found:
                await message.answer(_lf('<i>Пользователь @{0} не найден в базе бота!</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            target_user_id = found["user_id"]
            target_name = f"@{uname}"
        elif target_arg.isdigit():
            target_user_id = int(target_arg)
            target_name = get_user_display_name(target_user_id)
        else:
            found = get_user_by_username(target_arg)
            if found:
                target_user_id = found["user_id"]
                target_name = f"@{target_arg}"
            else:
                await message.answer(_lf('<i>Пользователь {0} не найден!</i>', (_fmt(target_arg, '', -1),)), parse_mode=ParseMode.HTML)
                return
    else:
        target_user_id = user_id
        target_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Администратор')

    text, keyboard = build_thistory_message(target_user_id, target_name, page=1)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("thist_")))
@_localized
async def process_thistory_page(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer(_l('У вас нет прав администратора!'), show_alert=True)
        return

    await callback.answer()
    parts = callback.data.split("_")
    try:
        target_user_id = int(parts[1])
        page = int(parts[2])
    except Exception:
        return

    target_name = get_user_display_name(target_user_id)
    text, keyboard = build_thistory_message(target_user_id, target_name, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass



@_localized
def get_day_declension(days: int) -> str:
    if 11 <= days % 100 <= 19:
        return _l('дней')
    last_digit = days % 10
    if last_digit == 1:
        return _l('день')
    elif 2 <= last_digit <= 4:
        return _l('дня')
    else:
        return _l('дней')


@_localized
def build_deposit_main_menu(user_id, user_name):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    text = (
        _lf('{0}\n<tg-emoji emoji-id="5264895611517300926">🏦</tg-emoji><b>ДЕПОЗИТ БАНК</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5390875094027344872">💲</tg-emoji> <b>Временные депозиты:</b>\n<blockquote>├ 1 день — 0,4%\n├ 3 дня — 1,5% (0,5%/день)\n├ 7 дней — 4% (0,57%/день)\n├ 15 дней — 10% (0,66%/день)\n├ 30 дней — 25% (0,83%/день) <tg-emoji emoji-id="5420315771991497307">🔥</tg-emoji>\n└ 60 дней — 65% (1,08%/день) <tg-emoji emoji-id="5274225173837394638">👑</tg-emoji> </blockquote>\n<b> <tg-emoji emoji-id="5296355151743838259">🪙</tg-emoji> Накопительный счет</b>\n<blockquote>└ 0.2%/день, вывод в любой момент</blockquote>\n<code>·····················</code>\nКуда хочешь <b>вложиться? 👇</b>', (_fmt(user_link, '', -1),))
    )

    keyboard_rows = [
        [
            InlineKeyboardButton(
                text=_l('Временные депозиты'),
                callback_data="dep_time",
                style="primary",
                icon_custom_emoji_id="5390875094027344872"
            ),
            InlineKeyboardButton(
                text=_l('Накопительный счет'),
                callback_data="dep_savings",
                style="success",
                icon_custom_emoji_id="5296355151743838259"
            )
        ]
    ]

    total_deps = get_user_time_deposits_history_count(user_id)
    if total_deps > 0:
        keyboard_rows.append([
            InlineKeyboardButton(
                text=_l('Мои депозиты'),
                callback_data="dep_my",
                style="primary"
            )
        ])

    return text, InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


@dp.message(Command("deposit", "депозит", "банк", "депозиты"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower() in ["депозит", "депозиты", "деп", "банк", "/deposit", "/депозит", "/банк"]))
@_localized
async def cmd_deposit(message: types.Message):
    user_id = message.from_user.id
    user_name = get_user_display_name(message.from_user.id, message.from_user.first_name)
    text, keyboard = build_deposit_main_menu(user_id, user_name)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "dep_main"))
@_localized
async def process_dep_main(callback: types.CallbackQuery):
    await callback.answer()
    text, keyboard = build_deposit_main_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@_localized
def build_time_deposits_menu(user_id, user_name):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    text = (
        _lf('{0}\n<tg-emoji emoji-id="5390875094027344872">💲</tg-emoji> <b>ВРЕМЕННЫЕ ДЕПОЗИТЫ</b>\n<code>·····················</code>\n<blockquote>ℹ️ Здесь вы можете вложить свои mCoin под проценты на фиксированный срок. При досрочном снятии возвращается только сумма без процентов.</blockquote>\nВыбери <b>срок депозита 👇</b>', (_fmt(user_link, '', -1),))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('1д.'), callback_data="dep_term_1_0", style="primary"),
                InlineKeyboardButton(text=_l('3д.'), callback_data="dep_term_3_0", style="primary"),
                InlineKeyboardButton(text=_l('7д.'), callback_data="dep_term_7_0", style="primary")
            ],
            [
                InlineKeyboardButton(text=_l('15д.'), callback_data="dep_term_15_0", style="primary"),
                InlineKeyboardButton(text=_l('30д.'), callback_data="dep_term_30_0", style="primary"),
                InlineKeyboardButton(text=_l('60д.'), callback_data="dep_term_60_0", style="primary")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="dep_main", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    return text, keyboard


@dp.callback_query(_inline_filter(lambda c: c.data == "dep_time"))
@_localized
async def process_dep_time(callback: types.CallbackQuery):
    await callback.answer()
    text, keyboard = build_time_deposits_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@_localized
def build_deposit_term_input_menu(user_id, user_name, days: int, is_locked: int = 0):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'
    user_data = get_user(user_id)
    balance = user_data.get("balance", 0)

    decl = get_day_declension(days).upper()
    text = (
        _lf('{0}\n<tg-emoji emoji-id="5264895611517300926">🏦</tg-emoji><b>ДЕПОЗИТ НА {1} {2}</b>\n<code>·····················</code>\n<blockquote>ℹ️ Чтобы внести другое количество mCoin, ответьте на это сообщение, указав нужное число.</blockquote>\n<blockquote> <tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> Лимит банка: 100kk mCoin.</blockquote>\n<tg-emoji emoji-id="5465347885614788367">💴</tg-emoji> Сколько <b>хочешь внести?</b>', (_fmt(user_link, '', -1), _fmt(days, '', -1), _fmt(decl, '', -1)))
    )

    b10 = max(1, int(balance * 0.10)) if balance > 0 else 0
    b25 = max(1, int(balance * 0.25)) if balance > 0 else 0
    b50 = max(1, int(balance * 0.50)) if balance > 0 else 0

    lock_icon = "✅" if is_locked else "❌"
    next_lock = 0 if is_locked else 1

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_lf('Все • {0} m¢', (_fmt(format_number(balance), '', -1),)), callback_data=f"dep_make_{days}_{is_locked}_all")
            ],
            [
                InlineKeyboardButton(text=f"{format_number(b10)} m¢", callback_data=f"dep_make_{days}_{is_locked}_10"),
                InlineKeyboardButton(text=f"{format_number(b25)} m¢", callback_data=f"dep_make_{days}_{is_locked}_25"),
                InlineKeyboardButton(text=f"{format_number(b50)} m¢", callback_data=f"dep_make_{days}_{is_locked}_50")
            ],
            [
                InlineKeyboardButton(text=_lf('Заблокировать снятие {0}', (_fmt(lock_icon, '', -1),)), callback_data=f"dep_term_{days}_{next_lock}")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="dep_time", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    return text, keyboard


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("dep_term_")))
@_localized
async def process_dep_term(callback: types.CallbackQuery):
    await callback.answer()
    parts = callback.data.split("_")
    days = int(parts[2])
    is_locked = int(parts[3]) if len(parts) > 3 else 0
    text, keyboard = build_deposit_term_input_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), days, is_locked)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("dep_make_")))
@_localized
async def process_dep_make(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    days = int(parts[2])
    is_locked = int(parts[3])
    pct_mode = parts[4]

    user_id = callback.from_user.id
    user_data = get_user(user_id)
    balance = user_data.get("balance", 0)

    if pct_mode == "all":
        amount = balance
    elif pct_mode == "10":
        amount = max(1, int(balance * 0.10))
    elif pct_mode == "25":
        amount = max(1, int(balance * 0.25))
    elif pct_mode == "50":
        amount = max(1, int(balance * 0.50))
    else:
        try:
            amount = int(pct_mode)
        except Exception:
            amount = balance

    if amount <= 0:
        await callback.answer(_l('У вас нет средств для внесения депозита!'), show_alert=True)
        return

    ok, res = create_time_deposit(user_id, amount, days, is_locked)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    await callback.answer(_l('Депозит успешно открыт!'))
    clean_name = html.escape(str(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    end_str = res["end_at"]
    rate_str = str(res["percent"]).replace(".", ",")
    text = (
        _lf('{0}\n<tg-emoji emoji-id="5264895611517300926">🏦</tg-emoji><b>ДЕПОЗИТ ПРИНЯТ</b>\n<code>·····················</code>\n💰 Сумма: <b>{1} m¢</b>\n🔘 Процент: <b>{2}% • {3} m¢</b>\n<code>············</code>\n⏳ До: <b>{4} ({5}д.)</b>', (_fmt(user_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(rate_str, '', -1), _fmt(format_number(res['profit']), '', -1), _fmt(end_str, '', -1), _fmt(days, '', -1)))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('Положить ещё'), callback_data="dep_main", style="primary")
            ]
        ]
    )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@_localized
def build_my_deposits_menu(user_id, user_name):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    active_deps = get_active_time_deposits(user_id)
    total_earned = get_user_earned_deposits_total(user_id)
    notif_enabled = get_bank_settings(user_id)["notifications_enabled"]

    active_count = len(active_deps)

    text = (
        _lf('{0}\n🏦 <b>МОИ ДЕПОЗИТЫ • {1}</b>\n<code>·····················</code>\n❇️ <b>Активные:</b>\n', (_fmt(user_link, '', -1), _fmt(active_count, '', -1)))
    )

    if active_deps:
        for idx, dep in enumerate(active_deps[:3]):
            dep_id, amount, days, percent, profit, is_locked, c_at, end_at, c_dt, e_dt = dep
            p_str = str(percent).replace(".", ",")
            lock_badge = " 🔒" if is_locked else ""
            text += _lf('До {0} • {1} m¢ ({2}%){3}\n', (_fmt(end_at, '', -1), _fmt(format_number(amount), '', -1), _fmt(p_str, '', -1), _fmt(lock_badge, '', -1)))
        if len(active_deps) > 3:
            text += _lf('<i>...и ещё {0} активных вкладов</i>\n', (_fmt(len(active_deps) - 3, '', -1),))
    else:
        text += _l('<i>Нет активных депозитов</i>\n')

    text += (
        _lf('\n<code>············</code>\n<blockquote>💰 Заработано: <b>{0} m¢</b></blockquote>', (_fmt(format_number(total_earned), '', -1),))
    )

    notif_icon = "✅" if notif_enabled else "❌"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('❇️ Все активные депозиты'), callback_data="dep_active_all_1", style="success")
            ],
            [
                InlineKeyboardButton(text=_l('Снять ⤵️'), callback_data="dep_withdraw_menu_1", style="primary"),
                InlineKeyboardButton(text=_l('История 🕐'), callback_data="dep_history_1", style="primary")
            ],
            [
                InlineKeyboardButton(text=_lf('Уведомления от банка {0}', (_fmt(notif_icon, '', -1),)), callback_data="dep_notif_toggle")
            ],
            [
                InlineKeyboardButton(text=_l('Положить ещё'), callback_data="dep_main", style="primary")
            ]
        ]
    )
    return text, keyboard


@dp.callback_query(_inline_filter(lambda c: c.data == "dep_my"))
@_localized
async def process_dep_my(callback: types.CallbackQuery):
    await callback.answer()
    text, keyboard = build_my_deposits_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "dep_notif_toggle"))
@_localized
async def process_dep_notif_toggle(callback: types.CallbackQuery):
    toggle_bank_notifications(callback.from_user.id)
    await callback.answer(_l('Настройки уведомлений обновлены!'))
    text, keyboard = build_my_deposits_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass


@_localized
def build_active_deposits_menu(user_id, user_name, page=1):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    active_deps = get_active_time_deposits(user_id)
    total_count = len(active_deps)
    per_page = 5
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    start_idx = (page - 1) * per_page
    page_items = active_deps[start_idx:start_idx + per_page]

    text = (
        _lf('{0}\n❇️ <b>АКТИВНЫЕ ДЕПОЗИТЫ</b>\n<code>·····················</code>\n', (_fmt(user_link, '', -1),))
    )

    if not page_items:
        text += _l('<i>Нет активных депозитов.</i>\n')
    else:
        for dep in page_items:
            dep_id, amount, days, percent, profit, is_locked, c_at, end_at, c_dt, e_dt = dep
            p_str = str(percent).replace(".", ",")
            lock_badge = " 🔒" if is_locked else ""
            text += _lf('До {0} • <b>{1} m¢</b> ({2}%){3}\n', (_fmt(end_at, '', -1), _fmt(format_number(amount), '', -1), _fmt(p_str, '', -1), _fmt(lock_badge, '', -1)))

    text += (
        _lf('<code>············</code>\n↗️ страница {0}/{1}', (_fmt(page, '', -1), _fmt(total_pages, '', -1)))
    )

    keyboard_rows = []
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"dep_active_all_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"dep_active_all_{page + 1}"))
    if nav_buttons:
        keyboard_rows.append(nav_buttons)

    keyboard_rows.append([
        InlineKeyboardButton(text=_l('Снять ⤵️'), callback_data="dep_withdraw_menu_1", style="primary"),
        InlineKeyboardButton(text=_l('История 🕐'), callback_data="dep_history_1", style="primary")
    ])
    keyboard_rows.append([
        InlineKeyboardButton(text=_l('Положить ещё'), callback_data="dep_main", style="primary"),
        InlineKeyboardButton(text=_l('Назад'), callback_data="dep_my", icon_custom_emoji_id="5255703720078879038")
    ])

    return text, InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("dep_active_all_")))
@_localized
async def process_dep_active_all(callback: types.CallbackQuery):
    await callback.answer()
    try:
        page = int(callback.data.split("_")[-1])
    except Exception:
        page = 1
    text, keyboard = build_active_deposits_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), page=page)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@_localized
def build_withdraw_deposits_menu(user_id, user_name, page=1):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    active_deps = get_active_time_deposits(user_id)
    unlocked_deps = [d for d in active_deps if not d[5]]

    total_count = len(unlocked_deps)
    per_page = 4
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    start_idx = (page - 1) * per_page
    page_items = unlocked_deps[start_idx:start_idx + per_page]

    text = (
        _lf('{0}\n🏦 <b>СНЯТЬ ДЕПОЗИТ</b>\n<code>·····················</code>\n<blockquote>ℹ️ Депозит снимается автоматически при нажатии на кнопку. Процент, начисленный на депозит, теряется в полном объеме при его снятии.</blockquote>\n↘️ страница {1}/{2}', (_fmt(user_link, '', -1), _fmt(page, '', -1), _fmt(total_pages, '', -1)))
    )

    keyboard_rows = []
    if unlocked_deps:
        keyboard_rows.append([
            InlineKeyboardButton(text=_l('❇️ снять всё'), callback_data="dep_wd_all", style="danger")
        ])
        for dep in page_items:
            dep_id, amount, days, percent, profit, is_locked, c_at, end_at, c_dt, e_dt = dep
            keyboard_rows.append([
                InlineKeyboardButton(text=_lf('до {0} — {1}', (_fmt(end_at, '', -1), _fmt(format_number(amount), '', -1))), callback_data=f"dep_wd_one_{dep_id}")
            ])

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"dep_withdraw_menu_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"dep_withdraw_menu_{page + 1}"))
    if nav_buttons:
        keyboard_rows.append(nav_buttons)

    keyboard_rows.append([
        InlineKeyboardButton(text=_l('Назад'), callback_data="dep_my", icon_custom_emoji_id="5255703720078879038")
    ])

    return text, InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("dep_withdraw_menu_")))
@_localized
async def process_dep_withdraw_menu(callback: types.CallbackQuery):
    await callback.answer()
    try:
        page = int(callback.data.split("_")[-1])
    except Exception:
        page = 1
    text, keyboard = build_withdraw_deposits_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), page=page)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@dp.callback_query(_inline_filter(lambda c: c.data == "dep_wd_all"))
@_localized
async def process_dep_wd_all(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    ok, res = withdraw_all_time_deposits(user_id)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return
    await callback.answer(_lf('Снято {0} mCoin на баланс!', (_fmt(format_number(res), '', -1),)))
    text, keyboard = build_my_deposits_menu(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("dep_wd_one_")))
@_localized
async def process_dep_wd_one(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        dep_id = int(callback.data.split("_")[-1])
    except Exception:
        return
    ok, res = withdraw_time_deposit(dep_id, user_id)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return
    await callback.answer(_lf('Депозит на {0} mCoin возвращен на баланс!', (_fmt(format_number(res), '', -1),)))
    text, keyboard = build_withdraw_deposits_menu(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), page=1)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        pass


@_localized
def build_deposits_history_menu(user_id, user_name, page=1):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'

    total_count = get_user_time_deposits_history_count(user_id)
    per_page = 5
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    offset = (page - 1) * per_page
    rows = get_user_time_deposits_history(user_id, limit=per_page, offset=offset)

    text = (
        _lf('{0}\n🕐 <b>ИСТОРИЯ ДЕПОЗИТОВ</b>\n<code>·····················</code>\n', (_fmt(user_link, '', -1),))
    )

    status_names = {
        "active": _l('❇️ Активен'),
        "completed": _l('✅ Завершен'),
        "withdrawn": _l('⤵️ Снят досрочно')
    }

    if not rows:
        text += _l('<i>История депозитов пуста.</i>\n')
    else:
        for dep in rows:
            dep_id, amount, days, percent, profit, is_locked, status, c_at, end_at = dep
            st_text = status_names.get(status, status)
            p_str = str(percent).replace(".", ",")
            text += (
                _lf('🏦 <b>Депозит #{0}</b> ({1}д., {2}%)\n<blockquote>💰 Сумма: <b>{3} m¢</b> | Прибыль: <b>+{4} m¢</b>\n📅 Создан: <i>{5}</i> | До: <i>{6}</i>\nСтатус: {7}</blockquote>\n', (_fmt(dep_id, '', -1), _fmt(days, '', -1), _fmt(p_str, '', -1), _fmt(format_number(amount), '', -1), _fmt(format_number(profit), '', -1), _fmt(c_at, '', -1), _fmt(end_at, '', -1), _fmt(st_text, '', -1)))
            )

    text += (
        _lf('<code>············</code>\n↗️ страница {0}/{1}', (_fmt(page, '', -1), _fmt(total_pages, '', -1)))
    )

    keyboard_rows = []
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"dep_history_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"dep_history_{page + 1}"))
    if nav_buttons:
        keyboard_rows.append(nav_buttons)

    keyboard_rows.append([
        InlineKeyboardButton(text=_l('Назад'), callback_data="dep_my", icon_custom_emoji_id="5255703720078879038")
    ])

    return text, InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("dep_history_")))
@_localized
async def process_dep_history(callback: types.CallbackQuery):
    await callback.answer()
    try:
        page = int(callback.data.split("_")[-1])
    except Exception:
        page = 1
    text, keyboard = build_deposits_history_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), page=page)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)



@_localized
def build_savings_menu(user_id, user_name):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'
    sav = get_savings_account(user_id)
    sav_bal = sav.get("balance", 0)
    accum = int(sav.get("accumulated_interest", 0.0))

    text = (
        _lf('{0}\n💸 <b>НАКОПИТЕЛЬНЫЙ СЧЕТ</b>\n<code>·····················</code>\n<blockquote>ℹ️ Здесь вы можете хранить свои mCoin и получать ежедневные проценты. Проценты начисляются каждый час. Снятие доступно в любой момент без потери начисленных процентов.</blockquote>\n<blockquote> <tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>  Лимит банка: 100kk mCoin.</blockquote>\n💰 <b>На счету:</b> {1} m¢\n🔘 <b>Ставка:</b> 0.2% дневных\n💸 <b>Накоплено:</b> {2} m¢', (_fmt(user_link, '', -1), _fmt(format_number(sav_bal), '', -1), _fmt(format_number(accum), '', -1)))
    )

    action_buttons = [
        InlineKeyboardButton(text=_l('Пополнить'), callback_data="dep_sav_dep", style="success")
    ]
    if (sav_bal + accum) > 0:
        action_buttons.append(
            InlineKeyboardButton(text=_l('Снять 💰'), callback_data="dep_sav_wd", style="primary")
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            action_buttons,
            [
                InlineKeyboardButton(text=_l('История пополнений 🕐'), callback_data="dep_sav_hist_1", style="primary")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="dep_main", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    return text, keyboard


@dp.callback_query(_inline_filter(lambda c: c.data == "dep_savings"))
@_localized
async def process_dep_savings(callback: types.CallbackQuery):
    await callback.answer()
    text, keyboard = build_savings_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@_localized
def build_savings_deposit_input_menu(user_id, user_name):
    user_name = get_user_display_name(user_id, user_name)
    clean_name = html.escape(str(user_name or _l('Игрок')))
    user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'
    user_data = get_user(user_id)
    balance = user_data.get("balance", 0)

    text = (
        _lf('{0}\n💳 <b>ПОПОЛНИТЬ НАКОП. СЧЕТ</b>\n<code>·····················</code>\n💰 Доступно: <b>{1} m¢</b>\n<i>Напишите в ответ на это сообщение сумму, которую хотите положить на накопительный счет:</i>', (_fmt(user_link, '', -1), _fmt(format_number(balance), '', -1)))
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_l('Назад'), callback_data="dep_savings", icon_custom_emoji_id="5255703720078879038")]
        ]
    )
    return text, keyboard


@dp.callback_query(_inline_filter(lambda c: c.data == "dep_sav_dep"))
@_localized
async def process_dep_sav_dep(callback: types.CallbackQuery):
    await callback.answer()
    text, keyboard = build_savings_deposit_input_menu(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "dep_sav_wd"))
@_localized
async def process_dep_sav_wd(callback: types.CallbackQuery):
    await callback.answer()
    clean_name = html.escape(str(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок')))
    user_link = f'<a href="tg://user?id={callback.from_user.id}">{clean_name}</a>'
    sav = get_savings_account(callback.from_user.id)
    sav_bal = sav.get("balance", 0)
    accum = int(sav.get("accumulated_interest", 0.0))
    total_avail = sav_bal + accum
    text = (
        _lf('{0}\n💸 <b>СНЯТЬ С НАКОП. СЧЕТА</b>\n<code>·····················</code>\n💰 Доступно к снятию: <b>{1} m¢</b>\n<i>Напишите в ответ на это сообщение сумму для снятия:</i>', (_fmt(user_link, '', -1), _fmt(format_number(total_avail), '', -1)))
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_l('Назад'), callback_data="dep_savings", icon_custom_emoji_id="5255703720078879038")]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("dep_sav_hist_")))
@_localized
async def process_dep_sav_hist(callback: types.CallbackQuery):
    await callback.answer()
    page = 1
    try:
        page = int(callback.data.replace("dep_sav_hist_", ""))
    except Exception:
        page = 1
    uid = callback.from_user.id
    history = get_savings_history(uid, limit=5, offset=(page-1)*5)
    total_cnt = get_savings_history_count(uid)
    total_pages = max(1, math.ceil(total_cnt / 5))
    clean_name = html.escape(str(get_user_display_name(callback.from_user.id, callback.from_user.first_name) or _l('Игрок')))
    user_link = f'<a href="tg://user?id={uid}">{clean_name}</a>'

    text = _lf('{0}\n📜 <b>История накопительного счета</b>\n<code>·····················</code>\n', (_fmt(user_link, '', -1),))
    if not history:
        text += _l('<i>История операций пуста</i>')
    else:
        for op_type, amount, dt in history:
            op_name = _l('Пополнение') if op_type == "deposit" else _l('Снятие')
            text += f'├ {op_name}: <b>{format_number(amount)} m¢</b> ({dt})\n'

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"dep_sav_hist_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop_p2p"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"dep_sav_hist_{page+1}"))

    kb = InlineKeyboardMarkup(
        inline_keyboard=[nav, [InlineKeyboardButton(text=_l('Назад'), callback_data="dep_savings", icon_custom_emoji_id="5255703720078879038")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)



def _reply_callback_data(reply):
    markup = getattr(reply, "reply_markup", None)
    rows = getattr(markup, "inline_keyboard", None)
    if not isinstance(rows, (list, tuple)):
        return ()
    return tuple(button.callback_data for row in rows for button in row if isinstance(getattr(button, "callback_data", None), str))


def _bank_reply_term(reply):
    for data in _reply_callback_data(reply):
        match = re.fullmatch(r"dep_make_(\d+)_(0|1)_(all|10|25|50)", data)
        if match and int(match[1]) in TIME_DEPOSIT_RATES:
            return int(match[1]), int(match[2])
    return None


def _p2p_reply_action(reply):
    buttons = _reply_callback_data(reply)
    for data in buttons:
        for prefix, action in (("p2p_bbot_", "buy_bot_custom"), ("p2p_sbot_", "sell_bot_custom"), ("p2p_dmc_", "dep_mcoin"), ("p2p_dmp_", "dep_mpoint"), ("p2p_wmc_", "wth_mcoin"), ("p2p_wmp_", "wth_mpoint")):
            if data.startswith(prefix) and data[len(prefix):].isdigit():
                return action
        match = re.fullmatch(r"p2p_(bamt|sbuy)_(\d+)_(\d+)", data)
        if match:
            prefix = "buy_seller_" if match[1] == "bamt" else "sell_buyer_"
            return prefix + match[2]
    if buttons == ("p2p_buy_bot",):
        return "buy_bot_custom"
    return None


@dp.message(_inline_filter(lambda message: message.reply_to_message and message.text and (
    _bank_reply_term(message.reply_to_message) is not None or
    "ДЕПОЗИТ НА" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
    "ПОПОЛНИТЬ НАКОП. СЧЕТ" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
    "СНЯТЬ С НАКОП. СЧЕТА" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "")
)))
@_localized
async def process_bank_reply_message(message: types.Message):
    rep_text = _canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or ""
    user_id = message.from_user.id
    raw_amount = resolve_bet_amount(message.text.strip(), get_user(user_id)["balance"])
    term = _bank_reply_term(message.reply_to_message)

    if raw_amount is None or raw_amount <= 0:
        return

    if term is not None or "ДЕПОЗИТ НА" in rep_text:
        m = re.search(r'ДЕПОЗИТ НА (\d+)', rep_text)
        if term is not None or m:
            days = term[0] if term is not None else int(m.group(1))
            is_locked = term[1] if term is not None else (1 if "Заблокировать снятие ✅" in _canonical_prompt(str(message.reply_to_message.reply_markup)) else 0)
            ok, res = create_time_deposit(user_id, raw_amount, days, is_locked)
            if not ok:
                await message.reply(_lf('<i>Ошибка: {0}</i>', (_fmt(res, '', -1),)), parse_mode=ParseMode.HTML)
                return
            clean_name = html.escape(str(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок')))
            user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'
            rate_str = str(res["percent"]).replace(".", ",")
            succ_text = (
                _lf('{0}\n<tg-emoji emoji-id="5264895611517300926">🏦</tg-emoji><b>ДЕПОЗИТ ПРИНЯТ</b>\n<code>·····················</code>\n💰 Сумма: <b>{1} m¢</b>\n🔘 Процент: <b>{2}% • {3} m¢</b>\n<code>············</code>\n⏳ До: <b>{4} ({5}д.)</b>', (_fmt(user_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(rate_str, '', -1), _fmt(format_number(res['profit']), '', -1), _fmt(res['end_at'], '', -1), _fmt(days, '', -1)))
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=_l('Положить ещё'), callback_data="dep_main", style="primary")]]
            )
            await message.reply(succ_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            return

    if "ПОПОЛНИТЬ НАКОП. СЧЕТ" in rep_text:
        ok, res = deposit_to_savings(user_id, raw_amount)
        if not ok:
            await message.reply(_lf('<i>Ошибка: {0}</i>', (_fmt(res, '', -1),)), parse_mode=ParseMode.HTML)
            return
        clean_name = html.escape(str(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок')))
        user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'
        succ_text = (
            _lf('{0}\n💸 <b>НАКОП. СЧЕТ ПОПОЛНЕН</b>\n<code>·····················</code>\n💰 Сумма: <b>{1} m¢</b>\n🔘 Ставка: 0.2% дневных\n<code>············</code>\n<blockquote>🏦 На счету: <b>{2} m¢</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(format_number(res), '', -1)))
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Накопительный счет'), callback_data="dep_savings", style="primary")]]
        )
        await message.reply(succ_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return

    if "СНЯТЬ С НАКОП. СЧЕТА" in rep_text:
        ok, res = withdraw_from_savings(user_id, raw_amount)
        if not ok:
            await message.reply(_lf('<i>Ошибка: {0}</i>', (_fmt(res, '', -1),)), parse_mode=ParseMode.HTML)
            return
        clean_name = html.escape(str(get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок')))
        user_link = f'<a href="tg://user?id={user_id}">{clean_name}</a>'
        succ_text = (
            _lf('🟢 {0}, ты вывел с накопительного счета <b>{1} mCoin!</b>\n<code>·····················</code>\n<tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> <b>Баланс:</b> <b>{2} mCoin</b>', (_fmt(user_link, '', -1), _fmt(format_number(res['withdrawn']), '', -1), _fmt(format_number(res['balance']), '', -1)))
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Накопительный счет'), callback_data="dep_savings", style="primary")]]
        )
        await message.reply(succ_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return



p2p_user_action = {}
admin_sexchange_state = {}


def format_deal_date(dt_str):
    if not dt_str:
        return ""
    try:
        if " " in dt_str:
            d_part, t_part = dt_str.split(" ", 1)
            d_sub = d_part.split(".")
            if len(d_sub) == 3:
                day, month, year = d_sub
                yy = year[-2:]
                time_short = ":".join(t_part.split(":")[:2])
                return f"{day}.{month}.{yy} {time_short}"
    except Exception:
        pass
    return dt_str


@_event_read_cache
def get_p2p_settings():
    try:
        cursor.execute("SELECT id, official_sell_enabled, official_buy_enabled, official_sell_rate, official_buy_rate, rate_min, rate_max, interval_minutes, last_update FROM p2p_settings WHERE id = 1")
        row = cursor.fetchone()
        if not row:
            now_iso = datetime.now().isoformat()
            cursor.execute("INSERT INTO p2p_settings (id, official_sell_enabled, official_buy_enabled, official_sell_rate, official_buy_rate, rate_min, rate_max, interval_minutes, last_update) VALUES (1, 1, 1, 10000, 10000, 7000, 29000, 150, ?) ON CONFLICT (id) DO NOTHING", (now_iso,))
            conn.commit()
            return {
                "official_sell_enabled": 1,
                "official_buy_enabled": 1,
                "official_sell_rate": 10000,
                "official_buy_rate": 10000,
                "rate_min": 7000,
                "rate_max": 29000,
                "interval_minutes": 150,
                "last_update": now_iso
            }
        return {
            "official_sell_enabled": row[1] if row[1] is not None else 1,
            "official_buy_enabled": row[2] if row[2] is not None else 1,
            "official_sell_rate": row[3] or 10000,
            "official_buy_rate": row[4] or 10000,
            "rate_min": row[5] or 7000,
            "rate_max": row[6] or 29000,
            "interval_minutes": row[7] or 150,
            "last_update": row[8]
        }
    except Exception:
        return {
            "official_sell_enabled": 1,
            "official_buy_enabled": 1,
            "official_sell_rate": 10000,
            "official_buy_rate": 10000,
            "rate_min": 7000,
            "rate_max": 29000,
            "interval_minutes": 150,
            "last_update": None
        }


def update_p2p_rate_fluctuation(force=False):
    settings = get_p2p_settings()
    now = datetime.now()
    if not force and settings.get("last_update"):
        try:
            last_dt = datetime.fromisoformat(settings["last_update"])
            if (now - last_dt).total_seconds() < settings.get("interval_minutes", 150) * 60:
                return False, settings
        except Exception:
            pass

    r_min = settings.get("rate_min", 7000) or 7000
    r_max = settings.get("rate_max", 29000) or 29000
    if r_min >= r_max:
        r_min, r_max = 7000, 29000

    new_rate = random.randint(r_min // 100, r_max // 100) * 100
    now_iso = now.isoformat()
    try:
        cursor.execute('''
            UPDATE p2p_settings 
            SET official_sell_rate = ?, official_buy_rate = ?, last_update = ? 
            WHERE id = 1
        ''', (new_rate, new_rate, now_iso))
        conn.commit()
        return True, get_p2p_settings()
    except Exception:
        return False, settings


@_event_read_cache
def get_p2p_account(user_id):
    try:
        cursor.execute("SELECT user_id, mcoin_balance, mp_balance, rating, deals_count, last_deposit_date, sell_order_active, sell_price, buy_order_active, buy_price FROM p2p_accounts WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO p2p_accounts (user_id) VALUES (?) ON CONFLICT (user_id) DO NOTHING", (user_id,))
            conn.commit()
            cursor.execute("SELECT user_id, mcoin_balance, mp_balance, rating, deals_count, last_deposit_date, sell_order_active, sell_price, buy_order_active, buy_price FROM p2p_accounts WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()

        if row:
            return {
                "user_id": row[0],
                "mcoin_balance": row[1] or 0,
                "mp_balance": row[2] or 0,
                "rating": row[3] if row[3] is not None else 100,
                "deals_count": row[4] or 0,
                "last_deposit_date": row[5],
                "sell_order_active": row[6] or 0,
                "sell_price": row[7] or 0,
                "buy_order_active": row[8] or 0,
                "buy_price": row[9] or 0
            }
    except Exception:
        pass
    return {
        "user_id": user_id,
        "mcoin_balance": 0,
        "mp_balance": 0,
        "rating": 100,
        "deals_count": 0,
        "last_deposit_date": None,
        "sell_order_active": 0,
        "sell_price": 0,
        "buy_order_active": 0,
        "buy_price": 0
    }


def get_p2p_bot_24h_stats():
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount_mp), 0) FROM p2p_bot_stats WHERE created_at >= ?", (cutoff,))
    row = cursor.fetchone()
    return row[0], row[1]


@db_transaction
@_localized
def deposit_to_p2p_mcoin(user_id, amount):
    amount = int(amount)
    if amount <= 0:
        return False, _l('Сумма должна быть больше 0!')
    if is_transfer_banned(user_id):
        return False, _l('Вам заблокированы переводы!')

    p2p = get_p2p_account(user_id)
    today_str = get_msk_today_str()
    is_first_today = (p2p["last_deposit_date"] != today_str)

    fee = 0 if is_first_today else int(amount * 0.015)
    total_deduct = amount + fee

    user_data = get_user(user_id)
    if user_data["balance"] < total_deduct:
        return False, _lf('Недостаточно mCoin! Нужно {0} mCoin (с учетом комиссии {1} mCoin).', (_fmt(format_number(total_deduct), '', -1), _fmt(format_number(fee), '', -1)))

    try:
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?", (total_deduct, user_id, total_deduct))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно mCoin на основном балансе!')

        credited = amount
        cursor.execute("UPDATE p2p_accounts SET mcoin_balance = mcoin_balance + ?, last_deposit_date = ? WHERE user_id = ?", (credited, today_str, user_id))
        conn.commit()

        updated_p2p = get_p2p_account(user_id)
        return True, {
            "amount": amount,
            "fee": fee,
            "is_first": is_first_today,
            "mcoin_balance": updated_p2p["mcoin_balance"],
            "mp_balance": updated_p2p["mp_balance"]
        }
    except Exception as e:
        return False, _lf('Ошибка пополнения: {0}', (_fmt(e, '', -1),))


@db_transaction
@_localized
def deposit_to_p2p_mpoint(user_id, amount):
    amount = int(amount)
    if amount <= 0:
        return False, _l('Сумма должна быть больше 0!')
    if is_transfer_banned(user_id):
        return False, _l('Вам заблокированы переводы!')

    get_p2p_account(user_id)
    user_data = get_user(user_id)
    if user_data.get("mp_balance", 0) < amount:
        return False, _lf('Недостаточно MPOINT! На балансе: {0} MP.', (_fmt(format_number(user_data.get('mp_balance', 0)), '', -1),))

    try:
        cursor.execute("UPDATE users SET mp_balance = mp_balance - ? WHERE user_id = ? AND mp_balance >= ?", (amount, user_id, amount))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно MPOINT на основном балансе!')

        cursor.execute("UPDATE p2p_accounts SET mp_balance = mp_balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

        updated_p2p = get_p2p_account(user_id)
        return True, {
            "amount": amount,
            "mcoin_balance": updated_p2p["mcoin_balance"],
            "mp_balance": updated_p2p["mp_balance"]
        }
    except Exception as e:
        return False, _lf('Ошибка пополнения: {0}', (_fmt(e, '', -1),))


@db_transaction
@_localized
def withdraw_from_p2p_mcoin(user_id, amount):
    amount = int(amount)
    if amount <= 0:
        return False, _l('Сумма должна быть больше 0!')
    if is_transfer_banned(user_id):
        return False, _l('Вам заблокированы переводы!')

    try:
        cursor.execute("UPDATE p2p_accounts SET mcoin_balance = mcoin_balance - ? WHERE user_id = ? AND mcoin_balance >= ?", (amount, user_id, amount))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно mCoin на балансе обменника!')

        cursor.execute("UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ?", (amount, amount, user_id))
        conn.commit()

        updated_p2p = get_p2p_account(user_id)
        return True, {
            "amount": amount,
            "mcoin_balance": updated_p2p["mcoin_balance"]
        }
    except Exception as e:
        return False, _lf('Ошибка вывода: {0}', (_fmt(e, '', -1),))


@db_transaction
@_localized
def withdraw_from_p2p_mpoint(user_id, amount):
    amount = int(amount)
    if amount <= 0:
        return False, _l('Сумма должна быть больше 0!')
    if is_transfer_banned(user_id):
        return False, _l('Вам заблокированы переводы!')

    try:
        cursor.execute("UPDATE p2p_accounts SET mp_balance = mp_balance - ? WHERE user_id = ? AND mp_balance >= ?", (amount, user_id, amount))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно MPOINT на балансе обменника!')

        cursor.execute("UPDATE users SET mp_balance = mp_balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

        updated_p2p = get_p2p_account(user_id)
        return True, {
            "amount": amount,
            "mp_balance": updated_p2p["mp_balance"]
        }
    except Exception as e:
        return False, _lf('Ошибка вывода: {0}', (_fmt(e, '', -1),))


@db_transaction
@_localized
def execute_p2p_buy_deal(buyer_id, seller_id, amount_mp):
    amount_mp = int(amount_mp)
    if amount_mp <= 0:
        return False, _l('Сумма должна быть больше 0!')
    if buyer_id == seller_id:
        return False, _l('Нельзя покупать у самого себя!')
    if is_transfer_banned(buyer_id) or is_transfer_banned(seller_id):
        return False, _l('Переводы заблокированы!')

    seller_p2p = get_p2p_account(seller_id)
    if not seller_p2p["sell_order_active"] or seller_p2p["sell_price"] <= 0:
        return False, _l('У продавца не активна заявка на продажу!')

    total_cost = amount_mp * seller_p2p["sell_price"]
    buyer_u = get_user(buyer_id)
    if buyer_u["balance"] < total_cost:
        return False, _lf('Недостаточно mCoin! Нужно {0} m¢.', (_fmt(format_number(total_cost), '', -1),))

    try:
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?", (total_cost, buyer_id, total_cost))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно mCoin на балансе!')

        cursor.execute("UPDATE p2p_accounts SET mp_balance = mp_balance - ?, deals_count = deals_count + 1 WHERE user_id = ? AND mp_balance >= ? AND sell_order_active = 1", (amount_mp, seller_id, amount_mp))
        if cursor.rowcount == 0:
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (total_cost, buyer_id))
            conn.commit()
            return False, _l('У продавца изменился баланс или заявка отключена!')

        cursor.execute("UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ?", (total_cost, total_cost, seller_id))
        cursor.execute("UPDATE users SET mp_balance = mp_balance + ? WHERE user_id = ?", (amount_mp, buyer_id))
        cursor.execute("UPDATE p2p_accounts SET deals_count = deals_count + 1 WHERE user_id = ?", (buyer_id,))
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute('''
            INSERT INTO p2p_deals_history (buyer_id, seller_id, amount_mp, price_per_mp, total_mcoin, commission, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            RETURNING id
        ''', (buyer_id, seller_id, amount_mp, seller_p2p["sell_price"], total_cost, now_str))
        res_row = cursor.fetchone()
        deal_id = res_row[0] if res_row else 0
        conn.commit()
        return True, {
            "deal_id": deal_id,
            "amount_mp": amount_mp,
            "total_mcoin": total_cost,
            "rate": seller_p2p["sell_price"],
            "seller_id": seller_id
        }
    except Exception as e:
        return False, _lf('Ошибка проведения сделки: {0}', (_fmt(e, '', -1),))


@db_transaction
@_localized
def execute_p2p_buy_from_bot(user_id, amount_mp):
    amount_mp = int(amount_mp)
    if amount_mp <= 0:
        return False, _l('Сумма должна быть больше 0!')
    if is_transfer_banned(user_id):
        return False, _l('Вам заблокированы переводы!')

    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    if not settings.get("official_buy_enabled", 1):
        return False, _l('Официальная покупка сейчас отключена!')

    rate = settings.get("official_buy_rate", 10000)
    total_mcoin = amount_mp * rate
    try:
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute("UPDATE users SET balance = balance - ?, mp_balance = mp_balance + ? WHERE user_id = ? AND balance >= ?", (total_mcoin, amount_mp, user_id, total_mcoin))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно mCoin на основном балансе!')

        cursor.execute("INSERT INTO p2p_bot_stats (user_id, amount_mp, amount_mcoin, created_at) VALUES (?, ?, ?, ?)", (user_id, amount_mp, total_mcoin, now_str))
        cursor.execute("INSERT INTO p2p_deals_history (buyer_id, seller_id, amount_mp, price_per_mp, total_mcoin, commission, created_at) VALUES (?, 0, ?, ?, ?, 0, ?) RETURNING id", (user_id, amount_mp, rate, total_mcoin, now_str))
        res_row = cursor.fetchone()
        deal_id = res_row[0] if res_row else 0
        conn.commit()
        return True, {
            "deal_id": deal_id,
            "amount_mp": amount_mp,
            "total_mcoin": total_mcoin,
            "rate": rate
        }
    except Exception as e:
        return False, _lf('Ошибка сделки: {0}', (_fmt(e, '', -1),))


@db_transaction
@_localized
def execute_p2p_sell_to_bot(user_id, amount_mp):
    amount_mp = int(amount_mp)
    if amount_mp <= 0:
        return False, _l('Сумма должна быть больше 0!')
    if is_transfer_banned(user_id):
        return False, _l('Вам заблокированы переводы!')

    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    if not settings.get("official_sell_enabled", 1):
        return False, _l('Официальная продажа сейчас отключена!')

    rate = settings.get("official_sell_rate", 10000)
    total_mcoin = amount_mp * rate
    try:
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute("UPDATE users SET mp_balance = mp_balance - ?, balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ? AND mp_balance >= ?", (amount_mp, total_mcoin, total_mcoin, user_id, amount_mp))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно MP на балансе!')

        cursor.execute("INSERT INTO p2p_bot_stats (user_id, amount_mp, amount_mcoin, created_at) VALUES (?, ?, ?, ?)", (user_id, amount_mp, total_mcoin, now_str))
        cursor.execute("INSERT INTO p2p_deals_history (buyer_id, seller_id, amount_mp, price_per_mp, total_mcoin, commission, created_at) VALUES (0, ?, ?, ?, ?, 0, ?) RETURNING id", (user_id, amount_mp, rate, total_mcoin, now_str))
        res_row = cursor.fetchone()
        deal_id = res_row[0] if res_row else 0
        conn.commit()
        return True, {
            "deal_id": deal_id,
            "amount_mp": amount_mp,
            "total_mcoin": total_mcoin,
            "rate": rate
        }
    except Exception as e:
        return False, _lf('Ошибка сделки: {0}', (_fmt(e, '', -1),))


@db_transaction
@_localized
def execute_p2p_sell_to_buyer(seller_id, buyer_id, amount_mp):
    amount_mp = int(amount_mp)
    if amount_mp <= 0:
        return False, _l('Сумма должна быть больше 0!')
    if seller_id == buyer_id:
        return False, _l('Нельзя совершать сделку с самим собой!')
    if is_transfer_banned(seller_id) or is_transfer_banned(buyer_id):
        return False, _l('Переводы заблокированы!')

    buyer_p2p = get_p2p_account(buyer_id)
    if not buyer_p2p["buy_order_active"] or buyer_p2p["buy_price"] <= 0:
        return False, _l('У покупателя не активна заявка на покупку!')

    total_mcoin = amount_mp * buyer_p2p["buy_price"]

    try:
        cursor.execute("UPDATE users SET mp_balance = mp_balance - ?, balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ? AND mp_balance >= ?", (amount_mp, total_mcoin, total_mcoin, seller_id, amount_mp))
        if cursor.rowcount == 0:
            return False, _l('Недостаточно MP на основном балансе!')

        cursor.execute("UPDATE p2p_accounts SET mcoin_balance = mcoin_balance - ?, deals_count = deals_count + 1 WHERE user_id = ? AND mcoin_balance >= ? AND buy_order_active = 1", (total_mcoin, buyer_id, total_mcoin))
        if cursor.rowcount == 0:
            cursor.execute("UPDATE users SET mp_balance = mp_balance + ?, balance = balance - ? WHERE user_id = ?", (amount_mp, total_mcoin, seller_id))
            conn.commit()
            return False, _l('У покупателя изменился баланс или заявка отключена!')

        cursor.execute("UPDATE users SET mp_balance = mp_balance + ? WHERE user_id = ?", (amount_mp, buyer_id))
        cursor.execute("UPDATE p2p_accounts SET deals_count = deals_count + 1 WHERE user_id = ?", (seller_id,))
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cursor.execute('''
            INSERT INTO p2p_deals_history (buyer_id, seller_id, amount_mp, price_per_mp, total_mcoin, commission, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            RETURNING id
        ''', (buyer_id, seller_id, amount_mp, buyer_p2p["buy_price"], total_mcoin, now_str))
        res_row = cursor.fetchone()
        deal_id = res_row[0] if res_row else 0
        conn.commit()
        return True, {
            "deal_id": deal_id,
            "amount_mp": amount_mp,
            "total_mcoin": total_mcoin,
            "rate": buyer_p2p["buy_price"],
            "buyer_id": buyer_id
        }
    except Exception as e:
        return False, _lf('Ошибка проведения сделки: {0}', (_fmt(e, '', -1),))



@_localized
async def show_p2p_main(event, user_id=None, first_name=None, edit=False):
    if hasattr(event, "from_user") and event.from_user:
        uid = user_id or event.from_user.id
        fname = first_name or get_user_display_name(event.from_user.id, event.from_user.first_name) or _l('Игрок')
    else:
        uid = user_id
        fname = first_name or _l('Игрок')

    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    user_link = get_user_mention(uid, fname)
    sell_rate = settings.get("official_sell_rate", 10000)

    text = (
        _lf('<tg-emoji emoji-id="5402186569006210455">💱</tg-emoji><b>P2P ОБМЕННИК</b>\n<code>·····················</code>\n<blockquote><i>ℹ️ Здесь ты можешь купить и продать MPOINT.</i></blockquote>\n<blockquote><tg-emoji emoji-id="5431577498364158238">📊</tg-emoji> <b>Оф. курс:</b> 1 MP ≈ {0} mCoin</blockquote>\n<tg-emoji emoji-id="5470177992950946662">👇</tg-emoji> {1}, что ты хочешь?', (_fmt(format_number(sell_rate), '', -1), _fmt(user_link, '', -1)))
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('КУПИТЬ'), callback_data="p2p_buy_list", style="success", icon_custom_emoji_id="5287231198098117669")
            ],
            [
                InlineKeyboardButton(text=_l('ПРОДАТЬ'), callback_data="p2p_sell_list", style="primary", icon_custom_emoji_id="5445353829304387411")
            ],
            [
                InlineKeyboardButton(text=" ", callback_data="p2p_manage", style="primary", icon_custom_emoji_id="5334882760735598374"),
                InlineKeyboardButton(text=" ", callback_data="p2p_hist_1", style="primary", icon_custom_emoji_id="5956561916573782596")
            ]
        ]
    )

    if isinstance(event, types.CallbackQuery):
        if edit and event.message:
            try:
                await event.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                return
            except Exception:
                pass
        if event.message:
            try:
                await event.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            except Exception:
                pass
    elif isinstance(event, types.Message):
        await event.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@_localized
def render_p2p_manage(user_id):
    p2p = get_p2p_account(user_id)

    sell_price = p2p["sell_price"]
    sell_active = p2p["sell_order_active"]
    mp_bal = p2p["mp_balance"]

    if sell_price <= 0:
        sell_status = "⚠️"
    elif not sell_active:
        sell_status = "⭕️"
    elif mp_bal <= 0:
        sell_status = "❗️"
    else:
        sell_status = "✅"

    sell_amount = mp_bal if sell_active else 0
    sell_total = sell_amount * sell_price

    buy_price = p2p["buy_price"]
    buy_active = p2p["buy_order_active"]
    mcoin_bal = p2p["mcoin_balance"]

    if buy_price <= 0:
        buy_status = "⚠️"
    elif not buy_active:
        buy_status = "⭕️"
    elif mcoin_bal < buy_price:
        buy_status = "❗️"
    else:
        buy_status = "✅"

    buy_amount = (mcoin_bal // buy_price) if (buy_price > 0 and buy_active) else 0
    buy_total = mcoin_bal if buy_active else 0

    text = (
        _lf('📝 <b>Управление обменом</b>\n<code>·····················</code>\n💵 <b>Баланс:</b> {0} m¢ | {1} MP\n<blockquote><i>ℹ️ Основной и обменный балансы не связаны. Используйте кнопки ниже для пополнения и вывода.</i></blockquote>\n<b>💰 Заявка на продажу:</b>\n├ <b>Курс:</b> 1 MP = {2} m¢ {3}\n├ <b>Налог:</b> 0 m¢ (за 1 ед.)\n├ <b>В продаже:</b> {4} MP\n└ <b>Получите:</b> {5} m¢\n\n💳 <b>Заявка на покупку:</b>\n├ <b>Курс:</b> {6} m¢ = 1 MP {7}\n├ <b>Сбор:</b> 0 m¢ (за 1 ед.)\n├ <b>Будет куплено:</b> {8} MP\n└ <b>На сумму:</b> {9} m¢\n\n<blockquote><b>Статусы ордеров:</b>\n<i>✅ — Активен\n⭕️ — Отключён\n❗️ — Недостаточно средств\n⚠️ — Курс не установлен</i></blockquote>\n💞 Рейтинг: {10}', (_fmt(format_number(mcoin_bal), '', -1), _fmt(format_number(mp_bal), '', -1), _fmt(format_number(sell_price), '', -1), _fmt(sell_status, '', -1), _fmt(format_number(sell_amount), '', -1), _fmt(format_number(sell_total), '', -1), _fmt(format_number(buy_price), '', -1), _fmt(buy_status, '', -1), _fmt(format_number(buy_amount), '', -1), _fmt(format_number(buy_total), '', -1), _fmt(p2p['rating'], '', -1)))
    )

    sell_btn_text = _l('🟢 Продажа') if sell_active else _l('🔴 Продажа')
    buy_btn_text = _l('🟢 Покупка') if buy_active else _l('🔴 Покупка')

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_l('Изменить курс продажи'), callback_data="p2p_set_sell_price")],
            [InlineKeyboardButton(text=_l('Изменить курс покупки'), callback_data="p2p_set_buy_price")],
            [
                InlineKeyboardButton(text=_l('📥 Пополнить'), callback_data="p2p_deposit"),
                InlineKeyboardButton(text=_l('📤 Вывести'), callback_data="p2p_withdraw")
            ],
            [
                InlineKeyboardButton(text=sell_btn_text, callback_data="p2p_toggle_sell"),
                InlineKeyboardButton(text=buy_btn_text, callback_data="p2p_toggle_buy")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_main", icon_custom_emoji_id="5255703720078879038"),
                InlineKeyboardButton(text=_l('🔄 Обновить'), callback_data="p2p_manage")
            ]
        ]
    )

    return text, keyboard


@_localized
def render_p2p_history(user_id, page=1):
    per_page = 5
    cursor.execute("SELECT COUNT(*) FROM p2p_deals_history WHERE buyer_id = ? OR seller_id = ?", (user_id, user_id))
    total_cnt = cursor.fetchone()[0]
    total_pages = max(1, math.ceil(total_cnt / per_page))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    cursor.execute('''
        SELECT buyer_id, seller_id, amount_mp, price_per_mp, total_mcoin, commission, created_at 
        FROM p2p_deals_history 
        WHERE buyer_id = ? OR seller_id = ?
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    ''', (user_id, user_id, per_page, offset))
    rows = cursor.fetchall()

    lines = [
        _l('🧾 <b>ИСТОРИЯ ОБМЕНОВ</b>'),
        '<code>·····················</code>'
    ]

    if not rows:
        lines.append(_l('<i>У вас пока нет истории обменов.</i>'))
    else:
        for buyer_id, seller_id, amount_mp, price_per_mp, total_mcoin, commission, created_at in rows:
            date_short = format_deal_date(created_at)
            if buyer_id == user_id:
                partner = _l('Оф. Покупка') if seller_id == 0 else get_user_display_name(seller_id)
                lines.append(_lf('💰(К) {0} GMP за {1} m¢', (_fmt(format_number(amount_mp), '', -1), _fmt(format_number(total_mcoin), '', -1))))
                lines.append(f'⤷ <i>{partner} · {date_short}</i>')
            else:
                partner = _l('Оф. Продажа') if buyer_id == 0 else get_user_display_name(buyer_id)
                lines.append(_lf('💳(П) {0} GMP за {1} m¢', (_fmt(format_number(amount_mp), '', -1), _fmt(format_number(total_mcoin), '', -1))))
                lines.append(f'⤷ <i>{partner} · {date_short}</i>')

    lines.append('<code>·····················</code>')
    lines.append(_lf('↗️ Показано: {0}/{1}', (_fmt(page, '', -1), _fmt(total_pages, '', -1))))
    lines.append(_l('<blockquote>ℹ️ (П) —> Продал, (К) —> Купил</blockquote>'))

    text = "\n".join(lines)

    buttons = []
    nav_row = []
    if page <= 1:
        nav_row.append(InlineKeyboardButton(text="🚫", callback_data="noop_p2p"))
    else:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"p2p_hist_{page-1}"))

    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop_p2p"))

    if page >= total_pages:
        nav_row.append(InlineKeyboardButton(text="🚫", callback_data="noop_p2p"))
    else:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"p2p_hist_{page+1}"))

    buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_main", icon_custom_emoji_id="5255703720078879038")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return text, keyboard


@_localized
def render_sexchange_menu():
    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    sell_en = settings.get("official_sell_enabled", 1)
    buy_en = settings.get("official_buy_enabled", 1)
    sell_rate = settings.get("official_sell_rate", 10000)
    buy_rate = settings.get("official_buy_rate", 10000)
    r_min = settings.get("rate_min", 7000)
    r_max = settings.get("rate_max", 29000)
    interval = settings.get("interval_minutes", 150)
    last_upd = settings.get("last_update")

    time_left_str = _l('скоро')
    if last_upd:
        try:
            last_dt = datetime.fromisoformat(last_upd)
            elapsed = (datetime.now() - last_dt).total_seconds()
            remaining = int((interval * 60) - elapsed)
            if remaining > 0:
                mins = remaining // 60
                secs = remaining % 60
                time_left_str = _lf('{0}м {1}с', (_fmt(mins, '', -1), _fmt(secs, '', -1)))
            else:
                time_left_str = _l('сейчас')
        except Exception:
            pass

    sell_status_str = _l('🟢 ВКЛ') if sell_en else _l('🔴 ВЫКЛ')
    buy_status_str = _l('🟢 ВКЛ') if buy_en else _l('🔴 ВЫКЛ')

    text = (
        _lf('⚙️ <b>НАСТРОЙКИ ОБМЕННИКА (/sexchange)</b>\n<code>································</code>\n📈 <b>Официальные курсы (1 MP):</b>\n├ 💰 <b>Оф. Продажа (бот выкупает):</b> <b>{0} m¢</b> ({1})\n└ 🛍 <b>Оф. Покупка (бот продает):</b> <b>{2} m¢</b> ({3})\n\n📊 <b>Параметры авто-курса:</b>\n├ <b>Диапазон:</b> <b>{4} — {5} m¢</b>\n├ <b>Интервал:</b> <b>{6} мин. ({7}ч {8}м)</b>\n└ <b>След. обновление:</b> <b>{9}</b>', (_fmt(format_number(sell_rate), '', -1), _fmt(sell_status_str, '', -1), _fmt(format_number(buy_rate), '', -1), _fmt(buy_status_str, '', -1), _fmt(format_number(r_min), '', -1), _fmt(format_number(r_max), '', -1), _fmt(interval, '', -1), _fmt(interval // 60, '', -1), _fmt(interval % 60, '', -1), _fmt(time_left_str, '', -1)))
    )

    btn_sell_tog = _l('🔴 Отключить оф. продажу') if sell_en else _l('🟢 Включить оф. продажу')
    btn_buy_tog = _l('🔴 Отключить оф. покупку') if buy_en else _l('🟢 Включить оф. покупку')

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=btn_sell_tog, callback_data="sexch_tog_sell")
            ],
            [
                InlineKeyboardButton(text=btn_buy_tog, callback_data="sexch_tog_buy")
            ],
            [
                InlineKeyboardButton(text=_l('🎲 Сгенерировать курс сейчас'), callback_data="sexch_reroll")
            ],
            [
                InlineKeyboardButton(text=_l('✏️ Курс продажи'), callback_data="sexch_set_sell"),
                InlineKeyboardButton(text=_l('✏️ Курс покупки'), callback_data="sexch_set_buy")
            ],
            [
                InlineKeyboardButton(text=_l('📊 Диапазон'), callback_data="sexch_set_range"),
                InlineKeyboardButton(text=_l('⏱ Интервал'), callback_data="sexch_set_interval")
            ],
            [
                InlineKeyboardButton(text=_l('🔄 Обновить меню'), callback_data="sexch_refresh")
            ]
        ]
    )
    return text, keyboard



@dp.message(Command("exchange", "обменник"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower() in ["обменник", "/exchange", "exchange", "/обменник"]))
@_localized
async def cmd_exchange(message: types.Message):
    if message.chat.type in ["group", "supergroup"]:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Перейти в обменник'),
                        url=f"https://t.me/{BOT_USERNAME}?start=p2p"
                    )
                ]
            ]
        )
        await message.reply(_l('<i>Эта команда работает только в личных сообщениях!</i>'), reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return

    await show_p2p_main(message, user_id=message.from_user.id, first_name=get_user_display_name(message.from_user.id, message.from_user.first_name))


@dp.message(Command("sexchange", "setexchange"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower() in ["/sexchange", "sexchange", "/setexchange", "setexchange"]))
@_localized
async def cmd_sexchange(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    text, keyboard = render_sexchange_menu()
    await message.reply(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)



@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_main"))
@_localized
async def cb_p2p_main(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    await callback.answer()
    await show_p2p_main(callback, user_id=callback.from_user.id, first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name), edit=True)


@dp.callback_query(_inline_filter(lambda c: c.data in ["p2p_history", "p2p_hist_1"] or c.data.startswith("p2p_hist_")))
@_localized
async def cb_p2p_history(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    await callback.answer()
    page = 1
    if callback.data.startswith("p2p_hist_"):
        try:
            page = int(callback.data.replace("p2p_hist_", ""))
        except Exception:
            page = 1
    text, kb = render_p2p_history(callback.from_user.id, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_manage"))
@_localized
async def cb_p2p_manage(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    await callback.answer()
    text, kb = render_p2p_manage(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_toggle_sell"))
@_localized
async def cb_p2p_toggle_sell(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    p2p = get_p2p_account(user_id)
    new_val = 0 if p2p["sell_order_active"] else 1
    cursor.execute("UPDATE p2p_accounts SET sell_order_active = ? WHERE user_id = ?", (new_val, user_id))
    conn.commit()
    text, kb = render_p2p_manage(user_id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_toggle_buy"))
@_localized
async def cb_p2p_toggle_buy(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    p2p = get_p2p_account(user_id)
    new_val = 0 if p2p["buy_order_active"] else 1
    cursor.execute("UPDATE p2p_accounts SET buy_order_active = ? WHERE user_id = ?", (new_val, user_id))
    conn.commit()
    text, kb = render_p2p_manage(user_id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)



def _get_p2p_offer_page(user_id, page, buying):
    if buying:
        condition = "sell_order_active = 1 AND sell_price > 0 AND mp_balance > 0 AND user_id != ?"
        columns = "user_id, sell_price, mp_balance, rating"
        order = "sell_price ASC"
    else:
        condition = "buy_order_active = 1 AND buy_price > 0 AND mcoin_balance >= buy_price AND user_id != ?"
        columns = "user_id, buy_price, mcoin_balance, rating"
        order = "buy_price DESC"
    cursor.execute(f"SELECT COUNT(*) FROM p2p_accounts WHERE {condition}", (user_id,))
    count = cursor.fetchone()[0]
    per_page = 8
    total_pages = max(1, math.ceil(count / per_page))
    page = max(1, min(page, total_pages))
    cursor.execute(f"SELECT {columns} FROM p2p_accounts WHERE {condition} ORDER BY {order} LIMIT ? OFFSET ?", (user_id, per_page, (page - 1) * per_page))
    return page, total_pages, cursor.fetchall()


@dp.callback_query(_inline_filter(lambda c: c.data in ["p2p_buy_list"] or c.data.startswith("p2p_buy_page_")))
@_localized
async def cb_p2p_buy_list(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    await callback.answer()
    page = 1
    if callback.data.startswith("p2p_buy_page_"):
        try:
            page = int(callback.data.replace("p2p_buy_page_", ""))
        except Exception:
            page = 1

    current_uid = callback.from_user.id
    page, total_pages, page_sellers = _get_p2p_offer_page(current_uid, page, True)

    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    buy_enabled = settings.get("official_buy_enabled", 1)
    buy_rate = settings.get("official_buy_rate", 10000)

    text = (
        _lf('<b>⚡️ КУПИТЬ MPOINT</b>\n<code>·····················</code>\n<blockquote expandable><i> ℹ️ MPOINT можно приобрести как у официального бота, так и у других игроков. Выгодные предложения находятся в верхней части списка.</i></blockquote>\n<blockquote>📊 Оф. курс покупки: <b>1 MP</b> ≈ {0} mCoin</blockquote>', (_fmt(format_number(buy_rate), '', -1),))
    )

    buttons = []
    if page == 1 and buy_enabled:
        buttons.append([
            InlineKeyboardButton(
                text=_lf('🏛 Оф. покупка • {0} m¢', (_fmt(format_number(buy_rate), '', -1),)),
                callback_data="p2p_buy_bot",
                icon_custom_emoji_id="5206607081334906820"
            )
        ])

    for s_uid, s_price, s_mp, s_rating in page_sellers:
        display_name = get_user_display_name(s_uid)
        buttons.append([
            InlineKeyboardButton(
                text=f"{display_name} • {format_number(s_price)} m¢",
                callback_data=f"p2p_buy_seller_{s_uid}"
            )
        ])

    nav_row = []
    if page <= 1:
        nav_row.append(InlineKeyboardButton(text="🚫", callback_data="noop_p2p"))
    else:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"p2p_buy_page_{page-1}"))

    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop_p2p"))

    if page >= total_pages:
        nav_row.append(InlineKeyboardButton(text="🚫", callback_data="noop_p2p"))
    else:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"p2p_buy_page_{page+1}"))

    buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_main", icon_custom_emoji_id="5255703720078879038")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)



@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_buy_bot"))
@_localized
async def cb_p2p_buy_bot(callback: types.CallbackQuery):
    await callback.answer()
    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    if not settings.get("official_buy_enabled", 1):
        await callback.answer(_l('Официальная покупка сейчас отключена!'), show_alert=True)
        return

    buy_rate = settings.get("official_buy_rate", 10000)
    user_u = get_user(callback.from_user.id)
    user_balance = user_u.get("balance", 0) or 0
    max_affordable_mp = user_balance // buy_rate if buy_rate > 0 else 0

    text = (
        _lf('<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji><b>КУПИТЬ MPOINT</b>\n<code>·····················</code>\n<i>👤 Продавец: 🏛 Оф. Покупка\n💞 Рейтинг: 100%\n❇️ Доступно: ∞ MP\n💸 Курс: 1 MP = {0} mCoin\n·····················\n🔘 Комиссия: 0%</i>\n<blockquote>💰 Твой баланс: <b>{1} mCoin</b> (хватит на <b>{2} MP</b>)</blockquote>\n<blockquote><i>ℹ️ Выберите количество MP или напишите в чат.</i></blockquote>', (_fmt(format_number(buy_rate), '', -1), _fmt(format_number(user_balance), '', -1), _fmt(format_number(max_affordable_mp), '', -1)))
    )

    p2p_user_action[callback.from_user.id] = "buy_bot_custom"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 MP", callback_data="p2p_bbot_1"),
                InlineKeyboardButton(text="5 MP", callback_data="p2p_bbot_5"),
                InlineKeyboardButton(text="10 MP", callback_data="p2p_bbot_10"),
            ],
            [
                InlineKeyboardButton(text="25 MP", callback_data="p2p_bbot_25"),
                InlineKeyboardButton(text="50 MP", callback_data="p2p_bbot_50"),
                InlineKeyboardButton(text="100 MP", callback_data="p2p_bbot_100"),
            ],
            [
                InlineKeyboardButton(text=_l('Ввести сумму ✏️'), callback_data="p2p_bbot_custom")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_buy_list", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_bbot_custom"))
@_localized
async def cb_p2p_bbot_custom(callback: types.CallbackQuery):
    await callback.answer()
    p2p_user_action[callback.from_user.id] = "buy_bot_custom"
    text = (
        _l('💎 <b>КУПИТЬ MPOINT (ОФ. ПОКУПКА)</b>\n<code>·····················</code>\n<i>Напишите в ответ или в чат количество MPOINT, которое хотите купить:</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_buy_bot", icon_custom_emoji_id="5255703720078879038")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_bbot_")))
@_localized
async def cb_p2p_buy_bot_amount(callback: types.CallbackQuery):
    try:
        amount_mp = int(callback.data.replace("p2p_bbot_", ""))
    except Exception:
        return

    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    buy_rate = settings.get("official_buy_rate", 10000)
    user_u = get_user(callback.from_user.id)
    total_cost = amount_mp * buy_rate

    user_link = get_user_mention(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    if user_u["balance"] < total_cost:
        shortage = total_cost - user_u["balance"]
        err_text = _lf('🚫 <i>{0}, не хватает <b>{1} mCoin!</b></i>', (_fmt(user_link, '', -1), _fmt(format_number(shortage), '', -1)))
        err_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_buy_bot", icon_custom_emoji_id="5255703720078879038")]]
        )
        try:
            await callback.message.edit_text(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
        except Exception:
            await callback.message.answer(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
        return

    conf_text = (
        _lf('<tg-emoji emoji-id="5452069934089641166">❓</tg-emoji> <b>ПОДТВЕРЖДЕНИЕ ПОКУПКИ</b>\n<code>·····················</code>\n<i>{0}, ты точно <b>хочешь купить {1} MPOINT</b> за <b>{2} mCoin?</b></i>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Оф. курс: {3} mCoin</blockquote>\n<blockquote>🔘 Комиссия: 0% = 0 mCoin</blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(amount_mp), '', -1), _fmt(format_number(total_cost), '', -1), _fmt(format_number(buy_rate), '', -1)))
    )
    conf_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('Да ✅'), callback_data=f"p2p_conf_bbot_{amount_mp}", style="success"),
                InlineKeyboardButton(text=_l('Отмена 💢'), callback_data="p2p_cancel_buy", style="danger")
            ]
        ]
    )
    try:
        await callback.message.edit_text(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_conf_bbot_")))
@_localized
async def cb_p2p_confirm_buy_bot(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    try:
        amount_mp = int(callback.data.replace("p2p_conf_bbot_", ""))
    except Exception:
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    ok, res = execute_p2p_buy_from_bot(callback.from_user.id, amount_mp)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    user_link = get_user_mention(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    succ_text = (
        _lf('🎉 <b>УСПЕШНАЯ ПОКУПКА MPOINT</b>\n<code>·····················</code>\n{0}, ты успешно купил <b>{1} MPOINT</b> за <b>{2} mCoin!</b>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Курс: {3} mCoin</blockquote>\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> MPOINT зачислены на твой основной баланс.', (_fmt(user_link, '', -1), _fmt(format_number(res['amount_mp']), '', -1), _fmt(format_number(res['total_mcoin']), '', -1), _fmt(format_number(res['rate']), '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data=f"p2p_rate_{res['deal_id']}_0_1", icon_custom_emoji_id="5393194986252542669", style="success"),
                InlineKeyboardButton(text="1", callback_data=f"p2p_rate_{res['deal_id']}_0_-1", icon_custom_emoji_id="5382261056078881010", style="danger")
            ],
            [
                InlineKeyboardButton(text=_l('В меню обмена'), callback_data="p2p_main", style="primary")
            ]
        ]
    )
    try:
        await callback.message.edit_text(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_buy_seller_")))
@_localized
async def cb_p2p_buy_seller(callback: types.CallbackQuery):
    try:
        seller_id = int(callback.data.replace("p2p_buy_seller_", ""))
    except Exception:
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    seller_p2p = get_p2p_account(seller_id)
    if not seller_p2p["sell_order_active"] or seller_p2p["mp_balance"] <= 0 or seller_p2p["sell_price"] <= 0:
        await callback.answer(_l('У этого продавца больше нет активных заявок!'), show_alert=True)
        return

    display_name = get_user_display_name(seller_id)
    text = (
        _lf('<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji><b>КУПИТЬ MPOINT</b>\n<code>·····················</code>\n<i>👤 Продавец: <a href="tg://user?id={0}">{1}</a>\n💞 Рейтинг: {2}\n❇️ Доступно: {3} MPOINT\n💸 Курс: 1 MP = {4} mCoin\n·····················\n🔘 Комиссия: 0%</i>\n<blockquote><i>ℹ️ Напишите в ответ на это сообщение, сколько вы хотите купить, или выберите один из вариантов ниже.</i></blockquote>', (_fmt(seller_id, '', -1), _fmt(display_name, '', -1), _fmt(seller_p2p['rating'], '', -1), _fmt(format_number(seller_p2p['mp_balance']), '', -1), _fmt(format_number(seller_p2p['sell_price']), '', -1)))
    )

    p2p_user_action[callback.from_user.id] = f"buy_seller_{seller_id}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 MP", callback_data=f"p2p_bamt_{seller_id}_1"),
                InlineKeyboardButton(text="5 MP", callback_data=f"p2p_bamt_{seller_id}_5"),
                InlineKeyboardButton(text="10 MP", callback_data=f"p2p_bamt_{seller_id}_10"),
            ],
            [
                InlineKeyboardButton(text="25 MP", callback_data=f"p2p_bamt_{seller_id}_25"),
                InlineKeyboardButton(text="50 MP", callback_data=f"p2p_bamt_{seller_id}_50"),
                InlineKeyboardButton(text="100 MP", callback_data=f"p2p_bamt_{seller_id}_100"),
            ],
            [
                InlineKeyboardButton(text=_l('Все MP'), callback_data=f"p2p_bamt_{seller_id}_{seller_p2p['mp_balance']}")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_buy_list", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_bamt_")))
@_localized
async def cb_p2p_buy_amount_choice(callback: types.CallbackQuery):
    parts = callback.data.replace("p2p_bamt_", "").split("_")
    if len(parts) < 2:
        return
    seller_id = int(parts[0])
    amount_mp = int(parts[1])

    seller_p2p = get_p2p_account(seller_id)
    buyer_id = callback.from_user.id
    buyer_u = get_user(buyer_id)
    buyer_link = get_user_mention(buyer_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))

    total_cost = amount_mp * seller_p2p["sell_price"]
    if buyer_u["balance"] < total_cost:
        shortage = total_cost - buyer_u["balance"]
        err_text = _lf('🚫 <i>{0}, не хватает <b>{1} mCoin!</b></i>', (_fmt(buyer_link, '', -1), _fmt(format_number(shortage), '', -1)))
        err_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data=f"p2p_buy_seller_{seller_id}", icon_custom_emoji_id="5255703720078879038")]]
        )
        try:
            await callback.message.edit_text(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
        except Exception:
            await callback.message.answer(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
        return

    conf_text = (
        _lf('<tg-emoji emoji-id="5452069934089641166">❓</tg-emoji> <b>ПОДТВЕРЖДЕНИЕ СДЕЛКИ</b>\n<code>·····················</code>\n<i>{0}, ты точно <b>хочешь купить {1} MPOINT</b> за <b>{2} mCoin?</b></i>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Курс: {3} mCoin</blockquote>\n<blockquote>🔘 Комиссия: 0% = 0 mCoin</blockquote>', (_fmt(buyer_link, '', -1), _fmt(format_number(amount_mp), '', -1), _fmt(format_number(total_cost), '', -1), _fmt(format_number(seller_p2p['sell_price']), '', -1)))
    )
    conf_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('Да ✅'), callback_data=f"p2p_conf_buy_{seller_id}_{amount_mp}", style="success"),
                InlineKeyboardButton(text=_l('Отмена 💢'), callback_data="p2p_cancel_buy", style="danger")
            ]
        ]
    )
    try:
        await callback.message.edit_text(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_cancel_buy"))
@_localized
async def cb_p2p_cancel_buy(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    await callback.answer(_l('Сделка отменена!'))
    await show_p2p_main(callback, user_id=callback.from_user.id, first_name=get_user_display_name(callback.from_user.id, callback.from_user.first_name), edit=True)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_conf_buy_")))
@_localized
async def cb_p2p_confirm_buy(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    parts = callback.data.replace("p2p_conf_buy_", "").split("_")
    if len(parts) < 2:
        return
    seller_id = int(parts[0])
    amount_mp = int(parts[1])

    buyer_id = callback.from_user.id
    ok, res = execute_p2p_buy_deal(buyer_id, seller_id, amount_mp)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    seller_name = get_user_display_name(seller_id)
    buyer_link = get_user_mention(buyer_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    succ_text = (
        _lf('🎉 <b>УСПЕШНАЯ СДЕЛКА</b>\n<code>·····················</code>\n{0}, ты успешно купил <b>{1} MPOINT</b> у <a href="tg://user?id={2}">{3}</a> за <b>{4} mCoin!</b>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Курс: {5} mCoin</blockquote>\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> MPOINT зачислены на твой основной баланс.', (_fmt(buyer_link, '', -1), _fmt(format_number(res['amount_mp']), '', -1), _fmt(seller_id, '', -1), _fmt(seller_name, '', -1), _fmt(format_number(res['total_mcoin']), '', -1), _fmt(format_number(res['rate']), '', -1)))
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data=f"p2p_rate_{res['deal_id']}_{seller_id}_1", icon_custom_emoji_id="5393194986252542669", style="success"),
                InlineKeyboardButton(text="1", callback_data=f"p2p_rate_{res['deal_id']}_{seller_id}_-1", icon_custom_emoji_id="5382261056078881010", style="danger")
            ],
            [
                InlineKeyboardButton(text=_l('В меню обмена'), callback_data="p2p_main", style="primary")
            ]
        ]
    )
    try:
        await callback.message.edit_text(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_rate_")))
@_localized
async def cb_p2p_rate_deal(callback: types.CallbackQuery):
    parts = callback.data.replace("p2p_rate_", "").split("_")
    if len(parts) < 3:
        return
    deal_id = int(parts[0])
    target_id = int(parts[1])
    delta = int(parts[2])
    rater_id = callback.from_user.id

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        cursor.execute('''
            INSERT INTO p2p_deal_ratings (deal_id, rater_id, target_id, rating_change, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (deal_id, rater_id, target_id, delta, now_str))
        if target_id == 0:
            cursor.execute("INSERT INTO p2p_accounts (user_id, rating) VALUES (0, 100) ON CONFLICT (user_id) DO UPDATE SET rating = p2p_accounts.rating + ?", (delta,))
        else:
            cursor.execute("UPDATE p2p_accounts SET rating = rating + ? WHERE user_id = ?", (delta, target_id))
        conn.commit()
        await callback.answer(_l('Спасибо за отзыв!'), show_alert=True)
    except Exception:
        await callback.answer(_l('Вы уже оставили отзыв по этой сделке!'), show_alert=True)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('В меню обмена'), callback_data="p2p_main", style="primary")]]
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass



@dp.callback_query(_inline_filter(lambda c: c.data in ["p2p_sell_list"] or c.data.startswith("p2p_sell_page_")))
@_localized
async def cb_p2p_sell_list(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    await callback.answer()
    page = 1
    if callback.data.startswith("p2p_sell_page_"):
        try:
            page = int(callback.data.replace("p2p_sell_page_", ""))
        except Exception:
            page = 1

    current_uid = callback.from_user.id
    page, total_pages, page_buyers = _get_p2p_offer_page(current_uid, page, False)

    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    sell_enabled = settings.get("official_sell_enabled", 1)
    sell_rate = settings.get("official_sell_rate", 10000)

    text = (
        _lf('<b><tg-emoji emoji-id="5834775782433492415">🔥</tg-emoji> ПРОДАТЬ MPOINT</b>\n<code>·····················</code>\n<blockquote expandable><i> ℹ️ Вы можете продать MPOINT как официальному боту, так и другим игрокам. Цена отображается уже с учётом всех параметров.</i></blockquote>\n<blockquote><tg-emoji emoji-id="5431577498364158238">📊</tg-emoji> Оф. курс продажи: <b>1 MP</b> ≈ {0} mCoin</blockquote>', (_fmt(format_number(sell_rate), '', -1),))
    )

    buttons = []
    if page == 1 and sell_enabled:
        buttons.append([
            InlineKeyboardButton(
                text=_lf('🏛 Оф. продажа • {0} m¢', (_fmt(format_number(sell_rate), '', -1),)),
                callback_data="p2p_sell_bot",
                icon_custom_emoji_id="5206607081334906820"
            )
        ])

    for b_uid, b_price, b_mcoin, b_rating in page_buyers:
        display_name = get_user_display_name(b_uid)
        buttons.append([
            InlineKeyboardButton(
                text=f"{display_name} • {format_number(b_price)} m¢",
                callback_data=f"p2p_sell_buyer_{b_uid}"
            )
        ])

    nav_row = []
    if page <= 1:
        nav_row.append(InlineKeyboardButton(text="🚫", callback_data="noop_p2p"))
    else:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"p2p_sell_page_{page-1}"))

    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop_p2p"))

    if page >= total_pages:
        nav_row.append(InlineKeyboardButton(text="🚫", callback_data="noop_p2p"))
    else:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"p2p_sell_page_{page+1}"))

    buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_main", icon_custom_emoji_id="5255703720078879038")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_sell_bot"))
@_localized
async def cb_p2p_sell_bot(callback: types.CallbackQuery):
    await callback.answer()
    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    if not settings.get("official_sell_enabled", 1):
        await callback.answer(_l('Официальная продажа сейчас отключена!'), show_alert=True)
        return

    deals_24h, mp_sold_24h = get_p2p_bot_24h_stats()
    user_u = get_user(callback.from_user.id)
    user_mp = user_u.get("mp_balance", 0) or 0
    sell_rate = settings.get("official_sell_rate", 10000)

    text = (
        _lf('<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji><b>ПРОДАТЬ MPOINT</b>\n<code>·····················</code>\n<i>👤 Покупатель: 🏛 Оф. Продажа\n💞 Рейтинг: 100%\n❇️ Доступно: ∞ mCoin\n💸 Курс: 1 MP = {0} mCoin\n·····················\n🔘 Комиссия: 0%</i>\n<blockquote><tg-emoji emoji-id="5332455502917949981">🏦</tg-emoji> <b>Продано за 24ч:</b> {1} / {2} MP</blockquote>\n<blockquote>💰 Твой баланс: <b>{3} MP</b></blockquote>\n<blockquote><i>ℹ️ Выберите количество MP или напишите в чат.</i></blockquote>', (_fmt(format_number(sell_rate), '', -1), _fmt(deals_24h, '', -1), _fmt(format_number(mp_sold_24h), '', -1), _fmt(format_number(user_mp), '', -1)))
    )

    p2p_user_action[callback.from_user.id] = "sell_bot_custom"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 MP", callback_data="p2p_sbot_1"),
                InlineKeyboardButton(text="5 MP", callback_data="p2p_sbot_5"),
                InlineKeyboardButton(text="10 MP", callback_data="p2p_sbot_10"),
            ],
            [
                InlineKeyboardButton(text="25 MP", callback_data="p2p_sbot_25"),
                InlineKeyboardButton(text="50 MP", callback_data="p2p_sbot_50"),
                InlineKeyboardButton(text="100 MP", callback_data="p2p_sbot_100"),
            ],
            [
                InlineKeyboardButton(text=_l('Все MP'), callback_data=f"p2p_sbot_{user_mp}")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_sell_list", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_sbot_")))
@_localized
async def cb_p2p_sell_bot_amount(callback: types.CallbackQuery):
    try:
        amount_mp = int(callback.data.replace("p2p_sbot_", ""))
    except Exception:
        return

    update_p2p_rate_fluctuation(force=False)
    settings = get_p2p_settings()
    sell_rate = settings.get("official_sell_rate", 10000)
    user_u = get_user(callback.from_user.id)
    user_link = get_user_mention(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))

    if user_u.get("mp_balance", 0) < amount_mp:
        shortage = amount_mp - user_u.get("mp_balance", 0)
        err_text = _lf('🚫 <i>{0}, не хватает <b>{1} MP!</b></i>', (_fmt(user_link, '', -1), _fmt(format_number(shortage), '', -1)))
        err_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_sell_bot", icon_custom_emoji_id="5255703720078879038")]]
        )
        try:
            await callback.message.edit_text(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
        except Exception:
            await callback.message.answer(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
        return

    total_mcoin = amount_mp * sell_rate
    conf_text = (
        _lf('<tg-emoji emoji-id="5452069934089641166">❓</tg-emoji> <b>ПОДТВЕРЖДЕНИЕ СДЕЛКИ</b>\n<code>·····················</code>\n<i>{0}, ты точно <b>хочешь продать {1} MPOINT</b> за <b>{2} mCoin?</b></i>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Оф. курс: {3} mCoin</blockquote>\n<blockquote>🔘 Комиссия: 0% = 0 mCoin</blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(amount_mp), '', -1), _fmt(format_number(total_mcoin), '', -1), _fmt(format_number(sell_rate), '', -1)))
    )
    conf_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('Да ✅'), callback_data=f"p2p_conf_sbot_{amount_mp}", style="success"),
                InlineKeyboardButton(text=_l('Отмена 💢'), callback_data="p2p_cancel_buy", style="danger")
            ]
        ]
    )
    try:
        await callback.message.edit_text(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_conf_sbot_")))
@_localized
async def cb_p2p_confirm_sell_bot(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    try:
        amount_mp = int(callback.data.replace("p2p_conf_sbot_", ""))
    except Exception:
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    ok, res = execute_p2p_sell_to_bot(callback.from_user.id, amount_mp)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    user_link = get_user_mention(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    succ_text = (
        _lf('🎉 <b>УСПЕШНАЯ ПРОДАЖА</b>\n<code>·····················</code>\n{0}, ты успешно продал <b>{1} MPOINT</b> за <b>{2} mCoin!</b>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Курс: {3} mCoin</blockquote>\n<tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> Баланс: <b>{4} mCoin</b>', (_fmt(user_link, '', -1), _fmt(format_number(res['amount_mp']), '', -1), _fmt(format_number(res['total_mcoin']), '', -1), _fmt(format_number(res['rate']), '', -1), _fmt(format_number(get_user(callback.from_user.id)['balance']), '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data=f"p2p_rate_{res['deal_id']}_0_1", icon_custom_emoji_id="5393194986252542669", style="success"),
                InlineKeyboardButton(text="1", callback_data=f"p2p_rate_{res['deal_id']}_0_-1", icon_custom_emoji_id="5382261056078881010", style="danger")
            ],
            [
                InlineKeyboardButton(text=_l('В меню обмена'), callback_data="p2p_main", style="primary")
            ]
        ]
    )
    try:
        await callback.message.edit_text(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_sell_buyer_")))
@_localized
async def cb_p2p_sell_buyer(callback: types.CallbackQuery):
    try:
        buyer_id = int(callback.data.replace("p2p_sell_buyer_", ""))
    except Exception:
        await callback.answer(_l('Ошибка!'), show_alert=True)
        return

    buyer_p2p = get_p2p_account(buyer_id)
    if not buyer_p2p["buy_order_active"] or buyer_p2p["mcoin_balance"] <= 0 or buyer_p2p["buy_price"] <= 0:
        await callback.answer(_l('У этого покупателя больше нет активных заявок!'), show_alert=True)
        return

    display_name = get_user_display_name(buyer_id)
    max_mp_buyer_can_buy = buyer_p2p["mcoin_balance"] // buyer_p2p["buy_price"]
    seller_u = get_user(callback.from_user.id)
    seller_mp = seller_u.get("mp_balance", 0) or 0

    text = (
        _lf('<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji><b>ПРОДАТЬ MPOINT</b>\n<code>·····················</code>\n<i>👤 Покупатель: <a href="tg://user?id={0}">{1}</a>\n💞 Рейтинг: {2}\n❇️ Готов купить: до {3} MP\n💸 Курс: 1 MP = {4} mCoin\n·····················\n🔘 Комиссия: 0%</i>\n<blockquote><i>ℹ️ Напишите в ответ на это сообщение, сколько вы хотите продать, или выберите один из вариантов ниже.</i></blockquote>', (_fmt(buyer_id, '', -1), _fmt(display_name, '', -1), _fmt(buyer_p2p['rating'], '', -1), _fmt(format_number(max_mp_buyer_can_buy), '', -1), _fmt(format_number(buyer_p2p['buy_price']), '', -1)))
    )

    p2p_user_action[callback.from_user.id] = f"sell_buyer_{buyer_id}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 MP", callback_data=f"p2p_sbuy_{buyer_id}_1"),
                InlineKeyboardButton(text="5 MP", callback_data=f"p2p_sbuy_{buyer_id}_5"),
                InlineKeyboardButton(text="10 MP", callback_data=f"p2p_sbuy_{buyer_id}_10"),
            ],
            [
                InlineKeyboardButton(text="25 MP", callback_data=f"p2p_sbuy_{buyer_id}_25"),
                InlineKeyboardButton(text="50 MP", callback_data=f"p2p_sbuy_{buyer_id}_50"),
                InlineKeyboardButton(text="100 MP", callback_data=f"p2p_sbuy_{buyer_id}_100"),
            ],
            [
                InlineKeyboardButton(text=_l('Все мои MP'), callback_data=f"p2p_sbuy_{buyer_id}_{min(seller_mp, max_mp_buyer_can_buy)}")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_sell_list", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_sbuy_")))
@_localized
async def cb_p2p_sell_buyer_amount(callback: types.CallbackQuery):
    parts = callback.data.replace("p2p_sbuy_", "").split("_")
    if len(parts) < 2:
        return
    buyer_id = int(parts[0])
    amount_mp = int(parts[1])

    buyer_p2p = get_p2p_account(buyer_id)
    seller_id = callback.from_user.id
    seller_u = get_user(seller_id)
    seller_link = get_user_mention(seller_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))

    if seller_u.get("mp_balance", 0) < amount_mp:
        shortage = amount_mp - seller_u.get("mp_balance", 0)
        err_text = _lf('🚫 <i>{0}, не хватает <b>{1} MP!</b></i>', (_fmt(seller_link, '', -1), _fmt(format_number(shortage), '', -1)))
        err_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data=f"p2p_sell_buyer_{buyer_id}", icon_custom_emoji_id="5255703720078879038")]]
        )
        try:
            await callback.message.edit_text(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
        except Exception:
            await callback.message.answer(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
        return

    total_mcoin = amount_mp * buyer_p2p["buy_price"]
    conf_text = (
        _lf('<tg-emoji emoji-id="5452069934089641166">❓</tg-emoji> <b>ПОДТВЕРЖДЕНИЕ СДЕЛКИ</b>\n<code>·····················</code>\n<i>{0}, ты точно <b>хочешь продать {1} MPOINT</b> за <b>{2} mCoin?</b></i>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Курс: {3} mCoin</blockquote>\n<blockquote>🔘 Комиссия: 0% = 0 mCoin</blockquote>', (_fmt(seller_link, '', -1), _fmt(format_number(amount_mp), '', -1), _fmt(format_number(total_mcoin), '', -1), _fmt(format_number(buyer_p2p['buy_price']), '', -1)))
    )
    conf_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('Да ✅'), callback_data=f"p2p_conf_sbuy_{buyer_id}_{amount_mp}", style="success"),
                InlineKeyboardButton(text=_l('Отмена 💢'), callback_data="p2p_cancel_buy", style="danger")
            ]
        ]
    )
    try:
        await callback.message.edit_text(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_conf_sbuy_")))
@_localized
async def cb_p2p_confirm_sell_buyer(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    parts = callback.data.replace("p2p_conf_sbuy_", "").split("_")
    if len(parts) < 2:
        return
    buyer_id = int(parts[0])
    amount_mp = int(parts[1])

    seller_id = callback.from_user.id
    ok, res = execute_p2p_sell_to_buyer(seller_id, buyer_id, amount_mp)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    buyer_name = get_user_display_name(buyer_id)
    seller_link = get_user_mention(seller_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    succ_text = (
        _lf('🎉 <b>УСПЕШНАЯ СДЕЛКА</b>\n<code>·····················</code>\n{0}, ты успешно продал <b>{1} MPOINT</b> покупателю <a href="tg://user?id={2}">{3}</a> за <b>{4} mCoin!</b>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Курс: {5} mCoin</blockquote>\n<tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> Баланс: <b>{6} mCoin</b>', (_fmt(seller_link, '', -1), _fmt(format_number(res['amount_mp']), '', -1), _fmt(buyer_id, '', -1), _fmt(buyer_name, '', -1), _fmt(format_number(res['total_mcoin']), '', -1), _fmt(format_number(res['rate']), '', -1), _fmt(format_number(get_user(seller_id)['balance']), '', -1)))
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data=f"p2p_rate_{res['deal_id']}_{buyer_id}_1", icon_custom_emoji_id="5393194986252542669", style="success"),
                InlineKeyboardButton(text="1", callback_data=f"p2p_rate_{res['deal_id']}_{buyer_id}_-1", icon_custom_emoji_id="5382261056078881010", style="danger")
            ],
            [
                InlineKeyboardButton(text=_l('В меню обмена'), callback_data="p2p_main", style="primary")
            ]
        ]
    )
    try:
        await callback.message.edit_text(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)



@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_deposit"))
@_localized
async def cb_p2p_deposit(callback: types.CallbackQuery):
    await callback.answer()
    text = (
        _l('📥 <b>ПОПОЛНЕНИЕ БАЛАНСА ОБМЕННИКА</b>\n<code>·····················</code>\n<i>Выберите, какую валюту вы хотите перевести с основного баланса на баланс обменника:</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="mCoin 💰", callback_data="p2p_dep_mcoin"),
                InlineKeyboardButton(text="MPOINT 💎", callback_data="p2p_dep_mpoint")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_manage", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_dep_mcoin"))
@_localized
async def cb_p2p_dep_mcoin(callback: types.CallbackQuery):
    await callback.answer()
    p2p_user_action[callback.from_user.id] = "dep_mcoin"
    user_u = get_user(callback.from_user.id)
    bal = user_u.get("balance", 0)
    p2p = get_p2p_account(callback.from_user.id)
    today_str = get_msk_today_str()
    is_first = (p2p["last_deposit_date"] != today_str)
    comm_str = _l('<b>0% (1-е пополнение за день)</b>') if is_first else "<b>1.5%</b>"

    text = (
        _lf('📥 <b>ПОПОЛНЕНИЕ mCoin</b>\n<code>·····················</code>\n💰 Основной баланс: <b>{0} m¢</b>\n🔘 Комиссия: {1}\n\n<i>Напишите в ответ или в чат сумму mCoin для пополнения, или выберите вариант:</i>', (_fmt(format_number(bal), '', -1), _fmt(comm_str, '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="100k", callback_data="p2p_dmc_100000"),
                InlineKeyboardButton(text="500k", callback_data="p2p_dmc_500000"),
                InlineKeyboardButton(text="1M", callback_data="p2p_dmc_1000000")
            ],
            [
                InlineKeyboardButton(text="5M", callback_data="p2p_dmc_5000000"),
                InlineKeyboardButton(text="10M", callback_data="p2p_dmc_10000000"),
                InlineKeyboardButton(text=_l('Все m¢'), callback_data=f"p2p_dmc_{bal}")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_deposit", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_dmc_")))
@_localized
async def cb_p2p_dep_mcoin_amount(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    try:
        amount = int(callback.data.replace("p2p_dmc_", ""))
    except Exception:
        return
    ok, res = deposit_to_p2p_mcoin(callback.from_user.id, amount)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    user_link = get_user_mention(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    comm_str = _l('<blockquote><b>🆓 Комиссия не списана (1-е пополнение за день)</b></blockquote>') if res["is_first"] else _lf('<blockquote><b>🔘 Комиссия: 1,5% ({0} mCoin)</b></blockquote>', (_fmt(format_number(res['fee']), '', -1),))
    succ_text = (
        _lf('✅ <b>УСПЕШНОЕ ПОПОЛНЕНИЕ</b>\n<code>·····················</code>\n{0}, твои <b>{1} mCoin</b> зачислены на баланс обменника.\n{2}\n<blockquote>💰 mCoin (обменник): <b>{3}</b></blockquote>\n<blockquote>💎 MPOINT (обменник): <b>{4}</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(comm_str, '', -1), _fmt(format_number(res['mcoin_balance']), '', -1), _fmt(format_number(res['mp_balance']), '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
    )
    try:
        await callback.message.edit_text(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_dep_mpoint"))
@_localized
async def cb_p2p_dep_mpoint(callback: types.CallbackQuery):
    await callback.answer()
    p2p_user_action[callback.from_user.id] = "dep_mpoint"
    user_u = get_user(callback.from_user.id)
    bal = user_u.get("mp_balance", 0)

    text = (
        _lf('📥 <b>ПОПОЛНЕНИЕ MPOINT</b>\n<code>·····················</code>\n💎 Основной баланс: <b>{0} MP</b>\n🔘 Комиссия: <b>0%</b>\n\n<i>Напишите в ответ или в чат количество MPOINT для пополнения, или выберите вариант:</i>', (_fmt(format_number(bal), '', -1),))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="5 MP", callback_data="p2p_dmp_5"),
                InlineKeyboardButton(text="10 MP", callback_data="p2p_dmp_10"),
                InlineKeyboardButton(text="25 MP", callback_data="p2p_dmp_25")
            ],
            [
                InlineKeyboardButton(text="50 MP", callback_data="p2p_dmp_50"),
                InlineKeyboardButton(text="100 MP", callback_data="p2p_dmp_100"),
                InlineKeyboardButton(text=_l('Все MP'), callback_data=f"p2p_dmp_{bal}")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_deposit", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_dmp_")))
@_localized
async def cb_p2p_dep_mpoint_amount(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    try:
        amount = int(callback.data.replace("p2p_dmp_", ""))
    except Exception:
        return
    ok, res = deposit_to_p2p_mpoint(callback.from_user.id, amount)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    user_link = get_user_mention(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    succ_text = (
        _lf('✅ <b>УСПЕШНОЕ ПОПОЛНЕНИЕ</b>\n<code>·····················</code>\n{0}, твои <b>{1} MPOINT</b> зачислены на баланс обменника.\n<blockquote><b>🆓 Комиссия не списана</b></blockquote>\n<blockquote>💰 mCoin (обменник): <b>{2}</b></blockquote>\n<blockquote>💎 MPOINT (обменник): <b>{3}</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(format_number(res['mcoin_balance']), '', -1), _fmt(format_number(res['mp_balance']), '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
    )
    try:
        await callback.message.edit_text(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_withdraw"))
@_localized
async def cb_p2p_withdraw(callback: types.CallbackQuery):
    await callback.answer()
    text = (
        _l('📤 <b>ВЫВОД С БАЛАНСА ОБМЕННИКА</b>\n<code>·····················</code>\n<i>Выберите, какую валюту вы хотите вывести с обменника на основной баланс:</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="mCoin 💰", callback_data="p2p_wth_mcoin"),
                InlineKeyboardButton(text="MPOINT 💎", callback_data="p2p_wth_mpoint")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_manage", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_wth_mcoin"))
@_localized
async def cb_p2p_wth_mcoin(callback: types.CallbackQuery):
    await callback.answer()
    p2p_user_action[callback.from_user.id] = "wth_mcoin"
    p2p = get_p2p_account(callback.from_user.id)
    bal = p2p["mcoin_balance"]

    text = (
        _lf('📤 <b>ВЫВОД mCoin</b>\n<code>·····················</code>\n💰 На балансе обменника: <b>{0} m¢</b>\n\n<i>Напишите в ответ или в чат сумму mCoin для вывода, или выберите вариант:</i>', (_fmt(format_number(bal), '', -1),))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="100k", callback_data="p2p_wmc_100000"),
                InlineKeyboardButton(text="500k", callback_data="p2p_wmc_500000"),
                InlineKeyboardButton(text="1M", callback_data="p2p_wmc_1000000")
            ],
            [
                InlineKeyboardButton(text="5M", callback_data="p2p_wmc_5000000"),
                InlineKeyboardButton(text="10M", callback_data="p2p_wmc_10000000"),
                InlineKeyboardButton(text=_l('Все m¢'), callback_data=f"p2p_wmc_{bal}")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_withdraw", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_wmc_")))
@_localized
async def cb_p2p_wth_mcoin_amount(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    try:
        amount = int(callback.data.replace("p2p_wmc_", ""))
    except Exception:
        return
    ok, res = withdraw_from_p2p_mcoin(callback.from_user.id, amount)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    user_link = get_user_mention(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    succ_text = (
        _lf('✅ <b>УСПЕШНЫЙ ВЫВОД</b>\n<code>·····················</code>\n{0}, твои <b>{1} mCoin</b> выведены на основной баланс.\n<blockquote>💰 mCoin (обменник): <b>{2}</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(format_number(res['mcoin_balance']), '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
    )
    try:
        await callback.message.edit_text(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_wth_mpoint"))
@_localized
async def cb_p2p_wth_mpoint(callback: types.CallbackQuery):
    await callback.answer()
    p2p_user_action[callback.from_user.id] = "wth_mpoint"
    p2p = get_p2p_account(callback.from_user.id)
    bal = p2p["mp_balance"]

    text = (
        _lf('📤 <b>ВЫВОД MPOINT</b>\n<code>·····················</code>\n💎 На балансе обменника: <b>{0} MP</b>\n\n<i>Напишите в ответ или в чат количество MPOINT для вывода, или выберите вариант:</i>', (_fmt(format_number(bal), '', -1),))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="5 MP", callback_data="p2p_wmp_5"),
                InlineKeyboardButton(text="10 MP", callback_data="p2p_wmp_10"),
                InlineKeyboardButton(text="25 MP", callback_data="p2p_wmp_25")
            ],
            [
                InlineKeyboardButton(text="50 MP", callback_data="p2p_wmp_50"),
                InlineKeyboardButton(text="100 MP", callback_data="p2p_wmp_100"),
                InlineKeyboardButton(text=_l('Все MP'), callback_data=f"p2p_wmp_{bal}")
            ],
            [
                InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_withdraw", icon_custom_emoji_id="5255703720078879038")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("p2p_wmp_")))
@_localized
async def cb_p2p_wth_mpoint_amount(callback: types.CallbackQuery):
    p2p_user_action.pop(callback.from_user.id, None)
    try:
        amount = int(callback.data.replace("p2p_wmp_", ""))
    except Exception:
        return
    ok, res = withdraw_from_p2p_mpoint(callback.from_user.id, amount)
    if not ok:
        await callback.answer(_lf('Ошибка: {0}', (_fmt(res, '', -1),)), show_alert=True)
        return

    user_link = get_user_mention(callback.from_user.id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    succ_text = (
        _lf('✅ <b>УСПЕШНЫЙ ВЫВОД</b>\n<code>·····················</code>\n{0}, твои <b>{1} MPOINT</b> выведены на основной баланс.\n<blockquote>💎 MPOINT (обменник): <b>{2}</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(amount), '', -1), _fmt(format_number(res['mp_balance']), '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
    )
    try:
        await callback.message.edit_text(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)



@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_set_sell_price"))
@_localized
async def cb_p2p_set_sell_price(callback: types.CallbackQuery):
    await callback.answer()
    p2p_user_action[callback.from_user.id] = "set_sell_price"
    text = (
        _l('💰 <b>ИЗМЕНИТЬ КУРС ПРОДАЖИ</b>\n<code>·····················</code>\n<i>Напишите новый курс продажи (сколько mCoin вы хотите получать за 1 MP, например: <b>15000</b> или <b>15.000</b>):</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_manage", icon_custom_emoji_id="5255703720078879038")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "p2p_set_buy_price"))
@_localized
async def cb_p2p_set_buy_price(callback: types.CallbackQuery):
    await callback.answer()
    p2p_user_action[callback.from_user.id] = "set_buy_price"
    text = (
        _l('💳 <b>ИЗМЕНИТЬ КУРС ПОКУПКИ</b>\n<code>·····················</code>\n<i>Напишите новый курс покупки (сколько mCoin вы готовы платить за 1 MP, например: <b>12000</b> или <b>12.000</b>):</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_manage", icon_custom_emoji_id="5255703720078879038")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "noop_p2p"))
@_localized
async def cb_noop_p2p(callback: types.CallbackQuery):
    await callback.answer()



@dp.callback_query(_inline_filter(lambda c: c.data == "sexch_refresh"))
@_localized
async def cb_sexch_refresh(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    admin_sexchange_state.pop(callback.from_user.id, None)
    await callback.answer(_l('Обновлено!'))
    text, kb = render_sexchange_menu()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "sexch_tog_sell"))
@_localized
async def cb_sexch_tog_sell(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    settings = get_p2p_settings()
    new_val = 0 if settings.get("official_sell_enabled", 1) else 1
    cursor.execute("UPDATE p2p_settings SET official_sell_enabled = ? WHERE id = 1", (new_val,))
    conn.commit()
    _admin_log(
        callback.from_user,
        "p2p_settings",
        details={"setting": "official_sell_enabled", "enabled": bool(new_val)},
    )
    await callback.answer(_l('Статус оф. продажи изменен!'))
    text, kb = render_sexchange_menu()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "sexch_tog_buy"))
@_localized
async def cb_sexch_tog_buy(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    settings = get_p2p_settings()
    new_val = 0 if settings.get("official_buy_enabled", 1) else 1
    cursor.execute("UPDATE p2p_settings SET official_buy_enabled = ? WHERE id = 1", (new_val,))
    conn.commit()
    _admin_log(
        callback.from_user,
        "p2p_settings",
        details={"setting": "official_buy_enabled", "enabled": bool(new_val)},
    )
    await callback.answer(_l('Статус оф. покупки изменен!'))
    text, kb = render_sexchange_menu()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "sexch_reroll"))
@_localized
async def cb_sexch_reroll(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    ok, res = update_p2p_rate_fluctuation(force=True)
    if ok:
        _admin_log(
            callback.from_user,
            "p2p_settings",
            details={"setting": "reroll", "value": format_number(res["official_sell_rate"])},
        )
    await callback.answer(_lf('Новый курс: {0} mCoin!', (_fmt(format_number(res['official_sell_rate']), '', -1),)), show_alert=True)
    text, kb = render_sexchange_menu()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "sexch_set_sell"))
@_localized
async def cb_sexch_set_sell(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    admin_sexchange_state[callback.from_user.id] = "set_sell_rate"
    await callback.answer()
    text = (
        _l('✏️ <b>ЗАДАТЬ КУРС ОФ. ПРОДАЖИ</b>\n<code>································</code>\n<i>Напишите новый фиксированный курс продажи для бота (например: <b>15000</b> или <b>15.000</b>):</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Назад в /sexchange'), callback_data="sexch_refresh")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "sexch_set_buy"))
@_localized
async def cb_sexch_set_buy(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    admin_sexchange_state[callback.from_user.id] = "set_buy_rate"
    await callback.answer()
    text = (
        _l('✏️ <b>ЗАДАТЬ КУРС ОФ. ПОКУПКИ</b>\n<code>································</code>\n<i>Напишите новый фиксированный курс покупки для бота (например: <b>15000</b> или <b>15.000</b>):</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Назад в /sexchange'), callback_data="sexch_refresh")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "sexch_set_range"))
@_localized
async def cb_sexch_set_range(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    admin_sexchange_state[callback.from_user.id] = "set_range"
    await callback.answer()
    text = (
        _l('📊 <b>ИЗМЕНИТЬ ДИАПАЗОН СКАЧКОВ КУРСА</b>\n<code>································</code>\n<i>Напишите минимальный и максимальный курс через дефис или пробел (например: <b>7000-29000</b> или <b>7.000-29.000</b>):</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Назад в /sexchange'), callback_data="sexch_refresh")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "sexch_set_interval"))
@_localized
async def cb_sexch_set_interval(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    admin_sexchange_state[callback.from_user.id] = "set_interval"
    await callback.answer()
    text = (
        _l('⏱ <b>ИЗМЕНИТЬ ИНТЕРВАЛ СМЕНЫ КУРСА</b>\n<code>································</code>\n<i>Напишите интервал в минутах (например: <b>150</b> для 2ч 30мин):</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_l('Назад в /sexchange'), callback_data="sexch_refresh")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)



@dp.message(_inline_filter(lambda message: message.text and (
    message.from_user.id in admin_sexchange_state or
    message.from_user.id in p2p_user_action or
    (message.reply_to_message and (
        _p2p_reply_action(message.reply_to_message) is not None or
        "КУПИТЬ MPOINT" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "ПРОДАТЬ MPOINT" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "Сколько mCoin пополняем?" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "Сколько MPOINT пополняем?" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "ПОПОЛНЕНИЕ mCoin" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "ПОПОЛНЕНИЕ MPOINT" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "ВЫВОД mCoin" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "ВЫВОД MPOINT" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "Сколько mCoin выводим?" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "Сколько MPOINT выводим?" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "ИЗМЕНИТЬ КУРС ПРОДАЖИ" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") or
        "ИЗМЕНИТЬ КУРС ПОКУПКИ" in (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "")
    ))
)))
@_localized
async def process_p2p_and_admin_reply_message(message: types.Message):
    if message.chat.type != "private":
        return
    user_id = message.from_user.id
    raw_text = message.text.strip()
    rep_text = (_canonical_prompt(message.reply_to_message.text or "") or _canonical_prompt(message.reply_to_message.caption or "") or "") if message.reply_to_message else ""
    user_action = _p2p_reply_action(message.reply_to_message) or p2p_user_action.get(user_id)
    admin_action = admin_sexchange_state.get(user_id)
    if user_action:
        rep_text = ""

    if admin_action and user_id in ADMINS:
        if admin_action == "set_sell_rate":
            val = parse_amount(raw_text)
            if val is None or val <= 0:
                await message.reply(_l('<i>Курс должен быть положительным числом!</i>'), parse_mode=ParseMode.HTML)
                return
            cursor.execute("UPDATE p2p_settings SET official_sell_rate = ? WHERE id = 1", (val,))
            conn.commit()
            _admin_log(
                message.from_user,
                "p2p_settings",
                details={"setting": "official_sell_rate", "value": format_number(val)},
            )
            admin_sexchange_state.pop(user_id, None)
            succ_text = _lf('✅ <i>Официальный курс продажи установлен: <b>1 MP = {0} mCoin</b></i>', (_fmt(format_number(val), '', -1),))
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('В меню /sexchange'), callback_data="sexch_refresh")]])
            await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if admin_action == "set_buy_rate":
            val = parse_amount(raw_text)
            if val is None or val <= 0:
                await message.reply(_l('<i>Курс должен быть положительным числом!</i>'), parse_mode=ParseMode.HTML)
                return
            cursor.execute("UPDATE p2p_settings SET official_buy_rate = ? WHERE id = 1", (val,))
            conn.commit()
            _admin_log(
                message.from_user,
                "p2p_settings",
                details={"setting": "official_buy_rate", "value": format_number(val)},
            )
            admin_sexchange_state.pop(user_id, None)
            succ_text = _lf('✅ <i>Официальный курс покупки установлен: <b>1 MP = {0} mCoin</b></i>', (_fmt(format_number(val), '', -1),))
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('В меню /sexchange'), callback_data="sexch_refresh")]])
            await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if admin_action == "set_range":
            cleaned = raw_text.replace("–", "-").replace("—", "-").replace(" ", "-")
            parts = [p for p in cleaned.split("-") if p]
            if len(parts) >= 2:
                r_min = parse_amount(parts[0])
                r_max = parse_amount(parts[1])
                if r_min and r_max and r_min > 0 and r_max > r_min:
                    cursor.execute("UPDATE p2p_settings SET rate_min = ?, rate_max = ? WHERE id = 1", (r_min, r_max))
                    conn.commit()
                    _admin_log(
                        message.from_user,
                        "p2p_settings",
                        details={"setting": "rate_range", "value": f"{format_number(r_min)}-{format_number(r_max)}"},
                    )
                    admin_sexchange_state.pop(user_id, None)
                    succ_text = _lf('✅ <i>Диапазон скачков курса успешно установлен: <b>{0} — {1} mCoin</b></i>', (_fmt(format_number(r_min), '', -1), _fmt(format_number(r_max), '', -1)))
                    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('В меню /sexchange'), callback_data="sexch_refresh")]])
                    await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
                    return
            await message.reply(_l('<i>Введите диапазон в формате: <b>7000-29000</b> или <b>7.000-29.000</b> (мин &lt; макс)!</i>'), parse_mode=ParseMode.HTML)
            return

        if admin_action == "set_interval":
            try:
                mins = int(raw_text)
                if mins < 1:
                    raise ValueError()
                cursor.execute("UPDATE p2p_settings SET interval_minutes = ? WHERE id = 1", (mins,))
                conn.commit()
                _admin_log(
                    message.from_user,
                    "p2p_settings",
                    details={"setting": "interval_minutes", "value": str(mins)},
                )
                admin_sexchange_state.pop(user_id, None)
                succ_text = _lf('✅ <i>Интервал смены курса установлен: <b>{0} мин. ({1}ч {2}м)</b></i>', (_fmt(mins, '', -1), _fmt(mins // 60, '', -1), _fmt(mins % 60, '', -1)))
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('В меню /sexchange'), callback_data="sexch_refresh")]])
                await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
                return
            except Exception:
                await message.reply(_l('<i>Интервал должен быть положительным числом минут (например: 150)!</i>'), parse_mode=ParseMode.HTML)
                return

    raw_amount = parse_amount(raw_text)

    if user_action == "set_sell_price" or "ИЗМЕНИТЬ КУРС ПРОДАЖИ" in rep_text:
        if raw_amount is None or raw_amount <= 0:
            await message.reply(_l('<i>Курс должен быть положительным числом!</i>'), parse_mode=ParseMode.HTML)
            return
        p2p_user_action.pop(user_id, None)
        cursor.execute("UPDATE p2p_accounts SET sell_price = ? WHERE user_id = ?", (raw_amount, user_id))
        conn.commit()
        succ_text = _lf('✅ <i>Курс продажи успешно установлен: <b>1 MP = {0} mCoin</b></i>', (_fmt(format_number(raw_amount), '', -1),))
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
        )
        await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if user_action == "set_buy_price" or "ИЗМЕНИТЬ КУРС ПОКУПКИ" in rep_text:
        if raw_amount is None or raw_amount <= 0:
            await message.reply(_l('<i>Курс должен быть положительным числом!</i>'), parse_mode=ParseMode.HTML)
            return
        p2p_user_action.pop(user_id, None)
        cursor.execute("UPDATE p2p_accounts SET buy_price = ? WHERE user_id = ?", (raw_amount, user_id))
        conn.commit()
        succ_text = _lf('✅ <i>Курс покупки успешно установлен: <b>{0} mCoin = 1 MP</b></i>', (_fmt(format_number(raw_amount), '', -1),))
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
        )
        await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if user_action == "dep_mcoin" or "ПОПОЛНЕНИЕ mCoin" in rep_text or "Сколько mCoin пополняем?" in rep_text:
        if raw_amount is None or raw_amount <= 0:
            await message.reply(_l('<i>Сумма должна быть положительным числом!</i>'), parse_mode=ParseMode.HTML)
            return
        p2p_user_action.pop(user_id, None)
        ok, res = deposit_to_p2p_mcoin(user_id, raw_amount)
        if not ok:
            await message.reply(_lf('<i>Ошибка: {0}</i>', (_fmt(res, '', -1),)), parse_mode=ParseMode.HTML)
            return
        user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
        comm_str = _l('<blockquote><b>🆓 Комиссия не списана (1-е пополнение за день)</b></blockquote>') if res["is_first"] else _lf('<blockquote><b>🔘 Комиссия: 1,5% ({0} mCoin)</b></blockquote>', (_fmt(format_number(res['fee']), '', -1),))
        succ_text = (
            _lf('✅ <b>УСПЕШНОЕ ПОПОЛНЕНИЕ</b>\n<code>·····················</code>\n{0}, твои <b>{1} mCoin</b> зачислены на баланс обменника.\n{2}\n<blockquote>💰 mCoin (обменник): <b>{3}</b></blockquote>\n<blockquote>💎 MPOINT (обменник): <b>{4}</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(comm_str, '', -1), _fmt(format_number(res['mcoin_balance']), '', -1), _fmt(format_number(res['mp_balance']), '', -1)))
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
        )
        await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if user_action == "dep_mpoint" or "ПОПОЛНЕНИЕ MPOINT" in rep_text or "Сколько MPOINT пополняем?" in rep_text:
        if raw_amount is None or raw_amount <= 0:
            await message.reply(_l('<i>Сумма должна быть положительным числом!</i>'), parse_mode=ParseMode.HTML)
            return
        p2p_user_action.pop(user_id, None)
        ok, res = deposit_to_p2p_mpoint(user_id, raw_amount)
        if not ok:
            await message.reply(_lf('<i>Ошибка: {0}</i>', (_fmt(res, '', -1),)), parse_mode=ParseMode.HTML)
            return
        user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
        succ_text = (
            _lf('✅ <b>УСПЕШНОЕ ПОПОЛНЕНИЕ</b>\n<code>·····················</code>\n{0}, твои <b>{1} MPOINT</b> зачислены на баланс обменника.\n<blockquote><b>🆓 Комиссия не списана</b></blockquote>\n<blockquote>💰 mCoin (обменник): <b>{2}</b></blockquote>\n<blockquote>💎 MPOINT (обменник): <b>{3}</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(format_number(res['mcoin_balance']), '', -1), _fmt(format_number(res['mp_balance']), '', -1)))
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
        )
        await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if user_action == "wth_mcoin" or "ВЫВОД mCoin" in rep_text or "Сколько mCoin выводим?" in rep_text:
        if raw_amount is None or raw_amount <= 0:
            await message.reply(_l('<i>Сумма должна быть положительным числом!</i>'), parse_mode=ParseMode.HTML)
            return
        p2p_user_action.pop(user_id, None)
        ok, res = withdraw_from_p2p_mcoin(user_id, raw_amount)
        if not ok:
            await message.reply(_lf('<i>Ошибка: {0}</i>', (_fmt(res, '', -1),)), parse_mode=ParseMode.HTML)
            return
        user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
        succ_text = (
            _lf('✅ <b>УСПЕШНЫЙ ВЫВОД</b>\n<code>·····················</code>\n{0}, твои <b>{1} mCoin</b> выведены на основной баланс.\n<blockquote>💰 mCoin (обменник): <b>{2}</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(format_number(res['mcoin_balance']), '', -1)))
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
        )
        await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if user_action == "wth_mpoint" or "ВЫВОД MPOINT" in rep_text or "Сколько MPOINT выводим?" in rep_text:
        if raw_amount is None or raw_amount <= 0:
            await message.reply(_l('<i>Сумма должна быть положительным числом!</i>'), parse_mode=ParseMode.HTML)
            return
        p2p_user_action.pop(user_id, None)
        ok, res = withdraw_from_p2p_mpoint(user_id, raw_amount)
        if not ok:
            await message.reply(_lf('<i>Ошибка: {0}</i>', (_fmt(res, '', -1),)), parse_mode=ParseMode.HTML)
            return
        user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
        succ_text = (
            _lf('✅ <b>УСПЕШНЫЙ ВЫВОД</b>\n<code>·····················</code>\n{0}, твои <b>{1} MPOINT</b> выведены на основной баланс.\n<blockquote>💎 MPOINT (обменник): <b>{2}</b></blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(format_number(res['mp_balance']), '', -1)))
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_l('Управление обменом'), callback_data="p2p_manage", style="primary")]]
        )
        await message.reply(succ_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if user_action == "buy_bot_custom" or ("КУПИТЬ MPOINT" in rep_text and "Оф. Покупка" in rep_text):
        if raw_amount is None or raw_amount <= 0:
            return
        p2p_user_action.pop(user_id, None)
        update_p2p_rate_fluctuation(force=False)
        settings = get_p2p_settings()
        buy_rate = settings.get("official_buy_rate", 10000)
        user_u = get_user(user_id)
        user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
        total_cost = raw_amount * buy_rate

        if user_u["balance"] < total_cost:
            shortage = total_cost - user_u["balance"]
            err_text = _lf('🚫 <i>{0}, не хватает <b>{1} mCoin!</b></i>', (_fmt(user_link, '', -1), _fmt(format_number(shortage), '', -1)))
            err_kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_buy_bot", icon_custom_emoji_id="5255703720078879038")]]
            )
            await message.reply(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
            return

        conf_text = (
            _lf('<tg-emoji emoji-id="5452069934089641166">❓</tg-emoji> <b>ПОДТВЕРЖДЕНИЕ ПОКУПКИ</b>\n<code>·····················</code>\n<i>{0}, ты точно <b>хочешь купить {1} MPOINT</b> за <b>{2} mCoin?</b></i>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Оф. курс: {3} mCoin</blockquote>\n<blockquote>🔘 Комиссия: 0% = 0 mCoin</blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(format_number(total_cost), '', -1), _fmt(format_number(buy_rate), '', -1)))
        )
        conf_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=_l('Да ✅'), callback_data=f"p2p_conf_bbot_{raw_amount}", style="success"),
                    InlineKeyboardButton(text=_l('Отмена 💢'), callback_data="p2p_cancel_buy", style="danger")
                ]
            ]
        )
        await message.reply(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)
        return

    if (user_action and user_action.startswith("buy_seller_")) or ("КУПИТЬ MPOINT" in rep_text and "Продавец:" in rep_text):
        if raw_amount is None or raw_amount <= 0:
            return
        if user_action and user_action.startswith("buy_seller_"):
            seller_id = int(user_action.replace("buy_seller_", ""))
        else:
            m = re.search(r'tg://user\?id=(\d+)', rep_text)
            if not m:
                return
            seller_id = int(m.group(1))

        p2p_user_action.pop(user_id, None)
        seller_p2p = get_p2p_account(seller_id)
        buyer_u = get_user(user_id)
        buyer_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))

        total_cost = raw_amount * seller_p2p["sell_price"]
        if buyer_u["balance"] < total_cost:
            shortage = total_cost - buyer_u["balance"]
            err_text = _lf('🚫 <i>{0}, не хватает <b>{1} mCoin!</b></i>', (_fmt(buyer_link, '', -1), _fmt(format_number(shortage), '', -1)))
            err_kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data=f"p2p_buy_seller_{seller_id}", icon_custom_emoji_id="5255703720078879038")]]
            )
            await message.reply(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
            return

        conf_text = (
            _lf('<tg-emoji emoji-id="5452069934089641166">❓</tg-emoji> <b>ПОДТВЕРЖДЕНИЕ СДЕЛКИ</b>\n<code>·····················</code>\n<i>{0}, ты точно <b>хочешь купить {1} MPOINT</b> за <b>{2} mCoin?</b></i>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Курс: {3} mCoin</blockquote>\n<blockquote>🔘 Комиссия: 0% = 0 mCoin</blockquote>', (_fmt(buyer_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(format_number(total_cost), '', -1), _fmt(format_number(seller_p2p['sell_price']), '', -1)))
        )
        conf_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=_l('Да ✅'), callback_data=f"p2p_conf_buy_{seller_id}_{raw_amount}", style="success"),
                    InlineKeyboardButton(text=_l('Отмена 💢'), callback_data="p2p_cancel_buy", style="danger")
                ]
            ]
        )
        await message.reply(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)
        return

    if user_action == "sell_bot_custom" or ("ПРОДАТЬ MPOINT" in rep_text and "Оф. Продажа" in rep_text):
        if raw_amount is None or raw_amount <= 0:
            return
        p2p_user_action.pop(user_id, None)
        update_p2p_rate_fluctuation(force=False)
        settings = get_p2p_settings()
        sell_rate = settings.get("official_sell_rate", 10000)
        user_u = get_user(user_id)
        user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
        if user_u.get("mp_balance", 0) < raw_amount:
            shortage = raw_amount - user_u.get("mp_balance", 0)
            err_text = _lf('🚫 <i>{0}, не хватает <b>{1} MP!</b></i>', (_fmt(user_link, '', -1), _fmt(format_number(shortage), '', -1)))
            err_kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data="p2p_sell_bot", icon_custom_emoji_id="5255703720078879038")]]
            )
            await message.reply(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
            return

        total_mcoin = raw_amount * sell_rate
        conf_text = (
            _lf('<tg-emoji emoji-id="5452069934089641166">❓</tg-emoji> <b>ПОДТВЕРЖДЕНИЕ СДЕЛКИ</b>\n<code>·····················</code>\n<i>{0}, ты точно <b>хочешь продать {1} MPOINT</b> за <b>{2} mCoin?</b></i>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Оф. курс: {3} mCoin</blockquote>\n<blockquote>🔘 Комиссия: 0% = 0 mCoin</blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(format_number(total_mcoin), '', -1), _fmt(format_number(sell_rate), '', -1)))
        )
        conf_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=_l('Да ✅'), callback_data=f"p2p_conf_sbot_{raw_amount}", style="success"),
                    InlineKeyboardButton(text=_l('Отмена 💢'), callback_data="p2p_cancel_buy", style="danger")
                ]
            ]
        )
        await message.reply(conf_text, reply_markup=conf_kb, parse_mode=ParseMode.HTML)
        return

    if (user_action and user_action.startswith("sell_buyer_")) or ("ПРОДАТЬ MPOINT" in rep_text and "Покупатель:" in rep_text):
        if raw_amount is None or raw_amount <= 0:
            return
        if user_action and user_action.startswith("sell_buyer_"):
            buyer_id = int(user_action.replace("sell_buyer_", ""))
        else:
            m = re.search(r'tg://user\?id=(\d+)', rep_text)
            if not m:
                return
            buyer_id = int(m.group(1))

        p2p_user_action.pop(user_id, None)
        buyer_p2p = get_p2p_account(buyer_id)
        seller_u = get_user(user_id)
        seller_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))

        if seller_u.get("mp_balance", 0) < raw_amount:
            shortage = raw_amount - seller_u.get("mp_balance", 0)
            err_text = _lf('🚫 <i>{0}, не хватает <b>{1} MP!</b></i>', (_fmt(seller_link, '', -1), _fmt(format_number(shortage), '', -1)))
            err_kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=_l('Назад'), callback_data=f"p2p_sell_buyer_{buyer_id}", icon_custom_emoji_id="5255703720078879038")]]
            )
            await message.reply(err_text, reply_markup=err_kb, parse_mode=ParseMode.HTML)
            return

        total_mcoin = raw_amount * buyer_p2p["buy_price"]
        conf_text = (
            _lf('<tg-emoji emoji-id="5452069934089641166">❓</tg-emoji> <b>ПОДТВЕРЖДЕНИЕ СДЕЛКИ</b>\n<code>·····················</code>\n<i>{0}, ты точно <b>хочешь продать {1} MPOINT</b> за <b>{2} mCoin?</b></i>\n<blockquote><tg-emoji emoji-id="5402186569006210455">💱</tg-emoji> Курс: {3} mCoin</blockquote>\n<blockquote>🔘 Комиссия: 0% = 0 mCoin</blockquote>', (_fmt(seller_link, '', -1), _fmt(format_number(raw_amount), '', -1), _fmt(format_number(total_mcoin), '', -1), _fmt(format_number(buyer_p2p['buy_price']), '', -1)))
        )
        conf_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=_l('Да ✅'), callback_data=f"p2p_conf_sbuy_{buyer_id}_{raw_amount}", style="success"),
                    InlineKeyboardButton(text=_l('Отмена 💢'), callback_data="p2p_cancel_buy", style="danger")
                ]
            ]
        )

TEMPLE_GIFTS = {
    "heart": {
        "name": "Сердце",
        "emoji": "💝",
        "stars": 15,
        "tg_gift_id": "5170145012310081615"
    },
    "bear": {
        "name": "Мишка",
        "emoji": "🧸",
        "stars": 15,
        "tg_gift_id": "5170233102089322756"
    },
    "box": {
        "name": "Подарок",
        "emoji": "🎁",
        "stars": 25,
        "tg_gift_id": "5170250947678437525"
    },
    "champagne": {
        "name": "Шампанское",
        "emoji": "🍾",
        "stars": 50,
        "tg_gift_id": "6028601630662853006"
    },
    "bouquet": {
        "name": "Букет",
        "emoji": "💐",
        "stars": 50,
        "tg_gift_id": "5170314324215857265"
    },
    "ring": {
        "name": "Кольцо",
        "emoji": "💍",
        "stars": 100,
        "tg_gift_id": "5170690322832818290"
    }
}

_temple_user_target = {}
_temple_user_comment = {}
_temple_waiting_comment = {}
_temple_waiting_target = set()


def get_temple_stats(user_id: int) -> dict:
    try:
        cursor.execute("SELECT gifts_sent, stars_spent FROM temple_user_stats WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return {"gifts_sent": row[0] or 0, "stars_spent": row[1] or 0}
        return {"gifts_sent": 0, "stars_spent": 0}
    except Exception:
        return {"gifts_sent": 0, "stars_spent": 0}


def record_temple_gift(sender_id: int, receiver_id: int, gift_key: str, gift_name: str, stars_cost: int, comment: str = ""):
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        cursor.execute("""
            INSERT INTO temple_user_stats (user_id, gifts_sent, stars_spent, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                gifts_sent = temple_user_stats.gifts_sent + 1,
                stars_spent = temple_user_stats.stars_spent + EXCLUDED.stars_spent,
                updated_at = EXCLUDED.updated_at
        """, (sender_id, stars_cost, now_str))
        
        cursor.execute("""
            INSERT INTO temple_gifts_history (sender_id, receiver_id, gift_key, gift_name, stars_cost, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (sender_id, receiver_id, gift_key, gift_name, stars_cost, comment or "", now_str))
        conn.commit()
    except Exception as e:
        logger.error(f"Error recording temple gift: {e}")


async def deliver_telegram_gift(user_id: int, gift_key: str, comment: str = ""):
    gift_info = TEMPLE_GIFTS.get(gift_key)
    if not gift_info:
        return False
    try:
        if hasattr(bot, "get_available_gifts"):
            gifts_res = await bot.get_available_gifts()
            gifts_list = getattr(gifts_res, "gifts", [])
            for g in gifts_list:
                if getattr(g, "star_count", 0) == gift_info["stars"]:
                    if hasattr(bot, "send_gift"):
                        await bot.send_gift(user_id=user_id, gift_id=g.id, text=comment if comment else None)
                        return True
    except Exception as e:
        logger.warning(f"deliver_telegram_gift note: {e}")

    try:
        if hasattr(bot, "send_gift"):
            await bot.send_gift(user_id=user_id, gift_id=gift_info["tg_gift_id"], text=comment if comment else None)
            return True
    except Exception as e:
        logger.warning(f"direct send_gift note: {e}")

    return False


async def resolve_temple_target(message: types.Message, raw_target: str) -> Optional[int]:
    if not raw_target:
        if message.reply_to_message and message.reply_to_message.from_user:
            return message.reply_to_message.from_user.id
        return None
    
    clean_target = raw_target.strip()
    if clean_target.startswith("@"):
        clean_uname = clean_target[1:].lower()
        u = get_user_by_username(clean_uname)
        if u:
            return u["user_id"]
        try:
            chat = await bot.get_chat(clean_target)
            if chat and chat.id:
                get_user(chat.id)
                return chat.id
        except Exception:
            pass
        return None
    elif clean_target.isdigit():
        uid = int(clean_target)
        get_user(uid)
        return uid
    else:
        u = get_user_by_username(clean_target)
        if u:
            return u["user_id"]
        try:
            chat = await bot.get_chat(f"@{clean_target}")
            if chat and chat.id:
                get_user(chat.id)
                return chat.id
        except Exception:
            pass
        return None


@_localized
async def show_temple_target_selected(event, sender_id: int, sender_name: str, target_id: int, edit: bool = False):
    sender_link = get_user_mention(sender_id, sender_name)
    target_link = get_user_mention(target_id)
    if sender_id == target_id:
        target_str = _l('<b>самого себя</b>')
    else:
        target_str = target_link
    text = (
        _lf('{0}\n<tg-emoji emoji-id="5472096095280569232">🎁</tg-emoji> Получатель {1} успешно выбран!', (_fmt(sender_link, '', -1), _fmt(target_str, '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Отправить подарок'),
                    callback_data=f"temple_gifts_{target_id}",
                    style="success",
                    icon_custom_emoji_id="5846184826184408721"
                )
            ],
            [
                InlineKeyboardButton(
                    text=_l('Сменить получателя'),
                    callback_data="temple_change_target",
                    style="danger",
                    icon_custom_emoji_id="5264727218734524899"
                )
            ]
        ]
    )
    if edit and isinstance(event, types.CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass
    if isinstance(event, types.CallbackQuery):
        await event.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await event.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)



@dp.message(Command("temple", "храм"))
@dp.message(_inline_filter(lambda message: message.text and re.match(r'^[!/.]?(храм|temple)(\s+|$)', message.text, re.IGNORECASE)))
@_localized
async def cmd_temple(message: types.Message):
    user_id = message.from_user.id
    raw_text = message.text.strip()
    parts = re.split(r'\s+', raw_text, maxsplit=1)
    
    if len(parts) > 1 or (message.reply_to_message and message.reply_to_message.from_user):
        arg = parts[1].strip() if len(parts) > 1 else ""
        target_id = await resolve_temple_target(message, arg)
        if not target_id:
            await message.reply(_l('<i>Пользователь не найден! Укажите корректный @username или ID.</i>'), parse_mode=ParseMode.HTML)
            return
        _temple_user_target[user_id] = target_id
        await show_temple_target_selected(message, user_id, get_user_display_name(message.from_user.id, message.from_user.first_name), target_id)
        return

    text = (
        _l('[NEW] <tg-emoji emoji-id="5834781387365818180">🎁</tg-emoji><b> Подарочный храм</b>\n\n<tg-emoji emoji-id="5942877472163892475">👥</tg-emoji> В подарочном храме ты сможешь:\n<i>Отправлять подарки своим друзьям.\nРазыгрывать подарки среди игроков.</i>')
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Войти'),
                    callback_data="temple_enter",
                    style="success",
                    icon_custom_emoji_id="5258084656674250503"
                )
            ]
        ]
    )
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "temple_enter"))
@_localized
async def cb_temple_enter(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    
    sticker_id = "CAACAgUAAxkBAAERq7xqdMNBP-oO2yCEC4DAChXoLQVFjgACCgQAAjHHqVblSt_BbuOy8D0E"
    try:
        st_msg = await callback.message.answer_sticker(sticker_id)
        await asyncio.sleep(2)
        try:
            await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=st_msg.message_id)
        except Exception:
            pass
    except Exception:
        pass

    stats = get_temple_stats(user_id)
    text = (
        _lf('{0}\n<tg-emoji emoji-id="5951637899777677904">👋</tg-emoji> Добро пожаловать в подарочный храм!\n\n<tg-emoji emoji-id="5422360266618707867">📊</tg-emoji> Твоя статистика\n<blockquote> <tg-emoji emoji-id="5357134848857241750">⬜️</tg-emoji>Отправлено подарков: {1}</blockquote>\n<blockquote><tg-emoji emoji-id="5463289097336405244">⭐️</tg-emoji>Потрачено звезд: {2}</blockquote>\n\n<b>Для того чтобы отправить подарок пользователю введи команда <code>храм &lt;username/id&gt;</code></b>', (_fmt(user_link, '', -1), _fmt(stats['gifts_sent'], '', -1), _fmt(stats['stars_spent'], '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('🎁 Подарить себе'),
                    callback_data=f"temple_gifts_{user_id}",
                    style="success"
                )
            ]
        ]
    )
    await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "temple_change_target"))
@_localized
async def cb_temple_change_target(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    _temple_waiting_target.add(user_id)
    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    text = (
        _lf('{0}\n<tg-emoji emoji-id="5472096095280569232">🎁</tg-emoji> Отправьте @username или ID получателя (или введите <code>храм &lt;username/id&gt;</code>):', (_fmt(user_link, '', -1),))
    )
    try:
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("temple_back_target_")))
@_localized
async def cb_temple_back_target(callback: types.CallbackQuery):
    await callback.answer()
    target_id = int(callback.data.replace("temple_back_target_", ""))
    user_id = callback.from_user.id
    await show_temple_target_selected(callback, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), target_id, edit=True)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("temple_gifts_")))
@_localized
async def cb_temple_gifts(callback: types.CallbackQuery):
    await callback.answer()
    target_id = int(callback.data.replace("temple_gifts_", ""))
    user_id = callback.from_user.id
    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    target_link = _l('самому себе') if target_id == user_id else get_user_mention(target_id)
    
    text = (
        _lf('{0}\n<tg-emoji emoji-id="5474371208176737086">✉️</tg-emoji> Выберите подарок которой вы хотите подарить {1}', (_fmt(user_link, '', -1), _fmt(target_link, '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💝", callback_data=f"temple_sel_{target_id}_heart"),
                InlineKeyboardButton(text="🧸", callback_data=f"temple_sel_{target_id}_bear"),
                InlineKeyboardButton(text="🎁", callback_data=f"temple_sel_{target_id}_box"),
            ],
            [
                InlineKeyboardButton(text="🍾", callback_data=f"temple_sel_{target_id}_champagne"),
                InlineKeyboardButton(text="💐", callback_data=f"temple_sel_{target_id}_bouquet"),
                InlineKeyboardButton(text="💍", callback_data=f"temple_sel_{target_id}_ring"),
            ],
            [
                InlineKeyboardButton(text=_l('« Назад'), callback_data=f"temple_back_target_{target_id}")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("temple_sel_")))
@_localized
async def cb_temple_select_gift(callback: types.CallbackQuery):
    await callback.answer()
    parts = callback.data.replace("temple_sel_", "").split("_")
    target_id = int(parts[0])
    gift_key = parts[1]
    user_id = callback.from_user.id
    
    gift = TEMPLE_GIFTS.get(gift_key, TEMPLE_GIFTS["heart"])
    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    target_link = _l('самому себе') if target_id == user_id else get_user_mention(target_id)
    
    comment = _temple_user_comment.get(user_id, "")
    comment_block = _lf('\n<blockquote>💬 <b>Комментарий:</b> <i>{0}</i></blockquote>\n', (_fmt(html.escape(comment), '', -1),)) if comment else '\n'

    text = (
        _lf('{0}\n<tg-emoji emoji-id="5472248119942979457">🤔</tg-emoji> Вы хотите отправить подарок <b>{1} {2} ({3}⭐️)</b> пользователю {4}?\n{5}\n<blockquote><i>Если хотите добавить комментарий к подарку, то нажмите кнопку ниже, если хотите без комментария просто проигнорируйте данное сообщение</i></blockquote>', (_fmt(user_link, '', -1), _fmt(gift['emoji'], '', -1), _fmt(_label(gift['name']), '', -1), _fmt(gift['stars'], '', -1), _fmt(target_link, '', -1), _fmt(comment_block, '', -1)))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('Отправить'), callback_data=f"temple_pay_{target_id}_{gift_key}", style="primary"),
                InlineKeyboardButton(text=_l('Добавить комментарий') if not comment else _l('Изменить комментарий'), callback_data=f"temple_com_{target_id}_{gift_key}", style="primary")
            ],
            [
                InlineKeyboardButton(text=_l('« Назад'), callback_data=f"temple_gifts_{target_id}")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("temple_com_")))
@_localized
async def cb_temple_add_comment(callback: types.CallbackQuery):
    await callback.answer()
    parts = callback.data.replace("temple_com_", "").split("_")
    target_id = int(parts[0])
    gift_key = parts[1]
    user_id = callback.from_user.id
    
    _temple_waiting_comment[user_id] = (target_id, gift_key)
    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    text = (
        _lf('{0}\n✍️ <b>Напишите комментарий к подарку в чат:</b>', (_fmt(user_link, '', -1),))
    )
    await callback.message.answer(text, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data.startswith("temple_pay_")))
@_localized
async def cb_temple_pay(callback: types.CallbackQuery):
    await callback.answer()
    parts = callback.data.replace("temple_pay_", "").split("_")
    target_id = int(parts[0])
    gift_key = parts[1]
    user_id = callback.from_user.id
    
    gift = TEMPLE_GIFTS.get(gift_key, TEMPLE_GIFTS["heart"])
    target_name = _l('себе') if target_id == user_id else get_user_display_name(target_id)
    
    payload = f"temple_gift_{user_id}_{target_id}_{gift_key}_{secrets.token_hex(4)}"
    title = _lf('Подарок {0} {1}', (_fmt(gift['emoji'], '', -1), _fmt(_label(gift['name']), '', -1)))
    description = _lf('Оплата подарка {0} пользователю {1}', (_fmt(_label(gift['name']), '', -1), _fmt(target_name, '', -1)))
    
    try:
        await callback.message.answer_invoice(
            title=title,
            description=description,
            payload=payload,
            currency="XTR",
            prices=[types.LabeledPrice(label=_lf('{0} {1}', (_fmt(gift['emoji'], '', -1), _fmt(_label(gift['name']), '', -1))), amount=gift["stars"])],
            provider_token=""
        )
    except Exception as e:
        await callback.answer(_lf('Ошибка создания счета: {0}', (_fmt(e, '', -1),)), show_alert=True)


@dp.pre_checkout_query(_inline_filter(lambda q: q.invoice_payload and q.invoice_payload.startswith("temple_gift_")))
async def cb_temple_pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@dp.message(_inline_filter(lambda m: m.successful_payment and m.successful_payment.invoice_payload and m.successful_payment.invoice_payload.startswith("temple_gift_")))
@_localized
async def cb_temple_successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    if len(parts) < 6:
        return
    sender_id = int(parts[2])
    target_id = int(parts[3])
    gift_key = parts[4]
    
    gift = TEMPLE_GIFTS.get(gift_key, TEMPLE_GIFTS["heart"])
    comment = _temple_user_comment.pop(sender_id, "")
    
    record_temple_gift(sender_id, target_id, gift_key, gift["name"], gift["stars"], comment)
    
    asyncio.create_task(deliver_telegram_gift(target_id, gift_key, comment))
    
    sender_link = get_user_mention(sender_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
    succ_text = (
        _lf('{0}\n<tg-emoji emoji-id="5472180551517477902">✅</tg-emoji> Ваша заявка обрабатывается!', (_fmt(sender_link, '', -1),))
    )
    await message.answer(succ_text, parse_mode=ParseMode.HTML)
    
    if sender_id == target_id:
        try:
            self_notify = (
                _lf('🎉 <b>Вы успешно подарили себе подарок {0} {1}!</b>\n', (_fmt(gift['emoji'], '', -1), _fmt(_label(gift['name']), '', -1)))
            )
            if comment:
                self_notify += f'💬 <i>«{html.escape(comment)}»</i>'
            await message.answer(self_notify, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    else:
        try:
            target_notify = (
                _lf('🎉 <b>Вам пришёл подарок {0} {1}!</b>\n👤 От: {2}\n', (_fmt(gift['emoji'], '', -1), _fmt(_label(gift['name'], user_id=target_id), '', -1), _fmt(sender_link, '', -1)), user_id=target_id)
            )
            if comment:
                target_notify += f'💬 <i>«{html.escape(comment)}»</i>'
            await bot.send_message(chat_id=target_id, text=target_notify, parse_mode=ParseMode.HTML)
        except Exception:
            pass


@dp.message(_inline_filter(lambda message: message.text and (
    message.from_user.id in _temple_waiting_comment or
    message.from_user.id in _temple_waiting_target
)))
@_localized
async def process_temple_text_input(message: types.Message):
    user_id = message.from_user.id
    raw_text = message.text.strip()

    if raw_text.startswith("/") and not raw_text.lower().startswith(("/храм", "/temple")):
        _temple_waiting_comment.pop(user_id, None)
        _temple_waiting_target.discard(user_id)
        return
    
    if user_id in _temple_waiting_comment:
        target_id, gift_key = _temple_waiting_comment.pop(user_id)
        _temple_user_comment[user_id] = raw_text
        gift = TEMPLE_GIFTS.get(gift_key, TEMPLE_GIFTS["heart"])
        user_link = get_user_mention(user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))
        target_link = _l('самому себе') if target_id == user_id else get_user_mention(target_id)
        text = (
            _lf('{0}\n<tg-emoji emoji-id="5472248119942979457">🤔</tg-emoji> Вы хотите отправить подарок <b>{1} {2} ({3}⭐️)</b> пользователю {4}?\n\n<blockquote>💬 <b>Комментарий:</b> <i>{5}</i></blockquote>\n\n<blockquote><i>Если хотите изменить комментарий, нажмите кнопку ниже</i></blockquote>', (_fmt(user_link, '', -1), _fmt(gift['emoji'], '', -1), _fmt(_label(gift['name']), '', -1), _fmt(gift['stars'], '', -1), _fmt(target_link, '', -1), _fmt(html.escape(raw_text), '', -1)))
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=_l('Отправить'), callback_data=f"temple_pay_{target_id}_{gift_key}", style="primary"),
                    InlineKeyboardButton(text=_l('Изменить комментарий'), callback_data=f"temple_com_{target_id}_{gift_key}", style="primary")
                ],
                [
                    InlineKeyboardButton(text=_l('« Назад'), callback_data=f"temple_gifts_{target_id}")
                ]
            ]
        )
        await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if user_id in _temple_waiting_target:
        _temple_waiting_target.discard(user_id)
        lookup_target = raw_text
        if lookup_target.lower().startswith(("храм ", "/храм ", "!храм ", "temple ", "/temple ")):
            lookup_target = lookup_target.split(None, 1)[1].strip()
        
        target_user = await resolve_temple_target(message, lookup_target)
        if not target_user:
            await message.reply(_l('<i>Пользователь не найден! Укажите корректный @username или ID.</i>'), parse_mode=ParseMode.HTML)
            return
        _temple_user_target[user_id] = target_user
        await show_temple_target_selected(message, user_id, get_user_display_name(message.from_user.id, message.from_user.first_name), target_user)
        return



@_localized
async def check_time_deposits_task():
    while True:
        try:
            now = datetime.now()
            cursor.execute(
                "SELECT id, user_id, amount, days, percent, profit, end_at_dt FROM time_deposits WHERE status = 'active' AND (end_at_dt <= ? OR end_at_dt NOT GLOB '????-??-??T??:??:??*')",
                (now.isoformat(),),
            )
            rows = cursor.fetchall()
            for r in rows:
                dep_id, uid, amount, days, percent, profit, end_at_dt_str = r
                try:
                    end_dt = datetime.fromisoformat(end_at_dt_str)
                except Exception:
                    continue
                if now >= end_dt:
                    cursor.execute("UPDATE time_deposits SET status = 'completed' WHERE id = ? AND status = 'active'", (dep_id,))
                    if cursor.rowcount > 0:
                        payout = amount + profit
                        cursor.execute("UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE user_id = ?", (payout, payout, uid))
                        conn.commit()

                        settings = get_bank_settings(uid)
                        if settings.get("notifications_enabled", True):
                            try:
                                u_data = get_user(uid)
                                msg_text = (
                                    _lf('🏦 <b>Депозит завершен!</b>\n<code>·····················</code>\nСрок депозита на {0}д. подошел к концу.\n💰 Выплата: <b>+{1} m¢</b> (прибыль: <b>+{2} m¢</b>)\n<tg-emoji emoji-id="5418238674267556907">⭐</tg-emoji> Баланс: <b>{3} m¢</b>', (_fmt(days, '', -1), _fmt(format_number(payout), '', -1), _fmt(format_number(profit), '', -1), _fmt(format_number(u_data['balance']), '', -1)), user_id=uid)
                                )
                                await bot.send_message(chat_id=uid, text=msg_text, parse_mode=ParseMode.HTML)
                            except Exception:
                                pass
        except Exception:
            pass
        await asyncio.sleep(30)


def _accrue_savings_interest(now_iso):
    cursor.execute(
        """
        UPDATE savings_accounts
        SET accumulated_interest = COALESCE(accumulated_interest, 0.0) + balance * ?, last_accrual = ?
        WHERE balance > 0
        """,
        (0.002 / 24.0, now_iso),
    )
    conn.commit()


async def accrue_savings_task():
    while True:
        try:
            await asyncio.sleep(3600)
            _accrue_savings_interest(datetime.now().isoformat())
        except Exception:
            await asyncio.sleep(60)


async def reset_daily_mp_limits_task():
    while True:
        try:
            now_msk = get_msk_now()
            tomorrow_msk = (now_msk + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            sleep_seconds = (tomorrow_msk - now_msk).total_seconds()
            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds + 1)
            else:
                await asyncio.sleep(1)

            today_str = get_msk_today_str()
            cursor.execute("UPDATE users SET mp_daily_transferred = 0, mp_daily_date = ?", (today_str,))
            conn.commit()
        except Exception:
            await asyncio.sleep(60)


async def p2p_rate_updater_task():
    while True:
        try:
            update_p2p_rate_fluctuation(force=False)
        except Exception:
            pass
        await asyncio.sleep(30)



promote_user_states = {}


@_localized
def get_promote_main_markup():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_l('Продвигать канал'),
                    callback_data="promote_type_channel",
                    style="primary",
                    icon_custom_emoji_id="5469903029144657419"
                )
            ],
            [
                InlineKeyboardButton(
                    text=_l('Продвигать чат/группу'),
                    callback_data="promote_type_chat",
                    style="primary",
                    icon_custom_emoji_id="5465300082628763143"
                )
            ],
            [
                InlineKeyboardButton(
                    text=_l('Активные'),
                    callback_data="promote_active",
                    style="success",
                    icon_custom_emoji_id="5809949600152296075"
                ),
                InlineKeyboardButton(
                    text=_l('Завершенные'),
                    callback_data="promote_completed",
                    style="danger",
                    icon_custom_emoji_id="5953810354365538566"
                )
            ],
            [
                InlineKeyboardButton(
                    text=_l('Правила'),
                    callback_data="promote_rules",
                    style="danger",
                    icon_custom_emoji_id="5222444124698853913"
                )
            ]
        ]
    )


@_localized
async def send_promote_main_menu(chat_id: int, user_id: int, user_first_name: str, message_to_edit: types.Message = None):
    user = get_user(user_id)
    mp_bal = user.get("mp_balance", 0) if user else 0
    user_link = get_user_mention(user_id, user_first_name)

    text = (
        _lf('<tg-emoji emoji-id="5341715473882955310">⚙️</tg-emoji> {0}, <i>что ты хочешь рекламировать?</i>\n----------------------\n<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji><b>Обязательно прочитай правила перед добавляем задания!</b>\n----------------------\n<tg-emoji emoji-id="5307594157739515229">💎</tg-emoji> Баланс: <b>{1} MPOINT</b>', (_fmt(user_link, '', -1), _fmt(format_number(mp_bal), '', -1)))
    )
    kb = get_promote_main_markup()

    if message_to_edit:
        try:
            await message_to_edit.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def check_user_subscribed(user_id, chat) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat, user_id=user_id)
        status = getattr(member, "status", "")
        status_value = getattr(status, "value", str(status)).lower()
        if any(s in status_value for s in ("member", "administrator", "creator", "owner")):
            return True
        if getattr(member, "is_member", False):
            return True
    except Exception as e:
        logging.warning(f"Failed to check subscription for {chat} / {user_id}: {e}")
    return False


@_event_read_cache
def task_completed(user_id, task_id) -> bool:
    try:
        cursor.execute(
            "SELECT 1 FROM user_completed_tasks WHERE user_id = ? AND task_id = ?",
            (user_id, task_id)
        )
        return cursor.fetchone() is not None
    except Exception as e:
        logging.error(f"Task completion check error for {user_id}/{task_id}: {e}")
        return False


def mark_task_completed(user_id, task_id):
    try:
        cursor.execute(
            "INSERT INTO user_completed_tasks (user_id, task_id, completed_at) VALUES (?, ?, ?) ON CONFLICT (user_id, task_id) DO NOTHING",
            (user_id, task_id, get_msk_now().isoformat())
        )
        return getattr(cursor, "rowcount", 0) > 0
    except Exception as e:
        logging.error(f"Task completion save error for {user_id}/{task_id}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        raise


@_localized
def build_earn_menu(user_id) -> (str, InlineKeyboardMarkup):
    user = get_user(user_id)
    mp_balance = user.get("mp_balance", 0) if user else 0
    available_tasks = [task for task in TASKS_INFO if not task_completed(user_id, task["id"])]

    lines = [
        _l('💰 <b>Заработать</b>'),
        "<code>·····················</code>",
        _lf('💎 Баланс: <b>{0} MP</b>', (_fmt(format_number(mp_balance), '', -1),)),
        "",
        _l('Доступные задания:'),
    ]

    keyboard_rows = []
    if available_tasks:
        for task in available_tasks:
            lines.append(_lf('• {0} — +{1} MP', (_fmt(_label(html.escape(task['title'])), '', -1), _fmt(format_number(task['reward']), '', -1))))
            keyboard_rows.append([
                InlineKeyboardButton(text=_l('➡️ Перейти'), url=task["url"]),
                InlineKeyboardButton(text=_l('✅ Проверить'), callback_data=f"earn_check:{task['id']}")
            ])
    else:
        lines.append(_l('• Все доступные задания уже выполнены ✅'))

    keyboard_rows.append([InlineKeyboardButton(text=_l('🔄 Обновить'), callback_data="earn_refresh")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


@dp.message(Command("earning", "earn", "заработать", "заработок"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower() in ["заработать", "заработок", "/earning", "earning", "/earn", "earn"]))
@_localized
async def cmd_earning(message: types.Message):
    user_id = message.from_user.id
    text, keyboard = build_earn_menu(user_id)
    if message.chat.type in ["group", "supergroup"]:
        await message.reply(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data == "earn_refresh"))
@_localized
async def process_earn_refresh(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    text, keyboard = build_earn_menu(user_id)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("earn_check:")))
@_localized
async def process_earn_check(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    task_id = callback.data.split(":", 1)[1]
    task = next((item for item in TASKS_INFO if item["id"] == task_id), None)
    if not task:
        await callback.answer(_l('Задание не найдено'), show_alert=True)
        return

    if task_completed(user_id, task_id):
        await callback.answer(_l('Уже выполнено'), show_alert=True)
        return

    is_subscribed = await check_user_subscribed(user_id, task["chat"])
    if not is_subscribed:
        await callback.answer(_l('Вы ещё не подписались на канал'), show_alert=True)
        return

    try:
        get_user(user_id)
        if not mark_task_completed(user_id, task_id):
            try:
                conn.rollback()
            except Exception:
                pass
            await callback.answer(_l('Уже выполнено'), show_alert=True)
            return
        cursor.execute(
            "UPDATE users SET mp_balance = COALESCE(mp_balance, 0) + ? WHERE user_id = ?",
            (int(task["reward"]), user_id)
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        await callback.answer(_l('Не удалось начислить награду. Попробуйте позже'), show_alert=True)
        return

    text, keyboard = build_earn_menu(user_id)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer(_lf('Задание выполнено! +{0} MP', (_fmt(format_number(task['reward']), '', -1),)), show_alert=True)


@dp.message(Command("promote", "продвижение"))
@dp.message(_inline_filter(lambda message: message.text and message.text.strip().lower() in ["продвижение", "/promote", "promote", "/продвижение"]))
@_localized
async def cmd_promote(message: types.Message):
    if message.chat.type in ["group", "supergroup"]:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_l('Перейти в продвижение'),
                        url=f"https://t.me/{BOT_USERNAME}?start=promote"
                    )
                ]
            ]
        )
        await message.reply(_l('<i>Эта команда работает только в личных сообщениях!</i>'), reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return

    user_id = message.from_user.id
    promote_user_states.pop(user_id, None)
    await send_promote_main_menu(message.chat.id, user_id, get_user_display_name(message.from_user.id, message.from_user.first_name))


@dp.callback_query(_inline_filter(lambda c: c.data == "promote_menu"))
@_localized
async def process_promote_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    promote_user_states.pop(user_id, None)
    await send_promote_main_menu(callback.message.chat.id, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), message_to_edit=callback.message)
    await callback.answer()


@dp.callback_query(_inline_filter(lambda c: c.data in ["promote_type_channel", "promote_type_chat"]))
@_localized
async def process_promote_type(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    target_type = "channel" if callback.data == "promote_type_channel" else "chat"
    promote_user_states[user_id] = {
        "target_type": target_type,
        "step": "price"
    }

    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    text = (
        _lf('<tg-emoji emoji-id="5373012449597335010">👤</tg-emoji> <i>{0}, напиши цену за 1 подписчика!\n----------------------\n<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> Минимальная цена - 1 MPOINT!</i>\n<blockquote>🔝 <b>Чем выше цена за подписчика — тем выше будет в списке твое задание!</b></blockquote>', (_fmt(user_link, '', -1),))
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 MP", callback_data="promote_price_1", style="primary"),
                InlineKeyboardButton(text="3 MP", callback_data="promote_price_3", style="primary"),
                InlineKeyboardButton(text="5 MP", callback_data="promote_price_5", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('« Назад'), callback_data="promote_menu")
            ]
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("promote_price_")))
@_localized
async def process_promote_price_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    state_data = promote_user_states.get(user_id, {})
    try:
        price = int(callback.data.replace("promote_price_", ""))
    except Exception:
        price = 1

    await handle_promote_price_selected(callback.message.chat.id, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), price, message_to_edit=callback.message)
    await callback.answer()


@_localized
async def handle_promote_price_selected(chat_id: int, user_id: int, first_name: str, price: int, message_to_edit: types.Message = None):
    if price < 1:
        price = 1

    state_data = promote_user_states.get(user_id, {})
    state_data["price"] = price
    state_data["step"] = "subs"
    promote_user_states[user_id] = state_data

    user = get_user(user_id)
    mp_balance = user.get("mp_balance", 0) if user else 0
    max_subs = int(mp_balance // price) if price > 0 else 0

    user_link = get_user_mention(user_id, first_name)

    if max_subs < 1:
        text = (
            _lf('{0}, <i>у вас недостаточно MPOINT на балансе!\nБаланс: <b>{1} MP</b>. Для цены {2} MP требуется минимум {3} MP.</i>', (_fmt(user_link, '', -1), _fmt(format_number(mp_balance), '', -1), _fmt(price, '', -1), _fmt(price, '', -1)))
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('« Назад'), callback_data="promote_type_channel" if state_data.get("target_type") == "channel" else "promote_type_chat")]])
        if message_to_edit:
            try:
                await message_to_edit.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
                return
            except Exception:
                pass
        await bot.send_message(chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    text = (
        _lf('<tg-emoji emoji-id="5472355270787079946">🧮</tg-emoji> <i>{0}, введи количество подписчиков:\n---------------\n🔘 <b>Максимум:</b> {1} чел.</i>', (_fmt(user_link, '', -1), _fmt(format_number(max_subs), '', -1)))
    )

    row1 = []
    for count_opt in [1, 5, 10]:
        if count_opt <= max_subs:
            row1.append(InlineKeyboardButton(text=_lf('{0} чел.', (_fmt(count_opt, '', -1),)), callback_data=f"promote_subs_{count_opt}", style="primary"))

    kb_rows = []
    if row1:
        kb_rows.append(row1)
    kb_rows.append([InlineKeyboardButton(text=_lf('Макс • {0} чел.', (_fmt(format_number(max_subs), '', -1),)), callback_data=f"promote_subs_{max_subs}", style="primary")])
    kb_rows.append([InlineKeyboardButton(text=_l('« Назад'), callback_data="promote_type_channel" if state_data.get("target_type") == "channel" else "promote_type_chat")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if message_to_edit:
        try:
            await message_to_edit.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("promote_subs_")))
@_localized
async def process_promote_subs_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        count = int(callback.data.replace("promote_subs_", ""))
    except Exception:
        count = 1

    await handle_promote_subs_selected(callback.message.chat.id, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name), count, message_to_edit=callback.message)
    await callback.answer()


@_localized
async def handle_promote_subs_selected(chat_id: int, user_id: int, first_name: str, count: int, message_to_edit: types.Message = None):
    state_data = promote_user_states.get(user_id, {})
    price = state_data.get("price", 1)

    user = get_user(user_id)
    mp_balance = user.get("mp_balance", 0) if user else 0
    max_subs = int(mp_balance // price) if price > 0 else 0

    if count < 1:
        count = 1
    if count > max_subs:
        count = max_subs

    state_data["subs"] = count
    state_data["step"] = "wait_chat"
    promote_user_states[user_id] = state_data

    target_type = state_data.get("target_type", "channel")
    is_channel = (target_type == "channel")
    btn_text = _l('Отправить канал') if is_channel else _l('Отправить чат')

    if message_to_edit:
        try:
            await message_to_edit.delete()
        except Exception:
            pass

    text1 = (
        _lf('<tg-emoji emoji-id="5274099962655816924">❗️</tg-emoji> ВАЖНО <tg-emoji emoji-id="5274099962655816924">❗️</tg-emoji>\n<blockquote>Канал/чат не должен нарушать правила Telegram. В случае нарушения мы ограничим доступ к боту навсегда.</blockquote>\n<i>{0} должен быть публичным и без заявок на вступление</i>', (_fmt(_l('Канал') if is_channel else _l('Чат'), '', -1),))
    )
    msg1 = await bot.send_message(chat_id, text1, parse_mode=ParseMode.HTML)

    text2 = _l('<i>⛓💥"Хотите отменить добавление? Если нет, выберите кнопку на клавиатуре.👇</i>')
    kb_cancel = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('Отмена'), callback_data="promote_cancel", style="danger")]])
    msg2 = await bot.send_message(chat_id, text2, reply_markup=kb_cancel, parse_mode=ParseMode.HTML)

    if is_channel:
        fields = {k: False for k in ChatAdministratorRights.model_fields.keys()}
        fields.update({
            "can_change_info": True,
            "can_post_messages": True,
            "can_edit_messages": True,
            "can_delete_messages": True,
            "can_invite_users": True,
            "can_pin_messages": True,
            "can_promote_members": True
        })
        channel_rights = ChatAdministratorRights(**fields)
    else:
        fields = {k: False for k in ChatAdministratorRights.model_fields.keys()}
        fields.update({
            "can_change_info": True,
            "can_delete_messages": True,
            "can_invite_users": True,
            "can_restrict_members": True,
            "can_pin_messages": True,
            "can_promote_members": True,
            "can_manage_video_chats": True
        })
        channel_rights = ChatAdministratorRights(**fields)

    reply_kb = ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text=btn_text,
                request_chat=KeyboardButtonRequestChat(
                    request_id=1001,
                    chat_is_channel=is_channel,
                    chat_has_username=True,
                    request_title=True,
                    request_username=True,
                    user_administrator_rights=channel_rights
                )
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    try:
        msg3 = await bot.send_message(chat_id, _l('👇 Нажмите кнопку внизу клавиатуры:'), reply_markup=reply_kb)
    except Exception as e:
        logging.warning(f"Failed to send KeyboardButtonRequestChat with rights: {e}")
        fallback_kb = ReplyKeyboardMarkup(
            keyboard=[[
                KeyboardButton(
                    text=btn_text,
                    request_chat=KeyboardButtonRequestChat(
                        request_id=1001,
                        chat_is_channel=is_channel,
                        chat_has_username=True,
                        request_title=True,
                        request_username=True
                    )
                )
            ]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        msg3 = await bot.send_message(chat_id, _l('👇 Нажмите кнопку внизу клавиатуры:'), reply_markup=fallback_kb)

    state_data["msg_ids"] = [msg1.message_id, msg2.message_id, msg3.message_id]
    promote_user_states[user_id] = state_data


@dp.callback_query(_inline_filter(lambda c: c.data == "promote_cancel"))
@_localized
async def process_promote_cancel(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    state_data = promote_user_states.pop(user_id, None)
    if state_data and "msg_ids" in state_data:
        await _delete_messages(callback.message.chat.id, state_data["msg_ids"], bot)

    rm_msg = await callback.message.answer(_l('❌ <i>Добавление задания отменено.</i>'), reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    try:
        await asyncio.sleep(1)
        await rm_msg.delete()
    except Exception:
        pass

    await send_promote_main_menu(callback.message.chat.id, user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))
    await callback.answer()


@_localized
async def finalize_p2p_promotion_creation(message: types.Message, user_id: int, first_name: str, state_data: dict, real_chat_id: int, chat_title: str, chat_username: str):
    target_type = state_data.get("target_type", "channel")
    price = state_data.get("price", 1)
    subs = state_data.get("subs", 1)
    total_cost = price * subs

    user = get_user(user_id)
    mp_balance = user.get("mp_balance", 0) if user else 0

    if mp_balance < total_cost:
        await message.answer(_lf('<i>Недостаточно MPOINT! Требуется {0} MP, у вас {1} MP.</i>', (_fmt(total_cost, '', -1), _fmt(mp_balance, '', -1))), reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return

    now_iso = get_msk_now().isoformat()
    clean_username = (chat_username or "").strip().lstrip("@")
    try:
        with conn:
            cursor.execute("UPDATE users SET mp_balance = COALESCE(mp_balance, 0) - ? WHERE user_id = ? AND COALESCE(mp_balance, 0) >= ?", (total_cost, user_id, total_cost))
            if cursor.rowcount != 1:
                raise ValueError("Insufficient MP balance")
            cursor.execute("""
                INSERT INTO p2p_promotions (user_id, chat_id, chat_title, chat_username, chat_type, price_per_sub, total_subs, completed_subs, total_spent, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 1, ?)
            """, (user_id, real_chat_id, chat_title, clean_username, target_type, price, subs, total_cost, now_iso))
    except Exception as e:
        logging.error(f"Failed to insert p2p_promotion: {e}")
        await message.answer(_l('<i>Произошла ошибка при сохранении задания. Попробуйте снова.</i>'), reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return

    target_ru = _l('канал') if target_type == "channel" else _l('чат')
    target_label = f"@{clean_username}" if clean_username else chat_title
    succ_text = (
        _lf('<tg-emoji emoji-id="5427009714745517609">✅</tg-emoji><i>{0}, твой {1} {2} успешно добавлен!</i>', (_fmt(html.escape(get_user_display_name(user_id, first_name)), '', -1), _fmt(target_ru, '', -1), _fmt(html.escape(target_label), '', -1)))
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('« В меню продвижения'), callback_data="promote_menu", style="primary")]])
    await message.answer(succ_text, reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    await message.answer(_l('Управляйте заданиями в меню:'), reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.message(_inline_filter(lambda message: message.chat_shared is not None))
@_localized
async def process_chat_shared(message: types.Message):
    if message.chat.type != "private":
        return
    user_id = message.from_user.id
    state_data = promote_user_states.pop(user_id, None)
    if not state_data or state_data.get("step") != "wait_chat":
        await message.reply(_l('<i>Сессия добавления задания истекла. Введите /promote заново.</i>'), reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        return

    if "msg_ids" in state_data:
        await _delete_messages(message.chat.id, state_data["msg_ids"], bot)
    try:
        await message.delete()
    except Exception:
        pass

    chat_id = message.chat_shared.chat_id
    target_type = state_data.get("target_type", "channel")

    shared_title = getattr(message.chat_shared, "title", None)
    shared_username = getattr(message.chat_shared, "username", None)

    real_chat_id = chat_id
    if isinstance(real_chat_id, int) and real_chat_id > 0:
        candidates = [int(f"-100{real_chat_id}"), real_chat_id]
    else:
        candidates = [real_chat_id]

    chat_title = shared_title or (_l('Канал') if target_type == "channel" else _l('Чат'))
    chat_username = (shared_username or "").strip().lstrip("@")

    if not chat_username or not shared_title:
        for cid in candidates:
            try:
                chat_obj = await bot.get_chat(cid)
                if chat_obj:
                    real_chat_id = chat_obj.id
                    if not shared_title and chat_obj.title:
                        chat_title = chat_obj.title
                    if not chat_username and chat_obj.username:
                        chat_username = chat_obj.username.strip().lstrip("@")
                    break
            except Exception as e:
                logging.warning(f"bot.get_chat({cid}) failed: {e}")

    first_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок')
    await finalize_p2p_promotion_creation(message, user_id, first_name, state_data, real_chat_id, chat_title, chat_username)


@dp.callback_query(_inline_filter(lambda c: c.data == "promote_active"))
@_localized
async def process_promote_active(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))

    try:
        cursor.execute("""
            SELECT id, chat_title, chat_type, price_per_sub, total_subs, completed_subs, is_active
            FROM p2p_promotions
            WHERE user_id = ? AND completed_subs < total_subs
            ORDER BY id DESC
        """, (user_id,))
        rows = cursor.fetchall()
    except Exception as e:
        logging.error(f"Error fetching active promotions: {e}")
        rows = []

    text = (
        _lf('🌀 <i>{0}, здесь можно включить и выключить задачи!</i>\n----------------------\n🟢 - вкл. / ⭕️ - выкл. / ❌ - удалить.\n\n<blockquote>ℹ️ Стикер показывают статус задания | название вашего канала/чата/поста | заданная цель / сделанная задача. Если вы удалите задание остаток MP будует возвращен на баланс.</blockquote>', (_fmt(user_link, '', -1),))
    )

    kb_rows = []
    if rows:
        for r in rows:
            p_id, p_title, p_type, p_price, p_total, p_done, p_active = r
            icon = "🟢" if p_active else "⭕️"
            short_title = p_title[:16] + ("..." if len(p_title) > 16 else "")
            btn_label = f"{icon} {short_title} | {p_done}/{p_total}"
            kb_rows.append([
                InlineKeyboardButton(text=btn_label, callback_data=f"promote_toggle_{p_id}", style="primary"),
                InlineKeyboardButton(text="❌", callback_data=f"promote_del_{p_id}", style="danger")
            ])
    else:
        text += _l('\n\n<blockquote><i>У вас пока нет активных заданий.</i></blockquote>')

    kb_rows.append([InlineKeyboardButton(text=_l('« Назад'), callback_data="promote_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("promote_toggle_")))
@_localized
async def process_promote_toggle(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        p_id = int(callback.data.replace("promote_toggle_", ""))
        cursor.execute("UPDATE p2p_promotions SET is_active = NOT is_active WHERE id = ? AND user_id = ?", (p_id, user_id))
        conn.commit()
    except Exception as e:
        logging.error(f"Error toggling promotion: {e}")

    await process_promote_active(callback)


@dp.callback_query(_inline_filter(lambda c: c.data and c.data.startswith("promote_del_")))
@_localized
async def process_promote_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        p_id = int(callback.data.replace("promote_del_", ""))
        cursor.execute("SELECT price_per_sub, total_subs, completed_subs FROM p2p_promotions WHERE id = ? AND user_id = ?", (p_id, user_id))
        row = cursor.fetchone()
        if row:
            p_price, p_total, p_done = row
            remaining = max(0, p_total - p_done)
            refund_mp = remaining * p_price
            cursor.execute("DELETE FROM p2p_promotions WHERE id = ? AND user_id = ?", (p_id, user_id))
            if refund_mp > 0:
                cursor.execute("UPDATE users SET mp_balance = COALESCE(mp_balance, 0) + ? WHERE user_id = ?", (refund_mp, user_id))
            conn.commit()
            await callback.answer(_lf('Задание удалено! Возвращено {0} MP.', (_fmt(refund_mp, '', -1),)), show_alert=True)
        else:
            await callback.answer(_l('Задание не найдено.'), show_alert=True)
    except Exception as e:
        logging.error(f"Error deleting promotion: {e}")
        await callback.answer(_l('Ошибка при удалении задания.'), show_alert=True)

    await process_promote_active(callback)


@dp.callback_query(_inline_filter(lambda c: c.data == "promote_completed"))
@_localized
async def process_promote_completed(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_link = get_user_mention(user_id, get_user_display_name(callback.from_user.id, callback.from_user.first_name))

    try:
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(completed_subs), 0)
            FROM p2p_promotions
            WHERE user_id = ?
        """, (user_id,))
        stats = cursor.fetchone()
        count_tasks, completed_subs = stats if stats else (0, 0)
    except Exception:
        count_tasks, completed_subs = 0, 0

    views = completed_subs * 3
    subs = completed_subs
    joins = completed_subs

    text = (
        _lf('<tg-emoji emoji-id="5312019687746349814">✅</tg-emoji><i> {0}, твои завершенные задачи:</i>\n----------------------\n👀 Показов: <b>{1}</b>\n👥 Подписчиков: <b>{2}</b>\n👫 Вступлений: <b>{3}</b>\n----------------------\n<blockquote>ℹ️ Данная статистика показывает все задания, за все время.</blockquote>', (_fmt(user_link, '', -1), _fmt(format_number(views), '', -1), _fmt(format_number(subs), '', -1), _fmt(format_number(joins), '', -1)))
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('« Назад'), callback_data="promote_menu")]])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.callback_query(_inline_filter(lambda c: c.data == "promote_rules"))
@_localized
async def process_promote_rules(callback: types.CallbackQuery):
    text = (
        _l('<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> <b>Правила добавления заданий:</b>\n----------------------\n1. Канал или чат должен быть публичным и без обязательных заявок на вступление.\n2. Запрещено рекламировать контент, нарушающий правила Telegram (мошенничество, спам, запрещенный контент).\n3. При удалении активного задания остаток неиспользованных MPOINT моментально возвращается на ваш баланс.\n4. Вы можете приостановить выполнение задания в любой момент в разделе «Активные».')
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_l('« Назад'), callback_data="promote_menu")]])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.message(_inline_filter(lambda message: message.text and message.from_user.id in promote_user_states))
@_localized
async def process_promote_text_input(message: types.Message):
    if message.chat.type != "private":
        return
    user_id = message.from_user.id
    state_data = promote_user_states.get(user_id)
    if not state_data:
        return

    if message.text.startswith("/"):
        promote_user_states.pop(user_id, None)
        return

    step = state_data.get("step")

    if step == "wait_chat":
        raw_text = message.text.strip()
        uname = raw_text.replace("https://t.me/", "").replace("http://t.me/", "").replace("t.me/", "").replace("@", "").strip().split("/")[0].split("?")[0]
        if not uname:
            await message.reply(_l('<i>Пожалуйста, укажите корректный юзернейм или ссылку (например: @channel или https://t.me/channel).</i>'), parse_mode=ParseMode.HTML)
            return

        try:
            chat_obj = await bot.get_chat(f"@{uname}")
            if not chat_obj:
                await message.reply(_lf('<i>Не удалось найти публичный канал/чат @{0}. Убедитесь, что он существует.</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
                return
            real_chat_id = chat_obj.id
            chat_title = chat_obj.title or uname
            chat_username = chat_obj.username or uname
        except Exception as e:
            logging.warning(f"Failed to get_chat for @{uname}: {e}")
            await message.reply(_lf('<i>Не удалось найти публичный канал/чат @{0}. Проверьте правильность написания и убедитесь, что канал публичный.</i>', (_fmt(uname, '', -1),)), parse_mode=ParseMode.HTML)
            return

        if "msg_ids" in state_data:
            await _delete_messages(message.chat.id, state_data["msg_ids"], bot)

        promote_user_states.pop(user_id, None)
        first_name = get_user_display_name(message.from_user.id, message.from_user.first_name) or _l('Игрок')
        await finalize_p2p_promotion_creation(message, user_id, first_name, state_data, real_chat_id, chat_title, chat_username)
        return

    raw_val = parse_amount(message.text.strip())

    if step == "price":
        if raw_val is None or raw_val < 1:
            await message.reply(_l('<i>Минимальная цена — 1 MPOINT! Введите корректное число.</i>'), parse_mode=ParseMode.HTML)
            return
        await handle_promote_price_selected(message.chat.id, user_id, get_user_display_name(message.from_user.id, message.from_user.first_name), int(raw_val))
        return

    if step == "subs":
        if raw_val is None or raw_val < 1:
            await message.reply(_l('<i>Количество подписчиков должно быть от 1! Введите корректное число.</i>'), parse_mode=ParseMode.HTML)
            return
        await handle_promote_subs_selected(message.chat.id, user_id, get_user_display_name(message.from_user.id, message.from_user.first_name), int(raw_val))
        return


_ROLE_COMMAND_PATTERN = re.compile(r"^([+-])(?:адм|adm)(?:\s+(.+))?$", re.IGNORECASE)
_ROLE_CUSTOM_EMOJIS = {
    "check": "5312019687746349814",
    "star": "5418238674267556907",
    "warning": "5447644880824181073",
}


def _role_emoji(name, fallback):
    return f'<tg-emoji emoji-id="{_ROLE_CUSTOM_EMOJIS[name]}">{fallback}</tg-emoji>'


def _register_handler_first(observer, handler, *filters):
    observer.register(handler, *(_inline_filter(predicate) for predicate in filters))
    observer.handlers.insert(0, observer.handlers.pop())


@_localized
def _resolve_role_target(message, raw_target=None):
    if raw_target:
        value = raw_target.strip()
        if value.isdigit():
            return int(value), _l('Пользователь'), None
        if value.startswith("@"):
            found = get_user_by_username(value[1:])
            if found:
                return (
                    int(found["user_id"]),
                    found.get("first_name") or value,
                    found.get("username"),
                )
        return None, _l('Пользователь'), None

    reply = getattr(message, "reply_to_message", None)
    replied_user = getattr(reply, "from_user", None)
    if replied_user:
        return (
            int(replied_user.id),
            get_user_display_name(replied_user.id, replied_user.first_name) or _l('Пользователь'),
            replied_user.username,
        )
    return None, _l('Пользователь'), None


def _role_user_link(user_id, name, username=None):
    safe_name = html.escape(get_user_display_name(user_id, name))
    if username:
        return f'<a href="tg://user?id={user_id}">{safe_name} (@{html.escape(username)})</a>'
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def _save_admin_role(user_id, enabled, changed_by):
    if int(user_id) == UNRESTRICTED_OWNER_ID and not enabled:
        return False
    cursor.execute(
        """
        INSERT INTO bot_admin_role_overrides (user_id, enabled, updated_by, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            enabled = excluded.enabled,
            updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (user_id, 1 if enabled else 0, changed_by, datetime.now().isoformat()),
    )
    conn.commit()
    ADMIN_ROLE_OVERRIDES[user_id] = bool(enabled)
    if enabled and user_id not in ADMINS:
        ADMINS.append(user_id)
    elif not enabled and user_id in ADMINS:
        ADMINS.remove(user_id)
    return True


@_localized
async def _handle_admin_role(message: types.Message):
    match = _ROLE_COMMAND_PATTERN.match((message.text or "").strip())
    if not match:
        return

    actor_id = int(message.from_user.id)
    if not is_owner(actor_id):
        await message.reply(
            _lf('{0} <b>МИНЫ · УПРАВЛЕНИЕ ДОСТУПОМ</b>\n━━━━━━━━━━━━━━━━━━\n<b>Изменять роли может только владелец бота.</b>', (_fmt(_role_emoji('warning', '⚠️'), '', -1),)),
            parse_mode=ParseMode.HTML,
        )
        return

    action = match.group(1)
    target_id, target_name, target_username = _resolve_role_target(message, match.group(2))
    if target_id is None or target_id <= 0:
        await message.reply(
            _lf('{0} <b>МИНЫ · УПРАВЛЕНИЕ ДОСТУПОМ</b>\n━━━━━━━━━━━━━━━━━━\n<b>Укажите пользователя</b>\n\n<blockquote>Ответьте на сообщение пользователя или укажите его ID / username.</blockquote>\nПримеры: <code>+ADM @username</code> · <code>-adm 123456789</code>', (_fmt(_role_emoji('warning', '⚠️'), '', -1),)),
            parse_mode=ParseMode.HTML,
        )
        return

    if is_owner(target_id):
        await message.reply(
            _lf('{0} <b>Владельца нельзя понизить до администратора.</b>\nID: <code>{1}</code>', (_fmt(_role_emoji('warning', '⚠️'), '', -1), _fmt(target_id, '', -1))),
            parse_mode=ParseMode.HTML,
        )
        return

    enabled = action == "+"
    was_admin = is_admin(target_id)
    if enabled and was_admin:
        result = _l('Пользователь уже является администратором.')
    elif not enabled and not was_admin:
        result = _l('У пользователя уже нет роли администратора.')
    else:
        try:
            if not _save_admin_role(target_id, enabled, actor_id):
                await message.reply(
                    _lf('{0} <b>Владельца нельзя понизить до администратора.</b>\nID: <code>{1}</code>', (_fmt(_role_emoji('warning', '⚠️'), '', -1), _fmt(target_id, '', -1))),
                    parse_mode=ParseMode.HTML,
                )
                return
            if enabled:
                get_admin_control(target_id)
            _admin_log(
                message.from_user,
                "grant_admin" if enabled else "revoke_admin",
                target_id=target_id,
                target_name=target_name,
            )
            result = _l('Администратор назначен.') if enabled else _l('Права администратора сняты.')
        except Exception:
            await message.reply(
                _lf('{0} <b>Не удалось сохранить изменение.</b>\nПроверьте доступность базы данных и повторите попытку.', (_fmt(_role_emoji('warning', '⚠️'), '', -1),)),
                parse_mode=ParseMode.HTML,
            )
            return

    role_label = _l('АДМИНИСТРАТОР') if enabled else _l('БЫВШИЙ АДМИНИСТРАТОР')
    await message.reply(
        _lf('🐍 <b>МИНЫ · УПРАВЛЕНИЕ ДОСТУПОМ</b>\n━━━━━━━━━━━━━━━━━━\n{0} <b>{1}</b>\n👤 ID: <code>{2}</code>\n🔗 {3}\n\n<blockquote>{4}. Изменение сохранено в SQLite и действует сразу.</blockquote>', (_fmt(_role_emoji('check', '✅'), '', -1), _fmt(html.escape(result), '', -1), _fmt(target_id, '', -1), _fmt(_role_user_link(target_id, target_name, target_username), '', -1), _fmt(role_label, '', -1))),
        parse_mode=ParseMode.HTML,
    )


def _role_command_filter(message):
    return bool(message.from_user and message.text and _ROLE_COMMAND_PATTERN.match(message.text.strip()))


def _message_command_name(message):
    text = (getattr(message, "text", None) or "").strip()
    if not text.startswith("/"):
        return ""
    return text.split(maxsplit=1)[0][1:].split("@", 1)[0].lower()


def _panel_command_filter(message):
    text = (getattr(message, "text", None) or "").strip().lower()
    return text == "панель" or _message_command_name(message) in {"panel", "панель"}


@_localized
def _panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_l('👥 Игроки'), callback_data="creator_panel:players", style="primary"),
                InlineKeyboardButton(text=_l('🎮 Игры'), callback_data="creator_panel:games", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('💰 Экономика'), callback_data="creator_panel:economy", style="success"),
                InlineKeyboardButton(text=_l('📊 Статистика'), callback_data="creator_panel:stats", style="primary"),
            ],
            [
                InlineKeyboardButton(text=_l('📜 Журнал'), callback_data="creator_panel:journal", style="primary"),
                InlineKeyboardButton(text=_l('⚙️ Система'), callback_data="creator_panel:system", style="primary"),
            ],
        ]
    )


@_localized
def _panel_home_text(user_id):
    user_data = get_user(user_id) or {}
    games_played = int(user_data.get("games") or 0)
    level = games_played // 100 + 1
    today = get_msk_today_str()
    transferred_today = int(user_data.get("mp_daily_transferred") or 0)
    if user_data.get("mp_daily_date") != today:
        transferred_today = 0
    rem_limit = get_user_mp_limit(user_data, user_id)
    transfer_limit = "∞" if rem_limit is None else format_number(transferred_today + int(rem_limit))
    role = _l('👑 Владелец') if is_owner(user_id) else _l('🛡 Администратор')
    return (
        _lf('🧿 <b>МИНЫ · ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n━━━━━━━━━━━━━━━━━━\n{0} <b>Система:</b> РАБОТАЕТ\n👤 <b>Роль:</b> {1}\n🆔 <b>Ваш ID:</b> <code>{2}</code>\n━━━━━━━━━━━━━━━━━━\n💰 <b>Баланс:</b> {3} mCoin\n💎 <b>Очки:</b> {4} MPOINT\n{5} <b>Уровень:</b> {6} · Игр: {7}\n🔄 <b>Переводы сегодня:</b> {8} / {9} MPOINT\n━━━━━━━━━━━━━━━━━━\n<i>Выберите раздел управления:</i>', (_fmt(_role_emoji('check', '✅'), '', -1), _fmt(role, '', -1), _fmt(user_id, '', -1), _fmt(format_number(user_data.get('balance') or 0), '', -1), _fmt(format_number(user_data.get('mp_balance') or 0), '', -1), _fmt(_role_emoji('star', '⭐'), '', -1), _fmt(level, '', -1), _fmt(format_number(games_played), '', -1), _fmt(format_number(transferred_today), '', -1), _fmt(transfer_limit, '', -1)))
    )


@_localized
async def _show_admin_panel(message, user_id, edit=False):
    if not is_admin(user_id):
        text = (
            _lf('{0} <b>Панель доступна только администраторам.</b>\nЕсли вам выдали права, отправьте команду ещё раз.', (_fmt(_role_emoji('warning', '⚠️'), '', -1),))
        )
        if edit:
            await message.edit_text(text, parse_mode=ParseMode.HTML)
        else:
            await message.answer(text, parse_mode=ParseMode.HTML)
        return

    text = _panel_home_text(user_id)
    markup = _panel_keyboard()
    if edit:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _handle_panel_command(message: types.Message):
    await _show_admin_panel(message, int(message.from_user.id))


@_localized
def _panel_section_text(section):
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = int(cursor.fetchone()[0] or 0)

    if section == "players":
        admins_count = sum(1 for user_id in ADMINS if is_admin(user_id))
        return (
            _lf('👥 <b>ИГРОКИ</b>\n━━━━━━━━━━━━━━━━━━\nВсего аккаунтов: <b>{0}</b>\nАдминистраторов: <b>{1}</b>\nВладельцев: <b>{2}</b>', (_fmt(format_number(users_count), '', -1), _fmt(admins_count, '', -1), _fmt(len(OWNER_IDS), '', -1)))
        )

    if section == "games":
        cursor.execute("SELECT COALESCE(SUM(games), 0) FROM users")
        games_total = int(cursor.fetchone()[0] or 0)
        cursor.execute("SELECT COUNT(*) FROM games_history")
        history_count = int(cursor.fetchone()[0] or 0)
        return (
            _lf('🎮 <b>ИГРЫ</b>\n━━━━━━━━━━━━━━━━━━\nСыграно всего: <b>{0}</b>\nЗаписей в журнале: <b>{1}</b>\nДоступны: мины, башня, рулетка, слоты и другие игры бота.', (_fmt(format_number(games_total), '', -1), _fmt(format_number(history_count), '', -1)))
        )

    if section == "economy":
        cursor.execute("SELECT COALESCE(SUM(balance), 0), COALESCE(SUM(mp_balance), 0) FROM users")
        row = cursor.fetchone()
        return (
            _lf('💰 <b>ЭКОНОМИКА</b>\n━━━━━━━━━━━━━━━━━━\nmCoin на аккаунтах: <b>{0}</b>\nMPOINT на аккаунтах: <b>{1}</b>', (_fmt(format_number(row[0] or 0), '', -1), _fmt(format_number(row[1] or 0), '', -1)))
        )

    if section == "stats":
        cursor.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN COALESCE(win_amount, 0) > 0 THEN 1 ELSE 0 END), "
            "COALESCE(SUM(win_amount), 0) FROM games_history"
        )
        row = cursor.fetchone()
        return (
            _lf('📊 <b>СТАТИСТИКА</b>\n━━━━━━━━━━━━━━━━━━\nАккаунтов: <b>{0}</b>\nРаундов в журнале: <b>{1}</b>\nРаундов с выигрышем: <b>{2}</b>\nНачислено выигрышей: <b>{3} mCoin</b>', (_fmt(format_number(users_count), '', -1), _fmt(format_number(row[0] or 0), '', -1), _fmt(format_number(row[1] or 0), '', -1), _fmt(format_number(row[2] or 0), '', -1)))
        )

    if section == "journal":
        cursor.execute(
            "SELECT user_id, game_type, bet, win_amount "
            "FROM games_history ORDER BY id DESC LIMIT 6"
        )
        rows = cursor.fetchall()
        if rows:
            entries = "\n".join(
                _lf('• <code>{0}</code> · {1} · ставка {2} · выигрыш {3}', (_fmt(int(row[0]), '', -1), _fmt(html.escape(str(row[1] or _l('игра'))), '', -1), _fmt(format_number(row[2] or 0), '', -1), _fmt(format_number(row[3] or 0), '', -1)))
                for row in rows
            )
        else:
            entries = _l('Журнал пока пуст.')
        return _lf('📜 <b>ПОСЛЕДНИЕ ИГРЫ</b>\n━━━━━━━━━━━━━━━━━━\n{0}', (_fmt(entries, '', -1),))

    if section == "system":
        size_mb = os.path.getsize(SQLITE_DB_PATH) / (1024 * 1024) if os.path.isfile(SQLITE_DB_PATH) else 0
        cursor.execute("PRAGMA quick_check")
        integrity = str(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM demo_modes WHERE enabled = 1")
        demo_count = int(cursor.fetchone()[0] or 0)
        return (
            _lf('⚙️ <b>СИСТЕМА</b>\n━━━━━━━━━━━━━━━━━━\nБот: <b>online</b>\nБаза SQLite: <b>{0}</b>\nРазмер базы: <b>{1} MB</b>\nАктивных creator/demo-режимов: <b>{2}</b>', (_fmt('OK' if integrity == 'ok' else html.escape(integrity), '', -1), _fmt(size_mb, f'.2f', -1), _fmt(demo_count, '', -1)))
        )

    raise ValueError("Unknown panel section")


@_localized
def _panel_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_l('← В панель'), callback_data="creator_panel:home", style="primary")]
        ]
    )


@_localized
async def _handle_panel_callback(callback: types.CallbackQuery):
    user_id = int(callback.from_user.id)
    if not is_admin(user_id):
        await callback.answer(_l('Раздел доступен только администраторам.'), show_alert=True)
        return

    section = str(callback.data).split(":", 1)[1]
    if section == "home":
        await _show_admin_panel(callback.message, user_id, edit=True)
    else:
        try:
            text = _panel_section_text(section)
            await callback.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=_panel_back_keyboard(),
            )
        except Exception:
            await callback.answer(_l('Не удалось загрузить раздел панели.'), show_alert=True)
            return
    await callback.answer()


@_localized
def _creator_mode_text(enabled):
    status = _l('ВКЛЮЧЁН') if enabled else _l('ВЫКЛЮЧЕН')
    status_icon = _role_emoji("check", "✅") if enabled else _role_emoji("warning", "⚠️")
    lines = [
        _l('🧪 <b>МИНЫ · РЕЖИМ СОЗДАТЕЛЯ</b>'),
        "━━━━━━━━━━━━━━━━━━",
        _lf('{0} <b>Статус: {1}</b>', (_fmt(status_icon, '', -1), _fmt(status, '', -1))),
        "",
    ]
    if enabled:
        lines.extend([
            _l('Все поддерживаемые игры для вашего аккаунта используют выигрышную тестовую ветку.'),
            _l('<blockquote>Это изолированный demo-режим: реальные балансы, история, статистика и рейтинги не меняются. На обычные игры других пользователей режим не влияет.</blockquote>'),
            _l('Отключить: <code>/creator_off</code>'),
        ])
    else:
        lines.extend([
            _l('Новые игры снова используют обычные случайные исходы.'),
            _l('<blockquote>Если при включённом режиме остался активный тестовый раунд, он завершится в demo-контексте и не изменит экономику.</blockquote>'),
            _l('Включить: <code>/creator_on</code>'),
        ])
    return "\n".join(lines)


@_localized
async def _set_creator_mode(message: types.Message, enabled):
    user_id = int(message.from_user.id)
    if not is_owner(user_id):
        await message.reply(
            _lf('{0} <b>Режим создателя доступен только владельцам.</b>', (_fmt(_role_emoji('warning', '⚠️'), '', -1),)),
            parse_mode=ParseMode.HTML,
        )
        return
    if not _set_demo_mode(user_id, enabled):
        await message.reply(
            _lf('{0} <b>Не удалось сохранить режим.</b>\nПроверьте доступность базы данных и повторите попытку.', (_fmt(_role_emoji('warning', '⚠️'), '', -1),)),
            parse_mode=ParseMode.HTML,
        )
        return
    _admin_log(
        message.from_user,
        "creator_mode",
        target_id=user_id,
        target_name=message.from_user.first_name,
        details={"enabled": bool(enabled)},
    )
    await message.reply(_creator_mode_text(enabled), parse_mode=ParseMode.HTML)


async def _handle_creator_on(message: types.Message):
    await _set_creator_mode(message, True)


async def _handle_creator_off(message: types.Message):
    await _set_creator_mode(message, False)


_register_handler_first(
    dp.callback_query,
    _handle_panel_callback,
    lambda callback: bool(callback.data and callback.data.startswith("creator_panel:")),
)
_register_handler_first(dp.message, _handle_settings_text, _settings_pending_filter)
_register_handler_first(dp.message, _handle_admin_role, _role_command_filter)
_register_handler_first(dp.message, _handle_panel_command, _panel_command_filter)
_register_handler_first(dp.message, _handle_creator_off, lambda message: _message_command_name(message) == "creator_off")
_register_handler_first(dp.message, _handle_creator_on, lambda message: _message_command_name(message) == "creator_on")


async def on_startup(bot: Bot) -> None:
    try:
        await init_db_pool()
    except Exception as e:
        logging.warning(f"Database init warning: {e}")
    try:
        await get_redis()
    except Exception as e:
        logging.warning(f"Redis init warning: {e}")

    init_caches()
    _restore_unrestricted_owner()
    _start_admin_logging()
    asyncio.create_task(check_expired_games_task())
    asyncio.create_task(check_time_deposits_task())
    asyncio.create_task(accrue_savings_task())
    asyncio.create_task(reset_daily_mp_limits_task())
    asyncio.create_task(p2p_rate_updater_task())
    logging.info("Bot started in polling mode")


async def on_shutdown(bot: Bot) -> None:
    await _stop_admin_logging()
    logging.info("Bot polling stopped")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types()
    )


if __name__ == "__main__":
    asyncio.run(main())