package com.dooh.dooh_player

import android.app.AlarmManager
import android.app.Application
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Process
import android.os.SystemClock
import android.util.Log
import kotlin.system.exitProcess

/** Installs a crash handler that relaunches the player instead of leaving the
 *  screen on the home screen or a crash dialog. */
class PlayerApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            try {
                Log.e("DOOH", "Player crashed; restarting", error)
                scheduleRestart(this)
            } catch (t: Throwable) {
                previous?.uncaughtException(thread, error)
            } finally {
                Process.killProcess(Process.myPid())
                exitProcess(10)
            }
        }
    }

    companion object {
        private const val RESTART_REQUEST = 7

        private fun backupIntent(context: Context, flags: Int): PendingIntent? = PendingIntent.getActivity(
            context, RESTART_REQUEST,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or flags
        )

        fun scheduleRestart(context: Context) {
            // 1) Backup alarm in case the immediate start below is blocked.
            backupIntent(context, PendingIntent.FLAG_CANCEL_CURRENT)?.let {
                context.getSystemService(AlarmManager::class.java)
                    ?.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime() + 5000, it)
            }
            // 2) Immediately, from a separate process (works while we're in the foreground).
            context.startActivity(
                Intent(context, RestartActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }

        /** Called once the player is back up, so the backup alarm doesn't
         *  launch it a second time. */
        fun cancelBackupRestart(context: Context) {
            backupIntent(context, PendingIntent.FLAG_NO_CREATE)?.let {
                context.getSystemService(AlarmManager::class.java)?.cancel(it)
                it.cancel()
            }
        }
    }
}
