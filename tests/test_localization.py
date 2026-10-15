import ast
import asyncio
from collections import Counter
from datetime import datetime, timedelta
import html
from pathlib import Path
import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import localization
import test_mines as fixtures


mines = fixtures.mines
ROOT = Path(__file__).resolve().parents[1]
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
FIELDS = re.compile(r"(?<!\{)\{(\d+)\}(?!\})")
TAGS = re.compile(r"<[^>]*>")


def templates():
    for node in ast.walk(ast.parse((ROOT / "mines.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"_l", "_lf"}:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                yield node.func.id, node.args[0].value, node.lineno


def message_text(mock):
    call = mock.call_args
    return call.kwargs.get("text") or (call.args[0] if call.args else call.kwargs.get("caption", ""))


def callback_ids(keyboard):
    return [[(button.callback_data, button.url, button.style, button.icon_custom_emoji_id) for button in row] for row in keyboard.inline_keyboard]


class CatalogTests(unittest.TestCase):
    def test_every_template_and_metadata_label_has_all_translations(self):
        keys = set()
        count = 0
        for kind, source, line in templates():
            keys.update(localization.template_keys(source))
            count += 1
        for name in ("TASKS_INFO", "DICE_CHOICES", "COIN_NAMES", "FISHING_OUTCOMES", "SCRATCH_SYMBOL_META", "TEMPLE_GIFTS"):
            def collect(value):
                if isinstance(value, str):
                    keys.update(localization.template_keys(value))
                elif isinstance(value, dict):
                    for item in value.values():
                        collect(item)
                elif isinstance(value, (tuple, list)):
                    for item in value:
                        collect(item)
            collect(getattr(mines, name))
        self.assertGreater(count, 1600)
        self.assertGreater(len(keys), 1200)
        self.assertFalse(keys - localization.CATALOG.keys(), sorted(keys - localization.CATALOG.keys()))
        for key, translations in localization.CATALOG.items():
            self.assertEqual(set(translations), {"en", "uk", "kk"}, key)
            for language, target in translations.items():
                self.assertTrue(target.strip(), (key, language))
                self.assertEqual(Counter(FIELDS.findall(key)), Counter(FIELDS.findall(target)), (key, language))
        for language in localization.LANGUAGES:
            self.assertEqual(set(mines.TRANSLATIONS["ru"]), set(mines.TRANSLATIONS[language]))

    def test_every_rendered_template_preserves_html_and_fields(self):
        for kind, source, line in templates():
            for language in localization.LANGUAGES:
                with self.subTest(line=line, language=language):
                    target = localization.translate_template(source, language)
                    self.assertEqual(TAGS.findall(source), TAGS.findall(target))
                    self.assertEqual(Counter(FIELDS.findall(source)), Counter(FIELDS.findall(target)))
                    if language == "ru":
                        self.assertEqual(target, source)
                    if language == "en":
                        self.assertIsNone(CYRILLIC.search(target), target)
                    if kind == "_lf":
                        fields = FIELDS.findall(source)
                        size = max(map(int, fields), default=-1) + 1
                        values = tuple(f"__VALUE_{index}__" for index in range(size))
                        rendered = target.format(*values)
                        original = source.format(*values)
                        for value in values:
                            self.assertEqual(original.count(value), rendered.count(value))

    def test_raw_user_values_are_never_translated_or_reformatted(self):
        raw = 'Назад Победа {0} <tag> & "quote"'
        for language in localization.LANGUAGES:
            with localization.language_context(language):
                rendered = localization.formatted("Комментарий: {0}", (raw,))
                self.assertTrue(rendered.endswith(raw))
                self.assertEqual(rendered.count(raw), 1)
                self.assertEqual(localization.formatted("Игрок: {0}", (raw,)).split(": ", 1)[1], raw)

    def test_format_conversion_matches_python_fstrings(self):
        for value in (1234, 1.23456, "строка", {"x": 1}, None):
            for conversion in (-1, 97, 114, 115):
                expected = value
                if conversion == 97:
                    expected = ascii(value)
                elif conversion == 114:
                    expected = repr(value)
                elif conversion == 115:
                    expected = str(value)
                self.assertEqual(localization.format_value(value, "", conversion), format(expected, ""))
        self.assertEqual(localization.format_value(1.2345, ".2f"), "1.23")
        self.assertEqual(localization.format_value(1234, ","), "1,234")
        self.assertEqual(localization.formatted("Сумма: {0} {{literal}}", ("{1}",)), "Сумма: {1} {literal}")

    def test_language_context_restored_after_exception(self):
        before = localization.current_language()
        with self.assertRaises(RuntimeError):
            with localization.language_context("kk"):
                self.assertEqual(localization.text("Назад"), "Артқа")
                raise RuntimeError("test")
        self.assertEqual(localization.current_language(), before)

    def test_all_prompt_markers_roundtrip_in_every_language(self):
        sources = [key for key in localization.CATALOG if any(marker in key for marker in localization.PROMPT_MARKERS)]
        self.assertGreater(len(sources), 15)
        for source in sources:
            for language in localization.LANGUAGES:
                with self.subTest(source=source, language=language):
                    target = localization.translate_template(source, language)
                    indices = FIELDS.findall(source)
                    values = ("15", "DAYS") if source == "ДЕПОЗИТ НА {0} {1}" else (("✅",) if indices else ())
                    expected = source.format(*values)
                    rendered = target.format(*values)
                    self.assertEqual(localization.canonical_prompt(rendered), expected)

    def test_existing_language_autonyms_and_callback_ids_stay_fixed(self):
        for language in localization.LANGUAGES:
            with localization.language_context(language):
                keyboard = mines._language_keyboard(1234)
                self.assertEqual([button.text for row in keyboard.inline_keyboard[:2] for button in row], ["Русский", "English", "Українська", "Қазақша"])
                self.assertEqual([button.callback_data for row in keyboard.inline_keyboard[:2] for button in row], ["settings_lang_ru", "settings_lang_en", "settings_lang_uk", "settings_lang_kk"])


    def test_prompt_patterns_are_bounded_and_safe_for_long_keyboard_repr(self):
        for pattern, source in localization._prompt_rules():
            self.assertNotIn("+?", pattern.pattern)
            self.assertNotIn(".*", pattern.pattern)
        value = "InlineKeyboardButton(text='Back', callback_data='noop'), " * 200
        self.assertEqual(localization.canonical_prompt(value), value)
        self.assertEqual(localization.canonical_prompt(None), "")

    def test_gendered_transfer_phrases_do_not_leave_unmatched_parentheses(self):
        for source in ("{0} передал(-а) ", "{0} перевел(-а) "):
            for language in localization.LANGUAGES:
                rendered = localization.translate_template(source, language).format("Sender")
                self.assertEqual(rendered.count("("), rendered.count(")"), (language, rendered))

    def test_unwrapped_russian_literals_are_only_input_protocol_or_autonyms(self):
        tree = ast.parse((ROOT / "mines.py").read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        failures = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or not CYRILLIC.search(node.value):
                continue
            ancestors = []
            parent = node
            while parent in parents:
                parent = parents[parent]
                ancestors.append(parent)
            function = next((item for item in ancestors if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
            if function is None or node.lineno < function.body[0].lineno:
                continue
            if function.name in {"is_bot_command", "parse_ban_duration"}:
                continue
            if function.name in {"init_caches", "ban_user"} and node.value == "Навсегда":
                continue
            if function.name == "_language_keyboard" and node.value in mines.LANGUAGE_NAMES.values():
                continue
            if any(isinstance(item, (ast.Compare, ast.Lambda)) for item in ancestors):
                continue
            if any(isinstance(item, ast.Dict) and node in item.keys for item in ancestors):
                continue
            allowed = False
            for item in ancestors:
                if not isinstance(item, ast.Call):
                    continue
                name = ast.unparse(item.func)
                if name in {"_l", "_lf", "_canonical_choice", "tr"} or name.startswith(("re.", "logging.", "logger.")):
                    allowed = True
                if isinstance(item.func, ast.Attribute) and item.func.attr in {"replace", "strip", "lstrip", "rstrip", "startswith", "endswith", "split", "rsplit", "strftime", "strptime"}:
                    if any(node is argument or node in ast.walk(argument) for argument in item.args):
                        allowed = True
            if not allowed:
                failures.append((node.lineno, function.name, node.value))
        self.assertEqual(failures, [])


    def test_translations_do_not_mix_latin_and_cyrillic_inside_words(self):
        mixed = re.compile(r"[А-Яа-яЁёІіЇїЄєӘәҚқҢңҒғӨөҮүҰұҺһ][A-Za-z]|[A-Za-z][А-Яа-яЁёІіЇїЄєӘәҚқҢңҒғӨөҮүҰұҺһ]")
        for source, translations in localization.CATALOG.items():
            for language, target in translations.items():
                self.assertIsNone(mixed.search(target), (source, language, target))

    def test_ban_examples_have_parseable_durations_in_every_language(self):
        examples = 0
        for kind, source, line in templates():
            if "<code>/ban " not in source:
                continue
            for language in localization.LANGUAGES:
                target = localization.translate_template(source, language)
                for code in re.findall(r"<code>(/ban .*?)</code>", target):
                    duration, permanent = mines.parse_ban_duration(code.split()[-1])
                    self.assertTrue(permanent or duration == timedelta(hours=1), (language, code))
                    examples += 1
        self.assertGreaterEqual(examples, 16)


class StopTick(BaseException):
    pass


class LocalizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.BotTests.setUp(self)
        self.message.reply = AsyncMock(return_value=SimpleNamespace(message_id=1))
        self.message.delete = AsyncMock()
        self.message.reply_to_message = None
        self.message.caption = None
        self.message.successful_payment = None
        self.message.photo = None
        self.user.is_bot = False
        mines.p2p_user_action.clear()
        mines.admin_sexchange_state.clear()
        mines.mp_pending_transfers.clear()
        mines._banned_users_cache.clear()
        mines._transfer_banned_users.clear()
        mines._top_banned_users.clear()
        mines.cursor.execute("DELETE FROM referrals")
        mines.conn.commit()

    def tearDown(self):
        mines._banned_users_cache.clear()
        mines.p2p_user_action.clear()
        mines.admin_sexchange_state.clear()
        mines.mp_pending_transfers.clear()

    def language(self, language):
        self.assertTrue(mines.set_user_settings(self.uid, language=language))

    def assert_english(self, text):
        self.assertIsNone(CYRILLIC.search(text), text)

    async def handler_matches(self, name, message=None):
        handlers = [handler for handler in mines.dp.message.handlers if handler.callback.__name__ == name]
        for handler in handlers:
            matches, _ = await handler.check(message or self.message, bot=mines.bot)
            if matches:
                return True
        return False

    async def test_language_switch_is_persisted_and_applies_immediately(self):
        for language, expected in (("en", "Back"), ("uk", "Назад"), ("kk", "Артқа"), ("ru", "Назад")):
            self.callback.data = "settings_lang_" + language
            await mines._handle_settings_callback(self.callback)
            self.assertEqual(mines.get_user_language(self.uid), language)
            mines._settings_cache.clear()
            self.assertEqual(mines.get_user_language(self.uid), language)
            keyboard = mines.build_deposit_term_input_menu(self.uid, "Telegram Name", 1)[1]
            self.assertTrue(any(button.text == expected for row in keyboard.inline_keyboard for button in row))

    async def test_all_game_help_is_translated_and_preserves_commands(self):
        for language in localization.LANGUAGES:
            self.language(language)
            for name in ("mines", "tower", "qwak", "diamonds", "twentyone", "gold", "crash", "slots", "bowling", "dice", "coin", "roulette", "chest", "scratch", "fishing", "darts", "basketball", "football"):
                with self.subTest(language=language, game=name):
                    self.message.answer.reset_mock()
                    await getattr(mines, "show_" + name + "_info")(self.message, self.uid)
                    rendered = message_text(self.message.answer)
                    self.assertIn("Telegram Name", rendered)
                    self.assertIn("m", rendered)
                    if language == "en":
                        self.assert_english(rendered)
                    self.assertIn("<code>", rendered)

    async def test_game_keyboards_translate_without_changing_callbacks_or_odds(self):
        builders = (mines.get_dice_choice_keyboard, mines.get_coin_choice_keyboard, mines.get_bowling_choice_keyboard, mines.get_darts_choice_keyboard, mines.get_basketball_choice_keyboard, mines.get_football_choice_keyboard, mines.get_roulette_main_keyboard, mines.get_roulette_numbers_keyboard, mines.get_roulette_streets_keyboard)
        for builder in builders:
            with localization.language_context("ru"):
                original = builder(100)
            for language in localization.LANGUAGES:
                with self.subTest(builder=builder.__name__, language=language):
                    with localization.language_context(language):
                        keyboard = builder(100)
                    self.assertEqual(callback_ids(keyboard), callback_ids(original))
                    if language == "en":
                        self.assert_english(" ".join(button.text for row in keyboard.inline_keyboard for button in row))

    async def test_localized_choices_keep_same_codes_and_coefficients(self):
        cases = (
            (mines.parse_dice_choice, "Больше 3-х", "gt3", 1.97),
            (mines.parse_dice_choice, "Меньше 3-х", "lt3", 2.32),
            (mines.parse_dice_choice, "Равно 3", "eq3", 5.8),
            (mines.parse_dice_choice, "Чёт", "even", 2.23),
            (mines.parse_dice_choice, "Нечёт", "odd", 2.23),
            (mines.parse_coin_choice, "Орёл", "heads", 1.97),
            (mines.parse_coin_choice, "Решка", "tails", 1.97),
            (mines.parse_darts_choice, "Красное", "red", 1.94),
            (mines.parse_darts_choice, "Белое", "white", 2.9),
            (mines.parse_darts_choice, "Центр", "center", 5.8),
            (mines.parse_basketball_choice, "Попадание", "hit", 2.4),
            (mines.parse_basketball_choice, "Застрял мяч", "stuck", 4.8),
            (mines.parse_football_choice, "Гол", "goal", 1.6),
            (mines.parse_football_choice, "Мимо", "miss", 2.4),
            (mines.parse_roulette_choice, "Чёрный", "black", 1.97),
            (mines.parse_roulette_choice, "Чётный", "even", 1.97),
            (mines.parse_roulette_choice, "Нечётный", "odd", 1.97),
        )
        for parser, source, code, coefficient in cases:
            for language in localization.LANGUAGES:
                with self.subTest(parser=parser.__name__, source=source, language=language):
                    translated = localization.translate_template(source, language)
                    with localization.language_context(language):
                        result = parser(translated)
                        self.assertEqual(result[0], code)
                        self.assertEqual(result[2], coefficient)
                        self.assertEqual(parser(source)[0], code)
        for language in localization.LANGUAGES:
            with localization.language_context(language):
                self.assertEqual(mines.parse_bowling_choice(localization.text("Страйк (6 кеглей)"))[0], 6)
                self.assertEqual(mines.parse_bowling_choice(localization.text("Мимо (0 кеглей)"))[0], 1)
                self.assertEqual(mines.parse_roulette_choice(localization.formatted("{0} ряд", ("1",)))[0], "row1")

    async def test_bank_prompts_keep_days_and_lock_across_language_switches(self):
        mines.update_user(self.uid, balance=1000000)
        for language in localization.LANGUAGES:
            for days in (1, 3, 7, 15, 30, 60):
                for locked in (0, 1):
                    with self.subTest(language=language, days=days, locked=locked):
                        self.language(language)
                        text, keyboard = mines.build_deposit_term_input_menu(self.uid, "Telegram Name", days, locked)
                        self.message.reply_to_message = SimpleNamespace(text=text, caption=None, reply_markup=keyboard)
                        self.message.text = "1000"
                        self.language("en" if language != "en" else "kk")
                        self.assertTrue(await self.handler_matches("process_bank_reply_message"))
                        await mines.process_bank_reply_message(self.message)
                        mines.cursor.execute("SELECT amount, days, is_locked FROM time_deposits WHERE user_id=? ORDER BY id DESC LIMIT 1", (self.uid,))
                        self.assertEqual(tuple(mines.cursor.fetchone()), (1000, days, locked))

    async def test_savings_reply_deposit_and_withdraw_in_all_languages(self):
        mines.update_user(self.uid, balance=10000)
        for language in localization.LANGUAGES:
            self.language(language)
            text, keyboard = mines.build_savings_deposit_input_menu(self.uid, "Telegram Name")
            self.message.reply_to_message = SimpleNamespace(text=None, caption=text, reply_markup=keyboard)
            self.message.text = "100"
            self.assertTrue(await self.handler_matches("process_bank_reply_message"))
            await mines.process_bank_reply_message(self.message)
            self.assertGreaterEqual(mines.get_savings_account(self.uid)["balance"], 100)
            with localization.language_context(language):
                prompt = localization.text("СНЯТЬ С НАКОП. СЧЕТА")
            self.message.reply_to_message = SimpleNamespace(text=prompt, caption=None, reply_markup=None)
            self.assertTrue(await self.handler_matches("process_bank_reply_message"))
            await mines.process_bank_reply_message(self.message)
        self.assertEqual(mines.get_user(self.uid)["balance"], 10000)

    async def test_p2p_reply_deposit_and_withdraw_in_all_languages(self):
        for language in localization.LANGUAGES:
            fixtures.BotTests.setUp(self)
            self.user.is_bot = False
            self.message.reply = AsyncMock(return_value=SimpleNamespace(message_id=1))
            self.language(language)
            mines.update_user(self.uid, balance=10000, mp_balance=100)
            for source in ("ПОПОЛНЕНИЕ mCoin", "ПОПОЛНЕНИЕ MPOINT", "ВЫВОД mCoin", "ВЫВОД MPOINT"):
                with self.subTest(language=language, source=source):
                    with localization.language_context(language):
                        prompt = localization.text(source)
                    self.message.reply_to_message = SimpleNamespace(text=prompt, caption=None, reply_markup=None)
                    self.message.text = "10"
                    self.message.reply.reset_mock()
                    self.assertTrue(await self.handler_matches("process_p2p_and_admin_reply_message"))
                    await mines.process_p2p_and_admin_reply_message(self.message)
                    self.message.reply.assert_awaited_once()
            self.assertEqual(mines.get_user(self.uid)["mp_balance"], 100)
            self.assertEqual(mines.get_user(self.uid)["balance"], 10000)
            self.assertEqual(mines.get_p2p_account(self.uid)["mp_balance"], 0)
            self.assertEqual(mines.get_p2p_account(self.uid)["mcoin_balance"], 0)

    async def test_p2p_buy_and_sell_quote_fallback_after_language_switch(self):
        mines.update_user(self.uid, balance=100000000, mp_balance=100)
        for language in localization.LANGUAGES:
            with localization.language_context(language):
                buy = localization.text("КУПИТЬ MPOINT") + "\n" + localization.text("Продавец: 🏛 Оф. Покупка")
                sell = localization.text("ПРОДАТЬ MPOINT") + "\n" + localization.text("Покупатель: 🏛 Оф. Продажа")
            self.language("kk" if language != "kk" else "en")
            for prompt, expected in ((buy, "p2p_conf_bbot_1"), (sell, "p2p_conf_sbot_1")):
                with self.subTest(language=language, expected=expected):
                    self.message.reply_to_message = SimpleNamespace(text=prompt, caption=None, reply_markup=None)
                    self.message.text = "1"
                    self.message.reply.reset_mock()
                    self.assertTrue(await self.handler_matches("process_p2p_and_admin_reply_message"))
                    await mines.process_p2p_and_admin_reply_message(self.message)
                    self.message.reply.assert_awaited_once()
                    keyboard = self.message.reply.call_args.kwargs["reply_markup"]
                    self.assertTrue(any(button.callback_data == expected for row in keyboard.inline_keyboard for button in row))

    async def test_notifications_use_recipient_language_and_preserve_comment(self):
        receiver_id = 9999
        mines.save_username(receiver_id, "receiver", "Receiver")
        mines.set_user_settings(receiver_id, language="kk", bot_nickname="Назад")
        self.language("en")
        mines.set_user_settings(self.uid, bot_nickname="Победа")
        mines.update_user(self.uid, balance=10000)
        self.message.text = "transfer 100 Назад <&> {0}"
        self.message.reply_to_message = SimpleNamespace(from_user=SimpleNamespace(id=receiver_id, first_name="Receiver"))
        with patch.object(mines.bot, "send_message", new_callable=AsyncMock) as send:
            await mines.cmd_transfer(self.message)
        sender_text = message_text(self.message.reply)
        received = send.call_args.kwargs["text"]
        self.assertIn("Comment:", sender_text)
        self.assertIn("Пікір:", received)
        self.assertNotIn("Comment:", received)
        for text in (sender_text, received):
            self.assertIn("Назад &lt;&amp;&gt; {0}", text)
            self.assertIn("Победа", text)
        self.assertIn(">Назад</a>", sender_text)
        self.assertEqual(send.call_args.kwargs["chat_id"], receiver_id)
        self.assertEqual(mines.get_user(self.uid)["balance"], 9900)
        self.assertEqual(mines.get_user(receiver_id)["balance"], 90)

    async def test_mp_notification_uses_receiver_language(self):
        receiver_id = 9999
        mines.save_username(receiver_id, "receiver", "Receiver")
        mines.set_user_settings(receiver_id, language="uk")
        self.language("en")
        mines.update_user(self.uid, mp_balance=100)
        mines.mp_pending_transfers["test"] = {"sender_id": self.uid, "receiver_id": receiver_id, "amount": 10, "target_name": "Receiver", "chat_id": self.uid}
        self.callback.data = "mp_yes_test"
        with patch.object(mines.bot, "send_message", new_callable=AsyncMock) as send:
            await mines.process_mp_yes(self.callback)
        self.assertIn("Надійшов переказ", send.call_args.kwargs["text"])
        self.assertIn("transferred", message_text(self.message.edit_text))
        self.assertEqual(mines.get_user(self.uid)["mp_balance"], 90)
        self.assertEqual(mines.get_user(receiver_id)["mp_balance"], 10)

    async def test_mcoin_and_mp_commands_never_cross_route(self):
        for text, expected in (("transfer 100", "cmd_transfer"), ("дать 100", "cmd_transfer"), ("send 100 @user", "cmd_send_mp"), ("/transfer 100", "cmd_transfer"), ("/send 100 @user", "cmd_send_mp")):
            with self.subTest(text=text):
                self.message.text = text
                self.message.reply_to_message = None
                self.message.entities = None
                self.assertTrue(await self.handler_matches(expected))
                other = "cmd_send_mp" if expected == "cmd_transfer" else "cmd_transfer"
                self.assertFalse(await self.handler_matches(other))

    async def test_middleware_language_uses_event_not_handler_argument(self):
        mines.ban_user(self.uid, "Назад", is_permanent=True)
        self.message.text = "/settings"
        try:
            for language, forever in (("en", "Forever"), ("uk", "Назавжди"), ("kk", "Мәңгілік")):
                self.language(language)
                self.message.reply.reset_mock()
                handler = AsyncMock()
                await mines.save_username_middleware(handler, self.message, {})
                rendered = message_text(self.message.reply)
                self.assertIn(forever, rendered)
                self.assertIn("Назад", rendered)
                handler.assert_not_awaited()
        finally:
            mines.unban_user(self.uid)

    async def test_concurrent_events_do_not_share_language(self):
        uid2 = 9999
        mines.get_user(uid2)
        self.language("en")
        mines.set_user_settings(uid2, language="kk")
        @localization.localized
        async def render(user_id):
            before = localization.text("Назад")
            await asyncio.sleep(0)
            return before, localization.text("Назад")
        self.assertEqual(await asyncio.gather(render(self.uid), render(uid2)), [("Back", "Back"), ("Артқа", "Артқа")])
        self.assertEqual(localization.current_language(), "ru")

    async def test_background_deposit_notifications_use_each_recipient(self):
        expected = {}
        for offset, language in enumerate(("en", "uk", "kk")):
            uid = self.uid + offset
            mines.get_user(uid)
            mines.update_user(uid, balance=10000)
            mines.set_user_settings(uid, language=language)
            self.assertTrue(mines.create_time_deposit(uid, 1000, 1)[0])
            expected[uid] = localization.translate_template("Депозит завершен", language)
        mines.cursor.execute("UPDATE time_deposits SET end_at_dt=?", ((datetime.now() - timedelta(days=1)).isoformat(),))
        mines.conn.commit()
        with patch.object(mines.bot, "send_message", new_callable=AsyncMock) as send, patch.object(mines.asyncio, "sleep", new_callable=AsyncMock, side_effect=StopTick):
            with self.assertRaises(StopTick):
                await mines.check_time_deposits_task()
        self.assertEqual(send.await_count, 3)
        for call in send.call_args_list:
            self.assertIn(expected[call.kwargs["chat_id"]], call.kwargs["text"])

    async def test_referral_notification_uses_referrers_language(self):
        receiver_id = 9999
        mines.get_user(receiver_id)
        mines.set_user_settings(receiver_id, language="kk")
        self.language("en")
        self.assertTrue(mines.register_referral(receiver_id, self.uid))
        with patch.object(mines.bot, "send_message", new_callable=AsyncMock) as send:
            await mines.activate_referral_if_needed(self.uid)
        self.assertEqual(send.call_args.kwargs["chat_id"], receiver_id)
        self.assertIn("Реферал бонусы", send.call_args.kwargs["text"])
        self.assertEqual(mines.get_user(receiver_id)["balance"], 100000)

    async def test_ukrainian_nickname_reset_matches_the_prompt(self):
        self.language("uk")
        mines.set_user_settings(self.uid, bot_nickname="Custom")
        mines.settings_nickname_pending.add(self.uid)
        self.message.text = "скинути"
        await mines._handle_settings_text(self.message)
        self.assertIsNone(mines.get_user_settings(self.uid)["bot_nickname"])

    async def test_admin_promotion_earn_and_bank_render_in_english(self):
        self.language("en")
        for builder in (mines.build_deposit_main_menu, mines.build_time_deposits_menu, mines.build_my_deposits_menu, mines.build_active_deposits_menu, mines.build_withdraw_deposits_menu, mines.build_deposits_history_menu, mines.build_savings_menu, mines.build_savings_deposit_input_menu):
            with self.subTest(builder=builder.__name__):
                text, keyboard = builder(self.uid, "Telegram Name")
                self.assert_english(text)
                self.assert_english(" ".join(button.text for row in keyboard.inline_keyboard for button in row))
        for builder in (mines.build_earn_menu, mines.render_p2p_manage, mines.render_p2p_history):
            text, keyboard = builder(self.uid)
            self.assert_english(text)
            self.assert_english(" ".join(button.text for row in keyboard.inline_keyboard for button in row))
        self.callback.data = "promote_rules"
        await mines.process_promote_rules(self.callback)
        self.assert_english(message_text(self.message.edit_text))
        for section in ("games", "economy", "system", "players"):
            with localization.language_context("en"):
                self.assert_english(mines._panel_section_text(section))

    async def test_bank_uses_callback_metadata_not_translated_lock_label(self):
        self.language("en")
        mines.update_user(self.uid, balance=10000)
        keyboard = mines.types.InlineKeyboardMarkup(inline_keyboard=[[
            mines.types.InlineKeyboardButton(text="Any translated lock label ❌", callback_data="dep_make_15_1_all")
        ]])
        self.message.reply_to_message = SimpleNamespace(text="Changed header", caption=None, reply_markup=keyboard)
        self.message.text = "1000"
        self.assertTrue(await self.handler_matches("process_bank_reply_message"))
        await mines.process_bank_reply_message(self.message)
        mines.cursor.execute("SELECT days, is_locked FROM time_deposits WHERE user_id=?", (self.uid,))
        self.assertEqual(tuple(mines.cursor.fetchone()), (15, 1))

    async def test_p2p_metadata_survives_restart_and_official_looking_nickname(self):
        seller_id = 9999
        mines.save_username(seller_id, "seller", "Official buy")
        mines.get_p2p_account(seller_id)
        mines.cursor.execute("UPDATE p2p_accounts SET sell_order_active=1, sell_price=100, mp_balance=10 WHERE user_id=?", (seller_id,))
        mines.conn.commit()
        mines.update_user(self.uid, balance=10000)
        self.language("en")
        self.callback.data = "p2p_buy_seller_9999"
        await mines.cb_p2p_buy_seller(self.callback)
        prompt = message_text(self.message.edit_text)
        keyboard = self.message.edit_text.call_args.kwargs["reply_markup"]
        self.assertIn("Official buy", prompt)
        mines.p2p_user_action.clear()
        self.language("kk")
        self.message.reply_to_message = SimpleNamespace(text=html.unescape(TAGS.sub("", prompt)), caption=None, reply_markup=keyboard)
        self.message.text = "1"
        self.assertTrue(await self.handler_matches("process_p2p_and_admin_reply_message"))
        await mines.process_p2p_and_admin_reply_message(self.message)
        result = self.message.reply.call_args.kwargs["reply_markup"]
        self.assertTrue(any(button.callback_data == "p2p_conf_buy_9999_1" for row in result.inline_keyboard for button in row))
        self.assertEqual(mines.get_user(self.uid)["balance"], 10000)

    async def test_known_p2p_state_cannot_be_overridden_by_visible_nickname(self):
        mines.get_p2p_account(9999)
        mines.cursor.execute("UPDATE p2p_accounts SET sell_price=100 WHERE user_id=9999")
        mines.conn.commit()
        mines.update_user(self.uid, balance=10000)
        self.language("en")
        mines.p2p_user_action[self.uid] = "buy_seller_9999"
        self.message.reply_to_message = SimpleNamespace(text="BUY MPOINT\nSeller: Official buy", caption=None, reply_markup=None)
        self.message.text = "1"
        await mines.process_p2p_and_admin_reply_message(self.message)
        keyboard = self.message.reply.call_args.kwargs["reply_markup"]
        self.assertTrue(any(button.callback_data == "p2p_conf_buy_9999_1" for row in keyboard.inline_keyboard for button in row))

    async def test_bot_authored_message_does_not_override_current_actor_language(self):
        self.language("en")
        mines.set_user_settings(9999, language="kk")
        @localization.localized
        async def inner(message):
            return localization.text("Назад")
        @localization.localized
        async def outer(user_id):
            message = SimpleNamespace(from_user=SimpleNamespace(id=9999, is_bot=True))
            return await inner(message)
        self.assertEqual(await outer(self.uid), "Back")
        self.assertEqual(localization.current_language(), "ru")
        @localization.localized
        async def fails(user_id):
            self.assertEqual(localization.text("Назад"), "Back")
            raise RuntimeError("test")
        with self.assertRaises(RuntimeError):
            await fails(self.uid)
        self.assertEqual(localization.current_language(), "ru")

    async def test_expired_game_notifications_use_recipient_language(self):
        expected = {}
        for offset, language in enumerate(("en", "uk", "kk")):
            uid = self.uid + offset
            mines.get_user(uid)
            mines.set_user_settings(uid, language=language)
            gid = 8000 + offset
            mines.games[gid] = {"owner_id": uid, "type": "tower", "bet": 100, "created_at": datetime.now() - timedelta(hours=13), "created_at_str": "01-01-2026 12:00:00"}
            mines.active_games[uid] = gid
            expected[uid] = localization.translate_template("башня", language)
        with patch.object(mines.bot, "send_message", new_callable=AsyncMock) as send, patch.object(mines.asyncio, "sleep", new_callable=AsyncMock, side_effect=StopTick):
            with self.assertRaises(StopTick):
                await mines.check_expired_games_task()
        self.assertEqual(send.await_count, 3)
        for call in send.call_args_list:
            self.assertIn(expected[call.kwargs["chat_id"]], call.kwargs["text"])
        self.assertFalse(mines.active_games)

    async def test_gift_invoice_localized_without_changing_payment_payload(self):
        self.language("en")
        mines.save_username(9999, "receiver", "Receiver")
        self.callback.data = "temple_pay_9999_heart"
        self.message.answer_invoice = AsyncMock()
        await mines.cb_temple_pay(self.callback)
        self.message.answer_invoice.assert_awaited_once()
        invoice = self.message.answer_invoice.call_args.kwargs
        self.assertIn("Heart", invoice["title"])
        self.assert_english(invoice["description"])
        self.assertEqual(invoice["currency"], "XTR")
        self.assertEqual(invoice["prices"][0].amount, mines.TEMPLE_GIFTS["heart"]["stars"])
        self.assertTrue(invoice["payload"].startswith(f"temple_gift_{self.uid}_9999_heart_"))

    async def test_gift_notification_localizes_gift_but_preserves_comment(self):
        self.language("en")
        receiver_id = 9999
        mines.get_user(receiver_id)
        mines.set_user_settings(receiver_id, language="kk")
        comment = "Назад <&> {0}"
        mines._temple_user_comment[self.uid] = comment
        self.message.successful_payment = SimpleNamespace(invoice_payload=f"temple_gift_{self.uid}_{receiver_id}_heart_test")
        with patch.object(mines.bot, "send_message", new_callable=AsyncMock) as send, patch.object(mines, "deliver_telegram_gift", new_callable=AsyncMock, return_value=True) as deliver:
            await mines.cb_temple_successful_payment(self.message)
            await asyncio.sleep(0)
            deliver.assert_awaited_once_with(receiver_id, "heart", comment)
        received = send.call_args.kwargs["text"]
        self.assertIn("Жүрек", received)
        self.assertIn(html.escape(comment), received)
        self.assertNotIn("Сердце", received)
        self.assertEqual(send.call_args.kwargs["chat_id"], receiver_id)

    async def test_leaderboard_fallback_names_use_viewer_not_ranked_user_language(self):
        self.language("en")
        other_id = 9999
        mines.get_user(other_id)
        mines.update_user(other_id, balance=10000)
        mines.set_user_settings(other_id, language="uk", hide_top_username=1)
        with patch.object(mines.bot, "get_chat", new_callable=AsyncMock, side_effect=RuntimeError("unavailable")):
            await mines.show_top(self.message)
        rendered = message_text(self.message.answer)
        self.assertIn("User", rendered)
        self.assertNotIn("Користувач", rendered)
        self.assert_english(rendered)

    async def test_event_unknown_participants_have_localized_fallback_names(self):
        mines.event_participants[9999] = 3
        try:
            with localization.language_context("kk"), patch.object(mines.bot, "get_chat", new_callable=AsyncMock, side_effect=RuntimeError("unavailable")):
                links = await mines._event_participant_links()
            self.assertEqual(links, ['<a href="tg://user?id=9999">Пайдаланушы</a>'])
        finally:
            mines.event_participants.clear()

    async def test_admin_role_and_permission_labels_are_fully_localized(self):
        self.message.from_user.id = min(mines.OWNER_IDS)
        for language in localization.LANGUAGES:
            with self.subTest(language=language), localization.language_context(language):
                await mines.cmd_admin_list(self.message)
                rendered = message_text(self.message.answer)
                self.assertIn(localization.text("Владелец"), rendered)
                self.assertIn(localization.text("Администратор"), rendered)
                self.assertIn(localization.text("установка"), rendered)
                keyboard = mines._admin_control_keyboard(self.message.from_user.id)
                self.assertIn(localization.text("Владелец"), keyboard.inline_keyboard[0][0].text)
                if language == "en":
                    self.assert_english(rendered)

    async def test_translated_promo_examples_work_with_multilingual_names(self):
        self.message.from_user.id = min(mines.OWNER_IDS)
        expected_names = {"ru": "Новый год", "en": "New Year", "uk": "Новий рік", "kk": "Жаңа жыл"}
        for language, expected in expected_names.items():
            with self.subTest(language=language), localization.language_context(language):
                self.message.text = "/cprom"
                await mines.cmd_cprom(self.message)
                help_text = message_text(self.message.answer)
                example = re.findall(r"<code>(/cprom .*?)</code>", help_text)[0]
                self.message.text = html.unescape(example)
                await mines.cmd_cprom(self.message)
                mines.cursor.execute("SELECT reward, total_activations FROM promo_codes WHERE code=?", (expected,))
                self.assertEqual(tuple(mines.cursor.fetchone()), (100000000, 10))
