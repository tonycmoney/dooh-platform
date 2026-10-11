package com.dooh.dooh_player

import android.Manifest
import android.app.Activity
import android.app.ActivityManager
import android.app.AlarmManager
import android.app.PendingIntent
import android.app.admin.DevicePolicyManager
import android.app.admin.SystemUpdatePolicy
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.UserManager
import android.provider.Settings
import android.util.Base64
import android.util.Log
import java.security.MessageDigest
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/**
 * Public-display lockdown. Everything here needs the player to be the
 * tablet's device owner; without that the app still plays, just unlocked.
 *
 * - Lock task mode with every system feature off: no Home, Recents, status
 *   bar, notification shade, power menu or other apps.
 * - Permanent Home app, no lock screen, screen kept on while powered.
 * - System error dialogs off, safe boot and new users blocked.
 * - System updates only install between 02:00 and 05:00.
 * - Maintenance mode: kiosk paused for a few minutes (after the secret tap
 *   pattern + PIN), then the player relaunches itself and locks again.
 */
object Kiosk {
    private const val TAG = "DOOH"
    private const val PREFS = "kiosk"
    private const val MAINTENANCE_UNTIL = "maintenance_until"
    private const val RELOCK_REQUEST = 11

    private val RESTRICTIONS = listOf(
        UserManager.DISALLOW_SYSTEM_ERROR_DIALOGS,
        UserManager.DISALLOW_SAFE_BOOT,
        UserManager.DISALLOW_ADD_USER,
    )

    private fun dpm(context: Context) = context.getSystemService(DevicePolicyManager::class.java)
    private fun admin(context: Context) = ComponentName(context, AdminReceiver::class.java)

    fun isDeviceOwner(context: Context): Boolean =
        dpm(context)?.isDeviceOwnerApp(context.packageName) == true

    /** Idempotent; safe to call on every start. */
    fun applyPolicies(context: Context) {
        if (!isDeviceOwner(context)) return
        val dpm = dpm(context)!!
        val admin = admin(context)
        fun attempt(what: String, block: () -> Unit) =
            try { block() } catch (e: Exception) { Log.w(TAG, "Kiosk policy '$what' not applied", e) }

        attempt("lock task") {
            dpm.setLockTaskPackages(admin, arrayOf(context.packageName))
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                dpm.setLockTaskFeatures(admin, DevicePolicyManager.LOCK_TASK_FEATURE_NONE)
            }
        }
        attempt("home app") {
            val home = IntentFilter(Intent.ACTION_MAIN).apply {
                addCategory(Intent.CATEGORY_HOME)
                addCategory(Intent.CATEGORY_DEFAULT)
            }
            dpm.addPersistentPreferredActivity(admin, home, ComponentName(context, MainActivity::class.java))
        }
        attempt("keyguard") { dpm.setKeyguardDisabled(admin, true) }
        attempt("status bar") { dpm.setStatusBarDisabled(admin, true) }
        attempt("stay on") {
            val anyPower = BatteryManager.BATTERY_PLUGGED_AC or BatteryManager.BATTERY_PLUGGED_USB or
                BatteryManager.BATTERY_PLUGGED_WIRELESS
            dpm.setGlobalSetting(admin, Settings.Global.STAY_ON_WHILE_PLUGGED_IN, anyPower.toString())
        }
        attempt("screen timeout") {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                dpm.setSystemSetting(admin, Settings.System.SCREEN_OFF_TIMEOUT, Int.MAX_VALUE.toString())
            }
        }
        attempt("restrictions") { RESTRICTIONS.forEach { dpm.addUserRestriction(admin, it) } }
        attempt("update window") {
            dpm.setSystemUpdatePolicy(admin, SystemUpdatePolicy.createWindowedInstallPolicy(2 * 60, 5 * 60))
        }
        attempt("location") {
            for (p in listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)) {
                dpm.setPermissionGrantState(admin, context.packageName, p,
                    DevicePolicyManager.PERMISSION_GRANT_STATE_GRANTED)
            }
        }
    }

    // --- Lock task ----------------------------------------------------------

    fun inMaintenance(context: Context): Boolean =
        System.currentTimeMillis() < prefs(context).getLong(MAINTENANCE_UNTIL, 0)

    fun isLocked(activity: Activity): Boolean =
        activity.getSystemService(ActivityManager::class.java)?.lockTaskModeState !=
            ActivityManager.LOCK_TASK_MODE_NONE

    /** Called whenever the player comes to the front. */
    fun lockIfNeeded(activity: Activity) {
        if (!isDeviceOwner(activity) || inMaintenance(activity)) return
        if (prefs(activity).contains(MAINTENANCE_UNTIL)) {
            // Maintenance time ran out: put everything back.
            prefs(activity).edit().remove(MAINTENANCE_UNTIL).apply()
            dpm(activity)?.setStatusBarDisabled(admin(activity), true)
        }
        if (isLocked(activity)) return
        if (dpm(activity)?.isLockTaskPermitted(activity.packageName) != true) applyPolicies(activity)
        try {
            activity.startLockTask()
        } catch (e: Exception) {
            Log.w(TAG, "startLockTask failed", e)
        }
    }

    /** Pauses the kiosk for [minutes] and opens Android Settings. The player
     *  comes back and locks again when the time is up. */
    fun startMaintenance(activity: Activity, minutes: Int) {
        val until = System.currentTimeMillis() + minutes * 60_000L
        prefs(activity).edit().putLong(MAINTENANCE_UNTIL, until).apply()
        if (isDeviceOwner(activity)) {
            dpm(activity)?.setStatusBarDisabled(admin(activity), false)
        }
        if (isLocked(activity)) activity.stopLockTask()
        relockAlarm(activity, PendingIntent.FLAG_UPDATE_CURRENT)?.let {
            activity.getSystemService(AlarmManager::class.java)
                ?.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, until, it)
        }
        activity.startActivity(Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun endMaintenance(activity: Activity) {
        prefs(activity).edit().remove(MAINTENANCE_UNTIL).apply()
        relockAlarm(activity, PendingIntent.FLAG_NO_CREATE)?.let {
            activity.getSystemService(AlarmManager::class.java)?.cancel(it)
            it.cancel()
        }
        if (isDeviceOwner(activity)) dpm(activity)?.setStatusBarDisabled(admin(activity), true)
        lockIfNeeded(activity)
    }

    private fun relockAlarm(context: Context, flags: Int): PendingIntent? = PendingIntent.getActivity(
        context, RELOCK_REQUEST,
        Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        PendingIntent.FLAG_IMMUTABLE or flags
    )

    /** Undoes everything and gives up device ownership, so the tablet can be
     *  used normally or the app uninstalled. */
    fun release(activity: Activity) {
        if (!isDeviceOwner(activity)) return
        val dpm = dpm(activity)!!
        val admin = admin(activity)
        if (isLocked(activity)) activity.stopLockTask()
        try {
            dpm.setLockTaskPackages(admin, arrayOf())
            dpm.clearPackagePersistentPreferredActivities(admin, activity.packageName)
            dpm.setKeyguardDisabled(admin, false)
            dpm.setStatusBarDisabled(admin, false)
            RESTRICTIONS.forEach { dpm.clearUserRestriction(admin, it) }
            dpm.setSystemUpdatePolicy(admin, null)
        } catch (e: Exception) {
            Log.w(TAG, "Clearing kiosk policies failed", e)
        }
        @Suppress("DEPRECATION")
        dpm.clearDeviceOwnerApp(activity.packageName)
        prefs(activity).edit().clear().apply()
    }

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    // --- PIN ------------------------------------------------------------------

    /** Checks [pin] against the dashboard's PBKDF2-HMAC-SHA256 hash. */
    fun verifyPin(pin: String, saltBase64: String, hashHex: String, iterations: Int): Boolean {
        return try {
            val salt = Base64.decode(saltBase64, Base64.DEFAULT)
            val spec = PBEKeySpec(pin.toCharArray(), salt, iterations, 256)
            val digest = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
            val expected = hashHex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
            MessageDigest.isEqual(digest, expected)
        } catch (e: Exception) {
            Log.w(TAG, "PIN check failed", e)
            false
        }
    }
}
