package com.familyvpn.poc

import org.json.JSONArray
import org.json.JSONObject

internal object ClientProfile {
    fun buildConfig(profile: JSONObject): String {
        require(profile.getInt("schema_version") == 1) { "Unsupported profile version" }
        val policy = profile.getJSONObject("policy")
        require(policy.getString("routing") == "full_tunnel") { "Unsupported routing policy" }
        require(policy.getString("dns") == "remote") { "Unsupported DNS policy" }

        val endpoint = profile.getJSONObject("endpoint")
        val vless = profile.getJSONObject("vless")
        val reality = profile.getJSONObject("reality")
        require(vless.getString("encryption") == "none") { "Unsupported encryption" }
        val tls = JSONObject()
            .put("enabled", true)
            .put("server_name", reality.getString("server_name"))
            .put("utls", JSONObject()
                .put("enabled", true)
                .put("fingerprint", reality.getString("fingerprint")))
            .put("reality", JSONObject()
                .put("enabled", true)
                .put("public_key", reality.getString("public_key"))
                .put("short_id", reality.getString("short_id")))
        val outbound = JSONObject()
            .put("type", "vless")
            .put("tag", "family-proxy")
            .put("server", endpoint.getString("address"))
            .put("server_port", endpoint.getInt("port"))
            .put("uuid", vless.getString("uuid"))
            .put("tls", tls)
        val flow = vless.optString("flow")
        if (flow.isNotBlank() && flow != "null") outbound.put("flow", flow)
        return ReferenceConfig.prepare(
            JSONObject().put("outbounds", JSONArray().put(outbound)).toString(),
        )
    }
}
