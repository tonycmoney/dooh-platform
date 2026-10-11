package com.dooh.dooh_player

import android.annotation.SuppressLint
import android.app.role.RoleManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {

    private val handler = Handler(Looper.getMainLooper())

    /** In kiosk mode the screen stays on: if someone presses the power
     *  button, it comes back on a few seconds later. */
    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (!Kiosk.isDeviceOwner(context) || Kiosk.inMaintenance(context)) return
            handler.postDelayed({ wakeScreen() }, 3000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PlayerApplication.cancelBackupRestart(this)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        hideSystemBars()
        Kiosk.applyPolicies(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF), Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF))
        }
    }

    override fun onResume() {
        super.onResume()
        Kiosk.lockIfNeeded(this)
    }

    override fun onDestroy() {
        unregisterReceiver(screenOff)
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    @Suppress("DEPRECATION")
    private fun wakeScreen() {
        val power = getSystemService(PowerManager::class.java) ?: return
        if (power.isInteractive) return
        power.newWakeLock(
            PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "dooh:wake"
        ).acquire(3000)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    @Suppress("DEPRECATION")
    private fun hideSystemBars() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.let {
                it.hide(WindowInsets.Type.systemBars())
                it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            window.decorView.systemUiVisibility = (View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "dooh/device").setMethodCallHandler { call, result ->
            when (call.method) {
                "deviceUid" -> result.success(deviceUid())
                "canStartFromBackground" -> result.success(Settings.canDrawOverlays(this))
                "openOverlaySettings" -> {
                    startActivity(
                        Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                    result.success(null)
                }
                "isDefaultHome" -> result.success(isDefaultHome())
                "requestDefaultHome" -> {
                    requestDefaultHome()
                    result.success(null)
                }
                "kioskStatus" -> result.success(mapOf(
                    "deviceOwner" to Kiosk.isDeviceOwner(this),
                    "locked" to Kiosk.isLocked(this),
                    "maintenance" to Kiosk.inMaintenance(this),
                ))
                "startMaintenance" -> {
                    Kiosk.startMaintenance(this, call.argument<Int>("minutes") ?: 15)
                    result.success(null)
                }
                "endMaintenance" -> {
                    Kiosk.endMaintenance(this)
                    result.success(null)
                }
                "releaseKiosk" -> {
                    Kiosk.release(this)
                    result.success(null)
                }
                "verifyPin" -> {
                    // PBKDF2 takes a moment: keep it off the UI thread.
                    val pin = call.argument<String>("pin") ?: ""
                    val salt = call.argument<String>("salt") ?: ""
                    val hash = call.argument<String>("hash") ?: ""
                    val iterations = call.argument<Int>("iterations") ?: 0
                    Thread {
                        val ok = Kiosk.verifyPin(pin, salt, hash, iterations)
                        handler.post { result.success(ok) }
                    }.start()
                }
                else -> result.notImplemented()
            }
        }
    }

    /** ANDROID_ID: stable for this app signing key + device + user, and survives
     *  reinstalls (it only changes on factory reset). */
    @SuppressLint("HardwareIds")
    private fun deviceUid(): String {
        val id = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
        return "android-" + (id ?: "unknown")
    }

    private fun isDefaultHome(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val roles = getSystemService(RoleManager::class.java)
            if (roles != null && roles.isRoleAvailable(RoleManager.ROLE_HOME)) {
                return roles.isRoleHeld(RoleManager.ROLE_HOME)
            }
        }
        val home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        val resolved = packageManager.resolveActivity(home, PackageManager.MATCH_DEFAULT_ONLY)
        return resolved?.activityInfo?.packageName == packageName
    }

    @Suppress("DEPRECATION")
    private fun requestDefaultHome() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val roles = getSystemService(RoleManager::class.java)
            if (roles != null && roles.isRoleAvailable(RoleManager.ROLE_HOME) && !roles.isRoleHeld(RoleManager.ROLE_HOME)) {
                startActivityForResult(roles.createRequestRoleIntent(RoleManager.ROLE_HOME), 42)
                return
            }
        }
        startActivity(Intent(Settings.ACTION_HOME_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
