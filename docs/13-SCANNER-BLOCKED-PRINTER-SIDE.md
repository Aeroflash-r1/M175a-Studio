# 13 — Scanner Service BLOCKED (printer-side) — wire-proven

## Symptom
Tap Scan → dies in ~4 s (or 45 s) with no result. Toner/status still read fine.
`ScannerState: Processing`, `ScannerStateReason: None` on the Printer tab.

## What the printer actually answers (captured verbatim, M175a, Sept 2026)

CreateScanJob is REFUSED with a SOAP fault:

```xml
<SOAP-ENV:Fault>
  <SOAP-ENV:Code>
    <SOAP-ENV:Value>SOAP-ENV:Receiver</SOAP-ENV:Value>
    <SOAP-ENV:Subcode>
      <SOAP-ENV:Value>wscn:ServerErrorNotAcceptingJobs</SOAP-ENV:Value>
    </SOAP-ENV:Subcode>
  </SOAP-ENV:Code>
  <SOAP-ENV:Reason>
    <SOAP-ENV:Text>The service is temporarily blocked and can't accept
      new job or document requests.</SOAP-ENV:Text>
  </SOAP-ENV:Reason>
</SOAP-ENV:Fault>
```

Later in the same wedge the scan service degrades further:

* `GET /` (GetScannerElements) → **HTTP 500** (internal error)
* `EP 0x83` (scan data IN) → **no response at all** (45 s timeout)

while `EP 0x09/0x89` (BIDI status/toner) keeps answering perfectly.

## What does NOT clear it (all measured)

| Attempt | Result |
|---|---|
| `CancelJob` for JobIds 1..40 | no change (state stays Processing) |
| Clear USB endpoint halts (`CLEAR_FEATURE ENDPOINT_HALT`) | no change |
| Drain EP 0x83 | no change |
| USB `SET_CONFIGURATION` + full re-enumeration + re-claim | no change |
| Waiting ~10 minutes | no change |

## What clears it

**Power-cycle the printer** (off, 10 s, on). Nothing reachable over USB does.

## How the state gets created

The printer's scan service holds the session until it is closed with the
**Windows (WIA) sequence**:

```
GetScannerElements (arm)
CreateScanJob            -> 202 + JobId
RetrieveImage            -> 200 + chunked DIME JPEG
GetJobInfo               -> 202      <-- session close #1
GetPreviousImagePadInfo  -> 202      <-- session close #2
```

If a client disappears mid-job (app force-stop / APK reinstall / process kill),
the service is left holding the job and goes "blocked". The wscn client used to
end sessions with `CancelJob` only — that is NOT the driver's close, and
repeatedly abandoning jobs this way leaves the service blocked.

## App-side changes that result

1. **wscn now closes sessions exactly like Windows** — `GetJobInfo` +
   `GetPreviousImagePadInfo` after every successful retrieve, instead of
   `CancelJob`. LEDM already did this.
2. **The block is typed and handled** — `ScannerBlockedException` is thrown
   when the fault subcode `ServerErrorNotAcceptingJobs` is seen (on both
   transports). The scan flow then **waits 25 s and retries** (up to 2 times)
   because the printer says the block is *temporary* — instead of dying
   silently or hammering the engine with cancels/resets.
3. **Errors are visible** — the Scan tab always shows a status card, even with
   no thumbnail.
4. **Printer tab warns proactively** — non-Idle scanner state (or caps fetch
   failure while toner still reads) produces a red "Scanner needs attention"
   card with the power-cycle instruction.
5. **Automatic recovery is now non-destructive** (`softRecover`: halt clear +
   drain). The heavy USB `SET_CONFIGURATION` reset is only behind the
   **Fix scanner** button, and only as a last resort.

## Operational rule for the user

Never force-kill the app in the middle of a scan, and let a scan finish its
session-close handshake. If the panel shows a stuck scan, prefer the printer's
Cancel key first; if the service is already blocked, power-cycle.
