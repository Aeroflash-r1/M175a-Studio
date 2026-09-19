# 14 — Print / Cancel / Manual duplex — what was wrong and what changed

## 1. Cancel job did nothing (two independent bugs)

**Bug A — the button was unreachable.** `BusyOverlay()` and `FlipDialog()` are
both Compose dialogs. While a job runs, `busy = true`, so the busy dialog sat
on top of the whole tab — including the Cancel button on the Print tab.
Fix: the progress dialog now carries its own **Cancel job / Cancel scan**
button (like the Windows spooler window).

**Bug B — nothing stopped the sender.** Cancel only pushed PJL
(`EOJ` + `RESET` + UEL) to EP 0x01 *while the print thread was still
streaming*. The abort bytes interleaved with live PCL XL data: the printer
ignores both and keeps printing.

Fix — a real spooler-style cancel (`print/JobControl`):
1. `JobControl.requestCancel()` + `usb.cancelRequested = true`
2. the sender checks the flag between USB chunks (`sendPrint` returns `-2`,
   `printStream()` throws `PrintCancelledException`) and **unwinds**
3. `JobControl.end()` clears the flag, then the abort sequence
   (`UEL + @PJL EOJ + @PJL RESET`) is sent on a now-quiet channel
4. the flip prompt is cleared from the printer's panel too

Result type is now precise: `Ok` / `Cancelled` / `Failed` (a cancel is no
longer reported as a failure, and does not trigger printer rescue).

**Scans are cancellable too** (`scan/ScanControl`): the reader checks the flag
between USB reads, so a hung scan (up to 45 s before) stops immediately and
cancels its job on the printer.

## 2. Manual duplex showed no text

Same dialog-stacking bug: the busy dialog covered `FlipDialog`, so the flip
instructions were never visible. Fix: the flow now calls `clearBusy()` before
showing the flip prompt, and re-arms the busy state after the user confirms.

**LCD prompt was also mistimed.** The flip text used to be embedded in pass 1's
PCL XL session (`@PJL RDYMSG` inside the job header), so it appeared while side
1 was still printing and was wiped by that session's own close.
Now it is a **separate tiny PJL job sent after pass 1 and before the flip
prompt** (`PclxlPage.lcdMessageBytes`), and cleared after pass 2:

```
pass 1 (even pages, reversed)      e.g. 4, 2
LCD + app: "FLIP STACK + RELOAD"   <-- panel and phone agree, at the right moment
pass 2 (odd pages, forward)        e.g. 1, 3
LCD cleared
```

Verified on hardware: `Side 1: even pages 4, 2` → flip prompt visible →
`Side 2: odd pages 1, 3` → job completed.

## 3. Not burdening the printer (driver-like behaviour)

| Was | Now |
|---|---|
| `@PJL RESET` at the start of **every** job (engine re-init each time) | no RESET on normal jobs — reserved for the recovery path, like Windows |
| 3 × 5 s drain reads before each scan = up to **15 s** of "Preparing scanner…" | 2 × 800 ms — scan starts immediately |
| LEDM flush waited a full 5 s timeout | 800 ms |
| 12-page job held all page bitmaps (OOM after 2 pages → dead session) | one page rendered/sent/released at a time (streaming, already in place) |
| session closed with `CancelJob` (wscn) | `GetJobInfo` + `GetPreviousImagePadInfo` — the Windows WIA close |

## 4. Verified on the real printer (this round)

* **Scan** — 300 dpi colour: `JobId=19`, `2550x3507`, 863,684 B,
  `session closed cleanly`; pulled file decodes **strict OK**, 17 % ink.
* **Print** — test page and a 4-page 600 dpi PDF: `result=Ok(bytesSent=1226760)`,
  all 4 pages sent; toner counters moved (Black 79 %→78 %), proving output.
* **Manual duplex** — correct pass order, flip prompt visible, completed.
* **Cancel** — sender stopped at offset 229,376 B mid-stream (nothing further
  transmitted).

## Note for testing

Do **not** force-stop the app or uninstall the APK while a job is streaming:
that abandons the session and is what leaves the printer's scan service
blocked (see doc 13). Use Cancel instead — it unwinds cleanly.
