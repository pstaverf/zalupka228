import inspect
import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps
from pathlib import Path
import re


LANGUAGES = ("ru", "en", "uk", "kk")
_LANGUAGE_ALIASES = {
    "ru": "ru",
    "en": "en",
    "uk": "uk",
    "ua": "uk",
    "kk": "kk",
    "kz": "kk",
}
_USER = ContextVar("locale_user", default=None)
_LANGUAGE = ContextVar("locale_language", default=None)
_language_getter = None
_language_ensurer = None
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_PARTS = re.compile(r"(<[^>]*>|\n)")
_EDGE = re.compile(r"[A-Za-zА-Яа-яЁё0-9{}]")
_FIELD = re.compile(r"(?<!\{)\{(\d+)\}(?!\})")
_CATALOG_PATH = Path(__file__).with_name("locales") / "messages.json"
_INTERFACE_PATH = Path(__file__).with_name("locales") / "interface.json"
CATALOG = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
INTERFACE = json.loads(_INTERFACE_PATH.read_text(encoding="utf-8"))


class UserSettings(dict):
    def __init__(
        self,
        user_id=0,
        language="ru",
        bot_nickname=None,
        hide_top_username=False,
        demo_balance=None,
    ):
        language = language if language in LANGUAGES else "ru"
        super().__init__(
            user_id=int(user_id),
            language=language,
            bot_nickname=bot_nickname,
            hide_top_username=bool(hide_top_username),
            demo_balance=int(demo_balance) if demo_balance is not None else None,
        )

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        if name == "language":
            value = value if value in LANGUAGES else "ru"
        elif name == "user_id":
            value = int(value)
        elif name == "hide_top_username":
            value = bool(value)
        elif name == "demo_balance" and value is not None:
            value = int(value)
        self[name] = value

    def copy(self):
        return UserSettings(**self)

    def to_dict(self):
        return dict(self)


def telegram_language(language_code=None, default="en"):
    if language_code is not None and not isinstance(language_code, str):
        actor = getattr(language_code, "from_user", None)
        language_code = getattr(language_code, "language_code", None)
        if language_code is None and actor is not None:
            language_code = getattr(actor, "language_code", None)
    if not isinstance(language_code, str):
        return default
    normalized = language_code.strip().lower().replace("_", "-")
    if not normalized:
        return default
    primary = normalized.split("-", 1)[0]
    return _LANGUAGE_ALIASES.get(primary, "en")


def configure(language_getter, language_ensurer=None):
    global _language_getter, _language_ensurer
    _language_getter = language_getter
    _language_ensurer = language_ensurer


def current_language(user_id=None):
    if user_id is None and _LANGUAGE.get() is not None:
        return _LANGUAGE.get()
    uid = user_id if user_id is not None else _USER.get()
    if uid is None or _language_getter is None:
        return "ru"
    language = _language_getter(int(uid))
    return language if language in LANGUAGES else "ru"


@contextmanager
def language_context(language):
    if language not in LANGUAGES:
        raise ValueError("Unsupported language")
    token = _LANGUAGE.set(language)
    try:
        yield
    finally:
        _LANGUAGE.reset(token)


def localized(function):
    parameters = tuple(inspect.signature(function).parameters)
    user_parameter = next((name for name in parameters if name in ("user_id", "admin_id", "owner_id", "buyer_id", "seller_id")), None)
    user_index = parameters.index(user_parameter) if user_parameter else None
    actor_parameters = tuple((name, parameters.index(name)) for name in ("callback", "message", "event", "message_or_callback", "target", "message_obj") if name in parameters)
    def enter(args, kwargs):
        uid = kwargs.get(user_parameter) if user_parameter else None
        if uid is None and user_index is not None and user_index < len(args):
            uid = args[user_index]
        actor_obj = None
        for name, index in actor_parameters:
            event = kwargs.get(name, args[index] if index < len(args) else None)
            actor = getattr(event, "from_user", None)
            if actor is not None and getattr(actor, "is_bot", False) is not True:
                actor_obj = actor
                if uid is None:
                    uid = getattr(actor, "id", None)
                break
        if actor_obj is not None and _language_ensurer is not None:
            _language_ensurer(actor_obj)
        return _USER.set(int(uid)) if uid is not None else None
    if inspect.iscoroutinefunction(inspect.unwrap(function)):
        @wraps(function)
        async def asynchronous(*args, **kwargs):
            token = enter(args, kwargs)
            try:
                return await function(*args, **kwargs)
            finally:
                if token is not None:
                    _USER.reset(token)
        return asynchronous
    @wraps(function)
    def synchronous(*args, **kwargs):
        token = enter(args, kwargs)
        try:
            return function(*args, **kwargs)
        finally:
            if token is not None:
                _USER.reset(token)
    return synchronous


def fragment_key(fragment):
    if not _CYRILLIC.search(fragment):
        return None
    positions = list(_EDGE.finditer(fragment))
    if not positions:
        return None
    start, end = positions[0].start(), positions[-1].end()
    indices = []
    def normalize(match):
        index = match.group(1)
        if index not in indices:
            indices.append(index)
        return "{" + str(indices.index(index)) + "}"
    key = _FIELD.sub(normalize, fragment[start:end])
    return start, end, key, indices


def template_keys(template):
    for part in _PARTS.split(template):
        if part.startswith("<") or part == "\n":
            continue
        key = fragment_key(part)
        if key is not None:
            yield key[2]


@lru_cache(maxsize=8192)
def translate_template(template, language):
    if language == "ru":
        return template
    parts = _PARTS.split(template)
    for index, part in enumerate(parts):
        if part.startswith("<") or part == "\n":
            continue
        item = fragment_key(part)
        if item is None:
            continue
        start, end, key, indices = item
        translated = CATALOG.get(key, {}).get(language)
        if translated is None:
            continue
        translated = _FIELD.sub(lambda match: "{" + indices[int(match.group(1))] + "}", translated)
        suffix = part[end:]
        if key.endswith("(-а") and suffix.startswith(")") and translated.count("(") == translated.count(")"):
            suffix = suffix[1:]
        parts[index] = part[:start] + translated + suffix
    return "".join(parts)


def text(source, *, user_id=None):
    return translate_template(source, current_language(user_id))


def formatted(source, values, *, user_id=None):
    return translate_template(source, current_language(user_id)).format(*values)


def format_value(value, spec="", conversion=-1):
    if conversion == 114:
        value = repr(value)
    elif conversion == 115:
        value = str(value)
    elif conversion == 97:
        value = ascii(value)
    return format(value, spec)


def label(value, *, user_id=None):
    if not isinstance(value, str):
        return value
    return text(value, user_id=user_id)


PROMPT_MARKERS = (
    "ДЕПОЗИТ НА", "ПОПОЛНИТЬ НАКОП. СЧЕТ", "СНЯТЬ С НАКОП. СЧЕТА",
    "Заблокировать снятие", "КУПИТЬ MPOINT", "ПРОДАТЬ MPOINT",
    "Сколько mCoin пополняем", "Сколько MPOINT пополняем", "ПОПОЛНЕНИЕ mCoin", "ПОПОЛНЕНИЕ MPOINT",
    "ВЫВОД mCoin", "ВЫВОД MPOINT", "Сколько mCoin выводим", "Сколько MPOINT выводим",
    "ИЗМЕНИТЬ КУРС ПРОДАЖИ", "ИЗМЕНИТЬ КУРС ПОКУПКИ", "Оф. Покупка", "Оф. Продажа", "Продавец", "Покупатель",
)


@lru_cache(maxsize=1)
def _prompt_rules():
    rules = []
    for source, translations in CATALOG.items():
        if not any(marker in source for marker in PROMPT_MARKERS):
            continue
        for language in ("en", "uk", "kk"):
            target = translations[language]
            if target == source:
                continue
            chunks = _FIELD.split(target)
            pattern = ""
            seen = set()
            for position, chunk in enumerate(chunks):
                if position % 2:
                    if chunk in seen:
                        pattern += f"(?P=v{chunk})"
                    else:
                        if source == "ДЕПОЗИТ НА {0} {1}":
                            value_pattern = r"\d{1,3}" if chunk == "0" else r"[^\W\d_]{1,24}"
                        elif source == "Заблокировать снятие {0}":
                            value_pattern = "[✅❌]"
                        else:
                            value_pattern = r"[^<>\n]{1,64}?"
                        pattern += f"(?P<v{chunk}>{value_pattern})"
                        seen.add(chunk)
                else:
                    pattern += re.escape(chunk)
            rules.append((re.compile(pattern), source))
    return tuple(sorted(rules, key=lambda item: len(item[0].pattern), reverse=True))


@lru_cache(maxsize=512)
def canonical_prompt(value):
    if not value:
        return value or ""
    for pattern, source in _prompt_rules():
        value = pattern.sub(lambda match: _FIELD.sub(lambda field: match.group("v" + field.group(1)), source), value)
    return value


def _choice_key(value):
    value = re.sub(r"\s*(?:\([xх][\d.,]+\)|[xх][\d.,]+)\s*$", "", value.casefold())
    value = re.sub(r"^[^\w<>=]+", "", value)
    return re.sub(r"[\s-]+", "", value).replace("ё", "е")


@lru_cache(maxsize=128)
def _choice_aliases(choices):
    aliases = {}
    for source, canonical in choices:
        for language in LANGUAGES:
            aliases[_choice_key(translate_template(source, language))] = canonical
    return aliases


def canonical_choice(value, choices):
    return _choice_aliases(choices).get(_choice_key(value or ""), value)
