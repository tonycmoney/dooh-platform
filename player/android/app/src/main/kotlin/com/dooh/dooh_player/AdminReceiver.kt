package com.dooh.dooh_player

import android.app.admin.DeviceAdminReceiver
import android.content.Context
import android.content.Intent

/** Makes the player eligible to be the tablet's device owner, set once with
 *  `adb shell dpm set-device-owner com.dooh.dooh_player/.AdminReceiver`
 *  (see scripts/provision_tablet.sh). */
class AdminReceiver : DeviceAdminReceiver() {
    override fun onEnabled(context: Context, intent: Intent) {
        Kiosk.applyPolicies(context)
    }
}
