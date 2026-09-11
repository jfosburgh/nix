import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower

// Power profile quick panel, opened from waybar's battery module (on-click:
// `quickshell-toggle power`). Built on Quickshell's native UPower binding
// (Quickshell.Services.UPower) rather than shelling out to
// powerprofilesctl -- same reasoning as ../audio, ../wifi, ../bluetooth.
//
// Unlike those, there's no list to scroll (exactly three profiles always
// exist) and nothing to toggle on/off, so this skips ListView/ScrollBar
// entirely in favor of a plain Repeater -- the row count and each row's
// height are constant regardless of which profile is active or whether
// Performance is available, so it never runs into the "window can't
// resize after creation" problem ../audio/shell.qml documents.
//
// title is a distinct hook for conf/rules.lua to position this window (top
// right, under waybar), the same mechanism the other panels use.
FloatingWindow {
	id: panel
	title: "quickshell-power"

	// See ../audio/shell.qml's identical note: without this, closing the
	// window (defocus, or `quickshell-toggle` clicking the bar icon again)
	// doesn't end the process -- Quickshell expects to keep running as a
	// shell with zero or more windows otherwise.
	onClosed: Qt.quit()

	readonly property int contentMargin: 10
	readonly property int contentSpacing: 6
	readonly property int rowHeight: 32
	readonly property int dividerHeight: 1
	readonly property int rowSpacing: 2
	readonly property int holdsRowHeight: 16

	readonly property int profileRowCount: 3
	readonly property int profileListHeight: profileRowCount * rowHeight + Math.max(0, profileRowCount - 1) * rowSpacing

	implicitWidth: 300
	implicitHeight: contentMargin * 2 + headerColumn.height + contentSpacing + dividerHeight + contentSpacing + profileLabel.height + contentSpacing + profileListHeight + contentSpacing + holdsRowHeight
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
	}

	// Same 10-step glyph sets waybar's battery module uses (format-icons),
	// so the panel's header icon matches the bar exactly.
	readonly property var chargingIcons: ["󰢜", "󰂆", "󰂇", "󰂈", "󰢝", "󰂉", "󰢞", "󰂊", "󰂋", "󰂅"]
	readonly property var dischargingIcons: ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]

	readonly property var profileOptions: [
		{ value: PowerProfile.PowerSaver, label: "Power Saver", icon: "󰌪" },
		{ value: PowerProfile.Balanced, label: "Balanced", icon: "󰊚" },
		{ value: PowerProfile.Performance, label: "Performance", icon: "󰓅" }
	]

	function batteryIcon() {
		const device = UPower.displayDevice;
		if (!device || !device.isPresent)
			return panel.dischargingIcons[9];
		const charging = device.state === UPowerDeviceState.Charging || device.state === UPowerDeviceState.PendingCharge || device.state === UPowerDeviceState.FullyCharged;
		const icons = charging ? panel.chargingIcons : panel.dischargingIcons;
		const index = Math.max(0, Math.min(9, Math.floor(device.percentage * 10)));
		return icons[index];
	}

	function formatDuration(seconds) {
		const total = Math.round(seconds / 60);
		const h = Math.floor(total / 60);
		const m = total % 60;
		return h > 0 ? h + "h " + m + "m" : m + "m";
	}

	function batteryStatusText() {
		const device = UPower.displayDevice;
		if (!device || !device.isPresent)
			return "No battery";
		if (device.state === UPowerDeviceState.FullyCharged)
			return "Fully charged";
		if (device.state === UPowerDeviceState.Charging || device.state === UPowerDeviceState.PendingCharge)
			return device.timeToFull > 0 ? panel.formatDuration(device.timeToFull) + " until full" : "Charging";
		if (device.state === UPowerDeviceState.Discharging || device.state === UPowerDeviceState.PendingDischarge)
			return device.timeToEmpty > 0 ? panel.formatDuration(device.timeToEmpty) + " remaining" : "On battery";
		return "";
	}

	// PowerProfiles.holds lists other processes (a game launcher, a
	// thermal daemon, ...) that have temporarily pinned a profile --
	// surfaced so a click here that doesn't seem to "stick" is
	// explainable instead of looking broken.
	function holdsNote() {
		const holds = PowerProfiles.holds;
		if (!holds || holds.length === 0)
			return "";
		const parts = [];
		for (let i = 0; i < holds.length; i++) {
			const hold = holds[i];
			parts.push((hold.applicationId || "An app") + " requested " + PowerProfile.toString(hold.profile));
		}
		return parts.join(", ");
	}

	function selectProfile(value) {
		if (value === PowerProfile.Performance && !PowerProfiles.hasPerformanceProfile)
			return;
		PowerProfiles.profile = value;
	}

	Component {
		id: profileDelegate

		Rectangle {
			id: row
			required property var modelData
			property bool hovered: false
			readonly property bool active: modelData.value === PowerProfiles.profile
			readonly property bool unavailable: modelData.value === PowerProfile.Performance && !PowerProfiles.hasPerformanceProfile

			Layout.fillWidth: true
			Layout.preferredHeight: panel.rowHeight
			radius: 6
			color: active ? Qt.alpha(colors.mauve, hovered ? 0.35 : 0.25) : (hovered && !unavailable ? colors.surface0 : "transparent")
			opacity: unavailable ? 0.4 : 1

			Behavior on color {
				ColorAnimation { duration: 100 }
			}

			RowLayout {
				anchors.fill: parent
				anchors.leftMargin: 10
				anchors.rightMargin: 10
				spacing: 10

				Text {
					text: modelData.icon
					color: row.active ? colors.mauve : colors.text
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}

				Text {
					Layout.fillWidth: true
					text: modelData.label
					color: colors.text
					font.pixelSize: 14
				}

				Text {
					visible: row.active
					text: "\uf00c"
					color: colors.mauve
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}
			}

			MouseArea {
				anchors.fill: parent
				hoverEnabled: !row.unavailable
				cursorShape: row.unavailable ? Qt.ArrowCursor : Qt.PointingHandCursor
				onEntered: row.hovered = true
				onExited: row.hovered = false
				onClicked: panel.selectProfile(modelData.value)
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
					text: panel.batteryIcon()
					color: colors.text
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}

				Text {
					Layout.fillWidth: true
					text: "Battery"
					color: colors.text
					font.pixelSize: 14
				}

				Text {
					visible: UPower.displayDevice && UPower.displayDevice.isPresent
					text: Math.round((UPower.displayDevice ? UPower.displayDevice.percentage : 0) * 100) + "%"
					color: colors.subtext0
					font.pixelSize: 12
				}
			}

			Text {
				Layout.fillWidth: true
				text: panel.batteryStatusText()
				color: colors.subtext0
				font.pixelSize: 12
				elide: Text.ElideRight
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.dividerHeight
			color: colors.surface0
		}

		Text {
			id: profileLabel
			text: "Power Profile"
			color: colors.subtext0
			font.pixelSize: 12
		}

		ColumnLayout {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.profileListHeight
			spacing: panel.rowSpacing

			Repeater {
				model: panel.profileOptions
				delegate: profileDelegate
			}
		}

		Text {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.holdsRowHeight
			text: panel.holdsNote()
			color: colors.subtext0
			font.pixelSize: 11
			elide: Text.ElideRight
		}
	}
}
