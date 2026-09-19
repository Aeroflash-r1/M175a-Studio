package com.ganesan.m175otg.scan

import java.util.concurrent.atomic.AtomicBoolean

/**
 * Cooperative cancel for the scan path.
 *
 * A scan can otherwise block for up to 45 s on a silent channel or a stalled
 * engine, with no way for the user to stop it. The reader loop checks this
 * flag between USB reads, unwinds, and the flow then cancels the job on the
 * printer (CancelJobRequest) so the engine returns to Idle.
 */
object ScanControl {

    private val cancelFlag = AtomicBoolean(false)

    /** True while a scan is running (Cancel button is meaningful). */
    @Volatile
    var active: Boolean = false
        private set

    fun begin() {
        cancelFlag.set(false)
        active = true
    }

    fun end() {
        active = false
        cancelFlag.set(false)
    }

    fun requestCancel() { cancelFlag.set(true) }

    val isCancelled: Boolean get() = cancelFlag.get()
}

/** Thrown when the user cancels a scan mid-flight. */
class ScanCancelledException : Exception("Scan cancelled")
