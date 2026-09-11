import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Networking

// Wifi quick panel, opened from waybar's network module (on-click: `qs -c
// wifi`). Built on Quickshell's native NetworkManager binding
// (Quickshell.Networking) rather than shelling out to nmcli: the network
// list, connect/forget, and Wi-Fi on/off are all real reactive
// properties/methods here -- same reasoning as ../audio/shell.qml using
// Quickshell.Services.Pipewire instead of wpctl.
//
// title is a distinct hook for conf/rules.lua to position this window (top
// right, under waybar), the same mechanism ../audio/shell.qml uses.
FloatingWindow {
	id: panel
	title: "quickshell-wifi"

	// See ../audio/shell.qml's identical note: without this, closing the
	// window (defocus, or `quickshell-toggle` clicking the bar icon again)
	// doesn't end the process -- Quickshell expects to keep running as a
	// shell with zero or more windows otherwise.
	onClosed: Qt.quit()

	readonly property int contentMargin: 10
	readonly property int contentSpacing: 6
	readonly property int rowHeight: 32
	readonly property int passwordRowHeight: 36
	readonly property int dividerHeight: 1
	readonly property int rowSpacing: 2
	readonly property int scrollGutter: 10
	// See ../audio/shell.qml's identical note: a FloatingWindow's
	// implicitHeight is only applied once at creation, so this is sized for
	// a fixed number of rows up front and the list scrolls past that rather
	// than growing to fit. The inline password prompt (below) expands a
	// delegate *within* that fixed-height ListView instead of touching the
	// window's own height, so it never hits that problem.
	readonly property int visibleNetworkRows: 6
	readonly property int networkListHeight: visibleNetworkRows * rowHeight + Math.max(0, visibleNetworkRows - 1) * rowSpacing

	implicitWidth: 420
	implicitHeight: contentMargin * 2 + headerColumn.height + contentSpacing + dividerHeight + contentSpacing + networksLabel.height + contentSpacing + networkListHeight
	color: colors.base

	// Catppuccin Macchiato, duplicated by hand -- see the same note in
	// ../audio/shell.qml for why this isn't a shared import.
	QtObject {
		id: colors
		readonly property color base: "#24273a"
		readonly property color text: "#cad3f5"
		readonly property color subtext0: "#a5adcb"
		readonly property color surface0: "#363a4f"
		readonly property color mauve: "#c6a0f6"
		readonly property color green: "#a6da95"
		readonly property color red: "#ed8796"
	}

	readonly property bool backendAvailable: Networking.backend === NetworkBackendType.NetworkManager
	readonly property bool hardwareEnabled: Networking.wifiHardwareEnabled
	readonly property var networkDevices: Networking.devices ? Networking.devices.values : []
	readonly property var wifiDevice: {
		for (const d of panel.networkDevices)
			if (d && d.type === DeviceType.Wifi)
				return d;
		return null;
	}
	readonly property var wifiNetworkObjects: panel.wifiDevice && panel.wifiDevice.networks ? panel.wifiDevice.networks.values : []

	// Plain data, not live WifiNetwork objects -- NetworkManager scan churn
	// can destroy/replace a WifiNetwork while a delegate built from it is
	// still incubating, which is a real segfault in quickshell's
	// wrap_slowPath (confirmed against this same Quickshell.Networking API
	// in ~/dev/misc/omarchy's network panel, which hit it and switched to
	// exactly this primitives-only-in-the-model shape). Anything that needs
	// the live object (connect/forget/watch for failure) resolves it fresh
	// by ssid right when it's needed via networkForSsid() instead of
	// holding onto one.
	property var networkRows: []
	property string passwordSsid: ""
	property string passwordText: ""
	property string passwordError: ""
	property string connectingSsid: ""
	property var pendingConnectNetwork: null

	readonly property var connectedRow: panel.networkRows.find(r => r.connected) || null

	readonly property string statusMessage: {
		if (!panel.backendAvailable)
			return "NetworkManager unavailable";
		if (!panel.hardwareEnabled)
			return "Wi-Fi hardware disabled";
		if (!panel.wifiDevice)
			return "No Wi-Fi device found";
		return "";
	}

	function wifiIcon(strength) {
		// Same 5-level glyph set as waybar's network module
		// (format-icons), weakest to strongest, so the panel and the bar
		// icon agree.
		const icons = ["󰤯", "󰤟", "󰤢", "󰤥", "󰤨"];
		const index = Math.max(0, Math.min(4, Math.ceil(strength / 20) - 1));
		return icons[index];
	}

	function requiresCredentials(security) {
		return security !== WifiSecurityType.Open && security !== WifiSecurityType.Owe;
	}

	function wifiRow(net) {
		return {
			ssid: net.name || "",
			connected: !!net.connected,
			known: !!net.known,
			signal: Math.round((net.signalStrength || 0) * 100),
			security: net.security
		};
	}

	function sortNetworks(rows) {
		const sorted = rows.slice();
		sorted.sort((a, b) => {
			if (a.connected !== b.connected)
				return a.connected ? -1 : 1;
			if (a.known !== b.known)
				return a.known ? -1 : 1;
			return b.signal - a.signal;
		});
		return sorted;
	}

	function refreshNetworks() {
		const nets = panel.wifiNetworkObjects || [];
		panel.networkRows = panel.sortNetworks(nets.map(panel.wifiRow));
	}

	function networkForSsid(ssid) {
		for (const n of panel.wifiNetworkObjects)
			if (n && n.name === ssid)
				return n;
		return null;
	}

	function openPasswordPrompt(ssid) {
		panel.passwordSsid = panel.passwordSsid === ssid ? "" : ssid;
		panel.passwordText = "";
		panel.passwordError = "";
	}

	function selectNetwork(row) {
		if (row.connected)
			return;
		if (panel.requiresCredentials(row.security) && !row.known) {
			panel.openPasswordPrompt(row.ssid);
			return;
		}
		panel.beginConnect(row.ssid, net => net.connect());
	}

	function submitPassword() {
		if (panel.passwordText.length === 0)
			return;
		const ssid = panel.passwordSsid;
		const pw = panel.passwordText;
		panel.beginConnect(ssid, net => net.connectWithPsk(pw));
	}

	// Tracked by ssid, not the live object -- see the networkRows note
	// above for why the model itself never holds one.
	function beginConnect(ssid, action) {
		const net = panel.networkForSsid(ssid);
		if (!net)
			return;
		panel.passwordError = "";
		panel.connectingSsid = ssid;
		panel.pendingConnectNetwork = net;
		action(net);
	}

	function forgetRow(row) {
		const net = panel.networkForSsid(row.ssid);
		if (net)
			net.forget();
	}

	function toggleWifi() {
		Networking.wifiEnabled = !Networking.wifiEnabled;
	}

	onWifiNetworkObjectsChanged: panel.refreshNetworks()
	onWifiDeviceChanged: if (panel.wifiDevice)
		panel.wifiDevice.scannerEnabled = true

	Component.onCompleted: {
		if (panel.wifiDevice)
			panel.wifiDevice.scannerEnabled = true;
		panel.refreshNetworks();
	}

	// Watches whichever network a connect attempt is currently in flight
	// for. Connections.target is live (same pattern as ../audio/shell.qml's
	// default-sink watcher) so reassigning pendingConnectNetwork in
	// beginConnect() above retargets this cleanly -- only ever one live
	// object referenced at a time, resolved right when it's needed.
	Connections {
		target: panel.pendingConnectNetwork

		function onConnectedChanged() {
			if (panel.pendingConnectNetwork && panel.pendingConnectNetwork.connected) {
				panel.passwordSsid = "";
				panel.passwordText = "";
				panel.connectingSsid = "";
				panel.pendingConnectNetwork = null;
			}
		}

		function onConnectionFailed(reason) {
			panel.connectingSsid = "";
			panel.passwordError = reason === ConnectionFailReason.NoSecrets || reason === ConnectionFailReason.WifiAuthTimeout ? "Wrong password" : "Couldn't connect";
			panel.pendingConnectNetwork = null;
		}
	}

	Component {
		id: networkDelegate

		Rectangle {
			id: row
			required property var modelData
			property bool hovered: false
			readonly property bool isPasswordOpen: panel.passwordSsid === modelData.ssid
			readonly property bool isConnecting: panel.connectingSsid === modelData.ssid
			readonly property bool needsPassword: panel.requiresCredentials(modelData.security) && !modelData.known
			readonly property bool canForget: modelData.known && !modelData.connected

			width: ListView.view.width - panel.scrollGutter
			height: panel.rowHeight + (isPasswordOpen ? panel.passwordRowHeight + panel.rowSpacing : 0)
			radius: 6
			color: modelData.connected ? Qt.alpha(colors.mauve, hovered ? 0.35 : 0.25) : (hovered ? colors.surface0 : "transparent")
			clip: true

			Behavior on height {
				NumberAnimation { duration: 120 }
			}
			Behavior on color {
				ColorAnimation { duration: 100 }
			}

			ColumnLayout {
				width: parent.width
				spacing: panel.rowSpacing

				RowLayout {
					Layout.fillWidth: true
					Layout.preferredHeight: panel.rowHeight
					Layout.leftMargin: 10
					Layout.rightMargin: 10
					spacing: 10

					Text {
						text: panel.wifiIcon(modelData.signal)
						color: modelData.connected ? colors.mauve : colors.text
						font.pixelSize: 14
						font.family: "IosevkaTerm Nerd Font"
					}

					Text {
						Layout.fillWidth: true
						text: modelData.ssid
						color: colors.text
						font.pixelSize: 14
						elide: Text.ElideRight
					}

					Text {
						visible: row.isConnecting
						text: "Connecting…"
						color: colors.subtext0
						font.pixelSize: 12
					}

					Text {
						// U+F023 = Font Awesome "lock". Literal glyphs
						// (typed directly as UTF-8) get silently dropped
						// somewhere in this tool's edit/write path -- \u
						// escapes survive because they're plain ASCII in
						// the source text. Same issue and workaround as
						// ../audio/shell.qml's check glyph.
						visible: row.needsPassword && !row.isConnecting
						text: "\uf023"
						color: colors.subtext0
						font.pixelSize: 13
						font.family: "IosevkaTerm Nerd Font"
					}

					Text {
						text: modelData.connected ? "\uf00c" : ""
						color: colors.mauve
						font.pixelSize: 14
						font.family: "IosevkaTerm Nerd Font"
					}

					Text {
						// U+F1F8 = Font Awesome "trash". Only shown on
						// hover so a known-but-unused network's row isn't
						// permanently cluttered with a delete affordance.
						visible: row.canForget && row.hovered && !row.isConnecting
						text: "\uf1f8"
						color: colors.red
						font.pixelSize: 13
						font.family: "IosevkaTerm Nerd Font"

						MouseArea {
							anchors.fill: parent
							anchors.margins: -4
							cursorShape: Qt.PointingHandCursor
							onClicked: panel.forgetRow(modelData)
						}
					}
				}

				RowLayout {
					visible: row.isPasswordOpen
					Layout.fillWidth: true
					Layout.preferredHeight: panel.passwordRowHeight
					Layout.leftMargin: 10
					Layout.rightMargin: 10
					spacing: 8

					TextField {
						id: passwordField
						Layout.fillWidth: true
						placeholderText: panel.passwordError || "Password"
						placeholderTextColor: panel.passwordError ? colors.red : colors.subtext0
						echoMode: TextInput.Password
						color: colors.text
						font.pixelSize: 13
						padding: 6

						background: Rectangle {
							color: colors.base
							radius: 6
							border.color: panel.passwordError ? colors.red : colors.surface0
							border.width: 1
						}

						onTextChanged: panel.passwordText = text
						onVisibleChanged: if (visible)
							forceActiveFocus()

						Keys.onReturnPressed: panel.submitPassword()
						Keys.onEnterPressed: panel.submitPassword()
						Keys.onEscapePressed: event => {
							event.accepted = true;
							panel.openPasswordPrompt(modelData.ssid);
						}
					}

					Text {
						// Doubles as the connect button.
						text: "\uf00c"
						color: panel.passwordText.length > 0 ? colors.green : colors.subtext0
						font.pixelSize: 16
						font.family: "IosevkaTerm Nerd Font"

						MouseArea {
							anchors.fill: parent
							anchors.margins: -6
							cursorShape: Qt.PointingHandCursor
							enabled: panel.passwordText.length > 0
							onClicked: panel.submitPassword()
						}
					}
				}
			}

			MouseArea {
				anchors.fill: parent
				anchors.bottomMargin: row.isPasswordOpen ? panel.passwordRowHeight + panel.rowSpacing : 0
				hoverEnabled: true
				cursorShape: Qt.PointingHandCursor
				onEntered: row.hovered = true
				onExited: row.hovered = false
				onClicked: panel.selectNetwork(modelData)
			}
		}
	}

	ColumnLayout {
		id: content
		anchors.fill: parent
		anchors.margins: panel.contentMargin
		spacing: panel.contentSpacing
		focus: true

		Keys.onEscapePressed: Qt.quit()
		Keys.onPressed: event => {
			if (event.text === "q") {
				event.accepted = true;
				Qt.quit();
			}
		}

		Component.onCompleted: forceActiveFocus()

		ColumnLayout {
			id: headerColumn
			Layout.fillWidth: true
			spacing: 4

			RowLayout {
				Layout.fillWidth: true
				spacing: 8

				Text {
					text: Networking.wifiEnabled ? panel.wifiIcon(panel.connectedRow ? panel.connectedRow.signal : 100) : "󰤮"
					color: colors.text
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}

				Text {
					Layout.fillWidth: true
					text: "Wi-Fi"
					color: colors.text
					font.pixelSize: 14
				}

				// Master on/off switch -- a bare status icon here (the
				// original design) doubled as the toggle but didn't read
				// as one, so this is a deliberately unambiguous switch
				// affordance instead.
				Rectangle {
					id: wifiSwitch
					implicitWidth: 34
					implicitHeight: 18
					radius: height / 2
					color: Networking.wifiEnabled ? colors.mauve : colors.surface0

					Behavior on color {
						ColorAnimation { duration: 120 }
					}

					Rectangle {
						width: 14
						height: 14
						radius: 7
						color: colors.base
						anchors.verticalCenter: parent.verticalCenter
						x: Networking.wifiEnabled ? parent.width - width - 2 : 2

						Behavior on x {
							NumberAnimation { duration: 120; easing.type: Easing.OutQuad }
						}
					}

					MouseArea {
						anchors.fill: parent
						anchors.margins: -6
						cursorShape: Qt.PointingHandCursor
						onClicked: panel.toggleWifi()
					}
				}
			}

			RowLayout {
				Layout.fillWidth: true
				spacing: 8

				Text {
					Layout.fillWidth: true
					text: !Networking.wifiEnabled ? "Off" : (panel.statusMessage || (panel.connectedRow ? panel.connectedRow.ssid : "Not Connected"))
					color: colors.subtext0
					font.pixelSize: 12
					elide: Text.ElideRight
				}

				Text {
					visible: Networking.wifiEnabled && panel.connectedRow !== null
					text: panel.connectedRow ? panel.connectedRow.signal + "%" : ""
					color: colors.subtext0
					font.pixelSize: 12
				}
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.dividerHeight
			color: colors.surface0
		}

		Text {
			id: networksLabel
			text: "Networks"
			color: colors.subtext0
			font.pixelSize: 12
		}

		Text {
			visible: !networkList.visible
			Layout.fillWidth: true
			Layout.preferredHeight: panel.networkListHeight
			text: !Networking.wifiEnabled ? "Wi-Fi is off" : panel.statusMessage
			color: colors.subtext0
			font.pixelSize: 13
			horizontalAlignment: Text.AlignHCenter
			verticalAlignment: Text.AlignVCenter
		}

		ListView {
			id: networkList
			visible: Networking.wifiEnabled && panel.statusMessage === ""
			Layout.fillWidth: true
			Layout.preferredHeight: panel.networkListHeight
			clip: true
			spacing: panel.rowSpacing
			model: panel.networkRows
			delegate: networkDelegate

			ScrollBar.vertical: ScrollBar {
				policy: ScrollBar.AsNeeded
				contentItem: Rectangle {
					implicitWidth: 4
					radius: 2
					color: colors.mauve
					opacity: 0.6
				}
			}
		}
	}
}
