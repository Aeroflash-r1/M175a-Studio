package com.ganesan.m175otg

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

/**
 * Notifications: job-done + low-toner alerts.
 * Channel created lazily; POST_NOTIFICATIONS is a runtime permission on
 * Android 13+ (requested from the UI).
 */
object Notifier {

    const val CH_EVENTS = "m175_events"
    const val CH_ALERTS = "m175_alerts"
    private const val ID_JOB_DONE = 1
    private const val ID_LOW_TONER = 2

    fun ensureChannels(ctx: Context) {
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
                as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CH_EVENTS, "Print & scan events",
                NotificationManager.IMPORTANCE_DEFAULT))
        nm.createNotificationChannel(
            NotificationChannel(CH_ALERTS, "Toner alerts",
                NotificationManager.IMPORTANCE_HIGH))
    }

    fun canNotify(ctx: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
                ContextCompat.checkSelfPermission(
                    ctx, Manifest.permission.POST_NOTIFICATIONS
                ) == PackageManager.PERMISSION_GRANTED

    private fun build(ctx: Context, ch: String, title: String,
                      text: String): Notification {
        val pi = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(ctx, ch)
            .setSmallIcon(android.R.drawable.stat_notify_more)
            .setContentTitle(title)
            .setContentText(text)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()
    }

    fun jobDone(ctx: Context, what: String, detail: String) {
        if (!canNotify(ctx)) return
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
                as NotificationManager
        nm.notify(ID_JOB_DONE, build(ctx, CH_EVENTS, what, detail))
    }

    /** Fires when any toner is below [pct]% or its pages-left estimate is low. */
    fun lowToner(ctx: Context, lines: List<String>) {
        if (lines.isEmpty() || !canNotify(ctx)) return
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
                as NotificationManager
        val big = NotificationCompat.BigTextStyle()
            .bigText(lines.joinToString("\n"))
        val pi = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(ID_LOW_TONER,
            NotificationCompat.Builder(ctx, CH_ALERTS)
                .setSmallIcon(android.R.drawable.stat_notify_error)
                .setContentTitle("Low toner - buy soon")
                .setStyle(big)
                .setAutoCancel(true)
                .setContentIntent(pi)
                .build())
    }
}
