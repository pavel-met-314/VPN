package com.familyvpn.poc

import org.json.JSONObject
import org.json.JSONArray

internal object ReferenceConfig {
    enum class Kind { COMPLETE, HIDDIFY_OUTBOUND, INVALID }

    fun kind(text: String): Kind {
        val json = JSONObject(text)
        val outbounds = json.optJSONArray("outbounds") ?: return Kind.INVALID
        if (outbounds.length() == 0) return Kind.INVALID
        val inbounds = json.optJSONArray("inbounds")
        if (inbounds != null) {
            for (index in 0 until inbounds.length()) {
                if (inbounds.optJSONObject(index)?.optString("type") == "tun") {
                    return Kind.COMPLETE
                }
            }
        }
        if (inbounds == null && outbounds.length() == 1 &&
            outbounds.optJSONObject(0)?.optString("type") == "vless"
        ) return Kind.HIDDIFY_OUTBOUND
        return Kind.INVALID
    }

    fun prepare(text: String): String {
        when (kind(text)) {
            Kind.COMPLETE -> return text
            Kind.INVALID -> error("Incomplete sing-box VPN config")
            Kind.HIDDIFY_OUTBOUND -> Unit
        }

        val source = JSONObject(text)
        val proxy = source.getJSONArray("outbounds").getJSONObject(0)
        val tag = proxy.optString("tag").takeUnless { it.isBlank() || it == "direct" }
            ?: "family-proxy"
        proxy.put("tag", tag)
        val direct = JSONObject().put("type", "direct").put("tag", "direct")
        val tun = JSONObject()
            .put("type", "tun")
            .put("tag", "family-tun")
            .put("address", JSONArray().put("172.19.0.1/30"))
            .put("mtu", 1500)
            .put("stack", "gvisor")
            .put("dns_mode", "hijack")
            .put("auto_route", true)
            .put("strict_route", true)
        val dnsServer = JSONObject()
            .put("type", "udp")
            .put("tag", "remote")
            .put("server", "1.1.1.1")
        val dns = JSONObject()
            .put("servers", JSONArray().put(dnsServer))
            .put("final", "remote")
            .put("strategy", "ipv4_only")
        val route = JSONObject()
            .put("auto_detect_interface", true)
            .put("final", tag)
            .put("rules", JSONArray()
                .put(JSONObject().put("protocol", "dns").put("action", "hijack-dns"))
                .put(JSONObject().put("ip_is_private", true).put("outbound", "direct")))
        return JSONObject()
            .put("dns", dns)
            .put("inbounds", JSONArray().put(tun))
            .put("outbounds", JSONArray().put(proxy).put(direct))
            .put("route", route)
            .toString()
    }
}
