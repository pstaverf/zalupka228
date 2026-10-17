import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import localization
import mines
from tests.test_mines import BotTests

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


class LocaleFlowsTests(BotTests):
    def setUp(self):
        super().setUp()
        self.message.reply = AsyncMock(return_value=SimpleNamespace(message_id=1))
        self.message.answer = AsyncMock(return_value=SimpleNamespace(message_id=1))

    def _call_text(self, mock_fn):
        call = mock_fn.call_args
        return call.kwargs.get("text") if call.kwargs and "text" in call.kwargs else call.args[0]

    def _button_texts(self, markup):
        if markup is None:
            return []
        rows = getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", None) or []
        return [btn.text for row in rows for btn in row]

    async def test_settings_and_language_flow_in_all_languages(self):
        self.message.chat = SimpleNamespace(id=self.uid, type="private")
        for lang, expected_header, expected_back in (
            ("en", "Settings", "Back"),
            ("uk", "Налаштування", "Назад"),
            ("kk", "Баптаулар", "Артқа"),
            ("ru", "Настройки", "Назад"),
        ):
            self.callback.data = f"settings_lang_{lang}"
            self.callback.message.chat = SimpleNamespace(id=self.uid, type="private")
            self.callback.message.edit_text = AsyncMock()
            self.callback.answer = AsyncMock()
            await mines._handle_settings_callback(self.callback)
            edited_text = self._call_text(self.callback.message.edit_text)
            self.assertIn(expected_header, edited_text)

            self.callback.data = "settings_languages"
            self.callback.message.edit_text.reset_mock()
            await mines._handle_settings_callback(self.callback)
            lang_markup = self.callback.message.edit_text.call_args.kwargs["reply_markup"]
            self.assertIn(expected_back, self._button_texts(lang_markup))

    async def test_english_flows_have_no_russian_in_messages_or_buttons(self):
        mines.set_user_settings(self.uid, language="en", bot_nickname="PlayerOne")
        mines.update_user(self.uid, balance=50000, mp_balance=200)

        await mines.cmd_balance(self.message)
        bal_text = self._call_text(self.message.answer)
        self.assertIsNone(CYRILLIC_RE.search(bal_text), bal_text)

        self.message.answer.reset_mock()
        await mines.cmd_point(self.message)
        mp_text = self._call_text(self.message.answer)
        self.assertIsNone(CYRILLIC_RE.search(mp_text), mp_text)

        self.message.answer.reset_mock()
        await mines.show_top(self.message)
        top_text = self._call_text(self.message.answer)
        top_markup = self.message.answer.call_args.kwargs.get("reply_markup")
        self.assertIsNone(CYRILLIC_RE.search(top_text), top_text)
        for btn_text in self._button_texts(top_markup):
            self.assertIsNone(CYRILLIC_RE.search(btn_text), btn_text)

        self.message.answer.reset_mock()
        await mines.show_records(self.message)
        rec_text = self._call_text(self.message.answer)
        self.assertIsNone(CYRILLIC_RE.search(rec_text), rec_text)

        mines.games.clear()
        mines.active_games.clear()
        self.message.answer.reset_mock()
        self.message.edit_text.reset_mock()
        await mines.start_mines_game_from_command(self.message, self.uid, self.uid, 100, 3)
        call = self.message.edit_text.call_args or self.message.answer.call_args
        game_text = call.kwargs.get("text") if call.kwargs and "text" in call.kwargs else call.args[0]
        game_markup = call.kwargs.get("reply_markup")
        self.assertIsNone(CYRILLIC_RE.search(game_text), game_text)
        for btn_text in self._button_texts(game_markup):
            self.assertIsNone(CYRILLIC_RE.search(btn_text), btn_text)

    async def test_nicknames_and_usernames_are_not_translated_and_are_html_escaped(self):
        receiver_id = 8888
        mines.get_user(receiver_id)
        mines.save_username(receiver_id, "user_name_raw", "RawName")
        mines.set_user_settings(self.uid, language="en", bot_nickname="Назад <script>&")
        mines.set_user_settings(receiver_id, language="uk", bot_nickname="Выход <b>&")
        mines.update_user(self.uid, balance=10000)

        self.message.text = "дать 500"
        self.message.reply_to_message = SimpleNamespace(
            from_user=SimpleNamespace(id=receiver_id, first_name="RawName", username="user_name_raw")
        )
        with patch.object(mines.bot, "send_message", new_callable=AsyncMock) as send_mock:
            await mines.cmd_transfer(self.message)

        reply_text = self._call_text(self.message.reply)
        self.assertIn("Назад &lt;script&gt;&amp;", reply_text)
        self.assertIn("Выход &lt;b&gt;&amp;", reply_text)
        self.assertNotIn("<script>", reply_text)

        dm_text = send_mock.call_args.kwargs["text"]
        self.assertIn("Назад &lt;script&gt;&amp;", dm_text)
        self.assertNotIn("<script>", dm_text)


if __name__ == "__main__":
    unittest.main()
