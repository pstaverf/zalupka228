import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import localization
import mines
from tests.test_mines import BotTests

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "tests" / "locale_contract.json"
INTERFACE_PATH = ROOT / "locales" / "interface.json"


class LocaleEntryTests(BotTests):
    def setUp(self):
        super().setUp()
        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_contract_digests_match_schema_and_settings(self):
        schema_sha256 = hashlib.sha256(mines.SQLITE_SCHEMA_SQL.encode("utf-8")).hexdigest()
        indexes_sha256 = hashlib.sha256("\n".join(mines.SQLITE_INDEXES).encode("utf-8")).hexdigest()
        interface_keys = list(localization.INTERFACE["ru"].keys())
        interface_keys_sha256 = hashlib.sha256("\n".join(interface_keys).encode("utf-8")).hexdigest()
        settings_defaults = mines.UserSettings(user_id=0).to_dict()
        settings_defaults_sha256 = hashlib.sha256(
            json.dumps(settings_defaults, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        self.assertEqual(self.contract["languages"], list(localization.LANGUAGES))
        self.assertEqual(self.contract["default_language"], "ru")
        self.assertEqual(self.contract["fallback_telegram_language"], "en")
        self.assertEqual(self.contract["interface_key_count"], 53)
        self.assertEqual(self.contract["interface_keys"], interface_keys)
        self.assertEqual(self.contract["interface_keys_sha256"], interface_keys_sha256)
        self.assertEqual(self.contract["sqlite_schema_sha256"], schema_sha256)
        self.assertEqual(self.contract["sqlite_indexes_sha256"], indexes_sha256)
        self.assertEqual(self.contract["settings_defaults"], settings_defaults)
        self.assertEqual(self.contract["settings_defaults_sha256"], settings_defaults_sha256)

    def test_interface_catalog_has_53_keys_per_language(self):
        raw_interface = json.loads(INTERFACE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(tuple(raw_interface.keys()), localization.LANGUAGES)
        expected_keys = set(self.contract["interface_keys"])
        self.assertEqual(len(expected_keys), 53)
        for lang in localization.LANGUAGES:
            self.assertEqual(set(raw_interface[lang].keys()), expected_keys)
            self.assertEqual(set(mines.TRANSLATIONS[lang].keys()), expected_keys)
            for key, value in raw_interface[lang].items():
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip(), f"{lang}:{key} must not be empty")

    def test_telegram_language_autodetection_and_fallback(self):
        self.assertEqual(localization.telegram_language("ru"), "ru")
        self.assertEqual(localization.telegram_language("ru-RU"), "ru")
        self.assertEqual(localization.telegram_language("en"), "en")
        self.assertEqual(localization.telegram_language("en-US"), "en")
        self.assertEqual(localization.telegram_language("uk"), "uk")
        self.assertEqual(localization.telegram_language("uk_UA"), "uk")
        self.assertEqual(localization.telegram_language("ua"), "uk")
        self.assertEqual(localization.telegram_language("kk"), "kk")
        self.assertEqual(localization.telegram_language("kk-KZ"), "kk")
        self.assertEqual(localization.telegram_language("kz"), "kk")
        self.assertEqual(localization.telegram_language("de"), "en")
        self.assertEqual(localization.telegram_language("fr-FR"), "en")
        self.assertEqual(localization.telegram_language(""), "en")
        self.assertEqual(localization.telegram_language(None), "en")
        self.assertEqual(localization.telegram_language(None, default="ru"), "ru")

    def test_user_settings_model_and_persistence(self):
        settings = mines.get_user_settings(self.uid)
        self.assertIsInstance(settings, localization.UserSettings)
        self.assertEqual(settings.user_id, self.uid)
        self.assertEqual(settings.language, "ru")
        self.assertEqual(settings["language"], "ru")
        self.assertIsNone(settings.bot_nickname)
        self.assertFalse(settings.hide_top_username)
        self.assertIsNone(settings.demo_balance)

        self.assertTrue(mines.set_user_settings(self.uid, language="kk", bot_nickname="Tester", hide_top_username=True))
        updated = mines.get_user_settings(self.uid)
        self.assertIsInstance(updated, localization.UserSettings)
        self.assertEqual(updated.language, "kk")
        self.assertEqual(updated.bot_nickname, "Tester")
        self.assertTrue(updated.hide_top_username)

        mines._settings_cache.clear()
        reloaded = mines.get_user_settings(self.uid)
        self.assertEqual(reloaded.language, "kk")
        self.assertEqual(reloaded.bot_nickname, "Tester")
        self.assertTrue(reloaded.hide_top_username)

    async def test_language_command_and_callback_apply_immediately(self):
        self.message.text = "/language"
        self.message.answer = AsyncMock()
        await mines.cmd_language(self.message)
        first_text = self.message.answer.call_args.args[0]
        markup = self.message.answer.call_args.kwargs["reply_markup"]
        buttons = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertIn("settings_lang_ru", buttons)
        self.assertIn("settings_lang_en", buttons)
        self.assertIn("settings_lang_uk", buttons)
        self.assertIn("settings_lang_kk", buttons)
        self.assertIn("Русский", first_text)

        for lang, expected_title in (
            ("en", "Interface language"),
            ("uk", "Мова інтерфейсу"),
            ("kk", "Интерфейс тілі"),
            ("ru", "Язык интерфейса"),
        ):
            self.callback.data = f"settings_lang_{lang}"
            self.callback.message.chat = SimpleNamespace(id=self.uid, type="private")
            self.callback.message.edit_text = AsyncMock()
            self.callback.answer = AsyncMock()
            await mines._handle_settings_callback(self.callback)
            self.assertEqual(mines.get_user_language(self.uid), lang)
            self.message.answer.reset_mock()
            await mines.cmd_language(self.message)
            self.assertIn(expected_title, self.message.answer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
