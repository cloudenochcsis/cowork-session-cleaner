#!/usr/bin/env python3
"""
Claude Session Manager
----------------------
Lists Claude Cowork and Code sessions, shows their size, date, and archive
status. Lets you delete to trash, restore, archive, unarchive, or purge sessions
interactively.

Usage:
    python3 cowork_session_cleaner.py                    # default: manage all sessions
    python3 cowork_session_cleaner.py --kind code        # manage only Code sessions
    python3 cowork_session_cleaner.py --show trash       # inspect deleted sessions in trash
    python3 cowork_session_cleaner.py --dry-run          # preview without changes
    python3 cowork_session_cleaner.py --sort size        # sort by size (default: date)
    python3 cowork_session_cleaner.py --sort name        # sort alphabetically
    python3 cowork_session_cleaner.py --archived         # show only archived sessions
    python3 cowork_session_cleaner.py --active           # show only active sessions

Actions menu:
    [D] Delete    - move selected sessions into the managed trash
    [R] Restore   - restore selected trashed sessions
    [P] Purge     - permanently delete selected trashed sessions
    [A] Archive   - hide sessions from the Claude sidebar
    [U] Unarchive - restore archived sessions to the Claude sidebar
    (Restart the Claude app after deleting, restoring, archiving, unarchiving,
    or purging for sidebar changes to take effect)
"""

import argparse
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path


COWORK_SESSIONS_ROOT = Path.home() / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
CODE_SESSIONS_ROOT = Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
GIT_WORKTREES_PATH = Path.home() / "Library" / "Application Support" / "Claude" / "git-worktrees.json"
CLI_SESSIONS_ROOT = Path.home() / ".claude" / "sessions"
CLI_PROJECTS_ROOT = Path.home() / ".claude" / "projects"
TRASH_ROOT = Path.home() / ".claude-session-cleaner" / "trash"


RESTORABLE_KINDS = {"cowork", "code"}
MANIFEST_NAME = "manifest.json"


def session_id_from_uuid(session_uuid):
    """Return Claude's local session identifier for a UUID."""
    return f"local_{session_uuid}"


def session_metadata_candidate_names(session_uuid):
    """Return supported metadata filenames for a session UUID."""
    return (f"local_{session_uuid}.json", f"{session_uuid}.json")


def extract_session_uuid_from_metadata_path(path):
    """
    Return the session UUID from a supported metadata filename, or None.

    Supported shapes:
    - local_<uuid>.json
    - <uuid>.json
    """
    if Path(path).suffix != ".json":
        return None

    stem = Path(path).stem
    if stem.startswith("local_"):
        stem = stem.replace("local_", "", 1)

    try:
        return str(uuid.UUID(stem))
    except ValueError:
        return None


def read_json_file(path):
    """Read a JSON file and return the parsed value, or None on error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_json_file(path, data):
    """Write JSON data with stable formatting."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def get_file_size(path):
    """Get the size of a file in bytes."""
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def get_path_size(path):
    """Get the total size of a file or directory in bytes."""
    path = Path(path)
    if not path.exists():
        return 0
    if path.is_file():
        return get_file_size(path)
    return get_folder_size(path)


def get_folder_size(path):
    """Calculate total size of a directory in bytes."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for filename in filenames:
            file_path = Path(dirpath) / filename
            total += get_file_size(file_path)
    return total


def human_size(num_bytes):
    """Convert bytes to a human readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def normalize_timestamp(timestamp):
    """Normalize Claude timestamps to epoch seconds."""
    if not timestamp:
        return 0

    timestamp = float(timestamp)
    if timestamp > 10**12:
        timestamp /= 1000.0
    return timestamp


def format_timestamp(timestamp):
    """Render a timestamp for display."""
    normalized = normalize_timestamp(timestamp)
    if normalized <= 0:
        return "unknown"
    return datetime.fromtimestamp(normalized).strftime("%Y-%m-%d %H:%M")


def get_last_modified(path):
    """Get the most recent modification time across all files in a directory."""
    latest = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for filename in filenames:
            file_path = Path(dirpath) / filename
            try:
                mtime = file_path.stat().st_mtime
                if mtime > latest:
                    latest = mtime
            except OSError:
                pass
    return latest


def short_label(value):
    """Shorten long org/project identifiers for display."""
    return value if len(value) <= 8 else value[:8] + "..."


def get_session_label(session):
    """Return the best display label for a session or trash item."""
    return session.get("title") or session.get("session_uuid") or session.get("session_id") or session.get("trash_id")


def remove_empty_parents(path, stop_at):
    """Remove empty parent directories up to, but not including, stop_at."""
    current = Path(path)
    stop_at = Path(stop_at)

    while current != stop_at and stop_at in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def is_pid_running(pid):
    """Return True when a PID exists and is reachable."""
    if not isinstance(pid, int) or pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def make_session_record(
    kind,
    session_id,
    org,
    project,
    size,
    last_modified,
    *,
    path=None,
    json_path=None,
    title=None,
    is_archived=False,
    orphaned=False,
    cli_session_id=None,
    history_paths=None,
    worktree_path=None,
    worktree_name=None,
    stale_session_files=None,
    live_session_files=None,
    live_pids=None,
):
    """Create a normalized session record for display and actions."""
    session_uuid = session_id.replace("local_", "", 1) if session_id.startswith("local_") else session_id
    history_paths = [Path(path) for path in (history_paths or [])]
    stale_session_files = [Path(path) for path in (stale_session_files or [])]
    live_session_files = [Path(path) for path in (live_session_files or [])]
    live_pids = list(live_pids or [])
    worktree_path = Path(worktree_path) if worktree_path else None
    path = Path(path) if path else None
    json_path = Path(json_path) if json_path else None
    last_modified = normalize_timestamp(last_modified)

    return {
        "kind": kind,
        "path": path,
        "name": session_id,
        "session_id": session_id,
        "session_uuid": session_uuid,
        "org": short_label(org),
        "project": short_label(project),
        "size": size,
        "size_str": human_size(size),
        "last_modified": last_modified,
        "last_modified_str": format_timestamp(last_modified),
        "is_archived": is_archived,
        "json_path": json_path,
        "title": title,
        "orphaned": orphaned,
        "cli_session_id": cli_session_id,
        "history_paths": history_paths,
        "worktree_path": worktree_path,
        "worktree_name": worktree_name,
        "stale_session_files": stale_session_files,
        "live_session_files": live_session_files,
        "live_pids": live_pids,
    }


def make_trash_record(manifest_path, manifest):
    """Create a normalized trash record from a manifest."""
    deleted_at = normalize_timestamp(manifest.get("deleted_at"))
    size = manifest.get("total_size_bytes", 0)
    session_id = manifest.get("session_id") or manifest.get("trash_id")
    session_uuid = manifest.get("session_uuid") or session_id.replace("local_", "", 1)

    return {
        "kind": manifest.get("kind", "unknown"),
        "session_id": session_id,
        "session_uuid": session_uuid,
        "title": manifest.get("title"),
        "org": short_label(manifest.get("org", "?")),
        "project": short_label(manifest.get("project", "?")),
        "size": size,
        "size_str": human_size(size),
        "last_modified": deleted_at,
        "last_modified_str": format_timestamp(deleted_at),
        "trash_id": manifest.get("trash_id"),
        "trash_dir": manifest_path.parent,
        "manifest_path": manifest_path,
        "restorable": bool(manifest.get("restorable", False)),
        "restore_note": manifest.get("restore_note"),
        "manifest": manifest,
        "json_path": None,
        "is_archived": False,
        "orphaned": manifest.get("orphaned", False),
    }


def find_session_json(session_dir):
    """
    Find the session metadata JSON file.
    Claude stores metadata as local_<uuid>.json in the project directory (parent of
    session_dir). Some older or unexpected layouts may use <uuid>.json instead, so
    we check both names in both locations.
    """
    session_uuid = session_dir.name.replace("local_", "", 1)
    candidate_names = session_metadata_candidate_names(session_uuid)

    for base_dir in (session_dir.parent, session_dir):
        for candidate_name in candidate_names:
            candidate = base_dir / candidate_name
            if candidate.exists():
                return candidate

    for base_dir in (session_dir.parent, session_dir):
        for json_file in base_dir.iterdir():
            if extract_session_uuid_from_metadata_path(json_file) == session_uuid:
                return json_file

    return None


def read_session_metadata(json_path):
    """Read a session metadata file as an object."""
    data = read_json_file(json_path)
    return data if isinstance(data, dict) else None


def get_archive_status(session_dir):
    """
    Read the session JSON and return archive status.
    Returns: (is_archived: bool, json_path: Path or None, title: str or None)
    """
    json_path = find_session_json(session_dir)
    if json_path is None:
        return False, None, None

    data = read_session_metadata(json_path)
    if data is None:
        return False, json_path, None

    is_archived = data.get("isArchived", False)
    title = data.get("title") or data.get("name") or None
    return is_archived, json_path, title


def set_archive_status(json_path, archived):
    """Set the isArchived flag in a session JSON file."""
    if json_path is None:
        return False

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("JSON root is not an object")
        data["isArchived"] = archived
        write_json_file(json_path, data)
        return True
    except (json.JSONDecodeError, OSError, ValueError) as e:
        print(f"  Error updating {json_path.name}: {e}")
        return False


def load_git_worktrees():
    """Load Claude's code worktree registry."""
    data = read_json_file(GIT_WORKTREES_PATH)
    if not isinstance(data, dict):
        return {"worktrees": {}}

    worktrees = data.get("worktrees")
    if not isinstance(worktrees, dict):
        data["worktrees"] = {}
    return data


def remove_git_worktree_entry(session_id):
    """Remove a code session entry from git-worktrees.json and return the removed snapshot."""
    data = load_git_worktrees()
    worktrees = data.setdefault("worktrees", {})
    if session_id not in worktrees:
        return None

    snapshot = worktrees.pop(session_id)
    write_json_file(GIT_WORKTREES_PATH, data)
    return snapshot


def restore_git_worktree_entry(session_id, entry):
    """Restore a code session entry into git-worktrees.json."""
    if not isinstance(entry, dict):
        return False

    data = load_git_worktrees()
    worktrees = data.setdefault("worktrees", {})
    if session_id in worktrees:
        return False

    worktrees[session_id] = entry
    write_json_file(GIT_WORKTREES_PATH, data)
    return True


def build_transcript_index():
    """Index Code session transcripts by cliSessionId."""
    transcripts = {}
    if not CLI_PROJECTS_ROOT.exists():
        return transcripts

    for transcript_path in CLI_PROJECTS_ROOT.rglob("*.jsonl"):
        transcripts.setdefault(transcript_path.stem, []).append(transcript_path)
    return transcripts


def load_active_code_sessions():
    """Index live and stale Code session pointer files by cliSessionId."""
    active_sessions = {}
    if not CLI_SESSIONS_ROOT.exists():
        return active_sessions

    for session_file in CLI_SESSIONS_ROOT.glob("*.json"):
        data = read_json_file(session_file)
        if not isinstance(data, dict):
            continue

        cli_session_id = data.get("sessionId")
        if not isinstance(cli_session_id, str) or not cli_session_id:
            continue

        pid = data.get("pid")
        if isinstance(pid, str) and pid.isdigit():
            pid = int(pid)
        elif not isinstance(pid, int):
            pid = None

        entry = active_sessions.setdefault(
            cli_session_id,
            {"live_files": [], "stale_files": [], "live_pids": []},
        )

        if pid is not None and is_pid_running(pid):
            entry["live_files"].append(session_file)
            entry["live_pids"].append(pid)
        else:
            entry["stale_files"].append(session_file)

    return active_sessions


def discover_cowork_sessions():
    """Walk the Cowork sessions root and find session folders and orphaned metadata."""
    sessions = []
    if not COWORK_SESSIONS_ROOT.exists():
        return sessions

    for org_dir in COWORK_SESSIONS_ROOT.iterdir():
        if not org_dir.is_dir():
            continue

        for project_dir in org_dir.iterdir():
            if not project_dir.is_dir():
                continue

            seen_uuids = set()

            for session_dir in project_dir.iterdir():
                if not session_dir.is_dir() or not session_dir.name.startswith("local_"):
                    continue

                session_uuid = session_dir.name.replace("local_", "", 1)
                seen_uuids.add(session_uuid)
                size = get_folder_size(session_dir)
                last_mod = get_last_modified(session_dir)
                is_archived, json_path, title = get_archive_status(session_dir)

                sessions.append(
                    make_session_record(
                        "cowork",
                        session_id_from_uuid(session_uuid),
                        org_dir.name,
                        project_dir.name,
                        size,
                        last_mod,
                        path=session_dir,
                        json_path=json_path,
                        title=title,
                        is_archived=is_archived,
                    )
                )

            for json_file in project_dir.iterdir():
                if not json_file.is_file():
                    continue

                session_uuid = extract_session_uuid_from_metadata_path(json_file)
                if session_uuid is None or session_uuid in seen_uuids:
                    continue

                data = read_session_metadata(json_file)
                title = data.get("title") or data.get("name") or None if data else None
                is_archived = data.get("isArchived", False) if data else False
                last_mod = json_file.stat().st_mtime if json_file.exists() else 0
                size = get_file_size(json_file)

                sessions.append(
                    make_session_record(
                        "cowork",
                        session_id_from_uuid(session_uuid),
                        org_dir.name,
                        project_dir.name,
                        size,
                        last_mod,
                        json_path=json_file,
                        title=title,
                        is_archived=is_archived,
                        orphaned=True,
                    )
                )

    return sessions


def discover_code_sessions():
    """Walk the Code sessions root and find Code session metadata."""
    sessions = []
    if not CODE_SESSIONS_ROOT.exists():
        return sessions

    transcript_index = build_transcript_index()
    active_sessions = load_active_code_sessions()
    worktrees = load_git_worktrees().get("worktrees", {})

    for org_dir in CODE_SESSIONS_ROOT.iterdir():
        if not org_dir.is_dir():
            continue

        for project_dir in org_dir.iterdir():
            if not project_dir.is_dir():
                continue

            for json_file in project_dir.iterdir():
                if not json_file.is_file():
                    continue

                session_uuid = extract_session_uuid_from_metadata_path(json_file)
                if session_uuid is None:
                    continue

                data = read_session_metadata(json_file)
                session_id = session_id_from_uuid(session_uuid)
                title = data.get("title") or data.get("name") or None if data else None
                is_archived = data.get("isArchived", False) if data else False
                cli_session_id = data.get("cliSessionId") if data else None
                worktree_entry = worktrees.get(session_id, {})
                worktree_path = (
                    data.get("worktreePath") if data and data.get("worktreePath") else worktree_entry.get("path")
                )
                worktree_name = (
                    data.get("worktreeName") if data and data.get("worktreeName") else worktree_entry.get("name")
                )
                history_paths = transcript_index.get(cli_session_id, []) if cli_session_id else []
                active_info = active_sessions.get(
                    cli_session_id,
                    {"live_files": [], "stale_files": [], "live_pids": []},
                )
                last_mod = (
                    data.get("lastActivityAt")
                    if data and data.get("lastActivityAt")
                    else data.get("createdAt")
                    if data and data.get("createdAt")
                    else json_file.stat().st_mtime
                )
                size = get_file_size(json_file)
                size += sum(get_file_size(path) for path in history_paths)
                size += sum(get_file_size(path) for path in active_info["stale_files"])

                sessions.append(
                    make_session_record(
                        "code",
                        session_id,
                        org_dir.name,
                        project_dir.name,
                        size,
                        last_mod,
                        json_path=json_file,
                        title=title,
                        is_archived=is_archived,
                        cli_session_id=cli_session_id,
                        history_paths=history_paths,
                        worktree_path=worktree_path,
                        worktree_name=worktree_name,
                        stale_session_files=active_info["stale_files"],
                        live_session_files=active_info["live_files"],
                        live_pids=active_info["live_pids"],
                    )
                )

    return sessions


def discover_trash_items(kind="all"):
    """Discover trashed sessions from the managed trash root."""
    items = []
    if not TRASH_ROOT.exists():
        return items

    for kind_dir in TRASH_ROOT.iterdir():
        if not kind_dir.is_dir():
            continue
        if kind not in ("all", kind_dir.name):
            continue

        for trash_dir in kind_dir.iterdir():
            manifest_path = trash_dir / MANIFEST_NAME
            manifest = read_json_file(manifest_path)
            if not isinstance(manifest, dict):
                continue
            items.append(make_trash_record(manifest_path, manifest))

    return items


def discover_sessions(kind="all", show="active"):
    """Discover sessions for the requested kind and view."""
    if show == "trash":
        return discover_trash_items(kind)

    sessions = []
    if kind in ("all", "cowork"):
        sessions.extend(discover_cowork_sessions())
    if kind in ("all", "code"):
        sessions.extend(discover_code_sessions())
    return sessions


def get_status_label(session, show):
    """Return the display status for a session."""
    if show == "trash":
        return "TRASH" if session.get("restorable") else "PURGEONLY"
    if session.get("orphaned"):
        return "ORPHANED"
    if session["kind"] == "code" and session.get("live_pids"):
        return "LIVE"
    if session.get("is_archived"):
        return "ARCHIVED"
    return "active"


def display_sessions(sessions, show="active"):
    """Print a numbered table of sessions or trash items."""
    if not sessions:
        print("No sessions found.")
        return

    total_size = sum(session["size"] for session in sessions)
    cowork_count = sum(1 for session in sessions if session["kind"] == "cowork")
    code_count = sum(1 for session in sessions if session["kind"] == "code")

    print(f"\n{'=' * 112}")
    if show == "trash":
        print("  Claude Session Manager — Trash")
        restorable_count = sum(1 for session in sessions if session.get("restorable"))
        purge_only_count = len(sessions) - restorable_count
        summary_parts = [
            f"{len(sessions)} trashed item(s)",
            f"{cowork_count} cowork",
            f"{code_count} code",
            f"{restorable_count} restorable",
            f"{purge_only_count} purge-only",
        ]
    else:
        print("  Claude Session Manager")
        archived_count = sum(1 for session in sessions if session.get("is_archived"))
        orphaned_count = sum(1 for session in sessions if session.get("orphaned"))
        active_count = len(sessions) - archived_count
        live_code_count = sum(1 for session in sessions if session["kind"] == "code" and session.get("live_pids"))
        summary_parts = [
            f"{len(sessions)} session(s)",
            f"{cowork_count} cowork",
            f"{code_count} code",
            f"{active_count} active",
            f"{archived_count} archived",
        ]
        if orphaned_count > 0:
            summary_parts.append(f"{orphaned_count} orphaned")
        if live_code_count > 0:
            summary_parts.append(f"{live_code_count} live code")

    print(f"  {' | '.join(summary_parts)}  |  {human_size(total_size)} total")
    print(f"{'=' * 112}\n")

    if show != "trash":
        orphaned_count = sum(1 for session in sessions if session.get("orphaned"))
        if orphaned_count > 0:
            print("  ⚠  Cowork orphaned metadata found (metadata without session data).")
            print("     These can be moved to trash, but they are intentionally restore-disabled.\n")

    has_titles = any(session.get("title") for session in sessions)
    title_column = "Title / Session ID" if has_titles else "Session ID"
    print(f"  {'#':>3}  {'Kind':<8} {'Status':<10} {'Last Modified':<18} {'Size':>10}  {title_column}")
    print(f"  {'---':>3}  {'-' * 6:<8} {'-' * 8:<10} {'-' * 16:<18} {'-' * 10:>10}  {'-' * 44}")

    for index, session in enumerate(sessions, 1):
        display_name = get_session_label(session)
        if len(display_name) > 50:
            display_name = display_name[:47] + "..."
        kind_label = session["kind"].upper()
        if show == "trash" and not session.get("restorable"):
            kind_label += "*"
        print(
            f"  {index:>3}  {kind_label:<8} {get_status_label(session, show):<10} "
            f"{session['last_modified_str']:<18} {session['size_str']:>10}  {display_name}"
        )

    if show == "trash":
        print("\n  * PURGEONLY items cannot be restored; they can only be purged.")

    print()


def parse_selection(text, count):
    """
    Parse user input into a set of indices (0-based).
    Supports: 'all', individual numbers, ranges like '1-5', comma separated.
    """
    text = text.strip().lower()

    if text in ("all", "a", "*"):
        return set(range(count))

    indices = set()
    parts = text.replace(" ", ",").split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                start, end = int(start.strip()), int(end.strip())
                for number in range(start, end + 1):
                    if 1 <= number <= count:
                        indices.add(number - 1)
            except ValueError:
                print(f"  Could not parse range: '{part}', skipping.")
        else:
            try:
                number = int(part)
                if 1 <= number <= count:
                    indices.add(number - 1)
                else:
                    print(f"  Number out of range: {number}, skipping.")
            except ValueError:
                print(f"  Could not parse: '{part}', skipping.")

    return indices


def build_trash_artifacts(session):
    """Build the manifest payload and artifact list for a session."""
    artifacts = []
    restore_note = None
    restorable = True
    git_worktree_entry = None

    if session["kind"] == "cowork":
        if session["path"] and session["path"].exists():
            artifacts.append({"type": "cowork_dir", "path": session["path"], "required": True})
        if session["json_path"] and session["json_path"].exists():
            artifacts.append({"type": "metadata_json", "path": session["json_path"], "required": False})
        if session.get("orphaned"):
            restorable = False
            restore_note = "Cowork orphaned metadata is preserved for audit/purge only to avoid recreating ghost sessions."
    elif session["kind"] == "code":
        if session["json_path"] and session["json_path"].exists():
            artifacts.append({"type": "metadata_json", "path": session["json_path"], "required": True})
        for history_path in session["history_paths"]:
            if history_path.exists():
                artifacts.append({"type": "transcript_jsonl", "path": history_path, "required": False})
        for stale_file in session["stale_session_files"]:
            if stale_file.exists():
                artifacts.append({"type": "stale_session_ref", "path": stale_file, "required": False})
        git_worktree_entry = load_git_worktrees().get("worktrees", {}).get(session["session_id"])
    else:
        raise ValueError(f"Unsupported session kind: {session['kind']}")

    total_size = sum(get_path_size(artifact["path"]) for artifact in artifacts)
    manifest = {
        "trash_id": str(uuid.uuid4()),
        "kind": session["kind"],
        "session_id": session["session_id"],
        "session_uuid": session["session_uuid"],
        "title": session.get("title"),
        "org": session.get("org"),
        "project": session.get("project"),
        "cli_session_id": session.get("cli_session_id"),
        "deleted_at": datetime.now().timestamp(),
        "restorable": restorable,
        "restore_note": restore_note,
        "orphaned": session.get("orphaned", False),
        "git_worktree_entry": git_worktree_entry,
        "worktree_path": str(session["worktree_path"]) if session.get("worktree_path") else None,
        "worktree_name": session.get("worktree_name"),
        "total_size_bytes": total_size,
        "artifacts": [],
    }
    return manifest, artifacts


def move_path_to_trash(path, destination):
    """Move a file or directory into the managed trash."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"trash path already exists: {destination}")
    shutil.move(str(path), str(destination))


def trash_session(session):
    """Move a session's deletable artifacts into managed trash."""
    manifest, artifacts = build_trash_artifacts(session)
    trash_dir = TRASH_ROOT / session["kind"] / manifest["trash_id"]
    if trash_dir.exists():
        raise FileExistsError(f"trash item already exists: {trash_dir}")

    moved = []
    removed_git_worktree_entry = None
    try:
        for index, artifact in enumerate(artifacts, 1):
            source = artifact["path"]
            if not source.exists():
                if artifact.get("required"):
                    raise FileNotFoundError(f"required artifact missing: {source}")
                continue

            destination = trash_dir / f"artifact_{index}_{source.name}"
            move_path_to_trash(source, destination)
            manifest["artifacts"].append({
                "type": artifact["type"],
                "original_path": str(source),
                "trash_relpath": destination.relative_to(trash_dir).as_posix(),
            })
            moved.append((source, destination, artifact["type"]))

        if session["kind"] == "code" and manifest["git_worktree_entry"] is not None:
            removed = remove_git_worktree_entry(session["session_id"])
            if removed is None:
                manifest["restore_note"] = (
                    manifest.get("restore_note") or ""
                ) + (" Missing git-worktrees entry during trashing." if manifest.get("restore_note") else "Missing git-worktrees entry during trashing.")
            else:
                removed_git_worktree_entry = removed
                manifest["git_worktree_entry"] = removed

        write_json_file(trash_dir / MANIFEST_NAME, manifest)

        if session["kind"] == "cowork" and session.get("json_path"):
            remove_empty_parents(session["json_path"].parent, COWORK_SESSIONS_ROOT)
        if session["kind"] == "code" and session.get("json_path"):
            remove_empty_parents(session["json_path"].parent, CODE_SESSIONS_ROOT)
        if session["kind"] == "code":
            for history_path in session["history_paths"]:
                remove_empty_parents(history_path.parent, CLI_PROJECTS_ROOT)
            for stale_file in session["stale_session_files"]:
                remove_empty_parents(stale_file.parent, CLI_SESSIONS_ROOT)

        return make_trash_record(trash_dir / MANIFEST_NAME, manifest)
    except Exception:
        # Best-effort rollback of moved artifacts.
        for original, destination, artifact_type in reversed(moved):
            if destination.exists() and not original.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(original))
        if removed_git_worktree_entry is not None:
            restore_git_worktree_entry(session["session_id"], removed_git_worktree_entry)
        if trash_dir.exists():
            shutil.rmtree(trash_dir, ignore_errors=True)
        raise


def restore_trash_item(item):
    """Restore a trashed session back to its original locations."""
    manifest = item["manifest"]
    if not manifest.get("restorable"):
        note = manifest.get("restore_note") or "This trash item is purge-only."
        raise RuntimeError(note)

    if manifest.get("kind") == "code":
        active = load_active_code_sessions().get(manifest.get("cli_session_id"), {})
        live_pids = active.get("live_pids", [])
        if live_pids:
            pid_text = ", ".join(str(pid) for pid in live_pids)
            raise RuntimeError(f"session is still active (PID {pid_text})")

    collisions = []
    for artifact in manifest.get("artifacts", []):
        if artifact.get("type") == "stale_session_ref":
            continue
        original_path = Path(artifact["original_path"])
        if original_path.exists():
            collisions.append(original_path)
    if collisions:
        collision_text = ", ".join(str(path) for path in collisions)
        raise RuntimeError(f"restore path already exists: {collision_text}")

    moved_back = []
    restored_git_worktree = False
    try:
        for artifact in manifest.get("artifacts", []):
            if artifact.get("type") == "stale_session_ref":
                continue
            original_path = Path(artifact["original_path"])
            trash_path = item["trash_dir"] / artifact["trash_relpath"]
            if not trash_path.exists():
                raise FileNotFoundError(f"missing trashed artifact: {trash_path}")
            original_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trash_path), str(original_path))
            moved_back.append((trash_path, original_path))

        if manifest.get("kind") == "code" and manifest.get("git_worktree_entry"):
            restored = restore_git_worktree_entry(manifest["session_id"], manifest["git_worktree_entry"])
            if not restored:
                raise RuntimeError(f"git-worktrees entry already exists for {manifest['session_id']}")
            restored_git_worktree = True

        shutil.rmtree(item["trash_dir"])
    except Exception:
        if restored_git_worktree:
            remove_git_worktree_entry(manifest["session_id"])
        for trash_path, original_path in reversed(moved_back):
            if original_path.exists() and not trash_path.exists():
                trash_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(original_path), str(trash_path))
        raise


def purge_trash_item(item):
    """Permanently delete a trash item."""
    shutil.rmtree(item["trash_dir"], ignore_errors=True)


def action_delete(sessions, selected, dry_run):
    """Move selected sessions into the managed trash."""
    blocked = [session for session in selected if session["kind"] == "code" and session.get("live_pids")]
    if blocked:
        print("\n  Warning: active Code sessions cannot be deleted while Claude Desktop is still using them.")
        for session in blocked:
            pid_text = ", ".join(str(pid) for pid in session["live_pids"])
            print(f"    - {get_session_label(session)} [CODE]  (PID {pid_text})")
        selected = [session for session in selected if session not in blocked]
        if not selected:
            print("\n  No deletable sessions remain.")
            return

    total_reclaim = sum(session["size"] for session in selected)
    print(f"\n  Sessions to DELETE TO TRASH ({human_size(total_reclaim)}):\n")
    for session in selected:
        suffixes = []
        if session.get("orphaned"):
            suffixes.append("restore-disabled")
        if session["kind"] == "code" and session["history_paths"]:
            suffixes.append(f"{len(session['history_paths'])} transcript(s)")
        suffix = f"  [{' | '.join(suffixes)}]" if suffixes else ""
        print(
            f"    - {get_session_label(session)} [{session['kind'].upper()}]  "
            f"({session['size_str']}, {session['last_modified_str']}){suffix}"
        )

    if dry_run:
        print(f"\n  [DRY RUN] Would move {len(selected)} session(s) into managed trash.")
        return

    print()
    try:
        confirm = input("  Confirm DELETE TO TRASH? (yes/no): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return

    if confirm not in ("yes", "y"):
        print("  Cancelled.")
        return

    deleted = 0
    for session in selected:
        try:
            trash_session(session)
            deleted += 1
            print(f"  Trashed: {get_session_label(session)} [{session['kind'].upper()}]")
        except Exception as e:
            print(f"  Error trashing {session['session_id']}: {e}")

    print(f"\n  Done. Trashed {deleted} session(s).")
    print("  Use restore from the trash view if you want to recover them later.")
    print("  Restart Claude for sidebar changes to take effect.")


def action_restore(items, selected, dry_run):
    """Restore selected trash items."""
    not_restorable = [item for item in selected if not item.get("restorable")]
    if not_restorable:
        print("\n  Warning: some trash items are purge-only and cannot be restored.")
        for item in not_restorable:
            print(f"    - {get_session_label(item)} [{item['kind'].upper()}]  ({item.get('restore_note') or 'purge only'})")
        selected = [item for item in selected if item.get("restorable")]
        if not selected:
            print("\n  No restorable items remain.")
            return

    print(f"\n  Sessions to RESTORE ({len(selected)}):\n")
    for item in selected:
        print(f"    - {get_session_label(item)} [{item['kind'].upper()}]  ({item['last_modified_str']})")

    if dry_run:
        print(f"\n  [DRY RUN] Would restore {len(selected)} trashed session(s).")
        return

    print()
    try:
        confirm = input("  Confirm RESTORE? (yes/no): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return

    if confirm not in ("yes", "y"):
        print("  Cancelled.")
        return

    restored = 0
    for item in selected:
        try:
            restore_trash_item(item)
            restored += 1
            print(f"  Restored: {get_session_label(item)} [{item['kind'].upper()}]")
        except Exception as e:
            print(f"  Error restoring {item['trash_id']}: {e}")

    print(f"\n  Done. Restored {restored} session(s).")
    print("  Restart Claude for sidebar changes to take effect.")


def action_purge(items, selected, dry_run):
    """Permanently purge selected trash items."""
    total_reclaim = sum(item["size"] for item in selected)
    print(f"\n  Trash items to PURGE ({human_size(total_reclaim)}):\n")
    for item in selected:
        note = f"  [{item['restore_note']}]" if item.get("restore_note") else ""
        print(f"    - {get_session_label(item)} [{item['kind'].upper()}]  ({item['size_str']}, {item['last_modified_str']}){note}")

    if dry_run:
        print(f"\n  [DRY RUN] Would permanently purge {len(selected)} trash item(s).")
        return

    print()
    try:
        confirm = input("  Confirm PURGE? This is permanent. (yes/no): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return

    if confirm not in ("yes", "y"):
        print("  Cancelled.")
        return

    purged = 0
    for item in selected:
        try:
            purge_trash_item(item)
            purged += 1
            print(f"  Purged: {get_session_label(item)} [{item['kind'].upper()}]")
        except Exception as e:
            print(f"  Error purging {item['trash_id']}: {e}")

    print(f"\n  Done. Purged {purged} trash item(s).")


def action_archive(sessions, selected, dry_run):
    """Archive selected sessions (hide from the Claude sidebar)."""
    to_archive = [session for session in selected if not session["is_archived"]]
    already = len(selected) - len(to_archive)

    if already > 0:
        print(f"\n  ({already} session(s) already archived, skipping those.)")

    if not to_archive:
        print("  No active sessions to archive.")
        return

    print(f"\n  Sessions to ARCHIVE ({len(to_archive)}):\n")
    for session in to_archive:
        print(f"    - {get_session_label(session)} [{session['kind'].upper()}]  ({session['last_modified_str']})")

    if dry_run:
        print(f"\n  [DRY RUN] Would archive {len(to_archive)} session(s).")
        return

    no_json = [session for session in to_archive if session.get("json_path") is None]
    if no_json:
        print(f"\n  Warning: {len(no_json)} session(s) have no JSON metadata file. These cannot be archived.")
        to_archive = [session for session in to_archive if session.get("json_path") is not None]
        if not to_archive:
            return

    print()
    try:
        confirm = input("  Confirm ARCHIVE? (yes/no): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return

    if confirm not in ("yes", "y"):
        print("  Cancelled.")
        return

    count = 0
    for session in to_archive:
        if set_archive_status(session["json_path"], True):
            count += 1
            print(f"  Archived: {get_session_label(session)} [{session['kind'].upper()}]")

    print(f"\n  Done. Archived {count} session(s). Restart Claude for changes to take effect.")


def action_unarchive(sessions, selected, dry_run):
    """Unarchive selected sessions (restore to the Claude sidebar)."""
    to_unarchive = [session for session in selected if session["is_archived"]]
    already = len(selected) - len(to_unarchive)

    if already > 0:
        print(f"\n  ({already} session(s) already active, skipping those.)")

    if not to_unarchive:
        print("  No archived sessions to unarchive.")
        return

    print(f"\n  Sessions to UNARCHIVE ({len(to_unarchive)}):\n")
    for session in to_unarchive:
        print(f"    - {get_session_label(session)} [{session['kind'].upper()}]  ({session['last_modified_str']})")

    if dry_run:
        print(f"\n  [DRY RUN] Would unarchive {len(to_unarchive)} session(s).")
        return

    no_json = [session for session in to_unarchive if session.get("json_path") is None]
    if no_json:
        print(f"\n  Warning: {len(no_json)} session(s) have no JSON metadata file. These cannot be unarchived.")
        to_unarchive = [session for session in to_unarchive if session.get("json_path") is not None]
        if not to_unarchive:
            return

    print()
    try:
        confirm = input("  Confirm UNARCHIVE? (yes/no): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return

    if confirm not in ("yes", "y"):
        print("  Cancelled.")
        return

    count = 0
    for session in to_unarchive:
        if set_archive_status(session["json_path"], False):
            count += 1
            print(f"  Unarchived: {get_session_label(session)} [{session['kind'].upper()}]")

    print(f"\n  Done. Unarchived {count} session(s). Restart Claude for changes to take effect.")


def main():
    parser = argparse.ArgumentParser(
        description="Manage Claude Cowork and Code sessions: list, delete to trash, restore, archive, and purge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 cowork_session_cleaner.py                  # manage all active sessions
  python3 cowork_session_cleaner.py --kind code      # show only Code sessions
  python3 cowork_session_cleaner.py --kind cowork    # show only Cowork sessions
  python3 cowork_session_cleaner.py --show trash     # show the managed trash
  python3 cowork_session_cleaner.py --archived       # show only archived sessions
  python3 cowork_session_cleaner.py --active         # show only active sessions
  python3 cowork_session_cleaner.py --sort size      # sort biggest first
  python3 cowork_session_cleaner.py --dry-run        # preview, no changes
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying anything")
    parser.add_argument("--sort", choices=["date", "size", "name"], default="date", help="Sort order (default: date)")
    parser.add_argument("--kind", choices=["all", "cowork", "code"], default="all", help="Session kind to manage (default: all)")
    parser.add_argument("--show", choices=["active", "trash"], default="active", help="What to display (default: active)")
    filter_group = parser.add_mutually_exclusive_group()
    filter_group.add_argument("--archived", action="store_true", help="Show only archived sessions")
    filter_group.add_argument("--active", action="store_true", help="Show only active (non-archived) sessions")
    args = parser.parse_args()

    if args.show == "trash" and (args.archived or args.active):
        parser.error("--archived and --active are only valid when showing active sessions")

    print("\nScanning sessions...")
    sessions = discover_sessions(args.kind, args.show)

    if args.show == "active":
        if args.archived:
            sessions = [session for session in sessions if session.get("is_archived")]
        elif args.active:
            sessions = [session for session in sessions if not session.get("is_archived")]

    if args.sort == "size":
        sessions.sort(key=lambda session: session["size"], reverse=True)
    elif args.sort == "name":
        sessions.sort(key=lambda session: (session.get("title") or session.get("session_id") or session.get("trash_id")).lower())
    else:
        sessions.sort(key=lambda session: session["last_modified"], reverse=True)

    display_sessions(sessions, args.show)

    if not sessions:
        return

    print("  What would you like to do?")
    if args.show == "trash":
        print("    [R] Restore sessions from trash")
        print("    [P] Purge sessions permanently")
    else:
        print("    [D] Delete sessions to trash")
        print("    [A] Archive sessions (hide from the Claude sidebar)")
        print("    [U] Unarchive sessions (restore to the Claude sidebar)")
    print("    [Q] Quit\n")

    try:
        action = input("  Action: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Bye.")
        return

    if action in ("q", "quit", "exit", ""):
        print("  Bye.")
        return

    allowed_actions = ("r", "restore", "p", "purge") if args.show == "trash" else ("d", "delete", "a", "archive", "u", "unarchive")
    if action not in allowed_actions:
        print(f"  Unknown action: '{action}'")
        return

    print("\n  Enter session numbers.")
    print("  Examples: 1,3,5  or  1-5  or  all")
    print("  Press Enter to cancel.\n")

    try:
        selection = input("  Select: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return

    if not selection:
        print("  Cancelled.")
        return

    indices = parse_selection(selection, len(sessions))
    if not indices:
        print("  No valid sessions selected.")
        return

    selected = [sessions[index] for index in sorted(indices)]

    if args.show == "trash":
        if action in ("r", "restore"):
            action_restore(sessions, selected, args.dry_run)
        elif action in ("p", "purge"):
            action_purge(sessions, selected, args.dry_run)
        return

    if action in ("d", "delete"):
        action_delete(sessions, selected, args.dry_run)
    elif action in ("a", "archive"):
        action_archive(sessions, selected, args.dry_run)
    elif action in ("u", "unarchive"):
        action_unarchive(sessions, selected, args.dry_run)


if __name__ == "__main__":
    main()
