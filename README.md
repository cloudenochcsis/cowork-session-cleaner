# Claude Session Manager

A Python script to list, archive, unarchive, delete to trash, restore, and purge your Claude Desktop Cowork and Code sessions from the command line.

## The Problem

Claude Desktop lets you delete standard chats from the UI, but Cowork and Code sessions are stored locally and can pile up with no equivalent cleanup workflow. Over time, these sessions consume disk space, clutter the sidebar, and are hard to manage in bulk.

Worse, if session data is manually deleted, metadata files can get left behind — causing ghost entries to linger in the Claude sidebar with no usable content.

This script gives you visibility into local Claude session storage and lets you manage Cowork and Code sessions directly, with a managed trash so future deletions can be undone.

## What It Does

- Lists both Cowork and Code sessions with their title, last modified date, size, kind, and archive status
- **Detects orphaned Cowork sessions** — metadata files left behind after session data was deleted, which cause ghost entries in the Claude sidebar
- **Delete to trash** instead of permanently deleting by default
- **Restore** trashed sessions when their original artifacts can be safely put back
- **Purge** trashed sessions permanently when you no longer need them
- **Archive** sessions to hide them from the Claude sidebar
- **Unarchive** sessions to restore previously archived sessions
- Refuses to delete or restore **live Code sessions** that Claude Desktop is still using
- Dry-run mode to preview changes before committing
- Sort by date, size, or name
- Filter by archived/active status, by session kind, or switch to the trash view

## Requirements

- macOS
- Python 3.8+
- No external dependencies (standard library only)

## Usage

```bash
# List all active Cowork and Code sessions and choose an action
python3 cowork_session_cleaner.py

# Only manage Code sessions
python3 cowork_session_cleaner.py --kind code

# Only manage Cowork sessions
python3 cowork_session_cleaner.py --kind cowork

# Show the managed trash so you can restore or purge items
python3 cowork_session_cleaner.py --show trash

# Preview without making any changes
python3 cowork_session_cleaner.py --dry-run

# Sort by size to find the biggest sessions
python3 cowork_session_cleaner.py --sort size

# Show only archived sessions
python3 cowork_session_cleaner.py --archived

# Show only active (non-archived) sessions
python3 cowork_session_cleaner.py --active
```

## Example Output

### Active sessions

```text
================================================================================================================
  Claude Session Manager
  4 session(s) | 1 cowork | 3 code | 4 active | 0 archived | 1 live code  |  2.4 MB total
================================================================================================================

    #  Kind     Status     Last Modified            Size  Title / Session ID
  ---  ------   --------   ----------------   ----------  --------------------------------------------
    1  CODE     LIVE       2026-03-31 18:09     131.1 KB  Investigate dependency security alert
    2  CODE     active     2026-03-26 10:05       1.6 MB  Sync staging branch with remote
    3  CODE     active     2026-03-19 08:32     293.1 KB  Align feature branch with main...
    4  COWORK   active     2026-03-31 21:31     417.6 KB  Review quarterly content updates
```

### Trash view

```text
================================================================================================================
  Claude Session Manager — Trash
  2 trashed item(s) | 1 cowork | 1 code | 1 restorable | 1 purge-only  |  1.8 MB total
================================================================================================================

    #  Kind*    Status     Last Modified            Size  Title / Session ID
  ---  ------   --------   ----------------   ----------  --------------------------------------------
    1  CODE     TRASH      2026-03-31 22:30       1.6 MB  Sync staging branch with remote
    2  COWORK*  PURGEONLY  2026-03-31 22:28     178.3 KB  Old ghost metadata
```

## How It Works

### Cowork sessions

Cowork sessions live at:

```text
~/Library/Application Support/Claude/local-agent-mode-sessions/<org-uuid>/<project-uuid>/local_<session-uuid>/
```

Each session has a corresponding `local_<session-uuid>.json` metadata file in the project directory. The cleaner prefers this documented filename and also falls back to legacy `<session-uuid>.json` metadata files if they are present.

- **Archiving/Unarchiving** sets `"isArchived": true` or `false` in the JSON file.
- **Delete to trash** moves the session directory and metadata into the managed trash.
- **Orphan detection** finds JSON metadata files that have no matching session directory.
- Orphaned Cowork metadata can be trashed and purged, but it is intentionally restore-disabled to avoid recreating ghost sidebar entries.

### Code sessions

Code sessions are stored across a few Claude Desktop locations:

- Sidebar metadata:
  `~/Library/Application Support/Claude/claude-code-sessions/<org>/<project>/local_<session-uuid>.json`
- Worktree registry:
  `~/Library/Application Support/Claude/git-worktrees.json`
- Transcript history:
  `~/.claude/projects/<normalized-worktree-path>/<cliSessionId>.jsonl`
- Live session references:
  `~/.claude/sessions/<pid>.json`

For Code sessions, the script:

- reads the sidebar metadata JSON to list titles, timestamps, and archive state
- indexes transcript files by `cliSessionId`
- detects live Code sessions via `~/.claude/sessions`
- snapshots and restores the matching `git-worktrees.json` entry when using trash/restore
- moves stale `~/.claude/sessions/*.json` references into trash, but does not restore them later

By default, deleting a Code session does **not** delete the linked git worktree directory. That keeps the cleanup focused on Claude session artifacts instead of repository contents.

## Managed Trash

Deleted sessions are moved into a tool-managed trash at:

```text
~/.claude-session-cleaner/trash/
```

Each trashed session gets its own directory with a manifest describing:

- session kind and identifiers
- original artifact paths
- total size
- whether the item is restorable or purge-only
- any saved `git-worktrees.json` entry for Code sessions

This means:

- **restore** works for sessions deleted after this feature was added
- sessions deleted by older versions of the tool remain permanently gone
- purge permanently removes the trash item and its manifest

## Safety Notes

- Live Code sessions are blocked from deletion while their PID is still active.
- Live Code sessions are also blocked from restore to avoid path and session-ID collisions.
- Archive/unarchive works by editing local metadata and does not touch your repository.
- Restart Claude Desktop after delete/archive/unarchive/restore/purge operations for sidebar changes to appear.
- The script intentionally does **not** delete Code worktree directories by default.

## Limitations

- macOS only for now
- Session titles depend on what Claude saved in the metadata JSON
- Code transcript discovery is based on `cliSessionId` matches under `~/.claude/projects`
- Restoring fails safely if the original destination path already exists
- Sessions permanently deleted before the managed trash feature was added cannot be restored

## Contributing

Suggestions and improvements are welcome. Some ideas:

- **Windows/Linux support** - adapt the session storage paths for other platforms
- **Search by title** - filter sessions by keyword instead of scrolling through the list
- **Optional worktree deletion** - add an explicit flag for removing Code worktrees too
- **Trash retention policy** - auto-purge items older than N days
- **Auto-detect Claude running** - warn or auto-restart the app after changes
- **TUI interface** - use curses or a library like `rich` for a nicer interactive experience

Open an issue or submit a PR if you have ideas or run into problems.

## License

MIT. Use it however you like.

## Credits

Archive/unarchive approach inspired by [this Reddit post](https://www.reddit.com/r/ClaudeAI/comments/1qqaung/where_are_archived_cowork_chats/) documenting the `isArchived` flag in Cowork session metadata.
