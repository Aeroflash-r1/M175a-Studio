package com.ganesan.m175otg.scan

/**
 * The printer's scan service is refusing jobs.
 *
 * VERIFIED on the wire (M175a, Sept 2026) — CreateScanJob is answered with:
 *
 *   <SOAP-ENV:Fault>
 *     <SOAP-ENV:Code><SOAP-ENV:Value>SOAP-ENV:Receiver</SOAP-ENV:Value>
 *       <SOAP-ENV:Subcode>
 *         <SOAP-ENV:Value>wscn:ServerErrorNotAcceptingJobs</SOAP-ENV:Value>
 *       </SOAP-ENV:Subcode></SOAP-ENV:Code>
 *     <SOAP-ENV:Reason><SOAP-ENV:Text>The service is temporarily blocked and
 *       can't accept new job or document requests.</SOAP-ENV:Text>
 *     </SOAP-ENV:Reason>
 *   </SOAP-ENV:Fault>
 *
 * ScannerState reads "Processing" (reason None) while this is up.
 * Measured: CancelJob for every plausible JobId does NOT clear it, and a
 * full USB SET_CONFIGURATION + re-enumeration does NOT clear it either —
 * the block is printer-internal and temporary. Waiting (and, if it
 * persists, power-cycling the printer) is the only recovery.
 */
class ScannerBlockedException :
    Exception("Printer's scanner service is temporarily blocked (not accepting jobs)")
