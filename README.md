# Cowork Session Manager

A Python script to list, delete, archive, and unarchive your Claude Cowork sessions from the command line.

## The Problem

Claude's Cowork mode stores sessions locally on your Mac, but there is currently no built-in UI to bulk-delete sessions or view/restore archived chats. Over time, sessions pile up, eat disk space, and there is no straightforward way to clean them up. Archived chats simply disappear from the sidebar with no option to bring them back through the app.

Worse, if session data is manually deleted, the JSON metadata files often get left behind — causing ghost entries to linger in the Claude sidebar with no content.

This script gives you visibility into all your Cowork sessions and lets you manage them directly.

## What It Does

- Lists all Cowork sessions with their title, last modified date, size, and archive status
- **Detects orphaned sessions** — metadata files left behind after session data was deleted, which cause ghost entries in the Claude sidebar
- **Delete** sessions to free up disk space (removes both session data and metadata)
- **Archive** sessions to hide them from the Cowork sidebar
- **Unarchive** sessions to restore previously archived chats
- Dry-run mode to preview changes before committing
- Sort by date, size, or name
- Filter to show only archived or only active sessions

## Requirements

- macOS (sessions are stored at `~/Library/Application Support/Claude/local-agent-mode-sessions/`)
- Python 3.8+
- No external dependencies (standard library only)

## Usage

```bash
# List all sessions and choose an action
python3 cowork_session_cleaner.py

# Preview without making any changes
python3 cowork_session_cleaner.py --dry-run

# Sort by size to find the biggest sessions
python3 cowork_session_cleaner.py --sort size

# Show only archived sessions (useful for finding chats to restore)
python3 cowork_session_cleaner.py --archived

# Show only active sessions
python3 cowork_session_cleaner.py --active
```

## Example Output

```
==========================================================================================
  Cowork Session Manager
  12 session(s) | 8 active | 2 archived | 2 orphaned  |  245.3 MB total
==========================================================================================

  ⚠  2 orphaned session(s) found (metadata without session data).
     These still appear in the Claude sidebar. Delete them to clean up.

    #  Status     Last Modified        Size  Title / Session ID
  ---  --------   ----------------   ----------  ----------------------------------------
    1  active     2026-03-19 14:22     52.3 MB  Website redesign project
    2  active     2026-03-18 09:10     38.1 MB  Help me write a cover letter
    3  ARCHIVED   2026-03-15 16:45     12.7 MB  Budget spreadsheet cleanup
    4  active     2026-03-12 11:30      8.4 MB  Debug my Python script
    5  ORPHANED   2026-03-01 08:55    178.3 KB  Old project notes
  ...

  What would you like to do?
    [D] Delete sessions
    [A] Archive sessions (hide from Cowork)
    [U] Unarchive sessions (restore to Cowork)
    [Q] Quit

  Action: d

  Enter session numbers.
  Examples: 1,3,5  or  1-5  or  all

  Select: 5

  Sessions to DELETE (178.3 KB):

    - Old project notes  (178.3 KB, 2026-03-01 08:55)  [orphaned metadata only]

  Confirm DELETE? This is permanent. (yes/no): yes
  Deleted: Old project notes

  Done. Deleted 1 session(s), freed 178.3 KB.
  Restart Claude for sidebar changes to take effect.
```

## How It Works

Cowork sessions live at:
```
~/Library/Application Support/Claude/local-agent-mode-sessions/<org-uuid>/<project-uuid>/local_<session-uuid>/
```

Each session has a corresponding `local_<session-uuid>.json` metadata file in the project directory. The Claude app reads these JSON files to populate the sidebar — they contain the session title, archive status, and other metadata.

- **Archiving/Unarchiving** sets `"isArchived": true` or `false` in the JSON file. Restart the Claude app for changes to appear.
- **Deleting** removes both the session folder and the JSON metadata file. This is important because deleting only the folder leaves the JSON behind, which causes the session to appear as a ghost entry in the sidebar (visible but empty).
- **Orphan detection** finds JSON metadata files that have no matching session directory. These are leftovers from previous deletions and can be cleaned up to remove ghost sidebar entries.

## Limitations

- macOS only for now (the session path is Mac-specific)
- You need to restart the Claude desktop app after archive/unarchive operations
- Session titles depend on what the Claude app saved in the JSON metadata. Some sessions may only show their UUID if no title was stored.

## Contributing

Suggestions and improvements are welcome. Some ideas:

- **Windows/Linux support** - adapt the session storage path for other platforms
- **Search by title** - filter sessions by keyword instead of scrolling through the list
- **Export session data** - dump conversation content before deleting
- **Auto-detect Claude running** - warn or auto-restart the app after changes
- **Age-based cleanup** - flag or auto-archive sessions older than N days
- **TUI interface** - use curses or a library like `rich` for a nicer interactive experience

Open an issue or submit a PR if you have ideas or run into problems.

## License

MIT. Use it however you like.

## Credits

Archive/unarchive approach inspired by [this Reddit post](https://www.reddit.com/r/ClaudeAI/comments/1qqaung/where_are_archived_cowork_chats/) documenting the `isArchived` flag in Cowork session metadata.
