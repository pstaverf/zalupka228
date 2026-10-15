import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
import tracemalloc
from unittest.mock import AsyncMock, patch
import types


ROOT = Path(__file__).resolve().parents[1]


def load_bot(ref, directory):
    source = subprocess.check_output(["git", "show", f"{ref}:mines.py"], cwd=ROOT, text=True) if ref else (ROOT / "mines.py").read_text()
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:" + "a" * 35
    os.environ["SQLITE_DB_PATH"] = str(Path(directory) / "benchmark.sqlite3")
    module = types.ModuleType("benchmark_bot")
    module.__file__ = str(ROOT / "mines.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


class StopTick(BaseException):
    pass


async def measure(module, iterations):
    user = module.types.User(id=1234, is_bot=False, first_name="Benchmark")
    message = module.types.Message(message_id=1, date=datetime.now(timezone.utc), chat=module.types.Chat(id=1234, type="private"), from_user=user, text="/settings")
    callback = module.types.CallbackQuery(id="benchmark", from_user=user, chat_instance="benchmark", message=message, data="promote_rules")
    result = {}
    for name, observer, event in (("settings_routing", module.dp.message, message), ("late_callback_routing", module.dp.callback_query, callback)):
        samples = []
        selected = None
        for iteration in range(iterations + 5):
            start = time.perf_counter()
            for handler in observer.handlers:
                matched, _ = await handler.check(event, bot=module.bot)
                if matched:
                    selected = handler.callback.__name__
                    break
            elapsed = (time.perf_counter() - start) * 1000
            if iteration >= 5:
                samples.append(elapsed)
        samples.sort()
        result[name] = {"median_ms": round(statistics.median(samples), 4), "p95_ms": round(samples[int(len(samples) * .95)], 4), "handler": selected}
    start = time.perf_counter()
    for _ in range(10000):
        module.get_multiplier(3, 5)
        module.get_tower_multiplier(2, 5)
        module.get_qwak_multiplier(3)
        module.get_diamonds_multiplier(1, 5)
    result["40000_multiplier_lookups_ms"] = round((time.perf_counter() - start) * 1000, 3)
    statements = []
    module.get_admin_control(1234)
    module.conn.set_trace_callback(statements.append)
    for _ in range(20):
        module.get_admin_control(1234)
    module.conn.set_trace_callback(None)
    result["20_admin_control_reads"] = {"statements": len(statements), "writes": sum(query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in statements)}
    module.get_user(1234)
    reads = []
    module.conn.set_trace_callback(reads.append)
    async def read_user(event, data):
        for _ in range(20):
            module.get_user(1234)
    if hasattr(module, "_cache_reads_middleware"):
        await module._cache_reads_middleware(read_user, message, {})
    else:
        await read_user(message, {})
    module.conn.set_trace_callback(None)
    result["20_user_reads_in_one_event"] = sum(query.startswith("SELECT balance, games") for query in reads)
    module.conn.executemany(
        "INSERT INTO p2p_accounts(user_id,sell_order_active,sell_price,mp_balance,rating) VALUES(?,1,?,100,100)",
        ((uid, ((uid % 100) + 1) * 100) for uid in range(2000, 12000)),
    )
    module.conn.commit()
    fake = types.SimpleNamespace(from_user=user, data="p2p_buy_list", answer=AsyncMock(), message=types.SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()))
    samples = []
    for iteration in range(35):
        fake.message.edit_text.reset_mock()
        start = time.perf_counter()
        await module.cb_p2p_buy_list(fake)
        if iteration >= 5:
            samples.append((time.perf_counter() - start) * 1000)
    fake.message.edit_text.reset_mock()
    tracemalloc.start()
    await module.cb_p2p_buy_list(fake)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result["p2p_first_page_10000_offers"] = {"median_ms": round(statistics.median(samples), 4), "peak_allocated_kib": round(peak / 1024, 1)}
    module.conn.executemany(
        "INSERT INTO savings_accounts(user_id,balance,accumulated_interest) VALUES(?,10000,0.0)",
        ((uid,) for uid in range(2000, 12000)),
    )
    module.conn.commit()
    updates = 0
    def count_updates(query):
        nonlocal updates
        if query.lstrip().startswith("UPDATE savings_accounts"):
            updates += 1
    module.conn.set_trace_callback(count_updates)
    with patch.object(module.asyncio, "sleep", new=AsyncMock(side_effect=[None, StopTick()])):
        start = time.perf_counter()
        try:
            await module.accrue_savings_task()
        except StopTick:
            pass
        elapsed = (time.perf_counter() - start) * 1000
    module.conn.set_trace_callback(None)
    result["savings_accrual_10000_accounts"] = {"elapsed_ms": round(elapsed, 3), "update_statements": updates}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref")
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        module = load_bot(args.ref, directory)
        try:
            print(json.dumps(asyncio.run(measure(module, args.iterations)), ensure_ascii=False, indent=2))
        finally:
            module.conn.close()


if __name__ == "__main__":
    main()
