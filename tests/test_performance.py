import asyncio
from datetime import datetime, timedelta
import inspect
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_mines as fixtures


mines = fixtures.mines


class StopTick(BaseException):
    pass


class PerformanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.BotTests.setUp(self)
        mines.conn.execute("DELETE FROM chat_members")
        mines.conn.execute("DELETE FROM admin_controls")
        mines.conn.commit()
        mines._known_chat_members.clear()
        mines.event_participants.clear()

    async def test_all_registered_filters_avoid_worker_threads(self):
        for name in ("message", "callback_query", "pre_checkout_query"):
            observer = getattr(mines.dp, name)
            for handler in observer.handlers:
                for predicate in handler.filters:
                    self.assertTrue(predicate.awaitable, handler.callback.__name__)
        self.callback.data = "promote_rules"
        with patch.object(asyncio, "to_thread", side_effect=AssertionError("Unexpected worker hop")):
            selected = None
            for handler in mines.dp.callback_query.handlers:
                matched, _ = await handler.check(self.callback, bot=mines.bot)
                if matched:
                    selected = handler.callback.__name__
                    break
            self.assertEqual(selected, "process_promote_rules")

    async def test_inline_filters_preserve_original_predicate_results(self):
        events = [SimpleNamespace(text=text, caption=None, chat=self.message.chat, from_user=self.user, successful_payment=None) for text in (None, "", " ", "/settings", "мины 100", "дать 100", "настройки", "+adm 42", "обмен", "anything")]
        callbacks = [SimpleNamespace(data=data, message=self.message, from_user=self.user) for data in (None, "", "cell_1_2", "tower_cell_1_0_1", "promote_rules", "settings_open", "creator_panel:main", "p2p_buy_list")]
        checked = 0
        for observer, samples in ((mines.dp.message, events), (mines.dp.callback_query, callbacks)):
            for handler in observer.handlers:
                for predicate in handler.filters:
                    callback = predicate.callback
                    if not inspect.isfunction(callback) or callback.__name__ != "evaluate":
                        continue
                    original = inspect.getclosurevars(callback).nonlocals["predicate"]
                    for event in samples:
                        try:
                            expected = original(event)
                        except Exception as error:
                            with self.assertRaises(type(error)):
                                await predicate.call(event)
                        else:
                            self.assertEqual(bool(await predicate.call(event)), bool(expected))
                    checked += 1
        self.assertGreater(checked, 200)

    async def test_event_reads_reuse_rows_and_invalidate_on_write(self):
        queries = []
        mines.conn.set_trace_callback(queries.append)
        try:
            async def handler(event, data):
                for _ in range(10):
                    user = mines.get_user(self.uid)
                    user["balance"] = -999
                    self.assertEqual(mines.get_user(self.uid)["balance"], 0)
                user_reads = [query for query in queries if query.startswith("SELECT balance, games")]
                self.assertEqual(len(user_reads), 1)
                mines.update_user(self.uid, balance=100)
                self.assertEqual(mines.get_user(self.uid)["balance"], 100)
                self.assertEqual(mines.get_user(self.uid)["balance"], 100)
                user_reads = [query for query in queries if query.startswith("SELECT balance, games")]
                self.assertEqual(len(user_reads), 2)
                self.assertIsNotNone(mines._READ_CONTEXT.get())
            await mines._cache_reads_middleware(handler, self.message, {})
            self.assertIsNone(mines._READ_CONTEXT.get())
        finally:
            mines.conn.set_trace_callback(None)

    async def test_dispatcher_applies_cache_to_real_updates(self):
        user = mines.types.User(id=self.uid, is_bot=False, first_name="Telegram Name", username="telegram_user")
        message = mines.types.Message(message_id=1, date=datetime.now(), chat=mines.types.Chat(id=self.uid, type="private"), from_user=user, text="anything")
        update = mines.types.Update(update_id=1, message=message)
        queries = []
        async def trigger(event, **data):
            self.assertIsNotNone(mines._READ_CONTEXT.get())
            for _ in range(10):
                self.assertEqual(mines.get_user(self.uid)["balance"], 0)
            return "handled"
        mines.conn.set_trace_callback(queries.append)
        try:
            with patch.object(mines.dp.message, "trigger", side_effect=trigger):
                self.assertEqual(await mines.dp.feed_update(mines.bot, update), "handled")
        finally:
            mines.conn.set_trace_callback(None)
        self.assertEqual(sum(query.startswith("SELECT balance, games") for query in queries), 1)
        self.assertIsNone(mines._READ_CONTEXT.get())

    async def test_concurrent_updates_keep_separate_read_caches(self):
        scopes = []
        async def handler(event, data):
            scope = mines._READ_CONTEXT.get()
            scopes.append(scope)
            mines.get_user(self.uid)
            await asyncio.sleep(0)
            self.assertIs(mines._READ_CONTEXT.get(), scope)
            self.assertEqual(mines.get_user(self.uid)["balance"], 0)
        await asyncio.gather(mines._cache_reads_middleware(handler, self.message, {}), mines._cache_reads_middleware(handler, self.message, {}))
        self.assertIsNot(scopes[0], scopes[1])
        self.assertEqual(scopes[0][1], {})
        self.assertEqual(scopes[1][1], {})

    async def test_event_cache_refreshes_after_io_and_external_writes(self):
        async def handler(event, data):
            self.assertEqual(mines.get_user(self.uid)["balance"], 0)
            revision = mines.conn.total_changes
            with sqlite3.connect(mines.SQLITE_DB_PATH) as external:
                external.execute("UPDATE users SET balance=321 WHERE user_id=?", (self.uid,))
            self.assertEqual(mines.conn.total_changes, revision)
            await asyncio.sleep(0)
            self.assertEqual(mines.get_user(self.uid)["balance"], 321)
        await mines._cache_reads_middleware(handler, self.message, {})

    async def test_event_cache_bypasses_transactions_and_rollback(self):
        mines.update_user(self.uid, balance=100)
        async def handler(event, data):
            self.assertEqual(mines.get_user(self.uid)["balance"], 100)
            @mines.db_transaction
            def fail_operation():
                mines.update_user(self.uid, balance=200)
                self.assertEqual(mines.get_user(self.uid)["balance"], 200)
                self.assertEqual(mines.get_user(self.uid)["balance"], 200)
                return False
            self.assertFalse(fail_operation())
            self.assertEqual(mines.get_user(self.uid)["balance"], 100)
            self.assertFalse(mines.conn.in_transaction)
        await mines._cache_reads_middleware(handler, self.message, {})

    async def test_event_cache_separates_demo_balances(self):
        mines.update_user(self.uid, balance=100)
        mines.set_demo_balance(self.uid, 900)
        async def handler(event, data):
            self.assertEqual(mines.get_user(self.uid)["balance"], 100)
            token = mines.DEMO_GAME_CONTEXT.set(True)
            try:
                self.assertEqual(mines.get_user(self.uid)["balance"], 900)
            finally:
                mines.DEMO_GAME_CONTEXT.reset(token)
            self.assertEqual(mines.get_user(self.uid)["balance"], 100)
        await mines._cache_reads_middleware(handler, self.message, {})

    async def test_event_cache_does_not_leak_into_background_tasks(self):
        gate = asyncio.Event()
        captured = []
        async def handler(event, data):
            mines.get_user(self.uid)
            scope = mines._READ_CONTEXT.get()
            captured.append(scope)
            async def worker():
                await gate.wait()
                self.assertIsNone(scope[0])
                self.assertEqual(scope[1], {})
                self.assertEqual(mines.get_user(self.uid)["balance"], 123)
            return asyncio.create_task(worker())
        task = await mines._cache_reads_middleware(handler, self.message, {})
        mines.update_user(self.uid, balance=123)
        gate.set()
        await task
        self.assertIsNone(mines._READ_CONTEXT.get())
        self.assertEqual(captured[0][1], {})

    async def test_event_cache_is_cleared_when_handler_raises(self):
        captured = []
        async def handler(event, data):
            mines.get_user(self.uid)
            captured.append(mines._READ_CONTEXT.get())
            raise ValueError("test error")
        with self.assertRaises(ValueError):
            await mines._cache_reads_middleware(handler, self.message, {})
        self.assertIsNone(mines._READ_CONTEXT.get())
        self.assertIsNone(captured[0][0])
        self.assertEqual(captured[0][1], {})

    async def test_admin_reads_do_not_write_existing_profiles(self):
        mines.get_admin_control(self.uid)
        queries = []
        mines.conn.set_trace_callback(queries.append)
        try:
            for _ in range(10):
                mines.get_admin_control(self.uid)
        finally:
            mines.conn.set_trace_callback(None)
        self.assertEqual(len(queries), 10)
        self.assertTrue(all(query.lstrip().startswith("SELECT") for query in queries))

    async def test_message_tracking_deduplicates_without_reordering(self):
        messages = {}
        for _ in range(10000):
            mines._remember_message(messages, "chat", 42)
        for message_id in (50, 42, 60, 50):
            mines._remember_message(messages, "chat", message_id)
        self.assertEqual(messages["chat"], [42, 50, 60])

    async def test_batch_delete_deduplicates_and_obeys_telegram_batch_limit(self):
        telegram = SimpleNamespace(delete_messages=AsyncMock(), delete_message=AsyncMock())
        ids = list(range(1, 206)) + [1, 2, 205]
        await mines._delete_messages(42, ids, telegram)
        self.assertEqual(telegram.delete_messages.await_count, 3)
        batches = [call.kwargs["message_ids"] for call in telegram.delete_messages.call_args_list]
        self.assertEqual([len(batch) for batch in batches], [100, 100, 5])
        self.assertEqual([item for batch in batches for item in batch], list(range(1, 206)))
        telegram.delete_message.assert_not_awaited()

    async def test_failed_batch_delete_falls_back_to_individual_requests(self):
        telegram = SimpleNamespace(delete_messages=AsyncMock(side_effect=RuntimeError("batch failed")), delete_message=AsyncMock(side_effect=[RuntimeError("missing"), True]))
        await mines._delete_messages(42, [10, 10, 20], telegram)
        self.assertEqual(telegram.delete_message.await_count, 2)
        self.assertEqual([call.kwargs["message_id"] for call in telegram.delete_message.call_args_list], [10, 20])
        telegram.delete_messages.reset_mock()
        telegram.delete_message = AsyncMock()
        await mines._delete_messages(42, [], telegram)
        telegram.delete_messages.assert_not_awaited()
        telegram.delete_message.assert_not_awaited()

    async def test_p2p_sql_pages_match_original_full_list(self):
        rows = [(uid, uid % 6, uid % 9, uid % 4, (uid % 5) * 100, (uid % 3), (uid % 7) * 100, uid % 3, (uid % 11) * 500) for uid in range(10, 310)]
        mines.conn.executemany("INSERT INTO p2p_accounts(user_id, sell_order_active, mp_balance, buy_order_active, sell_price, rating, buy_price, deals_count, mcoin_balance) VALUES(?,?,?,?,?,?,?,?,?)", rows)
        mines.conn.commit()
        for buying in (True, False):
            if buying:
                sql = "SELECT user_id, sell_price, mp_balance, rating FROM p2p_accounts WHERE sell_order_active=1 AND sell_price>0 AND mp_balance>0 AND user_id!=? ORDER BY sell_price ASC"
            else:
                sql = "SELECT user_id, buy_price, mcoin_balance, rating FROM p2p_accounts WHERE buy_order_active=1 AND buy_price>0 AND mcoin_balance>=buy_price AND user_id!=? ORDER BY buy_price DESC"
            all_rows = mines.conn.execute(sql, (self.uid,)).fetchall()
            total = max(1, (len(all_rows) + 7) // 8)
            for requested in (-10, 1, 2, 3, 10000):
                page, pages, actual = mines._get_p2p_offer_page(self.uid, requested, buying)
                expected_page = max(1, min(requested, total))
                self.assertEqual((page, pages), (expected_page, total))
                self.assertEqual([tuple(row) for row in actual], [tuple(row) for row in all_rows[(page - 1) * 8:page * 8]])
                self.assertLessEqual(len(actual), 8)
            plan = mines.conn.execute("EXPLAIN QUERY PLAN " + sql, (self.uid,)).fetchall()
            expected_index = "idx_p2p_sell_offers" if buying else "idx_p2p_buy_offers"
            self.assertTrue(any(expected_index in row[3] for row in plan))

    async def test_savings_accrual_updates_all_positive_balances_once(self):
        rows = [(uid, balance, accumulated, "old") for uid, balance, accumulated in ((10, 10000, 2.5), (20, 1000, None), (30, 0, 5.0), (40, -100, 1.0))]
        mines.conn.executemany("INSERT INTO savings_accounts(user_id,balance,accumulated_interest,last_accrual) VALUES(?,?,?,?)", rows)
        mines.conn.commit()
        queries = []
        mines.conn.set_trace_callback(queries.append)
        try:
            mines._accrue_savings_interest("now")
        finally:
            mines.conn.set_trace_callback(None)
        self.assertEqual(sum(query.lstrip().startswith("UPDATE") for query in queries), 1)
        self.assertFalse(any(query.lstrip().startswith("SELECT") for query in queries))
        for uid, balance, accumulated, _ in rows:
            result = mines.conn.execute("SELECT accumulated_interest,last_accrual FROM savings_accounts WHERE user_id=?", (uid,)).fetchone()
            expected = (accumulated or 0.0) + balance * (0.002 / 24.0) if balance > 0 else accumulated
            self.assertEqual(tuple(result), (expected, "now" if balance > 0 else "old"))

    async def test_due_deposit_filter_preserves_legacy_datetime_formats(self):
        now = datetime.now()
        past = now - timedelta(seconds=10)
        deadlines = (past.isoformat(), past.strftime("%Y%m%dT%H%M%S"), past.strftime("%Y-%m-%d %H:%M:%S"), (now + timedelta(days=5)).isoformat(), "invalid")
        mines.conn.executemany("INSERT INTO time_deposits(user_id,amount,days,percent,profit,status,end_at_dt) VALUES(?,10,1,0.4,1,'active',?)", [(self.uid, deadline) for deadline in deadlines])
        mines.conn.commit()
        with patch.object(mines.asyncio, "sleep", new=AsyncMock(side_effect=StopTick)), patch.object(mines.bot, "send_message", new=AsyncMock()):
            with self.assertRaises(StopTick):
                await mines.check_time_deposits_task()
        self.assertEqual(mines.get_user(self.uid)["balance"], 33)
        statuses = mines.conn.execute("SELECT status FROM time_deposits ORDER BY id").fetchall()
        self.assertEqual([row[0] for row in statuses], ["completed", "completed", "completed", "active", "active"])

    async def test_event_names_use_local_profiles_without_network(self):
        for uid in (20, 10, 30):
            mines.save_username(uid, None, f"Name {uid}")
            mines.event_participants[uid] = 3
        mines.set_user_settings(10, bot_nickname="Ник <&>")
        with patch.object(mines.bot, "get_chat", new=AsyncMock()) as get_chat:
            links = await mines._event_participant_links()
            get_chat.assert_not_awaited()
        self.assertIn("Name 20", links[0])
        self.assertIn("Ник &lt;&amp;&gt;", links[1])
        self.assertIn("Name 30", links[2])

    async def test_chat_membership_cache_is_bounded_and_failed_writes_retry(self):
        with patch.object(mines, "CACHE_LIMIT", 3):
            for uid in range(10):
                self.assertTrue(mines.add_chat_member(uid, -42))
            self.assertEqual(len(mines._known_chat_members), 3)
            self.assertEqual(mines.conn.execute("SELECT COUNT(*) FROM chat_members WHERE chat_id=-42").fetchone()[0], 10)
        proxy = Mock(wraps=mines.cursor)
        proxy.execute.side_effect = RuntimeError("test failure")
        with patch.object(mines, "cursor", proxy):
            self.assertFalse(mines.add_chat_member(99, -42))
        self.assertNotIn((99, -42), mines._known_chat_members)
        self.assertTrue(mines.add_chat_member(99, -42))


if __name__ == "__main__":
    unittest.main()
