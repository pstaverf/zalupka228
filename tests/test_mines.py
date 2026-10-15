import asyncio
import importlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


TEMP = tempfile.TemporaryDirectory()
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:" + "a" * 35
os.environ["SQLITE_DB_PATH"] = str(Path(TEMP.name) / "test.sqlite3")
mines = importlib.import_module("mines")


class BotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mines.conn.rollback()
        for table in ("users", "bot_user_settings", "games_history", "game_stats", "p2p_accounts", "p2p_deals_history", "savings_accounts", "savings_history", "time_deposits", "demo_modes", "active_games_state", "transfers_history", "mp_transfers_history", "p2p_promotions"):
            mines.cursor.execute(f'DELETE FROM "{table}"')
        mines.conn.commit()
        mines._known_names.clear()
        mines._known_usernames.clear()
        if hasattr(mines, "_settings_cache"):
            mines._settings_cache.clear()
        if hasattr(mines, "_identity_cache"):
            mines._identity_cache.clear()
        mines.games.clear()
        mines.active_games.clear()
        mines.user_messages.clear()
        mines.game_messages.clear()
        self.uid = 1234
        mines.get_user(self.uid)
        mines.save_username(self.uid, "telegram_user", "Telegram Name")
        self.user = SimpleNamespace(id=self.uid, first_name="Telegram Name", username="telegram_user")
        self.message = Mock(spec=mines.types.Message)
        self.message.from_user = self.user
        self.message.chat = SimpleNamespace(id=self.uid, type="private")
        self.message.answer = AsyncMock(return_value=SimpleNamespace(message_id=1))
        self.message.edit_text = AsyncMock(return_value=SimpleNamespace(message_id=1))
        self.callback = Mock(spec=mines.types.CallbackQuery)
        self.callback.from_user = self.user
        self.callback.message = self.message
        self.callback.answer = AsyncMock()

    async def test_custom_name_in_catalog_and_history(self):
        mines.set_user_settings(self.uid, bot_nickname="Ник <&>")
        for fn in (mines.show_catalog, mines.show_recent_games_menu):
            self.message.answer.reset_mock()
            if fn is mines.show_catalog:
                await fn(self.message, self.uid, "Telegram Name", self.uid)
            else:
                await fn(self.message, self.uid, "Telegram Name")
            call = self.message.answer.call_args
            text = call.kwargs.get("text") or call.args[0]
            self.assertIn("Ник &lt;&amp;&gt;", text)
            self.assertNotIn("Telegram Name", text)

    async def test_custom_name_in_mines_and_updated_callback(self):
        mines.games[1] = {"owner_id": self.uid, "chat_id": self.uid, "type": "mines", "stage": "playing", "mine_count": 3, "bet": 100, "revealed": set(), "mine_positions": {0, 1, 2}, "level": 0, "game_over": False}
        mines.set_user_settings(self.uid, bot_nickname="Первый")
        await mines.show_mines_grid_from_message(self.message, self.uid, 1)
        call = self.message.edit_text.call_args
        self.assertIn("Первый", call.kwargs.get("text") or call.args[0])
        mines.set_user_settings(self.uid, bot_nickname="Второй")
        await mines.show_mines_grid_from_callback(self.callback, self.uid, 1)
        call = self.message.edit_text.call_args
        self.assertIn("Второй", call.kwargs.get("text") or call.args[0])

    async def test_clear_nickname_and_escape(self):
        mines.set_user_settings(self.uid, bot_nickname='<a href="evil">ник</a>')
        self.assertNotIn('<a href="evil">', mines.get_user_mention(self.uid, "Old Name"))
        mines.set_user_settings(self.uid, bot_nickname=None)
        self.assertEqual(mines.get_user_display_name(self.uid), "Telegram Name")

    async def test_profile_persisted_on_first_event_and_username_removed(self):
        uid = 9999
        mines.save_username(uid, "original", "New User")
        self.assertEqual(mines.get_user(uid)["first_name"], "New User")
        mines.save_username(uid, None, "Changed Name")
        self.assertIsNone(mines.get_user(uid)["username"])
        self.assertIsNone(mines.get_user_by_username("original"))
        self.assertEqual(mines.get_user_display_name(uid), "Changed Name")

    async def test_parameterized_user_input(self):
        value = "x'); DROP TABLE users; --"
        self.assertTrue(mines.set_user_settings(self.uid, bot_nickname=value))
        self.assertEqual(mines.get_user_settings(self.uid)["bot_nickname"], value)
        self.assertIsNone(mines.get_user_by_username("' OR 1=1 --"))
        mines.add_game_history(self.uid, "mines; DROP TABLE users; --", 1, "win", 2)
        self.assertIsNotNone(mines.get_user(self.uid))
        mines.cursor.execute("SELECT COUNT(*) FROM users")
        self.assertEqual(mines.cursor.fetchone()[0], 1)
        await asyncio.sleep(0)

    async def test_balance_and_bank_roundtrip(self):
        self.assertTrue(mines.update_user(self.uid, balance=10000))
        self.assertTrue(mines.deposit_to_savings(self.uid, 1000)[0])
        self.assertEqual(mines.get_user(self.uid)["balance"], 9000)
        self.assertTrue(mines.withdraw_from_savings(self.uid, 1000)[0])
        self.assertEqual(mines.get_user(self.uid)["balance"], 10000)
        self.assertEqual(mines.get_user(self.uid)["max_balance"], 10000)
        self.assertTrue(mines.create_time_deposit(self.uid, 100, 1)[0])
        self.assertEqual(mines.get_user(self.uid)["balance"], 9900)

    async def test_demo_does_not_change_real_balance(self):
        mines.update_user(self.uid, balance=123)
        token = mines.DEMO_GAME_CONTEXT.set(True)
        try:
            mines.update_user(self.uid, balance=456, games=10, lost=20)
            self.assertEqual(mines.get_user(self.uid)["balance"], 456)
        finally:
            mines.DEMO_GAME_CONTEXT.reset(token)
        user = mines.get_user(self.uid)
        self.assertEqual((user["balance"], user["games"], user["lost"]), (123, 0, 0))

    async def test_p2p_roundtrip(self):
        mines.update_user(self.uid, balance=10000, mp_balance=100)
        self.assertTrue(mines.deposit_to_p2p_mcoin(self.uid, 1000)[0])
        self.assertTrue(mines.withdraw_from_p2p_mcoin(self.uid, 1000)[0])
        self.assertEqual(mines.get_user(self.uid)["balance"], 10000)
        self.assertTrue(mines.deposit_to_p2p_mpoint(self.uid, 10)[0])
        self.assertTrue(mines.withdraw_from_p2p_mpoint(self.uid, 10)[0])
        self.assertEqual(mines.get_user(self.uid)["mp_balance"], 100)

    async def test_async_database_helpers(self):
        row = await mines.fetchrow("SELECT user_id, balance FROM users WHERE user_id = ?", self.uid)
        self.assertEqual(row, {"user_id": self.uid, "balance": 0})
        self.assertEqual(await mines.fetchval("SELECT COUNT(*) FROM users"), 1)
        self.assertEqual(len(await mines.fetch("SELECT user_id FROM users")), 1)


    async def test_expired_and_evicted_cache_entries_are_removed(self):
        mines._in_memory_cache.clear()
        mines._in_memory_expire_at.clear()
        mines._cache_last_cleanup = 0.0
        with patch.object(mines.time, "time", return_value=100):
            await mines.redis_set("expired", {"key": "value"}, expire_sec=1)
            self.assertEqual(await mines.redis_get("expired"), {"key": "value"})
        with patch.object(mines.time, "time", return_value=200):
            await mines.redis_set("fresh", 5, expire_sec=100)
            self.assertNotIn("expired", mines._in_memory_cache)
            self.assertNotIn("expired", mines._in_memory_expire_at)
            with patch.object(mines, "CACHE_LIMIT", 3):
                for i in range(10):
                    await mines.redis_set(f"cache:{i}", i, expire_sec=100)
                self.assertEqual(len(mines._in_memory_cache), 3)
                self.assertEqual(set(mines._in_memory_cache), set(mines._in_memory_expire_at))
        mines._in_memory_cache.clear()
        mines._in_memory_expire_at.clear()

    async def test_admin_balance_commands_escape_custom_names(self):
        receiver_id = 9999
        mines.get_user(receiver_id)
        mines.set_user_settings(receiver_id, bot_nickname="Получатель <&>")
        self.message.reply_to_message = SimpleNamespace(from_user=SimpleNamespace(id=receiver_id, first_name="Receiver", username=None))
        self.message.reply = AsyncMock()
        with patch.object(mines, "ADMINS", [self.uid]), patch.object(mines, "OWNER_IDS", {self.uid}):
            for command in (mines.cmd_add, mines.cmd_set, mines.cmd_addmp, mines.cmd_setmp):
                with self.subTest(command=command.__name__):
                    self.message.reply.reset_mock()
                    self.message.text = f"/{command.__name__.removeprefix('cmd_')} 100"
                    await command(self.message)
                    self.assertIn("Получатель &lt;&amp;&gt;", self.message.reply.call_args.args[0])

    async def test_promotion_failure_rolls_back_and_names_are_escaped(self):
        mines.update_user(self.uid, mp_balance=100)
        mines.set_user_settings(self.uid, bot_nickname="Создатель <&>")
        state = {"price": 1, "subs": 10, "target_type": "channel"}
        mines.cursor.execute("CREATE TEMP TRIGGER fail_promotion BEFORE INSERT ON p2p_promotions BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        try:
            with self.assertLogs(level="ERROR"):
                await mines.finalize_p2p_promotion_creation(self.message, self.uid, "Telegram Name", state, -1000001, "Канал <&>", None)
            self.assertEqual(mines.get_user(self.uid)["mp_balance"], 100)
            self.assertFalse(mines.conn.in_transaction)
        finally:
            mines.cursor.execute("DROP TRIGGER fail_promotion")
        self.message.answer.reset_mock()
        await mines.finalize_p2p_promotion_creation(self.message, self.uid, "Telegram Name", state, -1000001, "Канал <&>", None)
        text = self.message.answer.call_args_list[0].args[0]
        self.assertIn("Создатель &lt;&amp;&gt;", text)
        self.assertIn("Канал &lt;&amp;&gt;", text)
        self.assertEqual(mines.get_user(self.uid)["mp_balance"], 90)

    async def test_transfer_handlers_display_both_custom_names(self):
        receiver_id = 9999
        mines.get_user(receiver_id)
        mines.save_username(receiver_id, "receiver", "Receiver Telegram")
        mines.set_user_settings(self.uid, bot_nickname="Отправитель <&>")
        mines.set_user_settings(receiver_id, bot_nickname="Получатель <&>")
        mines.update_user(self.uid, balance=10000, mp_balance=1000)
        self.message.text = "дать 1000"
        self.message.reply_to_message = SimpleNamespace(from_user=SimpleNamespace(id=receiver_id, first_name="Receiver Telegram", username="receiver"))
        self.message.reply = AsyncMock()
        with patch.object(mines.bot, "send_message", new=AsyncMock()):
            await mines.cmd_transfer(self.message)
            text = self.message.reply.call_args.args[0]
            self.assertIn("Отправитель &lt;&amp;&gt;", text)
            self.assertIn("Получатель &lt;&amp;&gt;", text)
            self.callback.data = "mp_yes_test"
            mines.mp_pending_transfers["test"] = {"sender_id": self.uid, "receiver_id": receiver_id, "amount": 100, "target_name": "@receiver"}
            await mines.process_mp_yes(self.callback)
            text = self.message.edit_text.call_args.kwargs["text"]
            self.assertIn("Получатель &lt;&amp;&gt;", text)
            self.assertEqual(mines.get_user(receiver_id)["mp_balance"], 100)
            self.assertNotIn("test", mines.mp_pending_transfers)

    async def test_settings_cache_copies_invalidates_and_is_bounded(self):
        statements = []
        mines.conn.set_trace_callback(statements.append)
        try:
            mines._settings_cache.clear()
            for _ in range(20):
                mines.get_user_settings(self.uid)
            reads = [q for q in statements if q.startswith("SELECT language")]
            self.assertEqual(len(reads), 1)
            settings = mines.get_user_settings(self.uid)
            settings["bot_nickname"] = "Unwanted mutation"
            self.assertIsNone(mines.get_user_settings(self.uid)["bot_nickname"])
            mines.set_user_settings(self.uid, bot_nickname="Changed")
            self.assertEqual(mines.get_user_display_name(self.uid), "Changed")
            statements.clear()
            for _ in range(20):
                mines.save_username(self.uid, "telegram_user", "Telegram Name")
            self.assertFalse(any(q.startswith("INSERT INTO users") or q.startswith("UPDATE users") for q in statements))
        finally:
            mines.conn.set_trace_callback(None)
        with patch.object(mines, "CACHE_LIMIT", 3):
            mines._settings_cache.clear()
            for uid in range(10):
                mines.get_user_settings(uid)
            self.assertEqual(len(mines._settings_cache), 3)

    async def test_top_and_records_use_local_custom_name_without_network(self):
        mines.update_user(self.uid, balance=100)
        mines.set_user_settings(self.uid, bot_nickname="Ник рейтинга")
        with patch.object(mines.bot, "get_chat", new=AsyncMock(side_effect=AssertionError("Unexpected network request"))) as get_chat:
            await mines.show_top(self.message)
            self.assertIn("Ник рейтинга", self.message.answer.call_args.kwargs["text"])
            await mines.show_records(self.message)
            call = self.message.answer.call_args
            self.assertIn("Ник рейтинга", call.kwargs.get("text") or call.args[0])
            get_chat.assert_not_awaited()

    async def test_name_on_all_persistent_game_boards(self):
        starts = (
            (mines.start_mines_game_from_command, mines.show_mines_grid_from_callback, (3,)),
            (mines.start_tower_game_from_command, mines.show_tower_grid_from_callback, (1,)),
            (mines.start_qwak_game_from_command, mines.show_qwak_grid_from_callback, ()),
            (mines.start_diamonds_game_from_command, mines.show_diamonds_grid_from_callback, (1,)),
            (mines.start_gold_game_from_command, mines.show_gold_grid_from_message, ()),
            (mines.start_twentyone_game_from_command, mines.show_twentyone_from_callback, ()),
        )
        for start, render, extra in starts:
            with self.subTest(game=start.__name__):
                mines.games.clear()
                mines.active_games.clear()
                mines.user_messages.clear()
                mines.game_messages.clear()
                self.message.answer.reset_mock()
                self.message.edit_text.reset_mock()
                mines.update_user(self.uid, balance=10000)
                mines.set_user_settings(self.uid, bot_nickname="Ник игры")
                await start(self.message, self.uid, self.uid, 100, *extra)
                call = self.message.edit_text.call_args or self.message.answer.call_args
                self.assertIn("Ник игры", call.kwargs.get("text") or call.args[0])
                gid = mines.active_games[self.uid]
                mines.set_user_settings(self.uid, bot_nickname="Новый ник игры")
                await render(self.callback, self.uid, gid)
                call = self.message.edit_text.call_args
                self.assertIn("Новый ник игры", call.kwargs.get("text") or call.args[0])
                mines.set_user_settings(self.uid, bot_nickname=None)
                await render(self.callback, self.uid, gid)
                call = self.message.edit_text.call_args
                self.assertIn("Telegram Name", call.kwargs.get("text") or call.args[0])
                self.assertEqual(mines.get_user(self.uid)["balance"], 9900)

    async def test_mp_deposit_creates_account_on_first_use(self):
        mines.update_user(self.uid, mp_balance=100)
        self.assertTrue(mines.deposit_to_p2p_mpoint(self.uid, 10)[0])
        self.assertEqual(mines.get_p2p_account(self.uid)["mp_balance"], 10)
        self.assertEqual(mines.get_user(self.uid)["mp_balance"], 90)

    async def test_savings_failure_rolls_back_even_helper_commit(self):
        mines.update_user(self.uid, balance=10000)
        mines.cursor.execute("CREATE TEMP TRIGGER fail_savings BEFORE INSERT ON savings_history BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        try:
            self.assertFalse(mines.deposit_to_savings(self.uid, 1000)[0])
            self.assertEqual(mines.get_user(self.uid)["balance"], 10000)
            mines.cursor.execute("SELECT COUNT(*) FROM savings_accounts WHERE user_id = ?", (self.uid,))
            self.assertEqual(mines.cursor.fetchone()[0], 0)
            self.assertFalse(mines.conn.in_transaction)
        finally:
            mines.cursor.execute("DROP TRIGGER fail_savings")

    async def test_p2p_failure_rolls_back_balances_and_history(self):
        seller_id = 9999
        mines.get_user(seller_id)
        mines.get_p2p_account(seller_id)
        mines.get_p2p_account(self.uid)
        mines.update_user(self.uid, balance=10000)
        mines.cursor.execute("UPDATE p2p_accounts SET mp_balance=100, sell_order_active=1, sell_price=100 WHERE user_id=?", (seller_id,))
        mines.conn.commit()
        mines.cursor.execute("CREATE TEMP TRIGGER fail_deal BEFORE INSERT ON p2p_deals_history BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        try:
            self.assertFalse(mines.execute_p2p_buy_deal(self.uid, seller_id, 10)[0])
            self.assertEqual(mines.get_user(self.uid)["balance"], 10000)
            self.assertEqual(mines.get_user(self.uid)["mp_balance"], 0)
            self.assertEqual(mines.get_user(seller_id)["balance"], 0)
            self.assertEqual(mines.get_p2p_account(seller_id)["mp_balance"], 100)
            self.assertFalse(mines.conn.in_transaction)
        finally:
            mines.cursor.execute("DROP TRIGGER fail_deal")
        self.assertTrue(mines.execute_p2p_buy_deal(self.uid, seller_id, 10)[0])
        self.assertEqual(mines.get_user(self.uid)["balance"], 9000)
        self.assertEqual(mines.get_user(self.uid)["mp_balance"], 10)
        self.assertEqual(mines.get_user(seller_id)["balance"], 1000)
        self.assertEqual(mines.get_p2p_account(seller_id)["mp_balance"], 90)

    async def test_atomic_transfers_and_daily_mp_limit(self):
        receiver_id = 9999
        mines.get_user(receiver_id)
        mines.update_user(self.uid, balance=10000, mp_balance=2000)
        self.assertTrue(mines._apply_mcoin_transfer(self.uid, receiver_id, 1000, 100))
        self.assertEqual(mines.get_user(self.uid)["balance"], 9000)
        self.assertEqual(mines.get_user(receiver_id)["balance"], 900)
        self.assertFalse(mines._apply_mcoin_transfer(self.uid, 8888, 100, 10))
        self.assertEqual(mines.get_user(self.uid)["balance"], 9000)
        today = mines.get_msk_today_str()
        self.assertTrue(mines._apply_mp_transfer(self.uid, receiver_id, 1000, today))
        self.assertFalse(mines._apply_mp_transfer(self.uid, receiver_id, 1, today))
        self.assertEqual(mines.get_user(self.uid)["mp_balance"], 1000)
        self.assertEqual(mines.get_user(receiver_id)["mp_balance"], 1000)
        self.assertFalse(mines.conn.in_transaction)

    async def test_transfer_history_failure_rolls_back(self):
        mines.get_user(9999)
        mines.update_user(self.uid, balance=10000)
        mines.cursor.execute("CREATE TEMP TRIGGER fail_transfer BEFORE INSERT ON transfers_history BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        try:
            with self.assertLogs(level="ERROR"):
                self.assertFalse(mines._apply_mcoin_transfer(self.uid, 9999, 1000, 100))
            self.assertEqual(mines.get_user(self.uid)["balance"], 10000)
            self.assertEqual(mines.get_user(9999)["balance"], 0)
        finally:
            mines.cursor.execute("DROP TRIGGER fail_transfer")


class SQLiteTests(unittest.TestCase):
    def test_additive_migration_preserves_existing_data_and_is_idempotent(self):
        path = str(Path(TEMP.name) / "legacy.sqlite3")
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE users(user_id BIGINT PRIMARY KEY, balance BIGINT DEFAULT 0)")
            db.execute("INSERT INTO users VALUES(42, 12345)")
        for _ in range(2):
            db = mines.SQLiteConnection(path)
            try:
                row = db.execute("SELECT balance, games, first_name FROM users WHERE user_id=42").fetchone()
                self.assertEqual(tuple(row), (12345, 0, None))
                self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                db.execute("SELECT enabled FROM bot_admin_role_overrides")
            finally:
                db.close()

    def test_native_cursor_rejects_multiple_statements(self):
        db = mines.SQLiteConnection(":memory:")
        try:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute("SELECT 1; DROP TABLE users")
            db.execute("SELECT COUNT(*) FROM users")
        finally:
            db.close()

    def test_indexes_cover_history_queries(self):
        plan = mines.conn.execute("EXPLAIN QUERY PLAN SELECT * FROM games_history WHERE user_id=? ORDER BY id DESC LIMIT 5", (1234,)).fetchall()
        self.assertTrue(any("idx_games_history_user" in row[3] for row in plan))
        self.assertEqual(mines.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
