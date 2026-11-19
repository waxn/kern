package app.kern.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// Mail (/api/mail/...): the same JSON the web app reads (backend/mail/api/views.py).

@Serializable
data class MailAddr(val name: String = "", val addr: String = "") {
    val label: String get() = name.ifBlank { addr }
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
)

@Serializable
data class MailThreads(val threads: List<MailThread> = emptyList(), val next: String? = null)

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
)

@Serializable
data class MailDraft(val id: Long, val status: String = "")

@Serializable
data class MailOpen(val threadId: Long)
