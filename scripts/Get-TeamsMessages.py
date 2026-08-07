#!/usr/bin/env python3
r"""Read a single day's Microsoft Teams chat/channel messages and emit them as JSON.

Used by the `close-day` skill to sweep the Teams messages the user exchanged today, so it can
spot asks / commitments / follow-ups the same way the Outlook Sent Mail sweep does.

When no Teams connector or Graph integration is configured, this optional Windows adapter reads
the **new Teams (MSTeams UWP) client's local Chromium IndexedDB LevelDB cache** directly with a
vendored, pure-Python Chromium reader (`scripts/vendor/ccl_chromium_reader`, no pip / no
native deps). Messages live in the `:replychain-manager:` database, `replychains` object
store, inside each record's `messageMap`; chat titles come from `:conversation-manager:`.

This is best-effort, READ-ONLY, point-in-time extraction from an UNDOCUMENTED cache whose
schema can change with Teams updates. It NEVER writes to Teams. On any failure (missing
cache, schema drift, lock) it prints an `error`/`warning` in the JSON and exits non-zero so
the skill can fall back to asking the user to paste the relevant chats.

Example:
    python Get-TeamsMessages.py --out "$env:TEMP\teams-today.json"
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor"
sys.path.insert(0, str(VENDOR))

DEFAULT_SRC = str(
    Path.home()
    / "AppData"
    / "Local"
    / "Packages"
    / "MSTeams_8wekyb3d8bbwe"
    / "LocalCache"
    / "Microsoft"
    / "MSTeams"
    / "EBWebView"
    / "WV2Profile_tfw"
    / "IndexedDB"
    / "https_teams.microsoft.com_0.indexeddb.leveldb"
)

# Message.type values that are real chat content (everything else is a control / system event).
_CONTENT_TYPE = "Message"
# messageType values we treat as human text.
_TEXT_MSG_TYPES = ("richtext", "text")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(raw: object) -> str:
    """Strip HTML tags/entities from a Teams message body into plain text."""
    if not isinstance(raw, str) or not raw:
        return ""
    # Preserve some structure before dropping tags.
    text = re.sub(r"(?i)<br\s*/?>", " ", raw)
    text = re.sub(r"(?i)</(p|div|li)>", " ", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def ms_to_local_dt(ms: object) -> datetime.datetime | None:
    """Convert an epoch-milliseconds value (Teams uses float ms) to a local datetime."""
    try:
        return datetime.datetime.fromtimestamp(float(ms) / 1000.0)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def find_database(wdb, needle: str):
    """Return the first WrappedDatabase whose name contains `needle`, else None."""
    for dbid in wdb.database_ids:
        if needle in (dbid.name or ""):
            try:
                return wdb[dbid.dbid_no]
            except Exception:
                return None
    return None


def build_title_map(wdb) -> dict:
    """Map conversationId -> chat title (best-effort; empty for many 1:1 chats)."""
    titles: dict = {}
    db = find_database(wdb, ":conversation-manager:")
    if db is None:
        return titles
    try:
        store = db.get_object_store_by_name("conversations")
    except Exception:
        return titles
    for rec in store.iterate_records(bad_deserializer_data_handler=lambda k, d: None):
        v = rec.value
        if not isinstance(v, dict):
            continue
        cid = v.get("id")
        title = v.get("chatTitle")
        if cid and isinstance(title, str) and title.strip():
            titles[cid] = title.strip()
    return titles


def collect_messages(wdb, day_start_ms: float, day_end_ms: float, body_max: int) -> list:
    """Pull today's text messages out of the replychains store, de-duplicated by message key."""
    db = find_database(wdb, ":replychain-manager:")
    if db is None:
        raise LookupError("replychain-manager database not found in Teams cache")
    try:
        store = db.get_object_store_by_name("replychains")
    except Exception as exc:
        raise LookupError(f"replychains object store not found: {exc}")

    titles = build_title_map(wdb)

    # Keep the highest-version copy of each message (edits/history produce duplicates).
    best: dict = {}
    for rec in store.iterate_records(bad_deserializer_data_handler=lambda k, d: None):
        v = rec.value
        if not isinstance(v, dict):
            continue
        message_map = v.get("messageMap")
        if not isinstance(message_map, dict):
            continue
        for msg_key, msg in message_map.items():
            if not isinstance(msg, dict):
                continue
            if msg.get("type") != _CONTENT_TYPE:
                continue  # skip control / system / activity messages
            mtype = str(msg.get("messageType") or "").lower()
            if not mtype.startswith(_TEXT_MSG_TYPES):
                continue
            ts = msg.get("originalArrivalTime")
            if ts is None:
                ts = msg.get("clientArrivalTime")
            dt = ms_to_local_dt(ts)
            if dt is None:
                continue
            ts_ms = float(ts)
            if ts_ms < day_start_ms or ts_ms >= day_end_ms:
                continue
            body = html_to_text(msg.get("content"))
            if not body:
                continue
            try:
                version = float(msg.get("version") or 0)
            except (TypeError, ValueError):
                version = 0.0
            prior = best.get(msg_key)
            if prior is not None and prior[0] >= version:
                continue
            cid = msg.get("conversationId") or v.get("conversationId")
            if len(body) > body_max:
                body = body[:body_max] + " ...[truncated]"
            best[msg_key] = (
                version,
                {
                    "sentOn": dt.strftime("%Y-%m-%dT%H:%M"),
                    "from": msg.get("imDisplayName") or "",
                    "chat": titles.get(cid, ""),
                    "messageType": msg.get("messageType") or "",
                    "isSentByCurrentUser": bool(msg.get("isSentByCurrentUser")),
                    "containsQuestion": "?" in body,
                    "body": body,
                },
            )

    messages = [entry[1] for entry in best.values()]
    messages.sort(key=lambda m: m["sentOn"])
    return messages


def write_result(obj: dict, out_file: str | None) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    sys.stdout.write(text + "\n")
    if out_file:
        # UTF-8 without BOM, matching the other close-day readers.
        Path(out_file).write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a day's Teams messages from the local cache.")
    parser.add_argument("--date", help="Day to read (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--out", help="Also write the JSON here (UTF-8, no BOM).")
    parser.add_argument("--src", default=DEFAULT_SRC, help="Teams IndexedDB LevelDB directory.")
    parser.add_argument("--body-max", type=int, default=1500, help="Truncate each body to N chars.")
    args = parser.parse_args()

    if args.date:
        try:
            day = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            day = datetime.date.today()
    else:
        day = datetime.date.today()

    day_start = datetime.datetime.combine(day, datetime.time.min)
    day_end = day_start + datetime.timedelta(days=1)
    day_start_ms = day_start.timestamp() * 1000.0
    day_end_ms = day_end.timestamp() * 1000.0

    base = {"date": day.strftime("%Y-%m-%d"), "dayOfWeek": day.strftime("%A")}

    tmp_dir = None
    try:
        src = Path(args.src)
        if not src.is_dir():
            raise FileNotFoundError(f"Teams IndexedDB cache not found: {src}")

        # Teams holds a LOCK on the live store; copy to temp (minus LOCK) for a stable read.
        tmp_dir = tempfile.mkdtemp(prefix="teamsidb_")
        dst = os.path.join(tmp_dir, "ldb")
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("LOCK"))

        from ccl_chromium_reader import ccl_chromium_indexeddb as idb

        wdb = idb.WrappedIndexDB(dst)
        try:
            messages = collect_messages(wdb, day_start_ms, day_end_ms, args.body_max)
        finally:
            try:
                wdb.close()
            except Exception:
                pass

        warning = ""
        if not messages:
            warning = ("No Teams messages found for this day in the local cache "
                       "(the cache may be stale, or there were none). Ask the user to paste any relevant chats.")
        write_result({**base, "count": len(messages), "warning": warning, "messages": messages}, args.out)
        return 0

    except Exception as exc:
        write_result(
            {**base, "count": 0, "warning": "",
             "error": f"{type(exc).__name__}: {exc}",
             "messages": []},
            args.out,
        )
        return 1
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
