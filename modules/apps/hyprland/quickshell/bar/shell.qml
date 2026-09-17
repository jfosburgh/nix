import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Services.Pipewire
import Quickshell.Services.UPower
import Quickshell.Networking
import Quickshell.Bluetooth

// The top bar, replacing waybar (see ../../waybar, now removed). One
// PanelWindow per output via the Variants below -- each instance resolves
// its own HyprlandMonitor (monitorFor) so workspace numbers reflect that
// output specifically, matching what waybar's hyprland/workspaces module
// did per-bar.
//
// This is the one long-lived quickshell surface in this config (autostart.lua
// runs `qs -c bar` directly, no toggle wrapper) -- everything else under
// ../ is a short-lived popup spawned per invocation via ../scripts/quickshell-toggle.
// Each right-side module here shells out to that same script on click so
// clicking twice toggles the popup shut, exactly like waybar's on-click did.
//
// Status icons reimplement the same native-binding choice ../audio, ../wifi,
// ../bluetooth and ../power already made (Pipewire/Networking/Bluetooth/UPower
// over CLI scraping) rather than duplicating their logic through a shared
// import -- see ../audio/shell.qml's note on why colors aren't shared either.
Variants {
	model: Quickshell.screens

	PanelWindow {
		id: bar
		required property var modelData
		screen: modelData

		anchors.top: true
		anchors.left: true
		anchors.right: true
		margins.top: 4
		margins.left: 4
		margins.right: 4

		implicitHeight: 26
		// Not implicitHeight + margins.top -- Hyprland already adds
		// margins.top on top of whatever exclusiveZone reports (verified
		// live: with that added in here, hyprctl monitors reported
		// reserved=34 for a 26px bar with a 4px top margin, and windows sat
		// 6px below the bar instead of the intended 4px gaps_out).
		exclusiveZone: implicitHeight
		color: "transparent"

		WlrLayershell.layer: WlrLayer.Top
		WlrLayershell.namespace: "quickshell:bar"

		// Catppuccin Macchiato, duplicated by hand -- see ../audio/shell.qml's
		// note for why this isn't a shared import.
		QtObject {
			id: colors
			readonly property color base: "#24273a"
			readonly property color surface0: "#363a4f"
			readonly property color surface2: "#5b6078"
			readonly property color text: "#cad3f5"
			readonly property color subtext0: "#a5adcb"
			readonly property color mauve: "#c6a0f6"
			readonly property color green: "#a6da95"
			readonly property color yellow: "#eed49f"
			readonly property color peach: "#f5a97f"
			readonly property color red: "#ed8796"
		}

		readonly property var monitor: Hyprland.monitorFor(bar.screen)
		readonly property var workspaceObjects: Hyprland.workspaces ? [...Hyprland.workspaces.values] : []
		readonly property var monitorWorkspaces: bar.workspaceObjects.filter(w => w.monitor === bar.monitor)

		// Slots run 1..slotCount, not a fixed 1..9 -- the highest id worth
		// showing is whatever's occupied or currently focused, so an idle
		// monitor shows just "1" and windows on 1 and 4 show "1 2 3 4" (2
		// and 3 greyed out as empty placeholders to reach 4, not because
		// they're expected to exist beyond that).
		readonly property int slotCount: {
			let highest = 1;
			for (const w of bar.monitorWorkspaces)
				if ((w.active || w.toplevels.values.length > 0) && w.id > highest)
					highest = w.id;
			return highest;
		}

		function workspaceFor(id) {
			return bar.monitorWorkspaces.find(w => w.id === id) || null;
		}

		function activateWorkspace(id) {
			Hyprland.dispatch("workspace " + id);
		}

		function openPopup(name) {
			Quickshell.execDetached(["quickshell-toggle", name]);
		}

		Rectangle {
			id: background
			anchors.fill: parent
			radius: 6
			color: Qt.alpha(colors.base, 0.75)
			border.color: colors.surface2
			border.width: 2

			Item {
				anchors.fill: parent
				anchors.leftMargin: 8
				anchors.rightMargin: 8
				// This font's glyphs sit slightly above true vertical center
				// of their own line box (ascent/descent aren't symmetric),
				// so everything centered against this Item read about a
				// pixel high -- confirmed by measuring ink rows in a bar
				// screenshot. Nudging the whole content area down corrects
				// it without picking apart every individual Text's
				// centering mechanism (anchors.centerIn here, RowLayout's
				// own cross-axis centering on the right side).
				anchors.topMargin: 1

				RowLayout {
					id: leftRow
					anchors.left: parent.left
					anchors.verticalCenter: parent.verticalCenter
					spacing: 0

					Repeater {
						model: bar.slotCount

						Rectangle {
							id: wsButton
							required property int index
							readonly property int wsId: index + 1
							readonly property var ws: bar.workspaceFor(wsId)
							readonly property bool active: ws !== null && ws.active
							readonly property bool empty: ws === null || ws.toplevels.values.length === 0
							property bool hovered: false

							implicitWidth: wsLabel.implicitWidth + 12
							implicitHeight: 20
							radius: 5
							color: !active && hovered ? colors.surface0 : "transparent"

							Behavior on color {
								ColorAnimation { duration: 100 }
							}

							// Active workspace swaps its number for waybar's
							// own format-icons.active glyph (U+F14FB,
							// md-square_rounded) instead of a background pill
							// -- an earlier attempt at this looked like the
							// glyph was tofu (blank), but that was this same
							// mauve-on-mauve: the glyph rendered fine, just
							// camouflaged against a same-color pill behind
							// it. Confirmed live against a plain background.
							Text {
								id: wsLabel
								anchors.centerIn: parent
								text: wsButton.active ? "󱓻" : String(wsButton.wsId)
								color: colors.text
								opacity: wsButton.empty && !wsButton.active ? 0.5 : 1
								font.pixelSize: 14
								// Mono even for the active-state icon (which
								// renders smaller here than it does using the
								// regular cut elsewhere in this bar) so this
								// slot's width never changes between the two
								// -- workspace numbers visibly shifting width
								// as you switch mattered more than the
								// active glyph's size.
								font.family: "IosevkaTerm Nerd Font Mono"
							}

							MouseArea {
								anchors.fill: parent
								hoverEnabled: true
								cursorShape: Qt.PointingHandCursor
								onEntered: wsButton.hovered = true
								onExited: wsButton.hovered = false
								onClicked: bar.activateWorkspace(wsButton.wsId)
							}
						}
					}
				}

				Text {
					id: clockText
					anchors.centerIn: parent
					color: colors.text
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font Mono"

					function refresh() {
						clockText.text = Qt.formatDateTime(new Date(), "dddd HH:mm");
					}

					Component.onCompleted: clockText.refresh()

					Timer {
						interval: 1000
						running: true
						repeat: true
						onTriggered: clockText.refresh()
					}
				}

				RowLayout {
					id: rightRow
					anchors.right: parent.right
					anchors.verticalCenter: parent.verticalCenter
					spacing: 10

					// --- Bluetooth
					Text {
						readonly property var adapter: Bluetooth.defaultAdapter
						readonly property bool connected: adapter && adapter.devices ? [...adapter.devices.values].some(d => d.connected) : false

						text: !adapter || !adapter.enabled ? "󰂲" : ""
						color: connected ? colors.mauve : colors.text
						font.pixelSize: 14
						font.family: "IosevkaTerm Nerd Font"

						MouseArea {
							anchors.fill: parent
							anchors.margins: -4
							cursorShape: Qt.PointingHandCursor
							onClicked: bar.openPopup("bluetooth")
						}
					}

					// --- Network. Same device-classification approach as
					// ../wifi/shell.qml: DeviceType.Wifi/Wired straight off
					// Quickshell.Networking rather than scraping nmcli.
					Text {
						readonly property var devices: Networking.devices ? [...Networking.devices.values] : []
						readonly property var wifiDevice: devices.find(d => d.type === DeviceType.Wifi) || null
						readonly property var wiredDevice: devices.find(d => d.type === DeviceType.Wired) || null
						readonly property var activeWifiNetwork: wifiDevice && wifiDevice.networks ? [...wifiDevice.networks.values].find(n => n.connected) : null

						readonly property string icon: {
							if (wiredDevice && wiredDevice.hasLink)
								return "󰀂";
							if (!Networking.wifiEnabled || !wifiDevice || !activeWifiNetwork)
								return "󰤮";
							// Same 5-level glyph set waybar's network module used
							// (format-icons) and ../wifi/shell.qml still uses.
							const icons = ["󰤯", "󰤟", "󰤢", "󰤥", "󰤨"];
							const index = Math.max(0, Math.min(4, Math.ceil(activeWifiNetwork.signalStrength * 100 / 20) - 1));
							return icons[index];
						}

						text: icon
						color: colors.text
						font.pixelSize: 14
						font.family: "IosevkaTerm Nerd Font"

						MouseArea {
							anchors.fill: parent
							anchors.margins: -4
							cursorShape: Qt.PointingHandCursor
							onClicked: bar.openPopup("wifi")
						}
					}

					// --- Volume. Native Pipewire binding, same reasoning as
					// ../audio/shell.qml -- scroll adjusts volume directly,
					// right-click toggles mute, both without shelling out.
					// volumePercent/muted are synced into plain properties via
					// sync() rather than bound straight to
					// Pipewire.defaultAudioSink.audio.volume/muted -- a direct
					// binding doesn't pick up external changes (hardware keys,
					// swayosd, another client), same reason
					// ../audio/shell.qml's syncFromDefaultSink() exists
					// instead of a plain binding there.
					Text {
						id: volumeIcon
						property real volumePercent: 0
						property bool muted: false

						function sync() {
							const audio = Pipewire.defaultAudioSink ? Pipewire.defaultAudioSink.audio : null;
							if (!audio)
								return;
							volumeIcon.volumePercent = Math.round(audio.volume * 100);
							volumeIcon.muted = audio.muted;
						}

						// Quickshell only subscribes to a PwNode's live
						// property updates (volume/muted included) once
						// something actively tracks it -- confirmed live:
						// without this, audio.volume read back as a stale 0
						// at startup and never changed afterward regardless
						// of Connections below. ../audio/shell.qml gets this
						// for free from its PwNodePeakMonitor on the same
						// node; this bar has no meter, so it needs its own
						// tracker.
						PwObjectTracker {
							objects: Pipewire.defaultAudioSink ? [Pipewire.defaultAudioSink] : []
						}

						text: muted ? "" : volumePercent < 1 ? "" : volumePercent < 50 ? "" : ""
						color: colors.text
						font.pixelSize: 14
						font.family: "IosevkaTerm Nerd Font"

						Component.onCompleted: volumeIcon.sync()

						Connections {
							target: Pipewire

							function onDefaultAudioSinkChanged() {
								volumeIcon.sync();
							}
						}

						Connections {
							target: Pipewire.defaultAudioSink ? Pipewire.defaultAudioSink.audio : null

							function onVolumeChanged() {
								volumeIcon.sync();
							}
							function onMutedChanged() {
								volumeIcon.sync();
							}
						}

						MouseArea {
							anchors.fill: parent
							anchors.margins: -4
							cursorShape: Qt.PointingHandCursor
							acceptedButtons: Qt.LeftButton | Qt.RightButton
							onClicked: mouse => {
								const audio = Pipewire.defaultAudioSink ? Pipewire.defaultAudioSink.audio : null;
								if (mouse.button === Qt.RightButton) {
									if (audio)
										audio.muted = !audio.muted;
								} else {
									bar.openPopup("audio");
								}
							}
							onWheel: wheel => {
								const audio = Pipewire.defaultAudioSink ? Pipewire.defaultAudioSink.audio : null;
								if (!audio)
									return;
								const step = wheel.angleDelta.y > 0 ? 0.05 : -0.05;
								audio.volume = Math.max(0, Math.min(1, audio.volume + step));
							}
						}
					}

					// --- Battery
					Text {
						readonly property var device: UPower.displayDevice
						readonly property var chargingIcons: ["󰢜", "󰂆", "󰂇", "󰂈", "󰢝", "󰂉", "󰢞", "󰂊", "󰂋", "󰂅"]
						readonly property var dischargingIcons: ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
						readonly property bool charging: device && (device.state === UPowerDeviceState.Charging || device.state === UPowerDeviceState.PendingCharge || device.state === UPowerDeviceState.FullyCharged)
						readonly property int level: device ? Math.max(0, Math.min(9, Math.floor(device.percentage * 10))) : 9

						visible: device && device.isPresent
						text: charging ? chargingIcons[level] : dischargingIcons[level]
						color: device && !charging && device.percentage <= 0.1 ? colors.red : (device && !charging && device.percentage <= 0.2 ? colors.yellow : colors.text)
						font.pixelSize: 14
						font.family: "IosevkaTerm Nerd Font"

						MouseArea {
							anchors.fill: parent
							anchors.margins: -4
							cursorShape: Qt.PointingHandCursor
							onClicked: bar.openPopup("power")
						}
					}

					// --- Settings (night light + session actions)
					Text {
						text: "󰒓"
						color: colors.text
						font.pixelSize: 14
						font.family: "IosevkaTerm Nerd Font"

						MouseArea {
							anchors.fill: parent
							anchors.margins: -4
							cursorShape: Qt.PointingHandCursor
							onClicked: bar.openPopup("settings")
						}
					}
				}
			}
		}
	}
}
