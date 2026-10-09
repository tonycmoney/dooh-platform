package com.dooh.dooh_player

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/** Starts the player when the tablet finishes booting or the app is updated.
 *  Android only allows this background start once "Display over other apps"
 *  is granted (or when the player is the default Home app). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED &&
            intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        Log.i("DOOH", "Starting player after ${intent.action}")
        try {
            context.startActivity(
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        } catch (e: Exception) {
            Log.w("DOOH", "Background start blocked", e)
        }
    }
}
