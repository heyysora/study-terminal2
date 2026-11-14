# Windows recovery audit (0.13.5, 2026-11-13)

What was tested for recovering from problems without a terminal, where it was tested, and what's still unknown.

## Three different environments. Don't mix them up.

| Environment | What it is | Counts as "works on my PC"? |
|---|---|---|
| **Linux build machine** | Where the code is written. Automated tests, and the recovery drill run against the app from source. | No |
| **GitHub-hosted Windows** | A clean Windows Server 2025 virtual machine on GitHub. Runs every test, installs the **real installer**, and drives the **installed app** through its own API (no window, no clicks). | **No.** It's Windows, but not your computer: no antivirus or sync apps, no Edge with TopstepX, different disk and user account. |
| **Your PC** | Your own Windows computer. | Only results from here. **Nothing in this report was run on your PC.** Your PC last ran Study Terminal 0.7.0 (20 of 20 checks passed). |

Final run for 0.13.5: GitHub Actions run **43555645264**: all **512 tests passed** on Windows, **39 of 39 reliability checks
passed**, and the release was published only because both did. The raw results are the `windows-reliability` file attached to
that run (`results.md`, `recovery-drill.json`, logs).

## What you asked for, and where it was tested

| Test | Linux | GitHub Windows (installed app) | Your PC | Result and evidence |
|---|---|---|---|---|
| Backup creation | ✓ | ✓ | — | Made through the app; the app's own check passed; the backup was also opened separately with SQLite and its journal, settings and practice tables matched the live data |
| Backup restoration | ✓ | ✓ | — | Restored a backup after a setting had changed; the setting went back; a "before a restore" backup of the current data was made first |
| Automatic restart after restoration | ✓ | ✓ | — | The app restarted itself and was back in **6.2 s** on Windows, with no window or clicks |
| Recovery from corrupted data | ✓ | ✓ | — | Damaged data file → Recovery mode; the damaged file left untouched until a choice was made; restore → restarted in **9.0 s**; the damaged file kept in `damaged\` |
| Partial data recovery | ✓ | ✓ | — | Part of the file wrecked → Recovery mode → rescue saved **19 of 20 tables**; only the deliberately damaged test table was lost; restarted in **10.1 s** |
| Application startup after recovery | ✓ | ✓ | — | Normal start after both the restore and the rescue; the data file opens |
| Failed restoration (backup damaged after it was picked) | ✓ | ✓ | — | Nothing changed: "Your data wasn't touched"; the app started normally on your original data; the bad backup is shown as damaged |
| Failed restoration and rollback (failure halfway, after the old file was moved aside) | ✓ | ✓ | — | Original put back byte for byte: "Your data was put back exactly as it was" (run by the app's built-in recovery check, which uses a test switch to cause the failure) |
| Journals, settings and practice accounts preserved | ✓ | ✓ | — | 10 tables (journal trades and notes, practice account, orders and fills, futures practice fills, settings, watchlists, learning progress) compared row by row before and after every step: **identical** each time |
| Upgrade from 0.13.4 keeps data | — | ✓ | — | All views identical; the backup made before the upgrade equals the data before the upgrade |
| Damaged data file opens Recovery mode (installer self-test) | ✓ | ✓ | — | Self-test reports Recovery mode (exit 2); file unchanged |
| Starts when its usual port is taken | ✓ | ✓ | — | Moved from 8811 to 8812 by itself |
| Chrome extension finds the app on another port | ✓ | ✓ (test suite) | — | The extension's own code (in Node, with Chrome's storage faked) found the app after it moved off a blocked 8765, remembered the port, and reached the real app. **Not tested in real Chrome.** |
| Backup verification: incomplete / missing files / damaged | ✓ | ✓ (test suite) | — | Each detected and refused for restore; the last usable backup is never pruned; "no usable backup" warns |
| System health page | ✓ | ✓ | — | Answers in normal and Recovery mode; shows backups, data file, chart monitor, extension, starts, errors |
| Recovery self-check (Health page) | ✓ | ✓ | **Not run yet** | 7 of 7 steps passed on Windows; your real data file is only read |
| Install, uninstall keeps data, installer rollback, logs without secrets | — | ✓ | — | All passed (unchanged from 0.13.4) |

## Problems found and fixed while testing

| Problem | Found by | Fix |
|---|---|---|
| A restore moved your current file aside *before* copying the backup in; a failure in between could leave no data file | Code review | The new file is built and checked first; a failure after the swap begins puts the original back |
| A backup refused at restart for being damaged still showed as "usable" in the list (damage that didn't change the file size) | Drill (Linux) | The check result is saved, so the list shows it as damaged |
| Old backups were pruned by count even when the newer ones were bad | Code review | Count only usable ones; never delete the newest usable backup |
| After a quick restart the app moved to another port for no reason (the old port was briefly reserved by Linux) | Drill (Linux) | The free-port check now matches the server's own rule. Windows doesn't reserve ports this way, but the drill would have caught it there too |
| The extension could wait forever if another program held its port without answering | Extension test (Linux) | 6-second limit, then it searches |
| On Windows the extension once didn't find the app within the time allowed for each port | Extension test (GitHub Windows) | 2.5 s per port, 20 ports at a time, a second pass if nothing answers |
| The recovery self-check collided with a table left empty by an earlier rescue | Drill (Linux) | Unique names; rescue reports tables it left empty |
| The Windows check compared the wrong backup once daily backups existed | GitHub Windows | Pick the backup named for the upgrade |

## Remaining limitations

- **None of this has run on your PC.** Antivirus, OneDrive or another sync app, a different disk or user account could
  behave differently. Use **Health > Run the recovery check** on your PC: it runs the same backup, restore, rescue, rollback
  and damaged-backup steps on a scratch copy next to your data and saves the result. **Save a complete help file** includes it.
  Until then, everything above is "GitHub Windows only".
- The automatic restart needs the desktop app. Opened in a plain browser tab, the page asks you to close and reopen.
- **The real window was not driven.** On Windows the installed app ran without its window; the screens themselves were checked
  in headless Chrome on Linux. Clicking the buttons in the real desktop window hasn't been done.
- Rescue saves tables that can still be read whole. A table with any unreadable part is left empty, not partly saved.
- A file that's completely unreadable can only come back from a backup; daily backups keep that loss to at most a day.
- A full disk and a locked data folder were simulated (Linux), not reproduced on Windows.
- The Chrome extension's discovery was tested with its own code in Node, not inside Chrome. A real Chrome install, pairing and
  a TradingView tab haven't been tried.
- If several copies of Study Terminal were somehow running (it normally refuses a second one), the extension would use the
  first one it finds.
- Backups are only as safe as the disk they're on: they live in the same data folder. Copying them elsewhere is up to you
  (**Open backups folder**).

## Nothing here changes trading

No strategy, risk calculation or safety rule was changed. Real order execution is still impossible; the practice-only lock
reported "live locked: True" in every Windows self-test.
