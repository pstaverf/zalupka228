import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

import mines
from tests.test_mines import BotTests


class AdminLoggingAndOwnerTests(BotTests):
    def setUp(self):
        super().setUp()
        self.message.reply = AsyncMock(return_value=SimpleNamespace(message_id=10))
        self.message.answer = AsyncMock(return_value=SimpleNamespace(message_id=11))
        self.message.reply_to_message = None
        mines.cursor.execute("DELETE FROM admin_audit_outbox")
        mines.cursor.execute("DELETE FROM bans")
        mines.cursor.execute("DELETE FROM top_bans")
        mines.cursor.execute("DELETE FROM transfer_bans")
        mines.cursor.execute("DELETE FROM admin_controls")
        mines.cursor.execute("DELETE FROM bot_admin_role_overrides")
        mines.conn.commit()
        mines._banned_users_cache.clear()
        mines._top_banned_users.clear()
        mines._transfer_banned_users.clear()
        mines.ADMIN_ROLE_OVERRIDES.clear()
        mines._restore_unrestricted_owner()

    async def asyncTearDown(self):
        await mines._stop_admin_logging()

    def _outbox_rows(self):
        mines.cursor.execute("SELECT id, message, created_at FROM admin_audit_outbox ORDER BY id ASC")
        return mines.cursor.fetchall()

    def test_constants_and_dictionaries(self):
        self.assertEqual(mines.ADMIN_LOG_CHAT_ID, -1004473332427)
        self.assertEqual(mines.ADMIN_LOG_INTERVAL, 3.1)
        self.assertEqual(mines.UNRESTRICTED_OWNER_ID, 6025818386)
        self.assertEqual(
            mines.ADMIN_LOG_HEADER,
            '<tg-emoji emoji-id="5444893443169983691">🚓</tg-emoji><b><i> Доставка лога</i></b>\n\n',
        )
        expected_actions = {
            "set_balance", "zero_balance", "zero_mp", "add_balance", "set_mp", "add_mp",
            "set_record", "reset_record", "reset_balances", "reset_database", "delete_user",
            "ban", "unban", "top_ban", "top_unban", "transfer_ban", "transfer_unban",
            "grant_admin", "revoke_admin", "admin_limit", "admin_permission", "create_promo",
            "giveaway", "event", "transfer_mcoin", "transfer_mp", "creator_mode", "p2p_settings",
        }
        self.assertEqual(set(mines.ADMIN_LOG_ACTIONS.keys()), expected_actions)
        expected_fields = {
            "amount", "balance", "currency", "field", "value", "reason", "until",
            "users", "kind", "permission", "enabled", "code", "activations", "setting", "yes", "no",
        }
        self.assertTrue(expected_fields.issubset(set(mines.ADMIN_LOG_FIELDS.keys())))

    def test_admin_log_formatting_truncation_escaping_and_permissions(self):
        non_admin_id = 777777
        self.assertFalse(mines._admin_log(non_admin_id, "set_balance", target_id=888888, details={"amount": 100}))
        self.assertEqual(len(self._outbox_rows()), 0)

        actor = SimpleNamespace(
            id=mines.UNRESTRICTED_OWNER_ID,
            first_name="<script>" + ("A" * 150),
            username=None,
        )
        details = {
            "amount": "<b>100</b> & " + ("9" * 200),
            "enabled": True,
            "flag_false": False,
            "d4": "v4",
            "d5": "v5",
            "d6": "v6",
            "d7_dropped": "should_not_appear",
        }
        ok = mines._admin_log(
            actor,
            "set_balance",
            target_id=9999,
            target_name="Target <img src=x> " + ("B" * 150),
            details=details,
        )
        self.assertTrue(ok)
        rows = self._outbox_rows()
        self.assertEqual(len(rows), 1)
        msg = rows[0][1]
        self.assertTrue(msg.startswith(mines.ADMIN_LOG_HEADER))
        self.assertIn(f'<a href="tg://user?id={mines.UNRESTRICTED_OWNER_ID}">', msg)
        self.assertIn(f"<code>{mines.UNRESTRICTED_OWNER_ID}</code>", msg)
        self.assertIn(f"<b>{mines.ADMIN_LOG_ACTIONS['set_balance']}</b>", msg)
        self.assertIn('<a href="tg://user?id=9999">', msg)
        self.assertIn("<code>9999</code>", msg)
        self.assertNotIn("<script>", msg)
        self.assertNotIn("<img", msg)
        self.assertIn("&lt;script&gt;", msg)
        self.assertIn("Сумма: &lt;b&gt;100&lt;/b&gt; &amp; ", msg)
        self.assertIn("Статус: да", msg)
        self.assertIn("flag_false: нет", msg)
        self.assertNotIn("d7_dropped", msg)
        self.assertIn("UTC", msg)

        mines.cursor.execute("DELETE FROM admin_audit_outbox")
        mines.conn.commit()
        self.assertTrue(mines._admin_log(actor, "reset_balances", all_users=True, details={"users": 10}))
        self.assertTrue(mines._admin_log(actor, "p2p_settings", details={"setting": "rate"}))
        rows = self._outbox_rows()
        self.assertIn("всех пользователей", rows[0][1])
        self.assertIn("настройки бота", rows[1][1])

    def test_admin_log_transaction_safety_and_insert_failure(self):
        actor = mines.UNRESTRICTED_OWNER_ID
        mines.update_user(self.uid, balance=500)
        mines.conn.execute("BEGIN IMMEDIATE")
        try:
            mines.cursor.execute("UPDATE users SET balance = 999999 WHERE user_id = ?", (self.uid,))
            with self.assertLogs(level="ERROR"):
                self.assertFalse(mines._admin_log(actor, "set_balance", target_id=self.uid))
            self.assertTrue(mines.conn.in_transaction)
            mines.conn.rollback()
        finally:
            if mines.conn.in_transaction:
                mines.conn.rollback()
        self.assertEqual(mines.get_user(self.uid)["balance"], 500)
        self.assertEqual(len(self._outbox_rows()), 0)

        mines.cursor.execute(
            "CREATE TEMP TRIGGER fail_outbox BEFORE INSERT ON admin_audit_outbox "
            "BEGIN SELECT RAISE(ABORT, 'outbox failure'); END"
        )
        try:
            mines.update_user(self.uid, balance=1234)
            with self.assertLogs(level="ERROR") as cm:
                self.assertFalse(mines._admin_log(actor, "set_balance", target_id=self.uid, details={"balance": 1234}))
            self.assertFalse(mines.conn.in_transaction)
            self.assertEqual(mines.get_user(self.uid)["balance"], 1234)
            log_output = "\n".join(cm.output)
            self.assertIn(str(actor), log_output)
            self.assertIn("set_balance", log_output)
            self.assertIn(str(self.uid), log_output)
        finally:
            mines.cursor.execute("DROP TRIGGER fail_outbox")

    async def test_admin_log_worker_fifo_retry_after_and_cancel(self):
        actor = mines.UNRESTRICTED_OWNER_ID
        mines._admin_log(actor, "add_balance", target_id=101, details={"amount": 10})
        mines._admin_log(actor, "set_balance", target_id=102, details={"balance": 20})
        self.assertEqual(len(self._outbox_rows()), 2)

        sent_messages = []
        calls = 0

        async def fake_send_message(chat_id, text, parse_mode=None, request_timeout=None, **kwargs):
            nonlocal calls
            calls += 1
            self.assertEqual(chat_id, mines.ADMIN_LOG_CHAT_ID)
            self.assertEqual(parse_mode, ParseMode.HTML)
            self.assertEqual(request_timeout, 15)
            if calls == 1:
                raise TelegramRetryAfter(
                    method=SendMessage(chat_id=chat_id, text=text),
                    message="Flood control",
                    retry_after=0.01,
                )
            sent_messages.append(text)
            return SimpleNamespace(message_id=calls)

        with patch.object(mines.bot, "send_message", side_effect=fake_send_message), patch.object(
            mines, "ADMIN_LOG_INTERVAL", 0.01
        ):
            task1 = mines._start_admin_logging()
            task2 = mines._start_admin_logging()
            self.assertIs(task1, task2)
            for _ in range(50):
                if not self._outbox_rows():
                    break
                await asyncio.sleep(0.01)
            await mines._stop_admin_logging()

        self.assertEqual(len(sent_messages), 2)
        self.assertIn("<code>101</code>", sent_messages[0])
        self.assertIn("<code>102</code>", sent_messages[1])
        self.assertEqual(len(self._outbox_rows()), 0)

    async def test_worker_preserves_row_on_send_error_or_cancellation(self):
        actor = mines.UNRESTRICTED_OWNER_ID
        mines._admin_log(actor, "ban", target_id=555, details={"reason": "test"})
        self.assertEqual(len(self._outbox_rows()), 1)

        async def cancel_during_send(*args, **kwargs):
            raise asyncio.CancelledError()

        with patch.object(mines.bot, "send_message", side_effect=cancel_during_send):
            task = mines._start_admin_logging()
            await mines._stop_admin_logging()
            self.assertTrue(task.done())

        self.assertEqual(len(self._outbox_rows()), 1)

    async def test_hooks_on_admin_commands_and_no_secret_leak_in_event(self):
        target_id = 4321
        mines.get_user(target_id)
        mines.save_username(target_id, "targetuser", "TargetUser")
        self.user.id = mines.UNRESTRICTED_OWNER_ID
        self.message.from_user = self.user
        self.message.reply_to_message = SimpleNamespace(
            from_user=SimpleNamespace(id=target_id, first_name="TargetUser", username="targetuser")
        )

        self.message.text = "/add 500"
        await mines.cmd_add(self.message)
        self.message.text = "/set 0"
        await mines.cmd_set(self.message)
        self.message.text = "/set 1000"
        await mines.cmd_set(self.message)
        self.message.text = "/addmp 50"
        await mines.cmd_addmp(self.message)
        self.message.text = "/setmp 0"
        await mines.cmd_setmp(self.message)
        self.message.text = "/setmp 25"
        await mines.cmd_setmp(self.message)
        self.message.text = "/setrec баланс 5000"
        await mines.cmd_setrec(self.message)
        self.message.text = "/delrec все"
        await mines.cmd_delrec(self.message)
        self.message.text = "/ban спам 1ч"
        await mines.cmd_ban(self.message)
        self.message.text = "/unban"
        await mines.cmd_unban(self.message)
        self.message.text = "/tban"
        await mines.cmd_tban(self.message)
        self.message.text = "/untban"
        await mines.cmd_untban(self.message)
        self.message.text = "/trban"
        await mines.cmd_trban(self.message)
        self.message.text = "/untrban"
        await mines.cmd_untrban(self.message)
        self.message.text = "/cprom PROMO1 1000 5"
        await mines.cmd_cprom(self.message)

        with patch.object(mines.bot, "pin_chat_message", new_callable=AsyncMock):
            mines.event_active = False
            self.message.text = "/event 100 999 10000 5"
            await mines.cmd_event(self.message)
            mines.event_active = False

        rows = [r[1] for r in self._outbox_rows()]
        self.assertGreaterEqual(len(rows), 16)
        event_log = rows[-1]
        self.assertIn(mines.ADMIN_LOG_ACTIONS["event"], event_log)
        self.assertIn("100-999", event_log)
        self.assertNotIn(f": {mines.event_number}\n", event_log)

        count_before_get = len(self._outbox_rows())
        self.message.text = "/get"
        await mines.cmd_get(self.message)
        self.assertEqual(len(self._outbox_rows()), count_before_get)

    async def test_unrestricted_owner_protections_and_privileges(self):
        owner_id = mines.UNRESTRICTED_OWNER_ID
        mines.cursor.execute(
            "INSERT OR REPLACE INTO bans (user_id, reason, until, is_permanent) VALUES (?, 'x', NULL, 1)",
            (owner_id,),
        )
        mines.cursor.execute("INSERT OR REPLACE INTO top_bans (user_id, banned_at) VALUES (?, 'now')", (owner_id,))
        mines.cursor.execute("INSERT OR REPLACE INTO transfer_bans (user_id, banned_at) VALUES (?, 'now')", (owner_id,))
        mines.cursor.execute(
            "INSERT OR REPLACE INTO bot_admin_role_overrides (user_id, enabled, updated_by, updated_at) VALUES (?, 0, 1, 'now')",
            (owner_id,),
        )
        mines.cursor.execute(
            "INSERT OR REPLACE INTO admin_controls (admin_id, can_ban, transfer_limit) VALUES (?, 0, 10)",
            (owner_id,),
        )
        mines.conn.commit()
        mines._banned_users_cache[owner_id] = {"reason": "x", "is_perm": True}
        mines._top_banned_users.add(owner_id)
        mines._transfer_banned_users.add(owner_id)
        mines.ADMIN_ROLE_OVERRIDES[owner_id] = False

        mines._restore_unrestricted_owner()

        self.assertTrue(mines.is_owner(owner_id))
        self.assertTrue(mines.is_admin(owner_id))
        self.assertIn(owner_id, mines.ADMINS)
        self.assertIn(owner_id, mines.OWNER_IDS)
        self.assertIsNone(mines.check_user_ban(owner_id))
        self.assertFalse(mines.is_top_banned(owner_id))
        self.assertFalse(mines.is_transfer_banned(owner_id))

        self.assertFalse(mines.ban_user(owner_id, "reason", is_permanent=True))
        self.assertFalse(mines.ban_user_top(owner_id))
        self.assertFalse(mines.ban_user_transfers(owner_id))
        self.assertFalse(mines.set_admin_limit(owner_id, "all", 100, owner_id))
        self.assertFalse(mines.set_admin_permission(owner_id, "ban", False, owner_id))
        self.assertFalse(mines._save_admin_role(owner_id, False, owner_id))
        self.assertTrue(mines.admin_has_permission(owner_id, "ban"))
        self.assertEqual(mines.reserve_admin_usage(owner_id, "transfer", 10**12), (True, None))

        mines._top_banned_users.add(owner_id)
        mines._transfer_banned_users.add(owner_id)
        self.user.id = owner_id
        self.message.from_user = self.user
        self.message.reply_to_message = SimpleNamespace(
            from_user=SimpleNamespace(id=owner_id, first_name="Owner", username="owner")
        )
        self.message.text = "/untban"
        await mines.cmd_untban(self.message)
        self.assertNotIn(owner_id, mines._top_banned_users)
        self.message.text = "/untrban"
        await mines.cmd_untrban(self.message)
        self.assertNotIn(owner_id, mines._transfer_banned_users)

        other_admin = 555555
        mines.get_user(other_admin)
        if other_admin not in mines.ADMINS:
            mines.ADMINS.append(other_admin)
        self.message.reply_to_message = SimpleNamespace(
            from_user=SimpleNamespace(id=other_admin, first_name="AdminTwo", username="admintwo")
        )
        self.message.text = "/ban тест 1ч"
        await mines.cmd_ban(self.message)
        self.assertIsNotNone(mines.check_user_ban(other_admin))
        mines.unban_user(other_admin)

    async def test_owner_unlimited_mp_transfers_and_ui_infinity(self):
        owner_id = mines.UNRESTRICTED_OWNER_ID
        receiver_id = 654321
        mines.get_user(owner_id)
        mines.get_user(receiver_id)
        mines.update_user(owner_id, mp_balance=5000)

        owner_data = mines.get_user(owner_id)
        self.assertIsNone(mines.get_user_mp_limit(owner_data))
        self.assertIsNone(mines.get_user_mp_limit(owner_id))
        self.assertEqual(mines.get_user_mp_limit(mines.get_user(receiver_id)), 1000)

        today = mines.get_msk_today_str()
        self.assertTrue(mines._apply_mp_transfer(owner_id, receiver_id, 2500, today))
        self.assertEqual(mines.get_user(owner_id)["mp_balance"], 2500)
        self.assertEqual(mines.get_user(receiver_id)["mp_balance"], 2500)

        mines.update_user(receiver_id, mp_balance=5000)
        self.assertFalse(mines._apply_mp_transfer(receiver_id, owner_id, 1500, today))

        self.user.id = owner_id
        self.message.from_user = self.user
        self.message.answer.reset_mock()
        await mines.cmd_point(self.message)
        self.assertIn("∞", self.message.answer.call_args.args[0])

        panel_text = mines._panel_home_text(owner_id)
        self.assertIn("∞", panel_text)

    def test_sqlite_error_handling_in_ban_and_admin_controls(self):
        target_id = 333333
        mines.get_user(target_id)
        if target_id not in mines.ADMINS:
            mines.ADMINS.append(target_id)

        mines.cursor.execute(
            "CREATE TEMP TRIGGER fail_bans BEFORE INSERT ON bans "
            "BEGIN SELECT RAISE(ABORT, 'ban db error'); END"
        )
        try:
            with self.assertLogs(level="ERROR"):
                self.assertFalse(mines.ban_user(target_id, "err", is_permanent=True))
            self.assertFalse(mines.conn.in_transaction)
            self.assertIsNone(mines.check_user_ban(target_id))
        finally:
            mines.cursor.execute("DROP TRIGGER fail_bans")

        mines.cursor.execute(
            "CREATE TEMP TRIGGER fail_admin_ctl BEFORE UPDATE ON admin_controls "
            "BEGIN SELECT RAISE(ABORT, 'ctl db error'); END"
        )
        try:
            with self.assertLogs(level="ERROR"):
                self.assertFalse(mines.set_admin_limit(target_id, "transfer", 500, mines.UNRESTRICTED_OWNER_ID))
            self.assertFalse(mines.conn.in_transaction)
            with self.assertLogs(level="ERROR"):
                self.assertFalse(mines.set_admin_permission(target_id, "ban", False, mines.UNRESTRICTED_OWNER_ID))
            self.assertFalse(mines.conn.in_transaction)
        finally:
            mines.cursor.execute("DROP TRIGGER fail_admin_ctl")


if __name__ == "__main__":
    unittest.main()
