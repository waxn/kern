package app.kern

import android.app.Application
import android.content.Context
import app.kern.data.Api
import app.kern.data.Kern
import app.kern.data.Settings
import app.kern.notify.Notifications
import app.kern.notify.SyncWorker
import coil.ImageLoader
import coil.ImageLoaderFactory

class KernApp : Application(), ImageLoaderFactory {
    lateinit var settings: Settings
    lateinit var api: Api
    lateinit var kern: Kern

    override fun onCreate() {
        super.onCreate()
        settings = Settings(this)
        api = Api(this, settings)
        kern = Kern(api)
        Notifications.createChannels(this)
        if (settings.user != null) SyncWorker.schedule(this)
    }

    /** Images on the server (`/media/…`) need the session cookie, so Coil shares the API's client. */
    override fun newImageLoader(): ImageLoader = ImageLoader.Builder(this)
        .okHttpClient(api.http)
        .crossfade(true)
        .build()
}

val Context.app: KernApp get() = applicationContext as KernApp
