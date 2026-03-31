#!/usr/bin/env python3
"""
Cowork Session Manager
----------------------
Lists all Claude Cowork local sessions, shows their size, date, and archive
status. Lets you delete, archive, or unarchive sessions interactively.

Usage:
    python3 cowork_session_cleaner.py                    # default: manage all sessions
    python3 cowork_session_cleaner.py --dry-run          # preview without changes
    python3 cowork_session_cleaner.py --sort size         # sort by size (default: date)
    python3 cowork_session_cleaner.py --sort name         # sort alphabetically
    python3 cowork_session_cleaner.py --archived          # show only archived sessions
    python3 cowork_session_cleaner.py --active            # show only active sessions

Actions menu:
    [D] Delete   - permanently remove selected sessions
    [A] Archive  - hide sessions from Cowork UI
    [U] Unarchive - restore archived sessions to Cowork UI
    (Restart the Claude app after archiving/unarchiving for changes to take effect)
"""

import os
import sys
import json
import shutil
import argparse
import uuid
from pathlib import Path
from datetime import datetime


SESSIONS_ROOT = Path.home() / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"


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
    if path.suffix != ".json":
        return None

    stem = path.stem
    if stem.startswith("local_"):
        stem = stem.replace("local_", "", 1)

    try:
        return str(uuid.UUID(stem))
    except ValueError:
        return None


def get_folder_size(path):
    """Calculate total size of a directory in bytes."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def human_size(num_bytes):
    """Convert bytes to a human readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def get_last_modified(path):
    """Get the most recent modification time across all files in a directory."""
    latest = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                mtime = os.path.getmtime(fp)
                if mtime > latest:
                    latest = mtime
            except OSError:
                pass
    return latest


def find_session_json(session_dir):
    """
    Find the session metadata JSON file.
    Claude stores metadata as local_<uuid>.json in the project directory (parent of
    session_dir). Some older or unexpected layouts may use <uuid>.json instead, so
    we check both names in both locations.
    """
    session_uuid = session_dir.name.replace("local_", "")
    candidate_names = session_metadata_candidate_names(session_uuid)

    # Prefer the documented location first: project-level metadata next to
    # session directories. Fall back to the session directory for robustness.
    for base_dir in (session_dir.parent, session_dir):
        for candidate_name in candidate_names:
            candidate = base_dir / candidate_name
            if candidate.exists():
                return candidate

    # Broader search: any .json in either directory that matches this session's
    # supported metadata filename shapes.
    for base_dir in (session_dir.parent, session_dir):
        for json_file in base_dir.iterdir():
            if extract_session_uuid_from_metadata_path(json_file) == session_uuid:
                return json_file

    return None


def get_archive_status(session_dir):
    """
    Read the session JSON and return archive status.
    Returns: (is_archived: bool, json_path: Path or None, title: str or None)
    """
    json_path = find_session_json(session_dir)
    if json_path is None:
        return False, None, None

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        is_archived = data.get("isArchived", False)
        title = data.get("title") or data.get("name") or None
        return is_archived, json_path, title
    except (json.JSONDecodeError, OSError):
        return False, json_path, None


def set_archive_status(json_path, archived):
    """Set the isArchived flag in a session JSON file."""
    if json_path is None:
        return False

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        data["isArchived"] = archived
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Error updating {json_path.name}: {e}")
        return False


def discover_sessions():
    """Walk the sessions root and find all individual session folders and orphaned JSON files."""
    sessions = []

    if not SESSIONS_ROOT.exists():
        print(f"Sessions directory not found: {SESSIONS_ROOT}")
        sys.exit(1)

    for org_dir in SESSIONS_ROOT.iterdir():
        if not org_dir.is_dir():
            continue
        for project_dir in org_dir.iterdir():
            if not project_dir.is_dir():
                continue

            # Track which session UUIDs have directories
            seen_uuids = set()

            for session_dir in project_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                if not session_dir.name.startswith("local_"):
                    continue

                session_uuid = session_dir.name.replace("local_", "")
                seen_uuids.add(session_uuid)

                size = get_folder_size(session_dir)
                last_mod = get_last_modified(session_dir)
                last_mod_str = (
                    datetime.fromtimestamp(last_mod).strftime("%Y-%m-%d %H:%M")
                    if last_mod > 0
                    else "unknown"
                )
                is_archived, json_path, title = get_archive_status(session_dir)

                sessions.append({
                    "path": session_dir,
                    "name": session_dir.name,
                    "org": org_dir.name[:8] + "...",
                    "project": project_dir.name[:8] + "...",
                    "size": size,
                    "size_str": human_size(size),
                    "last_modified": last_mod,
                    "last_modified_str": last_mod_str,
                    "is_archived": is_archived,
                    "json_path": json_path,
                    "title": title,
                    "orphaned": False,
                })

            # Find orphaned JSON files: metadata with no matching session directory
            for json_file in project_dir.iterdir():
                if not json_file.is_file():
                    continue
                session_uuid = extract_session_uuid_from_metadata_path(json_file)
                if session_uuid is None:
                    continue
                if session_uuid in seen_uuids:
                    continue  # has a directory, already discovered

                # Orphaned JSON — session dir was deleted but metadata remains
                try:
                    with open(json_file, "r") as f:
                        data = json.load(f)
                    title = data.get("title") or data.get("name") or None
                    is_archived = data.get("isArchived", False)
                    last_mod = os.path.getmtime(json_file)
                except (json.JSONDecodeError, OSError):
                    title = None
                    is_archived = False
                    last_mod = 0

                last_mod_str = (
                    datetime.fromtimestamp(last_mod).strftime("%Y-%m-%d %H:%M")
                    if last_mod > 0
                    else "unknown"
                )
                size = json_file.stat().st_size if json_file.exists() else 0

                sessions.append({
                    "path": None,  # no directory exists
                    "name": f"local_{session_uuid}",
                    "org": org_dir.name[:8] + "...",
                    "project": project_dir.name[:8] + "...",
                    "size": size,
                    "size_str": human_size(size),
                    "last_modified": last_mod,
                    "last_modified_str": last_mod_str,
                    "is_archived": is_archived,
                    "json_path": json_file,
                    "title": title,
                    "orphaned": True,
                })

    return sessions


def display_sessions(sessions, show_title="auto"):
    """Print a numbered table of sessions."""
    if not sessions:
        print("No sessions found.")
        return

    total_size = sum(s["size"] for s in sessions)
    archived_count = sum(1 for s in sessions if s["is_archived"])
    orphaned_count = sum(1 for s in sessions if s.get("orphaned"))
    active_count = len(sessions) - archived_count

    print(f"\n{'='*90}")
    print(f"  Cowork Session Manager")
    summary_parts = [f"{len(sessions)} session(s)", f"{active_count} active", f"{archived_count} archived"]
    if orphaned_count > 0:
        summary_parts.append(f"{orphaned_count} orphaned")
    print(f"  {' | '.join(summary_parts)}  |  {human_size(total_size)} total")
    print(f"{'='*90}\n")

    if orphaned_count > 0:
        print(f"  ⚠  {orphaned_count} orphaned session(s) found (metadata without session data).")
        print(f"     These still appear in the Claude sidebar. Delete them to clean up.\n")

    # Decide whether to show title column
    has_titles = any(s["title"] for s in sessions)

    # Header
    status_col = "Status"
    if has_titles:
        print(f"  {'#':>3}  {status_col:<10} {'Last Modified':<18} {'Size':>10}  {'Title / Session ID'}")
        print(f"  {'---':>3}  {'-'*8:<10} {'-'*16:<18} {'-'*10:>10}  {'-'*40}")
    else:
        print(f"  {'#':>3}  {status_col:<10} {'Last Modified':<18} {'Size':>10}  {'Session ID'}")
        print(f"  {'---':>3}  {'-'*8:<10} {'-'*16:<18} {'-'*10:>10}  {'-'*40}")

    for i, s in enumerate(sessions, 1):
        session_id = s["name"].replace("local_", "")
        if s.get("orphaned"):
            status = "ORPHANED"
        elif s["is_archived"]:
            status = "ARCHIVED"
        else:
            status = "active"
        display_name = s["title"] if s.get("title") else session_id
        # Truncate long titles
        if len(display_name) > 50:
            display_name = display_name[:47] + "..."
        print(f"  {i:>3}  {status:<10} {s['last_modified_str']:<18} {s['size_str']:>10}  {display_name}")

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
                for n in range(start, end + 1):
                    if 1 <= n <= count:
                        indices.add(n - 1)
            except ValueError:
                print(f"  Could not parse range: '{part}', skipping.")
        else:
            try:
                n = int(part)
                if 1 <= n <= count:
                    indices.add(n - 1)
                else:
                    print(f"  Number out of range: {n}, skipping.")
            except ValueError:
                print(f"  Could not parse: '{part}', skipping.")

    return indices


def action_delete(sessions, selected, dry_run):
    """Delete selected sessions."""
    total_reclaim = sum(s["size"] for s in selected)
    orphaned_count = sum(1 for s in selected if s.get("orphaned"))

    print(f"\n  Sessions to DELETE ({human_size(total_reclaim)}):\n")
    for s in selected:
        session_id = s["name"].replace("local_", "")
        label = s["title"] or session_id
        suffix = "  [orphaned metadata only]" if s.get("orphaned") else ""
        print(f"    - {label}  ({s['size_str']}, {s['last_modified_str']}){suffix}")

    if dry_run:
        print(f"\n  [DRY RUN] Would delete {len(selected)} session(s), freeing {human_size(total_reclaim)}.")
        if orphaned_count:
            print(f"  [DRY RUN] {orphaned_count} orphaned metadata file(s) would be removed from sidebar.")
        return

    print()
    try:
        confirm = input("  Confirm DELETE? This is permanent. (yes/no): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.")
        return

    if confirm not in ("yes", "y"):
        print("  Cancelled.")
        return

    deleted = 0
    freed = 0
    for s in selected:
        try:
            # Delete the session directory if it exists
            if s["path"] and s["path"].exists():
                shutil.rmtree(s["path"])
            # Always remove the JSON metadata file (this is what the Claude
            # sidebar reads — leaving it behind causes ghost entries)
            if s["json_path"] and s["json_path"].exists():
                s["json_path"].unlink(missing_ok=True)
            deleted += 1
            freed += s["size"]
            label = s["title"] or s["name"].replace("local_", "")
            print(f"  Deleted: {label}")
        except Exception as e:
            print(f"  Error deleting {s['name']}: {e}")

    print(f"\n  Done. Deleted {deleted} session(s), freed {human_size(freed)}.")
    print(f"  Restart Claude for sidebar changes to take effect.")


def action_archive(sessions, selected, dry_run):
    """Archive selected sessions (hide from Cowork UI)."""
    # Filter to only active sessions
    to_archive = [s for s in selected if not s["is_archived"]]
    already = len(selected) - len(to_archive)

    if already > 0:
        print(f"\n  ({already} session(s) already archived, skipping those.)")

    if not to_archive:
        print("  No active sessions to archive.")
        return

    print(f"\n  Sessions to ARCHIVE ({len(to_archive)}):\n")
    for s in to_archive:
        session_id = s["name"].replace("local_", "")
        label = s["title"] or session_id
        print(f"    - {label}  ({s['last_modified_str']})")

    if dry_run:
        print(f"\n  [DRY RUN] Would archive {len(to_archive)} session(s).")
        return

    no_json = [s for s in to_archive if s["json_path"] is None]
    if no_json:
        print(f"\n  Warning: {len(no_json)} session(s) have no JSON metadata file. These cannot be archived.")
        to_archive = [s for s in to_archive if s["json_path"] is not None]
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
    for s in to_archive:
        if set_archive_status(s["json_path"], True):
            count += 1
            label = s["title"] or s["name"].replace("local_", "")
            print(f"  Archived: {label}")

    print(f"\n  Done. Archived {count} session(s). Restart Claude for changes to take effect.")


def action_unarchive(sessions, selected, dry_run):
    """Unarchive selected sessions (restore to Cowork UI)."""
    to_unarchive = [s for s in selected if s["is_archived"]]
    already = len(selected) - len(to_unarchive)

    if already > 0:
        print(f"\n  ({already} session(s) already active, skipping those.)")

    if not to_unarchive:
        print("  No archived sessions to unarchive.")
        return

    print(f"\n  Sessions to UNARCHIVE ({len(to_unarchive)}):\n")
    for s in to_unarchive:
        session_id = s["name"].replace("local_", "")
        label = s["title"] or session_id
        print(f"    - {label}  ({s['last_modified_str']})")

    if dry_run:
        print(f"\n  [DRY RUN] Would unarchive {len(to_unarchive)} session(s).")
        return

    no_json = [s for s in to_unarchive if s["json_path"] is None]
    if no_json:
        print(f"\n  Warning: {len(no_json)} session(s) have no JSON metadata file. These cannot be unarchived.")
        to_unarchive = [s for s in to_unarchive if s["json_path"] is not None]
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
    for s in to_unarchive:
        if set_archive_status(s["json_path"], False):
            count += 1
            label = s["title"] or s["name"].replace("local_", "")
            print(f"  Unarchived: {label}")

    print(f"\n  Done. Unarchived {count} session(s). Restart Claude for changes to take effect.")


def main():
    parser = argparse.ArgumentParser(
        description="Manage Claude Cowork sessions: list, delete, archive, and unarchive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 cowork_session_cleaner.py                  # manage all sessions
  python3 cowork_session_cleaner.py --archived       # show only archived
  python3 cowork_session_cleaner.py --active         # show only active
  python3 cowork_session_cleaner.py --sort size      # sort biggest first
  python3 cowork_session_cleaner.py --dry-run        # preview, no changes
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying anything")
    parser.add_argument("--sort", choices=["date", "size", "name"], default="date", help="Sort order (default: date)")
    filter_group = parser.add_mutually_exclusive_group()
    filter_group.add_argument("--archived", action="store_true", help="Show only archived sessions")
    filter_group.add_argument("--active", action="store_true", help="Show only active (non-archived) sessions")
    args = parser.parse_args()

    print("\nScanning sessions...")
    sessions = discover_sessions()

    # Filter by archive status
    if args.archived:
        sessions = [s for s in sessions if s["is_archived"]]
    elif args.active:
        sessions = [s for s in sessions if not s["is_archived"]]

    # Sort
    if args.sort == "size":
        sessions.sort(key=lambda s: s["size"], reverse=True)
    elif args.sort == "name":
        sessions.sort(key=lambda s: (s["title"] or s["name"]).lower())
    else:
        sessions.sort(key=lambda s: s["last_modified"], reverse=True)

    display_sessions(sessions)

    if not sessions:
        return

    # Action menu
    print("  What would you like to do?")
    print("    [D] Delete sessions")
    print("    [A] Archive sessions (hide from Cowork)")
    print("    [U] Unarchive sessions (restore to Cowork)")
    print("    [Q] Quit\n")

    try:
        action = input("  Action: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Bye.")
        return

    if action in ("q", "quit", "exit", ""):
        print("  Bye.")
        return

    if action not in ("d", "delete", "a", "archive", "u", "unarchive"):
        print(f"  Unknown action: '{action}'")
        return

    # Select sessions
    print(f"\n  Enter session numbers.")
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

    selected = [sessions[i] for i in sorted(indices)]

    # Dispatch action
    if action in ("d", "delete"):
        action_delete(sessions, selected, args.dry_run)
    elif action in ("a", "archive"):
        action_archive(sessions, selected, args.dry_run)
    elif action in ("u", "unarchive"):
        action_unarchive(sessions, selected, args.dry_run)


if __name__ == "__main__":
    main()
