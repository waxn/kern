package app.kern.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// Mail (/api/mail/...): the same JSON the web app reads (backend/mail/api/views.py).

@Serializable
data class MailAddr(val name: String = "", val addr: String = "", val to: Boolean = false) {
    val label: String get() = name.ifBlank { addr }
    /** The same rule as the web app and the server (mail/names.py): their name, else the part before the @. */
    val display: String get() = name.trim().ifBlank { addr.substringBefore('@') }
}

@Serializable
data class MailFolder(
    val id: Long,
    val name: String = "",
    val displayName: String = "",
    val role: String = "",
    val unread: Int = 0,
    val total: Int = 0,
)

@Serializable
data class MailFolders(val folders: List<MailFolder> = emptyList(), val starred: Int = 0)

@Serializable
data class MailThread(
    val id: Long,
    /** "Alice", "Alice, Bob", "To: Dana": worked out by the server so every app names people alike. */
    val who: String = "",
    val subject: String = "",
    val snippet: String = "",
    val lastDate: String? = null,
    val count: Int = 1,
    val unread: Int = 0,
    val starred: Boolean = false,
    val hasAttachments: Boolean = false,
    val participants: List<MailAddr> = emptyList(),
    val risk: String = "",
    val snoozeUntil: String? = null,
    val muted: Boolean = false,
    val hit: String = "",
    val `package`: MailPackageChip? = null,
)

@Serializable
data class MailPackageChip(val status: String = "", val label: String = "")

@Serializable
data class MailScan(val at: String? = null, val text: String = "", val where: String = "")

@Serializable
data class MailPackage(
    val id: Long,
    val number: String = "",
    val carrierName: String = "",
    val status: String = "",
    val statusLabel: String = "",
    val statusAt: String? = null,
    val step: Int = 1,
    val expected: String? = null,
    val merchant: String = "",
    val subject: String = "",
    val trackUrl: String = "",
    val threadId: Long? = null,
    val live: Boolean = false,
    val location: String = "",
    val events: List<MailScan> = emptyList(),
    val assumed: Boolean = false,
    val route: MailRoute = MailRoute(),
)

/** Where a package has been, oldest first: [lat, lon, place] (backend/mail/geo.py). */
@Serializable
data class MailRoute(val origin: String = "", val destination: String = "", val points: List<kotlinx.serialization.json.JsonArray> = emptyList()) {
    val latLon: List<Pair<Double, Double>> get() = points.mapNotNull { p ->
        val lat = p.getOrNull(0)?.let { (it as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull() }
        val lon = p.getOrNull(1)?.let { (it as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull() }
        if (lat != null && lon != null) lat to lon else null
    }
}

@Serializable
data class MailTracking(val provider: String = "", val hasKey: Boolean = false, val lastError: String = "")

@Serializable
data class MailPackages(val active: List<MailPackage> = emptyList(), val delivered: List<MailPackage> = emptyList(), val tracking: MailTracking? = null, val map: MailMapInfo = MailMapInfo())

/** Whose map tiles the server hands out (backend/mail/geo.py) and the credit line to show. */
@Serializable
data class MailMapInfo(val provider: String = "osm", val attribution: String = "© OpenStreetMap contributors")

@Serializable
data class MailIdentity(val address: String = "", val name: String = "")

@Serializable
data class MailInfo(val address: String = "", val fromName: String = "", val identities: List<MailIdentity> = emptyList())

@Serializable
data class MailThreads(val threads: List<MailThread> = emptyList(), val next: String? = null, val total: Int? = null)

@Serializable
data class MailAttachment(val id: Long, val filename: String = "", val contentType: String = "", val size: Long = 0, val inline: Boolean = false)

@Serializable
data class MailRisk(val level: String = "", val score: Int = 0, val findings: List<JsonObject> = emptyList())

@Serializable
data class MailMessage(
    val id: Long,
    val threadId: Long? = null,
    val messageId: String = "",
    val from: MailAddr = MailAddr(),
    val to: List<MailAddr> = emptyList(),
    val cc: List<MailAddr> = emptyList(),
    val replyTo: List<MailAddr> = emptyList(),
    val subject: String = "",
    val date: String? = null,
    val seen: Boolean = true,
    val flagged: Boolean = false,
    val snippet: String = "",
    val fromMe: Boolean = false,
    val isDraft: Boolean = false,
    val attachments: List<MailAttachment> = emptyList(),
    val risk: MailRisk = MailRisk(),
)

@Serializable
data class MailThreadDetail(
    val thread: MailThread,
    val messages: List<MailMessage> = emptyList(),
    val tasks: List<Task> = emptyList(),
)

@Serializable
data class MailBody(
    val html: String? = null,
    val text: String? = null,
    val textHtml: String? = null,
    val remoteImages: Int = 0,
    /** How the server fitted its colors to the theme (backend/mail/colors.py). */
    val colors: String = "none",
)

@Serializable
data class MailTwoFactor(val enabled: Boolean = false, @SerialName("session_verified") val sessionVerified: Boolean = false)

@Serializable
data class MailStatus(
    val allowed: Boolean = true,
    val connected: Boolean = false,
    val account: JsonObject? = null,
    @SerialName("two_factor") val twoFactor: MailTwoFactor = MailTwoFactor(),
)

@Serializable
data class MailTodayItem(val threadId: Long, val subject: String = "", val from: String = "", val date: String? = null)

@Serializable
data class MailToday(
    val connected: Boolean = false,
    val unread: Int = 0,
    val latest: List<MailTodayItem> = emptyList(),
    val scheduledToday: Int = 0,
)

@Serializable
data class MailPrefill(
    val to: List<MailAddr> = emptyList(),
    val cc: List<MailAddr> = emptyList(),
    val subject: String = "",
    @SerialName("body_html") val bodyHtml: String = "",
    val from: String = "",
)

@Serializable
data class MailDraft(val id: Long, val status: String = "")

@Serializable
data class MailOpen(val threadId: Long)

/** One entry of /mail/changes (backend/mail/events.py). */
@Serializable
data class MailEvent(
    val id: Long = 0,
    val kind: String = "",
    val folder: Long? = null,
    val thread: Long? = null,
    val threads: List<Long> = emptyList(),
    val new: Boolean = false,
)

@Serializable
data class MailChanges(val last: Long = 0, val events: List<MailEvent> = emptyList(), val more: Boolean = false, val reset: Boolean = false)
