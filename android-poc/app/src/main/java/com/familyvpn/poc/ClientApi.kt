package com.familyvpn.poc

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

internal class ClientApiException(val status: Int, val code: String) : Exception(code)

internal class ClientApi(portalUrl: String) {
    val baseUrl: String

    init {
        val uri = URI(portalUrl.trim().trimEnd('/'))
        require(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.userInfo == null) {
            "Portal URL must use HTTPS"
        }
        require(uri.path.isNullOrEmpty() && uri.query == null && uri.fragment == null) {
            "Enter only the portal origin"
        }
        baseUrl = uri.toString()
    }

    fun login(username: String, password: String): JSONObject = request(
        "POST", "/sessions",
        JSONObject()
            .put("username", username)
            .put("password", password)
            .put("device_name", "Android phone"),
    )

    fun refresh(refreshToken: String): JSONObject = request(
        "POST", "/sessions/refresh",
        JSONObject().put("refresh_token", refreshToken),
    )

    fun profile(accessToken: String): JSONObject =
        request("GET", "/profile", bearer = accessToken)

    fun logout(accessToken: String) {
        request("DELETE", "/sessions/current", bearer = accessToken)
    }

    private fun request(
        method: String,
        path: String,
        body: JSONObject? = null,
        bearer: String? = null,
    ): JSONObject {
        val connection = (URL("$baseUrl/portal/api/client/v1$path").openConnection()
            as HttpURLConnection)
        try {
            connection.requestMethod = method
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 10_000
            connection.readTimeout = 10_000
            connection.setRequestProperty("Accept", "application/json")
            if (bearer != null) connection.setRequestProperty("Authorization", "Bearer $bearer")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            if (status == 204) return JSONObject()
            val text = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.use { it.bufferedReader(Charsets.UTF_8).readText() }.orEmpty()
            if (status !in 200..299) {
                val code = runCatching {
                    JSONObject(text).getJSONObject("detail").getString("code")
                }.getOrDefault("HTTP_$status")
                throw ClientApiException(status, code)
            }
            return JSONObject(text)
        } finally {
            connection.disconnect()
        }
    }
}
