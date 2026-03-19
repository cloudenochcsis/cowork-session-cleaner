# Cowork Session Manager

A Python script to list, delete, archive, and unarchive your Claude Cowork sessions from the command line.

## The Problem

Claude's Cowork mode stores sessions locally on your Mac, but there is currently no built-in UI to bulk-delete sessions or view/restore archived chats. Over time, sessions pile up, eat disk space, and there is no straightforward way to clean them up. Archived chats simply disappear from the sidebar with no option to bring them back through the app.

This script gives you visibility into all your Cowork sessions and lets you manage them directly.

## What It Does

- Lists all Cowork sessions with their title, last modified date, size, and archive status
- **Delete** sessions to free up disk space
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
  12 session(s)  |  9 active, 3 archived  |  245.3 MB total
==========================================================================================

    #  Status     Last Modified        Size  Title / Session ID
  ---  --------   ----------------   ----------  ----------------------------------------
    1  active     2026-03-19 14:22     52.3 MB  Website redesign project
    2  active     2026-03-18 09:10     38.1 MB  Help me write a cover letter
    3  ARCHIVED   2026-03-15 16:45     12.7 MB  Budget spreadsheet cleanup
    4  active     2026-03-12 11:30      8.4 MB  Debug my Python script
    5  ARCHIVED   2026-03-01 08:55      3.2 MB  Meeting notes summary
  ...

  What would you like to do?
    [D] Delete sessions
    [A] Archive sessions (hide from Cowork)
    [U] Unarchive sessions (restore to Cowork)
    [Q] Quit

  Action: u

  Enter session numbers.
  Examples: 1,3,5  or  1-5  or  all

  Select: 3,5

  Sessions to UNARCHIVE (2):
    - Budget spreadsheet cleanup  (2026-03-15 16:45)
    - Meeting notes summary  (2026-03-01 08:55)

  Confirm UNARCHIVE? (yes/no): yes
  Unarchived: Budget spreadsheet cleanup
  Unarchived: Meeting notes summary

  Done. Unarchived 2 session(s). Restart Claude for changes to take effect.
```

## How It Works

Cowork sessions live at:
```
~/Library/Application Support/Claude/local-agent-mode-sessions/<org-uuid>/<project-uuid>/local_<session-uuid>/
```

Each session has a corresponding JSON metadata file. The script reads these to get the session title and archive status. Archiving and unarchiving works by setting `"isArchived": true` or `false` in that JSON file, which is how the Claude app tracks visibility. You need to restart the Claude app after archiving or unarchiving for the changes to appear.

Deleting removes the entire session folder and its metadata permanently.

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

Archive/unarchive approach based on [this Reddit post](https://www.reddit.com/r/ClaudeAI/) documenting the `isArchived` flag in Cowork session metadata.
