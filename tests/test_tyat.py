"""Unit tests for the tyat CLI (stdlib unittest; run: python3 -m unittest discover tests)."""
import contextlib
import datetime as dt
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_tmp = tempfile.TemporaryDirectory()
os.environ["TYAT_TASKS"] = str(Path(_tmp.name) / "tasks.md")  # never touch the real task file

_loader = importlib.machinery.SourceFileLoader("tyat", str(REPO / "tyat"))
_spec = importlib.util.spec_from_loader("tyat", _loader)
tyat = importlib.util.module_from_spec(_spec)
_loader.exec_module(tyat)

NOW = dt.datetime(2026, 10, 28, 12, 0)  # a Wednesday


class Base(unittest.TestCase):
    def setUp(self):
        self._now, tyat.now = tyat.now, NOW
        tyat.TASKS.unlink(missing_ok=True)

    def tearDown(self):
        tyat.now = self._now


class TaskLine(Base):
    def test_parse_fields(self):
        t = tyat.Task(False, "Review report @products/x due:2026-10-27T14:00 pri:2 id:b via:claude sid:abc")
        self.assertEqual(t.text, "Review report")
        self.assertEqual(t.f["at"], "products/x")
        self.assertEqual((t.id, t.pri, t.f["via"], t.f["sid"]), ("b", 2, "claude", "abc"))
        self.assertEqual(t.due, dt.datetime(2026, 10, 27, 14, 0))

    def test_missing_fields(self):
        t = tyat.Task(False, "Plain text")
        self.assertEqual((t.id, t.due, t.pri, t.next), ("?", None, 0, None))

    def test_bad_due_is_none(self):
        self.assertIsNone(tyat.Task(False, "x due:soon").due)

    def test_hand_edited_bad_pri_is_zero(self):
        self.assertEqual(tyat.Task(False, "x pri:high").pri, 0)

    def test_save_leaves_no_temp_file(self):
        tyat.save(*tyat.load())
        self.assertEqual([p.name for p in tyat.TASKS.parent.iterdir()], [tyat.TASKS.name])

    def test_next_is_latest_note(self):
        t = tyat.Task(False, "x id:a")
        t.notes = ["next: first", "other", "next: second"]
        self.assertEqual(t.next, "second")

    def test_save_load_roundtrip(self):
        head, _ = tyat.load()
        a = tyat.Task(False, "Open one @p due:2026-10-29T09:00 pri:1 id:a")
        a.notes.append("next: do it")
        b = tyat.Task(True, "Closed one id:b done:2026-10-28T10:00")
        tyat.save(head, [b, a])
        head2, tasks2 = tyat.load()
        self.assertEqual(head2, head)
        self.assertEqual([t.line() for t in tasks2], [a.line(), b.line()])  # open first, then closed
        self.assertEqual(tasks2[0].next, "do it")


class NewId(Base):
    def test_first_and_skips_used_and_reserved(self):
        self.assertEqual(tyat.new_id([]), "a")
        used = [tyat.Task(False, f"t id:{c}") for c in "abcdefghijklm"]
        self.assertEqual(tyat.new_id(used), "p")  # n and o are reserved board keys

    def test_done_ids_are_reusable(self):
        self.assertEqual(tyat.new_id([tyat.Task(True, "t id:a")]), "a")
        self.assertEqual(tyat.new_id([tyat.Task(True, "t id:a done:2026-10-20T10:00")]), "a")

    def test_ids_finished_today_are_not_reused_yet(self):
        # "af is done" and "the new af" in one evening is how tasks get mixed up
        self.assertEqual(tyat.new_id([tyat.Task(True, "t id:a done:2026-10-28T09:30")]), "b")

    def test_rolls_over_to_two_letters(self):
        used = [tyat.Task(False, f"t id:{chr(97 + i)}") for i in range(26)]
        self.assertEqual(tyat.new_id(used), "aa")


class ParseWhen(Base):
    def when(self, s):
        return tyat.parse_when(s.split())

    def test_no_time_words(self):
        self.assertEqual(self.when("buy milk"), (None, ["buy", "milk"]))

    def test_today_tomorrow_default_nine(self):
        self.assertEqual(self.when("x tomorrow")[0], dt.datetime(2026, 10, 29, 9, 0))
        self.assertEqual(self.when("morgen 14:30")[0], dt.datetime(2026, 10, 29, 14, 30))

    def test_bare_time_rolls_to_tomorrow_when_past(self):
        self.assertEqual(self.when("15:00")[0], dt.datetime(2026, 10, 28, 15, 0))
        self.assertEqual(self.when("10:00")[0], dt.datetime(2026, 10, 29, 10, 0))

    def test_weekday_is_always_future(self):
        self.assertEqual(self.when("fri")[0], dt.datetime(2026, 10, 30, 9, 0))
        self.assertEqual(self.when("wednesday")[0], dt.datetime(2026, 11, 4, 9, 0))

    def test_relative(self):
        self.assertEqual(self.when("2h")[0], dt.datetime(2026, 10, 28, 14, 0))
        self.assertEqual(self.when("3d")[0], dt.datetime(2026, 10, 31, 9, 0))
        self.assertEqual(self.when("+30min")[0], dt.datetime(2026, 10, 28, 12, 30))

    def test_am_pm_and_uhr(self):
        self.assertEqual(self.when("tomorrow 3pm")[0], dt.datetime(2026, 10, 29, 15, 0))
        self.assertEqual(self.when("tomorrow 12am")[0], dt.datetime(2026, 10, 29, 0, 0))
        self.assertEqual(self.when("tomorrow 8uhr")[0], dt.datetime(2026, 10, 29, 8, 0))

    def test_dates(self):
        self.assertEqual(self.when("2026-11-02")[0], dt.datetime(2026, 11, 2, 9, 0))
        self.assertEqual(self.when("02.11.")[0], dt.datetime(2026, 11, 2, 9, 0))
        self.assertEqual(self.when("01.02.")[0], dt.datetime(2027, 2, 1, 9, 0))  # past day-month → next year

    def test_invalid_date_or_time_exits_cleanly(self):
        for w in ("31.02.", "25:00", "2026-13-01"):
            with self.subTest(w=w), self.assertRaises(SystemExit) as cm:
                self.when(w)
            self.assertIn("invalid date/time", str(cm.exception.code))

    def test_keeps_other_words(self):
        due, rest = self.when("Send list, tomorrow 17:00")
        self.assertEqual((due, rest), (dt.datetime(2026, 10, 29, 17, 0), ["Send", "list,"]))


class Recommend(Base):
    def test_ranking_order(self):
        tasks = [
            tyat.Task(False, "later id:a due:2026-11-10T09:00"),
            tyat.Task(False, "someday id:b"),
            tyat.Task(False, "prio id:c pri:3"),
            tyat.Task(False, "soon id:d due:2026-10-28T13:00"),
            tyat.Task(False, "overdue id:e due:2026-10-28T08:00"),
            tyat.Task(False, "tonight id:f due:2026-10-28T20:00"),
            tyat.Task(True, "finished id:g due:2026-10-27T08:00"),
        ]
        ss = [{"sid": "s1", "status": "waiting", "since": 600, "who": "claude", "cwd": str(tyat.ROOT / "p")}]
        recs = tyat.recommend(tasks, ss)
        self.assertEqual([r[2] for r in recs],
                         [("jump", 1), ("go", "e"), ("go", "d"), ("go", "c"), ("go", "f"), ("go", "b")])

    def test_task_with_live_session_is_not_started_again(self):
        t = tyat.Task(False, "busy id:a sid:s1 due:2026-10-28T08:00")
        ss = [{"sid": "s1", "status": "busy", "since": 60, "who": "claude", "cwd": "/x"}]
        self.assertEqual(tyat.recommend([t], ss), [])


class Page(Base):
    def test_effort_and_reach_tokens_roundtrip(self):
        t = tyat.Task(False, "Push commits @p est:10m reach:4 id:a")
        self.assertEqual((t.text, tyat.est_min(t.f["est"]), t.f["reach"]), ("Push commits", 10, "4"))
        self.assertIn("est:10m reach:4 id:a", t.line())
        self.assertEqual((tyat.est_min("2h"), tyat.est_min("soon"), tyat.est_min(None)), (120, None, None))

    def test_quick_high_reach_beats_slow_low_reach(self):
        quick = tyat.leverage(2 * 4 + 1.5 * tyat.urgency(NOW + dt.timedelta(hours=5)), 10)
        slow = tyat.leverage(2 * 2 + 1.5 * tyat.urgency(None), 180)
        self.assertGreater(quick, slow)
        self.assertEqual([tyat.urgency(NOW + dt.timedelta(hours=h)) for h in (-1, 5, 48, 100, 400)], [4, 3, 2, 1, 0])

    def test_calendar_rows(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        pub = Path(tmp.name); (pub / "docs").mkdir()
        (pub / "docs/priority.json").write_text('{"hack": {"wichtigkeit": 5}}')
        (pub / "docs/editorial-calendar.md").write_text(
            "| story | group | channel | owner | target_datetime | ready_by | status | source_article | blocker |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| **Hack Day** | hack | LinkedIn | M | **Fr 2026-10-30, 08:30** ~~Do 2026-10-29, 07:00~~ | x | ready | a.md | — |\n"
            "| Old | x | WA | M | So 2026-11-01 | x | planned | — | Text fehlt |\n"
            "| Done | x | WA | M | 2026-10-29, 10:00 | x | posted | — | — |\n"
            "| Far | x | WA | M | 2026-12-01, 10:00 | x | planned | — | — |\n")
        old, tyat.PUB = tyat.PUB, pub
        try: rows = tyat.calendar_rows()
        finally: tyat.PUB = old
        self.assertEqual([(r["title"], r["due"], r["reach"], r["status"]) for r in rows],
                         [("Hack Day", dt.datetime(2026, 10, 30, 8, 30), 5, "ready"),
                          ("Old", dt.datetime(2026, 11, 1, 9, 0), 3, "planned")])


class Launch(Base):
    def test_without_a_terminal_it_opens_an_iterm_tab_instead_of_running_headless(self):
        calls = []
        real_run = tyat.subprocess.run
        tyat.subprocess.run = lambda argv, **kw: calls.append(argv)
        try:  # a StringIO stdout is no terminal, like an agent's
            with contextlib.redirect_stdout(io.StringIO()):
                tyat.launch(Path("/tmp/x y"), "claude", ["claude", "--session-id", "s1", "Task [a]: it's \"quoted\""])
        finally: tyat.subprocess.run = real_run
        self.assertEqual(calls[0][:2], ["osascript", "-e"])
        self.assertIn("iTerm2", calls[0][2])
        self.assertIn("cd '/tmp/x y' && claude --session-id s1", calls[0][2])


class Dispatch(Base):
    def test_commands_after_the_unknown_check_still_dispatch(self):
        called = []
        old = tyat.notify_pass
        tyat.notify_pass = lambda: called.append("notify")
        try: tyat.main(["notify"])
        finally: tyat.notify_pass = old
        self.assertEqual(called, ["notify"])


class Rhythm(Base):
    def test_defaults_and_override(self):
        old = os.environ.pop("TYAT_RHYTHM", None)
        try:
            self.assertEqual((tyat.rhythm()["prep"], tyat.rhythm()["stop"]), ((22, 3.5), (1, 30)))
            os.environ["TYAT_RHYTHM"] = "do=11,1.5 stop=23:00 sport=bad"
            g = tyat.rhythm()
            self.assertEqual((g["do"], g["stop"], g["sport"]), ((11, 1.5), (23, 0), (16, 1.5)))
        finally:
            os.environ.pop("TYAT_RHYTHM", None)
            if old is not None: os.environ["TYAT_RHYTHM"] = old

    def test_night_share_counts_after_stop_and_before_five(self):
        counts = [0] * 24
        counts[1], counts[12], counts[22], counts[23] = 10, 70, 10, 10
        self.assertEqual(tyat.night_share(counts, (22, 30)), 20)  # 22:00 is still before 22:30
        self.assertEqual(tyat.night_share(counts, (22, 0)), 30)
        self.assertEqual(tyat.night_share(counts, (1, 30)), 0)   # 01:00 is inside a 01:30 stop
        self.assertEqual(tyat.night_share(counts, (0, 30)), 10)

    def test_next_slot(self):
        self.assertEqual(tyat.next_slot(12, 2), NOW)  # 12:00 is inside 12–14
        self.assertEqual(tyat.next_slot(20, 2), dt.datetime(2026, 10, 28, 20, 0))
        self.assertEqual(tyat.next_slot(9, 1), dt.datetime(2026, 10, 29, 9, 0))

    def test_deadline_before_next_block_is_done_now_not_dropped(self):
        tyat.now = dt.datetime(2026, 10, 30, 15, 0)  # 1h left in the deep block, next block 22:00
        def item(id, mins, due, lev=1):
            return {"id": id, "mode": "prep", "mins": mins, "due": dt.datetime(2026, 10, 30, *due), "lev": lev}
        video, devpost, hopeless = item("g", 90, (16, 30)), item("h", 45, (17, 30)), item("x", 120, (15, 45))
        timeline, overflow = tyat.schedule([devpost, video, hopeless], tyat.rhythm())
        start, kind, rows = timeline[0]
        self.assertEqual((start, kind, rows), (tyat.now, "now", [video, devpost]))
        self.assertEqual(overflow, [hopeless])  # 2h of work, 30m to the deadline: that one really doesn't fit


class Phone(Base):
    def item(self, id, mins, due=None, mode="prep", lev=1):
        return {"kind": "task", "id": id, "title": f"Task {id}", "mode": mode, "mins": mins, "lev": lev, "where": "p",
                "next": None, "cmd": f"t go {id}", "due": due and dt.datetime(2026, 10, 28, *due)}

    def test_sections_cover_work_sport_and_stop_in_order(self):
        tyat.now = dt.datetime(2026, 10, 28, 23, 0)  # inside the night block
        secs, overflow = tyat.phone_sections([self.item("a", 60), self.item("b", 10, mode="exec")], tyat.rhythm())
        kinds = [(k, s) for _, k, s, _, _ in secs]
        self.assertEqual(kinds[0], ("prep", tyat.now))
        self.assertEqual(secs[0][3], dt.datetime(2026, 10, 29, 1, 30))  # the night block ends at 01:30, not 01:30 + a day
        self.assertIn(("stop", dt.datetime(2026, 10, 29, 1, 30)), kinds)
        self.assertEqual([k for k, _ in kinds], sorted([k for k, _ in kinds], key=lambda k: dict(kinds)[k]))
        self.assertEqual(overflow, [])

    def test_block_that_began_yesterday_ends_today(self):
        tyat.now = dt.datetime(2026, 10, 29, 0, 30)
        secs, _ = tyat.phone_sections([self.item("a", 30)], tyat.rhythm())
        self.assertEqual((secs[0][1], secs[0][3]), ("prep", dt.datetime(2026, 10, 29, 1, 30)))

    def test_page_escapes_and_voice_is_speakable(self):
        it = {**self.item("a", 30), "title": "<b>Send</b> 🚀 deck to ~/x/y"}
        html = tyat.phone_html([("prep-x", "prep", NOW, NOW + dt.timedelta(hours=1), [it])], [], tyat.rhythm())
        self.assertIn("&lt;b&gt;Send", html)
        self.assertNotIn("<b>Send", html)
        self.assertIn('data-voice="prep-x"', html)
        self.assertEqual(tyat.voice_text("prep", [it], (1, 30)), "Nacht-Block. Erstens: Send deck to.")
        self.assertIn("1 Uhr.", tyat.voice_text("stop", [], (1, 0)))

    def test_voice_clips_are_cached_by_text_outside_the_deployed_folder(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out, cache, calls = Path(tmp.name) / "public/voice", Path(tmp.name) / ".voice-cache", []
        out.mkdir(parents=True); (out / "old.mp3").write_bytes(b"x")
        old_key = tyat.eleven_key; self.addCleanup(setattr, tyat, "eleven_key", old_key)
        tyat.eleven_key = lambda: "k"
        def say(text, key): calls.append(text); return text.encode()
        self.assertEqual(tyat.render_voices({"a": "Hallo", "b": "Tschüss"}, out, cache, say), 12)
        self.assertEqual(tyat.render_voices({"a": "Hallo", "c": "Hallo"}, out, cache, say), 0)  # same text: no new characters
        self.assertEqual(calls, ["Hallo", "Tschüss"])
        self.assertEqual(sorted(f.name for f in out.iterdir()), ["a.mp3", "c.mp3"])  # no cache, nothing stale deployed

    def test_without_a_key_a_changed_briefing_loses_its_old_clip(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out, cache = Path(tmp.name) / "voice", Path(tmp.name) / "cache"
        old_key = tyat.eleven_key; self.addCleanup(setattr, tyat, "eleven_key", old_key)
        tyat.eleven_key = lambda: "k"
        tyat.render_voices({"a": "Alter Titel", "b": "Sport"}, out, cache, lambda t, k: b"mp3")
        tyat.eleven_key = lambda: ""
        with contextlib.redirect_stdout(io.StringIO()):
            tyat.render_voices({"a": "Neuer Titel", "b": "Sport"}, out, cache, lambda t, k: self.fail("no key, no call"))
        self.assertEqual(sorted(f.name for f in out.iterdir()), ["b.mp3"])  # cache hit kept, stale "a" gone

    def test_never_deploys_without_the_key_guard(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        plan = Path(tmp.name)
        cfg = plan / "wrangler.jsonc"
        self.assertFalse(tyat.guarded(plan))
        (plan / "worker.js").write_text('if (!env.PLAN_KEY) ...; return new Response("x", { status: 401 })')
        cfg.write_text('{"main": "worker.js", "assets": {"directory": "./public"}}')
        self.assertFalse(tyat.guarded(plan))
        cfg.write_text('{\n  /* "run_worker_first": true */\n  "main": "worker.js", "assets": {"run_worker_first": false}}')
        self.assertFalse(tyat.guarded(plan))  # a commented-out flag does not count
        cfg.write_text('{\n  // key guard, url "https://x//y"\n  "main": "worker.js", "assets": {"run_worker_first": true}}')
        self.assertTrue(tyat.guarded(plan))
        (plan / "worker.js").write_text("export default { fetch: (r, env) => env.ASSETS.fetch(r) }")
        self.assertFalse(tyat.guarded(plan))  # a worker that checks no key is no guard

    def test_task_must_finish_before_its_deadline_not_just_start(self):
        tyat.now = dt.datetime(2026, 10, 29, 0, 30)  # 1h left of the night block
        late = self.item("a", 45, None); late["due"] = dt.datetime(2026, 10, 29, 0, 45)
        _, overflow = tyat.schedule([late], tyat.rhythm())
        self.assertEqual(overflow, [late])

    def test_rush_work_comes_after_the_running_blocks_items(self):
        tyat.now = dt.datetime(2026, 10, 28, 15, 0)  # deep block 14–16 is running
        a, b = self.item("a", 30, (15, 30)), self.item("b", 90, (17, 0))
        secs, overflow = tyat.phone_sections([a, b], tyat.rhythm())
        work = [(k, s, [i["id"] for i in r]) for _, k, s, _, r in secs if r]
        self.assertEqual(work[:2], [("deep", tyat.now, ["a"]), ("now", dt.datetime(2026, 10, 28, 15, 30), ["b"])])
        self.assertEqual(overflow, [])

    def test_running_windows_keep_their_real_end(self):
        tyat.now = dt.datetime(2026, 10, 28, 17, 0)  # inside sport 16:00–17:30
        secs, _ = tyat.phone_sections([], tyat.rhythm())
        self.assertIn(("sport", tyat.now, dt.datetime(2026, 10, 28, 17, 30)), [(k, s, e) for _, k, s, e, _ in secs])
        tyat.now = dt.datetime(2026, 10, 29, 4, 45)  # inside the stop 01:30–05:00
        secs, _ = tyat.phone_sections([], tyat.rhythm())
        self.assertIn(("stop", tyat.now, dt.datetime(2026, 10, 29, 5, 0)), [(k, s, e) for _, k, s, e, _ in secs])


class Report(Base):
    def test_workday_runs_from_five_to_five(self):
        tyat.now = dt.datetime(2026, 10, 29, 0, 30)
        self.assertEqual(tyat.workday_start(), dt.datetime(2026, 10, 28, 5, 0))
        tyat.now = dt.datetime(2026, 10, 29, 6, 0)
        self.assertEqual(tyat.workday_start(), dt.datetime(2026, 10, 29, 5, 0))

    def test_report_counts_today_done_late_and_soon(self):
        tyat.now = dt.datetime(2026, 10, 29, 0, 30)
        tasks = [tyat.Task(True, "Shipped @p id:a done:2026-10-28T23:10"), tyat.Task(True, "Old @p id:b done:2026-10-27T23:10"),
                 tyat.Task(False, "Late one @p id:c due:2026-10-28T20:00"), tyat.Task(False, "Soon @p id:d due:2026-10-29T12:00")]
        old, tyat.prompts_since = tyat.prompts_since, lambda start: [5 if h == 3 else 1 for h in range(24)]
        self.addCleanup(setattr, tyat, "prompts_since", old)
        r = tyat.report(tasks, tyat.rhythm())
        self.assertEqual([[t.id for t in r[k]] for k in ("done", "late", "soon")], [["a"], ["c"], ["d"]])
        self.assertEqual((r["prompts"], r["after_stop"]), (28, 7))  # hours 2, 3, 4 are after a 01:30 stop
        self.assertEqual(tyat.report_text(r, tyat.rhythm()),
                         "Tagesbericht. Erledigt: 1, nämlich Shipped. Überfällig: 1, zuerst Late one. Erledigen oder mit t snooze "
                         "verschieben. In den nächsten 24 Stunden fällig: 1. 7 von 28 Prompts lagen nach 1 Uhr 30.")

    def test_phone_page_has_report_and_feedback(self):
        r = {"done": [tyat.Task(True, "<i>x</i> @p id:a")], "late": [], "prompts": 3, "after_stop": 0}
        page = tyat.phone_html([], [], tyat.rhythm(), r)
        self.assertIn("1 erledigt", page)
        self.assertIn("&lt;i&gt;x", page)
        self.assertIn('id="mic"', page)
        self.assertIn('fetch("api/inbox"', page)


class Inbox(Base):
    def test_notes_are_transcribed_saved_and_deleted_remotely(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        calls, store = [], {"1761700000000-aa": (b"voice", "audio/mp4"), "1761700060000-bb": ("Sayproof ist raus".encode(), "text/plain")}
        def api(method, path, data=None, ctype=None):
            calls.append((method, path))
            if path == "/api/inbox": return json.dumps([{"id": k, "type": v[1]} for k, v in store.items()]).encode()
            return store[path.rsplit("/", 1)[1]][0] if method == "GET" else b"{}"
        saved = (tyat.plan_api, tyat.transcribe, tyat.eleven_key, tyat.INBOX)
        def restore(): tyat.plan_api, tyat.transcribe, tyat.eleven_key, tyat.INBOX = saved
        self.addCleanup(restore)
        tyat.plan_api, tyat.eleven_key, tyat.INBOX = api, lambda: "k", Path(tmp.name) / "inbox.md"
        tyat.transcribe = lambda audio, ctype, key: f"transcribed {audio.decode()} as {ctype}"
        with contextlib.redirect_stdout(io.StringIO()): tyat.inbox_cmd([])
        text = tyat.INBOX.read_text()
        self.assertIn("transcribed voice as audio/mp4", text)
        self.assertIn("Sayproof ist raus", text)
        self.assertEqual(sorted(p for m, p in calls if m == "DELETE"), ["/api/inbox/1761700000000-aa", "/api/inbox/1761700060000-bb"])

    def test_voice_memo_stays_remote_without_a_key(self):
        calls = []
        def api(method, path, data=None, ctype=None):
            calls.append(method)
            return json.dumps([{"id": "1761700000000-aa", "type": "audio/mp4"}]).encode() if path == "/api/inbox" else b"voice"
        saved = (tyat.plan_api, tyat.eleven_key)
        self.addCleanup(lambda: (setattr(tyat, "plan_api", saved[0]), setattr(tyat, "eleven_key", saved[1])))
        tyat.plan_api, tyat.eleven_key = api, lambda: ""
        with contextlib.redirect_stdout(io.StringIO()): tyat.inbox_cmd([])
        self.assertNotIn("DELETE", calls)

    def test_already_fetched_note_in_a_lagging_listing_is_skipped(self):
        saved = tyat.plan_api; self.addCleanup(setattr, tyat, "plan_api", saved)
        tyat.plan_api = lambda method, path, data=None, ctype=None: (
            json.dumps([{"id": "1761700000000-aa", "type": "text/plain"}]).encode() if path == "/api/inbox" else None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out): tyat.inbox_cmd([])
        self.assertIn("inbox empty", out.getvalue())


class Check(Base):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "proj").mkdir()
        (self.tmp / "proj" / "notes.md").write_text("sent the mail")
        self._saved = {k: getattr(tyat, k) for k in ("ROOT", "PROJECTS", "CHECK_CACHE", "CHECK_LOG", "INBOX")}
        tyat.ROOT, tyat.PROJECTS = self.tmp, self.tmp / "projects"
        tyat.CHECK_CACHE, tyat.CHECK_LOG, tyat.INBOX = self.tmp / "c.json", self.tmp / "c.log", self.tmp / "inbox.md"

    def tearDown(self):
        for k, v in self._saved.items(): setattr(tyat, k, v)
        super().tearDown()

    def test_parse_verdicts_tolerates_fences_and_clamps(self):
        text = '```json\n{"tasks": [{"id": "a", "verdict": "done", "confidence": 3, "why": "x"},' \
               ' {"id": "b", "verdict": "maybe"}, {"id": "c", "verdict": "none", "confidence": "?"}]}\n```'
        v = tyat.parse_verdicts(text)
        self.assertEqual(sorted(v), ["a", "c"])
        self.assertEqual((v["a"]["confidence"], v["c"]["confidence"]), (1.0, 0.0))
        self.assertEqual(tyat.parse_verdicts("no json here"), {})

    def test_only_tasks_with_evidence_are_asked_and_cache_reuses(self):
        tasks = [tyat.Task(False, "Send mail @proj id:a"), tyat.Task(False, "Quiet one @nowhere id:b")]
        calls = []
        def ask(prompt):
            calls.append(prompt)
            return '{"tasks": [{"id": "a", "verdict": "done", "confidence": 0.9, "why": "notes.md says sent"}]}'
        v, asked = tyat.check(tasks, ask=ask)
        self.assertEqual((asked, list(v)), (1, ["a"]))
        self.assertIn("notes.md", calls[0]); self.assertNotIn("Quiet one", calls[0])
        v2, asked2 = tyat.check(tasks, ask=ask)
        self.assertEqual((asked2, v2), (0, v))  # same evidence: no second model call

    def test_apply_marks_confident_done_and_moves_late(self):
        head, _ = tyat.load()
        tyat.save(head, [tyat.Task(False, "Send mail @proj id:a"), tyat.Task(False, "Unsure @proj id:b"),
                         tyat.Task(False, "Late one @nowhere due:2026-10-27T10:00 est:30m id:c")])
        answer = '{"tasks": [{"id": "a", "verdict": "done", "confidence": 0.95, "why": "sent"},' \
                 ' {"id": "b", "verdict": "done", "confidence": 0.5, "why": "maybe"}]}'
        orig, tyat.slm = tyat.slm, lambda p: answer
        try:
            with contextlib.redirect_stdout(io.StringIO()): tyat.check_cmd(["--apply"])
        finally: tyat.slm = orig
        by = {t.id: t for t in tyat.load()[1]}
        self.assertTrue(by["a"].done); self.assertIn("auto-check: sent", by["a"].notes)
        self.assertFalse(by["b"].done)  # below TYAT_CHECK_MIN
        self.assertGreater(by["c"].due, NOW)  # late task got a slot ahead
        self.assertIn("move [c]", tyat.CHECK_LOG.read_text())


class Ticks(Base):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        saved = (tyat.plan_api, tyat.STATE)
        self.addCleanup(lambda: (setattr(tyat, "plan_api", saved[0]), setattr(tyat, "STATE", saved[1])))
        tyat.STATE = Path(tmp.name) / "state.json"
        tyat.TASKS.write_text("- [ ] Send mail @p id:a\n- [ ] Other @p id:b\n")
        self.ticks, self.puts = [], []
        def api(method, path, data=None, ctype=None):
            if method == "GET": return json.dumps(self.ticks).encode()
            self.puts.append((path, json.loads(data)))
        tyat.plan_api = api

    def sync(self):
        with contextlib.redirect_stdout(io.StringIO()): return tyat.ticks_sync()

    def test_tick_marks_done_once_and_flags_applied(self):
        self.ticks = [{"k": "aSend mail", "on": True, "tid": "a"}, {"k": "📰Post", "on": True, "tid": ""}]
        self.assertEqual(len(self.sync()), 1)
        by = {t.id: t for t in tyat.load()[1]}
        self.assertTrue(by["a"].done); self.assertFalse(by["b"].done)
        self.assertEqual(self.puts[0][1], {"on": True, "tid": "a", "t": "", "applied": True})
        self.assertEqual(self.sync(), [])  # already done: nothing to do again

    def test_untick_reopens_only_what_the_phone_closed(self):
        self.ticks = [{"k": "aSend mail", "on": True, "tid": "a"}]; self.sync()
        self.ticks = [{"k": "aSend mail", "on": False, "tid": "a"}]; self.sync()
        self.assertFalse({t.id: t for t in tyat.load()[1]}["a"].done)
        tyat.TASKS.write_text("- [x] Old @p id:c done:2026-10-27T10:00\n")
        self.ticks = [{"k": "cOld", "on": False, "tid": "c"}]
        self.assertEqual(self.sync(), [])  # done by hand stays done

    def test_page_saves_ticks_with_the_task_id(self):
        it = {"kind": "task", "id": "a", "title": "Send", "where": "p", "next": "", "due": None, "mins": 10, "cmd": "t go a"}
        page = tyat.phone_html([("do-x", "do", NOW, NOW + dt.timedelta(hours=1), [it])], [], tyat.rhythm())
        self.assertIn('data-tid="a"', page)
        self.assertIn('"api/ticks/"', page)


class NeedsMe(Base):
    def test_guess_and_override(self):
        self.assertTrue(tyat.needs_me(tyat.Task(False, "Sponsor-Outreach senden @p id:a")))
        self.assertTrue(tyat.needs_me(tyat.Task(False, "Versicherung anrufen @p id:a")))
        self.assertFalse(tyat.needs_me(tyat.Task(False, "Refactor the parser @p id:a")))
        self.assertTrue(tyat.needs_me(tyat.Task(False, "Nebius exams @p me:1 id:a")))
        self.assertFalse(tyat.needs_me(tyat.Task(False, "send weekly digest automatically @p me:0 id:a")))

    def test_me_token_roundtrips_and_is_not_title(self):
        t = tyat.Task(False, "Call Bob @p me:1 id:a")
        self.assertEqual(t.text, "Call Bob"); self.assertIn("me:1", t.line())

    def test_phone_page_marks_and_filters_my_items(self):
        it = {"kind": "task", "id": "a", "title": "Send", "where": "p", "next": "", "due": None, "mins": 10, "cmd": "t go a", "me": True}
        page = tyat.phone_html([("do-x", "do", NOW, NOW + dt.timedelta(hours=1), [it])], [], tyat.rhythm())
        self.assertIn('data-me="1"', page); self.assertIn('id="mef"', page)


class Rules(Base):
    def plan(self, text):
        tyat.TASKS.write_text(text)
        return tyat.replan(tyat.load()[1], tyat.rhythm())

    def test_send_is_never_moved_into_the_night(self):
        moves, _ = self.plan("- [ ] Sponsor-Outreach senden @p due:2026-10-27T22:00 est:1h id:a\n")
        self.assertIn("a", moves)
        self.assertTrue(12 <= moves["a"].hour < 14, moves["a"])

    def test_long_drafting_still_goes_to_the_night(self):
        moves, _ = self.plan("- [ ] Write the article draft @p due:2026-10-27T22:00 est:1h id:a\n")
        self.assertNotIn(moves["a"].hour, (12, 13))

    def test_missed_appointment_is_asked_not_moved(self):
        text = "- [ ] Meeting with Luis @p due:2026-10-28T09:00 id:a\n- [ ] Pick up file @p due:2026-10-27T10:00 fix:1 id:b\n"
        moves, stuck = self.plan(text)
        self.assertEqual(moves, {}); self.assertEqual(stuck, [])
        self.assertEqual(sorted(tyat.missed(tyat.load()[1])), ["a", "b"])

    def test_move_never_passes_the_deadline(self):
        moves, stuck = self.plan("- [ ] Write report @p due:2026-10-27T22:00 dl:2026-10-28T12:30 est:2h id:a\n")
        self.assertNotIn("a", moves); self.assertEqual(stuck, ["a"])

    def test_fix_and_dl_tokens_roundtrip(self):
        t = tyat.Task(False, "X @p due:2026-10-28T09:00 dl:2026-10-29T12:00 fix:1 id:a")
        self.assertEqual(t.text, "X"); self.assertIn("dl:2026-10-29T12:00", t.line()); self.assertIn("fix:1", t.line())


class VoiceFails(Base):
    def test_tts_error_leaves_blocks_silent_instead_of_crashing(self):
        tmp = Path(tempfile.mkdtemp()); saved = tyat.eleven_key; self.addCleanup(setattr, tyat, "eleven_key", saved)
        tyat.eleven_key = lambda: "k"
        def say(text, key): raise OSError("HTTP Error 401")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tyat.render_voices({"a": "x", "b": "y"}, tmp / "out", tmp / "cache", say=say), 0)
        self.assertEqual(list((tmp / "out").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
