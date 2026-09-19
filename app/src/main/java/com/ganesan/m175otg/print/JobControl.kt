package com.ganesan.m175otg.print

import java.util.concurrent.atomic.AtomicBoolean

/**
 * Cooperative cancel for the print path — what the Windows spooler's
 * "Delete job" does.
 *
 * Cancelling a USB print job is NOT just sending PJL: the job is streamed
 * to EP 0x01 by a background sender, so the sender must stop FIRST, and only
 * then may an abort sequence be pushed to the printer. Otherwise the abort
 * bytes interleave with live PCL XL data (the printer ignores both) and the
 * job keeps printing — exactly the old "Cancel does nothing" behaviour.
 */
object JobControl {

    private val cancelFlag = AtomicBoolean(false)

    /** True while a job is being streamed (Cancel button is meaningful). */
    @Volatile
    var active: Boolean = false
        private set

    /** Start of a job: clear any stale cancel request. */
    fun begin() {
        cancelFlag.set(false)
        active = true
    }

    /** Job finished (normally, cancelled or failed). */
    fun end() {
        active = false
        cancelFlag.set(false)
    }

    /** Cancel button / aborted flow. */
    fun requestCancel() { cancelFlag.set(true) }

    val isCancelled: Boolean get() = cancelFlag.get()
}
