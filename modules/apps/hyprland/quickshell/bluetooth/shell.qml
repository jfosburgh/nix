import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Bluetooth

// Bluetooth quick panel, opened from waybar's bluetooth module (on-click:
// `qs -c bluetooth`). Built on Quickshell's native BlueZ binding
// (Quickshell.Bluetooth) rather than shelling out to bluetoothctl -- same
// reasoning as ../audio/shell.qml (Pipewire) and ../wifi/shell.qml
// (Networking).
//
// Unlike wifi/audio, Bluetooth is multi-connect (a mouse and a keyboard can
// both be connected at once), so clicking a row toggles that specific
// device rather than implicitly dropping whatever else was connected --
// see selectDevice() below.
//
// title is a distinct hook for conf/rules.lua to position this window (top
// right, under waybar), the same mechanism ../audio and ../wifi use.
FloatingWindow {
	id: panel
	title: "quickshell-bluetooth"

	// See ../audio/shell.qml's identical note: without this, closing the
	// window (defocus, or `quickshell-toggle` clicking the bar icon again)
	// doesn't end the process -- Quickshell expects to keep running as a
	// shell with zero or more windows otherwise. Especially important
	// here since a live device-list binding keeps a BlueZ discovery
	// session going for as long as the process runs.
	onClosed: Qt.quit()

	readonly property int contentMargin: 10
	readonly property int contentSpacing: 6
	readonly property int rowHeight: 32
	readonly property int dividerHeight: 1
	readonly property int rowSpacing: 2
	readonly property int scrollGutter: 10
	// See ../audio/shell.qml's identical note: a FloatingWindow's
	// implicitHeight is only applied once at creation, so this is sized for
	// a fixed number of rows up front and the list scrolls past that
	// rather than growing to fit.
	readonly property int visibleDeviceRows: 6
	readonly property int deviceListHeight: visibleDeviceRows * rowHeight + Math.max(0, visibleDeviceRows - 1) * rowSpacing

	implicitWidth: 420
	implicitHeight: contentMargin * 2 + headerColumn.height + contentSpacing + dividerHeight + contentSpacing + devicesLabel.height + contentSpacing + deviceListHeight
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
		readonly property color red: "#ed8796"
	}

	readonly property var adapter: Bluetooth.defaultAdapter
	readonly property bool adapterAvailable: panel.adapter !== null
	readonly property var deviceObjects: panel.adapter && panel.adapter.devices ? panel.adapter.devices.values : []

	// Plain data, not live BluetoothDevice objects -- see ../wifi/shell.qml's
	// identical note on networkRows: BlueZ discovery/unpair churn can
	// destroy a device object while a delegate built from it is still
	// incubating, which is the same quickshell wrap_slowPath segfault
	// ~/dev/misc/omarchy's bluetooth panel documents hitting against this
	// same Quickshell.Bluetooth API. Anything that needs the live object
	// resolves it fresh by address via deviceForAddress() instead of
	// holding onto one.
	property var deviceRows: []
	property string pendingAddress: ""
	property string pendingAction: ""
	property var pendingDevice: null

	readonly property var connectedRows: panel.deviceRows.filter(r => r.connected)

	readonly property string statusMessage: {
		if (!panel.adapterAvailable)
			return "No Bluetooth adapter found";
		if (panel.adapter.state === BluetoothAdapterState.Blocked)
			return "Bluetooth blocked";
		return "";
	}

	// BlueZ discovery surfaces devices before it has resolved a real name
	// for them (bare UUID or MAC address as the "name") -- filtered out
	// the same way ~/dev/misc/omarchy's hasHumanName() does, so the list
	// doesn't fill up with unidentifiable noise while scanning.
	function isUuidLike(value) {
		return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) || /^[0-9a-f]{32}$/i.test(value);
	}

	function isAddressLike(value) {
		return /^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$/i.test(value);
	}

	function hasHumanName(label) {
		return label !== "" && !panel.isUuidLike(label) && !panel.isAddressLike(label);
	}

	function deviceRow(d) {
		const label = (d.deviceName || d.name || "").trim();
		const connected = !!d.connected;
		const paired = !!(d.paired || d.bonded || d.trusted);
		return {
			address: d.address || "",
			name: label,
			connected: connected,
			paired: paired,
			pairing: !!d.pairing,
			batteryAvailable: !!d.batteryAvailable,
			battery: d.battery || 0,
			// Drives the ListView section divider below, splitting saved
			// (connected or paired) devices from ones only ever seen
			// during a scan.
			group: connected || paired ? "saved" : "new"
		};
	}

	function sortDevices(rows) {
		const sorted = rows.slice();
		sorted.sort((a, b) => {
			if (a.connected !== b.connected)
				return a.connected ? -1 : 1;
			if (a.paired !== b.paired)
				return a.paired ? -1 : 1;
			return a.name.localeCompare(b.name);
		});
		return sorted;
	}

	function refreshDevices() {
		const devs = panel.deviceObjects || [];
		const rows = [];
		for (const d of devs) {
			if (!d)
				continue;
			const row = panel.deviceRow(d);
			// Discovered-but-unpaired devices only belong in the list
			// while actively scanning -- otherwise every device that's
			// ever drifted into range lingers here forever.
			if (!row.paired && !row.connected && !(panel.adapter && panel.adapter.discovering))
				continue;
			if (!panel.hasHumanName(row.name))
				continue;
			rows.push(row);
		}
		panel.deviceRows = panel.sortDevices(rows);
	}

	function deviceForAddress(address) {
		for (const d of panel.deviceObjects)
			if (d && d.address === address)
				return d;
		return null;
	}

	function selectDevice(row) {
		const device = panel.deviceForAddress(row.address);
		if (!device)
			return;
		panel.pendingAddress = row.address;
		panel.pendingDevice = device;
		if (row.connected) {
			panel.pendingAction = "disconnecting";
			device.disconnect();
		} else if (row.paired) {
			panel.pendingAction = "connecting";
			device.connect();
		} else {
			panel.pendingAction = "pairing";
			device.pair();
		}
		pendingTimeout.restart();
	}

	function forgetRow(row) {
		const device = panel.deviceForAddress(row.address);
		if (device)
			device.forget();
	}

	function toggleBluetooth() {
		if (panel.adapter)
			panel.adapter.enabled = !panel.adapter.enabled;
	}

	function toggleScan() {
		if (panel.adapter)
			panel.adapter.discovering = !panel.adapter.discovering;
	}

	function clearPending() {
		panel.pendingAddress = "";
		panel.pendingAction = "";
		panel.pendingDevice = null;
		pendingTimeout.stop();
	}

	onDeviceObjectsChanged: panel.refreshDevices()

	Component.onCompleted: panel.refreshDevices()

	// BlueZ has no "this specific action failed" signal on the device
	// object (unlike Quickshell.Networking's Network.connectionFailed), so
	// this is a blunt safety net: if neither connectedChanged nor
	// pairedChanged fires within a reasonable window, drop the pending
	// state so the row doesn't say "Connecting..." forever.
	Timer {
		id: pendingTimeout
		interval: 15000
		repeat: false
		onTriggered: panel.clearPending()
	}

	// Connections.target is live (same pattern as ../audio and
	// ../wifi's watchers) so reassigning pendingDevice in selectDevice()
	// above retargets this cleanly -- only ever one live object
	// referenced at a time, resolved right when it's needed.
	Connections {
		target: panel.pendingDevice

		function onConnectedChanged() {
			panel.clearPending();
		}

		function onPairedChanged() {
			if (panel.pendingDevice && panel.pendingDevice.paired && panel.pendingAction === "pairing")
				panel.clearPending();
		}
	}

	Component {
		id: deviceDelegate

		Rectangle {
			id: row
			required property var modelData
			property bool hovered: false
			readonly property bool isPending: panel.pendingAddress === modelData.address
			readonly property bool canForget: modelData.paired && !modelData.connected

			width: ListView.view.width - panel.scrollGutter
			height: panel.rowHeight
			radius: 6
			color: modelData.connected ? Qt.alpha(colors.mauve, hovered ? 0.35 : 0.25) : (hovered ? colors.surface0 : "transparent")

			Behavior on color {
				ColorAnimation { duration: 100 }
			}

			RowLayout {
				anchors.fill: parent
				anchors.leftMargin: 10
				anchors.rightMargin: 10
				spacing: 10

				Text {
					text: "\uf294"
					color: modelData.connected ? colors.mauve : colors.text
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}

				Text {
					Layout.fillWidth: true
					text: modelData.name
					color: colors.text
					font.pixelSize: 14
					elide: Text.ElideRight
				}

				Text {
					visible: modelData.batteryAvailable && !row.isPending
					text: Math.round(modelData.battery * 100) + "%"
					color: colors.subtext0
					font.pixelSize: 12
				}

				Text {
					visible: row.isPending
					text: panel.pendingAction === "pairing" ? "Pairing…" : panel.pendingAction === "connecting" ? "Connecting…" : "Disconnecting…"
					color: colors.subtext0
					font.pixelSize: 12
				}

				Text {
					visible: modelData.connected && !row.isPending
					text: "\uf00c"
					color: colors.mauve
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}

				Text {
					// Only shown on hover so a known-but-unused device's
					// row isn't permanently cluttered with a delete
					// affordance.
					visible: row.canForget && row.hovered && !row.isPending
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

			MouseArea {
				anchors.fill: parent
				hoverEnabled: true
				cursorShape: Qt.PointingHandCursor
				onEntered: row.hovered = true
				onExited: row.hovered = false
				onClicked: panel.selectDevice(modelData)
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
					text: panel.adapterAvailable && panel.adapter.enabled ? "\uf294" : "\udb80\udcb2"
					color: colors.text
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}

				Text {
					Layout.fillWidth: true
					text: "Bluetooth"
					color: colors.text
					font.pixelSize: 14
				}

				// Master on/off switch -- same affordance as
				// ../wifi/shell.qml's, for the same reason: a bare status
				// icon didn't read as a toggle.
				Rectangle {
					implicitWidth: 34
					implicitHeight: 18
					radius: height / 2
					color: panel.adapterAvailable && panel.adapter.enabled ? colors.mauve : colors.surface0

					Behavior on color {
						ColorAnimation { duration: 120 }
					}

					Rectangle {
						width: 14
						height: 14
						radius: 7
						color: colors.base
						anchors.verticalCenter: parent.verticalCenter
						x: panel.adapterAvailable && panel.adapter.enabled ? parent.width - width - 2 : 2

						Behavior on x {
							NumberAnimation { duration: 120; easing.type: Easing.OutQuad }
						}
					}

					MouseArea {
						anchors.fill: parent
						anchors.margins: -6
						cursorShape: Qt.PointingHandCursor
						enabled: panel.adapterAvailable
						onClicked: panel.toggleBluetooth()
					}
				}
			}

			RowLayout {
				Layout.fillWidth: true
				spacing: 8

				Text {
					Layout.fillWidth: true
					text: !panel.adapterAvailable || !panel.adapter.enabled ? "Off" : (panel.statusMessage || (panel.connectedRows.length > 0 ? panel.connectedRows.map(r => r.name).join(", ") : "Not Connected"))
					color: colors.subtext0
					font.pixelSize: 12
					elide: Text.ElideRight
				}

				Text {
					visible: panel.adapterAvailable && panel.adapter.enabled
					text: panel.adapter && panel.adapter.discovering ? "Scanning…" : "Scan"
					color: colors.mauve
					font.pixelSize: 12

					MouseArea {
						anchors.fill: parent
						anchors.margins: -4
						cursorShape: Qt.PointingHandCursor
						onClicked: panel.toggleScan()
					}
				}
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.dividerHeight
			color: colors.surface0
		}

		Text {
			id: devicesLabel
			text: "Devices"
			color: colors.subtext0
			font.pixelSize: 12
		}

		Text {
			visible: !deviceList.visible
			Layout.fillWidth: true
			Layout.preferredHeight: panel.deviceListHeight
			text: !panel.adapterAvailable || !panel.adapter.enabled ? (panel.statusMessage || "Bluetooth is off") : "No devices"
			color: colors.subtext0
			font.pixelSize: 13
			horizontalAlignment: Text.AlignHCenter
			verticalAlignment: Text.AlignVCenter
		}

		ListView {
			id: deviceList
			visible: panel.adapterAvailable && panel.adapter.enabled && panel.statusMessage === "" && panel.deviceRows.length > 0
			Layout.fillWidth: true
			Layout.preferredHeight: panel.deviceListHeight
			clip: true
			spacing: panel.rowSpacing
			model: panel.deviceRows
			delegate: deviceDelegate

			// Rows are pre-sorted saved-then-new (see sortDevices), so a
			// section change only ever happens once, right where a new
			// (never-paired) device first appears -- this draws a divider
			// there instead of the "New" tag this used to be, and draws
			// nothing above the very first row.
			section.property: "group"
			section.delegate: Item {
				width: deviceList.width - panel.scrollGutter
				height: section === "new" ? panel.dividerHeight + panel.rowSpacing * 2 : 0

				Rectangle {
					visible: section === "new"
					anchors.left: parent.left
					anchors.right: parent.right
					anchors.verticalCenter: parent.verticalCenter
					height: panel.dividerHeight
					color: colors.surface0
				}
			}

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
