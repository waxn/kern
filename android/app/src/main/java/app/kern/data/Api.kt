package app.kern.data

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

val KernJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
    isLenient = true
    encodeDefaults = true
}

class ApiError(val status: Int, message: String, val data: JsonElement? = null) : Exception(message)

/** Session cookies kept in app-private storage so the sign-in survives restarts (like the browser's). */
class PersistentCookieJar(private val prefs: SharedPreferences) : CookieJar {
    private val cookies = mutableMapOf<String, Cookie>()

    init {
        prefs.getStringSet("cookies", emptySet())!!.forEach { line ->
            val parts = line.split("\u0001", limit = 2)
            if (parts.size == 2) {
                val url = parts[0].toHttpUrlOrNull() ?: return@forEach
                Cookie.parse(url, parts[1])?.let { if (it.expiresAt > System.currentTimeMillis()) cookies[key(it)] = it }
            }
        }
    }

    private fun key(c: Cookie) = "${c.domain}|${c.path}|${c.name}"

    @Synchronized
    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        for (c in cookies) {
            if (c.expiresAt < System.currentTimeMillis()) this.cookies.remove(key(c)) else this.cookies[key(c)] = c
        }
        persist(url)
    }

    @Synchronized
    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val now = System.currentTimeMillis()
        cookies.values.removeAll { it.expiresAt < now }
        return cookies.values.filter { it.matches(url) }
    }

    private fun persist(url: HttpUrl) {
        val base = "${url.scheme}://${url.host}"
        prefs.edit().putStringSet("cookies", cookies.values.filter { it.persistent }.map { "$base\u0001$it" }.toSet()).apply()
    }

    @Synchronized
    fun clear() {
        cookies.clear()
        prefs.edit().remove("cookies").apply()
    }

    @Synchronized
    fun hasSession() = cookies.values.any { it.name == "kern_sid" && it.expiresAt > System.currentTimeMillis() }
}

class Api(context: Context, private val settings: Settings) {
    val cookieJar = PersistentCookieJar(context.getSharedPreferences("kern_cookies", Context.MODE_PRIVATE))

    val http: OkHttpClient = OkHttpClient.Builder()
        .cookieJar(cookieJar)
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS) // AI replies can take a while
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()

    private val _signedOut = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val signedOut = _signedOut.asSharedFlow()

    val base: String get() = settings.serverUrl.trimEnd('/')

    /** Absolute URL for a server path such as `/media/…`; leaves full URLs alone. */
    fun abs(path: String?): String? {
        if (path.isNullOrBlank()) return null
        if (path.startsWith("http://") || path.startsWith("https://")) return path
        return base + (if (path.startsWith("/")) path else "/$path")
    }

    suspend fun raw(method: String, path: String, body: RequestBody? = null): String = withContext(Dispatchers.IO) {
        if (base.isBlank()) throw ApiError(0, "Set your server address first.")
        val req = Request.Builder()
            .url(base + "/api" + path)
            .header("X-Kern", "1")
            .header("Accept", "application/json")
            .method(method, body ?: if (method == "GET" || method == "DELETE") null else "{}".toRequestBody(JSON))
            .build()
        val res = try {
            http.newCall(req).execute()
        } catch (e: IOException) {
            throw ApiError(0, "Cannot reach the server.")
        } catch (e: IllegalArgumentException) {
            throw ApiError(0, "That server address is not valid.")
        }
        res.use {
            val text = it.body?.string().orEmpty()
            if (it.code == 401 && !Regex("^/(auth|setup|site)").containsMatchIn(path)) _signedOut.tryEmit(Unit)
            if (!it.isSuccessful) {
                val data = runCatching { KernJson.parseToJsonElement(text) }.getOrNull()
                val detail = (data as? JsonObject)?.get("detail")?.jsonPrimitive?.contentOrNull
                throw ApiError(it.code, detail ?: it.message.ifBlank { "Request failed (${it.code})." }, data)
            }
            text
        }
    }

    suspend inline fun <reified T> get(path: String): T = KernJson.decodeFromString(raw("GET", path))
    suspend inline fun <reified T> post(path: String, body: JsonElement? = null): T =
        decode(raw("POST", path, (body ?: JsonObject(emptyMap())).toString().toRequestBody(JSON)))
    suspend inline fun <reified T> patch(path: String, body: JsonElement): T = decode(raw("PATCH", path, body.toString().toRequestBody(JSON)))
    suspend inline fun <reified T> put(path: String, body: JsonElement): T = decode(raw("PUT", path, body.toString().toRequestBody(JSON)))
    suspend fun delete(path: String) { raw("DELETE", path) }

    inline fun <reified T> decode(text: String): T =
        if (T::class == Unit::class) Unit as T else KernJson.decodeFromString(text.ifBlank { "{}" })

    suspend fun upload(name: String, mime: String, bytes: ByteArray): Uploaded {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", name, bytes.toRequestBody(mime.toMediaType()))
            .build()
        return decode(raw("POST", "/files", body))
    }

    companion object {
        val JSON = "application/json".toMediaType()
    }
}

fun JsonElement?.str(key: String): String? = (this as? JsonObject)?.get(key)?.let { runCatching { it.jsonPrimitive.contentOrNull }.getOrNull() }
fun JsonElement?.obj(key: String): JsonObject? = runCatching { (this as? JsonObject)?.get(key)?.jsonObject }.getOrNull()
