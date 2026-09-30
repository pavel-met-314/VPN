package com.familyvpn.poc

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import android.os.Process
import android.system.OsConstants
import io.nekohasekai.libbox.BridgeOptions
import io.nekohasekai.libbox.BridgeSession
import io.nekohasekai.libbox.ConnectionOwner
import io.nekohasekai.libbox.InterfaceUpdateListener
import io.nekohasekai.libbox.LocalDNSTransport
import io.nekohasekai.libbox.NeighborUpdateListener
import io.nekohasekai.libbox.NetworkInterfaceIterator
import io.nekohasekai.libbox.PlatformInterface
import io.nekohasekai.libbox.PlatformUser
import io.nekohasekai.libbox.ShellSession
import io.nekohasekai.libbox.StringIterator
import io.nekohasekai.libbox.TunOptions
import io.nekohasekai.libbox.WIFIState
import io.nekohasekai.libbox.Notification as CoreNotification
import io.nekohasekai.libbox.NetworkInterface as CoreNetworkInterface
import java.net.InetSocketAddress
import java.net.NetworkInterface

internal class AndroidPlatformBridge(private val service: FamilyVpnService) : PlatformInterface {
    private val connectivity = service.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private var callback: ConnectivityManager.NetworkCallback? = null
    @Volatile private var physicalNetwork: Network? = null

    override fun localDNSTransport(): LocalDNSTransport? = null
    override fun usePlatformAutoDetectInterfaceControl(): Boolean = true
    override fun autoDetectInterfaceControl(fd: Int) = service.protectSocket(fd)
    override fun openTun(options: TunOptions): Int = service.openTun(options)
    override fun useProcFS(): Boolean = Build.VERSION.SDK_INT < 29

    override fun findConnectionOwner(
        ipProtocol: Int,
        sourceAddress: String?, sourcePort: Int,
        destinationAddress: String?, destinationPort: Int,
    ): ConnectionOwner {
        val uid = if (Build.VERSION.SDK_INT >= 29 && sourceAddress != null && destinationAddress != null) {
            runCatching {
                connectivity.getConnectionOwnerUid(
                    ipProtocol,
                    InetSocketAddress(sourceAddress, sourcePort),
                    InetSocketAddress(destinationAddress, destinationPort),
                )
            }.getOrDefault(Process.INVALID_UID)
        } else Process.INVALID_UID
        return ConnectionOwner().apply {
            userId = uid
            userName = if (uid == Process.INVALID_UID) "" else service.packageManager.getPackagesForUid(uid)?.firstOrNull().orEmpty()
            processPath = ""
        }
    }

    override fun startDefaultInterfaceMonitor(listener: InterfaceUpdateListener) {
        val next = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = publish(network)
            override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) = publish(network)
            override fun onLost(network: Network) {
                if (network != physicalNetwork) return
                physicalNetwork = null
                connectivity.allNetworks.forEach { candidate ->
                    if (candidate != network) publish(candidate)
                }
                if (physicalNetwork != null) return
                listener.updateDefaultInterface("", -1, false, false)
            }

            private fun publish(network: Network) {
                val capabilities = connectivity.getNetworkCapabilities(network) ?: return
                if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) return
                val name = connectivity.getLinkProperties(network)?.interfaceName ?: return
                val index = NetworkInterface.getByName(name)?.index ?: return
                physicalNetwork = network
                listener.updateDefaultInterface(
                    name, index,
                    !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED),
                    false,
                )
            }
        }
        callback?.let { connectivity.unregisterNetworkCallback(it) }
        callback = next
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()
        connectivity.registerNetworkCallback(request, next)
    }

    override fun closeDefaultInterfaceMonitor(listener: InterfaceUpdateListener) {
        callback?.let { connectivity.unregisterNetworkCallback(it) }
        callback = null
        physicalNetwork = null
    }

    override fun getInterfaces(): NetworkInterfaceIterator {
        val values = mutableListOf<CoreNetworkInterface>()
        for (network in connectivity.allNetworks) {
            val properties = connectivity.getLinkProperties(network) ?: continue
            val capabilities = connectivity.getNetworkCapabilities(network) ?: continue
            if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue
            val name = properties.interfaceName ?: continue
            val system = NetworkInterface.getByName(name) ?: continue
            val item = CoreNetworkInterface()
            item.name = name
            item.index = system.index
            item.mtu = runCatching { system.mtu }.getOrDefault(1500)
            item.addresses = Strings(system.interfaceAddresses.mapNotNull { address ->
                val host = address.address.hostAddress ?: return@mapNotNull null
                "${host.substringBefore('%')}/${address.networkPrefixLength}"
            })
            item.dnsServer = Strings(properties.dnsServers.mapNotNull { it.hostAddress })
            item.gateway = Strings(properties.routes.mapNotNull { it.gateway?.hostAddress })
            item.type = when {
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> io.nekohasekai.libbox.Libbox.InterfaceTypeWIFI
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> io.nekohasekai.libbox.Libbox.InterfaceTypeCellular
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> io.nekohasekai.libbox.Libbox.InterfaceTypeEthernet
                else -> io.nekohasekai.libbox.Libbox.InterfaceTypeOther
            }
            item.flags = OsConstants.IFF_UP or OsConstants.IFF_RUNNING
            item.metered = !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
            values.add(item)
        }
        return Interfaces(values)
    }

    override fun underNetworkExtension(): Boolean = false
    override fun includeAllNetworks(): Boolean = false
    override fun readWIFIState(): WIFIState? = null
    override fun clearDNSCache() = Unit
    override fun sendNotification(notification: CoreNotification?) = Unit
    override fun cancelNotification(identifier: String?, typeID: Int) = Unit
    override fun startNeighborMonitor(listener: NeighborUpdateListener?) = Unit
    override fun closeNeighborMonitor(listener: NeighborUpdateListener?) = Unit
    override fun registerMyInterface(name: String?) = Unit
    override fun usePlatformShell(): Boolean = false
    override fun checkPlatformShell(): Unit = error("Unsupported in PoC")
    override fun openShellSession(
        user: PlatformUser?, command: String?, environ: StringIterator?,
        term: String?, rows: Int, cols: Int,
    ): ShellSession = error("Unsupported in PoC")
    override fun lookupUser(username: String?): PlatformUser? = null
    override fun lookupSFTPServer(): String = ""
    override fun readSystemSSHHostKey(): String = ""
    override fun tailscaleHostname(): String = ""
    override fun usePlatformBridge(): Boolean = false
    override fun createBridge(options: BridgeOptions?): BridgeSession = error("Unsupported in PoC")

    private class Strings(values: List<String>) : StringIterator {
        private val iterator = values.iterator()
        private var remaining = values.size
        override fun hasNext(): Boolean = iterator.hasNext()
        override fun len(): Int = remaining
        override fun next(): String = iterator.next().also { remaining-- }
    }

    private class Interfaces(values: List<CoreNetworkInterface>) : NetworkInterfaceIterator {
        private val iterator = values.iterator()
        override fun hasNext(): Boolean = iterator.hasNext()
        override fun next(): CoreNetworkInterface = iterator.next()
    }
}
