import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

// Combined settings quick panel -- night light + session actions -- opened
// from waybar's custom/settings module (on-click: `quickshell-toggle
// settings`). Started as two separate panels/bar icons (../nightlight,
// ../session) but two single-purpose "misc settings" icons was more bar
// clutter than either pulled its own weight, so they're merged here under
// one gear icon. Session actions in particular shrank from a full
// label+row list down to icon-only buttons in the header (see the
// `actions` property below) once there wasn't room to spell each one out
// alongside night light. The underlying mechanics (hyprsunset's
// read-only-via-socat socket quirk, the confirm-to-fire guard on Log
// Out/Hibernate/Shutdown, etc.) are unchanged from the originals -- see
// git log for ../nightlight and ../session if those comments are wanted.
//
// title is a distinct hook for conf/rules.lua to position this window (top
// right, under waybar), the same mechanism the other panels use.
FloatingWindow {
	id: panel
	title: "quickshell-settings"

	// See ../audio/shell.qml's identical note: without this, closing the
	// window (defocus, or `quickshell-toggle` clicking the bar icon again)
	// doesn't end the process -- Quickshell expects to keep running as a
	// shell with zero or more windows otherwise.
	onClosed: Qt.quit()

	readonly property int contentMargin: 10
	readonly property int contentSpacing: 6
	readonly property int dividerHeight: 1
	readonly property int sliderRowHeight: 32
	readonly property int iconButtonSpacing: 2
	readonly property int minTemp: 2500
	readonly property int maxTemp: 6500

	// Icon-only, packed into the header's right side rather than a full
	// label+row list (see ../session/shell.qml for the original,
	// list-style version) -- there wasn't room to spell each one out once
	// this got folded in alongside night light, so the confirm-to-fire
	// guard on Log Out/Hibernate/Shutdown shows as the button itself
	// turning red on the first click instead of a "Click to confirm"
	// label (see sessionButtonDelegate below).
	readonly property var actions: [
		{ id: "lock", label: "Lock", icon: "\uf023", confirm: false },
		{ id: "logout", label: "Log Out", icon: "󰍃", confirm: true },
		{ id: "hibernate", label: "Hibernate", icon: "󰒲", confirm: true },
		{ id: "shutdown", label: "Shutdown", icon: "󰐥", confirm: true }
	]

	implicitWidth: 300
	implicitHeight: contentMargin * 2 + headerRow.height + contentSpacing + dividerHeight + contentSpacing + nightLabel.height + contentSpacing + nightToggleRow.height + contentSpacing + sliderRow.height
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

	// --- Night light. hyprsunset exposes no way to query whether a filter
	// is currently active, only its last-set temperature (confirmed live
	// with socat against its unix socket), so on/off is tracked in this
	// state file rather than asked of hyprsunset -- and can drift from
	// reality if something outside this panel changes it (hyprsunset's own
	// day/night `profile` blocks in hyprsunset.conf, e.g.).
	property bool nightLightEnabled: false
	property real temperature: 3500

	FileView {
		id: stateFile
		path: Quickshell.env("HOME") + "/.cache/quickshell-nightlight-state"
		watchChanges: false
		printErrors: false
		onLoaded: panel.parseState(text())
		onLoadFailed: panel.parseState("")
	}

	function parseState(raw) {
		const parts = (raw || "").trim().split(" ");
		panel.nightLightEnabled = parts[0] === "on";
		const t = parseInt(parts[1], 10);
		panel.temperature = Number.isFinite(t) && t >= panel.minTemp && t <= panel.maxTemp ? t : 3500;
	}

	function saveState() {
		stateFile.setText((panel.nightLightEnabled ? "on" : "off") + " " + Math.round(panel.temperature));
	}

	// hyprsunset has to actually be running for `hyprctl hyprsunset` to
	// have a socket to talk to -- same lazy-start idiom as the lock action
	// below (`pidof X || X`), just with a beat afterward for hyprsunset's
	// Wayland protocol bind to finish before the first real command hits
	// it. Normally already running via autostart.lua; this is only the
	// fallback.
	function applyNightLightState() {
		const command = panel.nightLightEnabled ? "hyprctl hyprsunset temperature " + Math.round(panel.temperature) : "hyprctl hyprsunset identity";
		Quickshell.execDetached(["bash", "-c", "pidof hyprsunset >/dev/null || { hyprsunset & sleep 0.3; }; " + command]);
		panel.saveState();
	}

	function toggleNightLight() {
		panel.nightLightEnabled = !panel.nightLightEnabled;
		panel.applyNightLightState();
	}

	// --- Session actions. Lock/Log Out use the exact commands
	// conf/bindings.lua's own keybinds use (SUPER+SHIFT+L, SUPER+M), so
	// this menu and those keybinds never disagree about what they mean.
	// Log Out/Hibernate/Shutdown require a second click within a few
	// seconds to actually fire (armedAction below) -- those end the
	// session or the machine outright, with no undo, so a single
	// mis-click here shouldn't be able to do that. Lock has no such guard
	// since it's the one action here that's harmless to fire by accident.
	property string armedAction: ""

	Timer {
		id: armTimeout
		interval: 3000
		repeat: false
		onTriggered: panel.armedAction = ""
	}

	function commandFor(id) {
		if (id === "lock")
			return ["bash", "-c", "pidof hyprlock || hyprlock"];
		if (id === "logout")
			return ["uwsm", "stop"];
		if (id === "hibernate")
			return ["systemctl", "hibernate"];
		if (id === "shutdown")
			return ["systemctl", "poweroff"];
		return null;
	}

	function runAction(id) {
		const command = panel.commandFor(id);
		if (!command)
			return;
		Quickshell.execDetached(command);
		Qt.quit();
	}

	function selectAction(action) {
		if (!action.confirm) {
			panel.runAction(action.id);
			return;
		}
		if (panel.armedAction === action.id) {
			panel.runAction(action.id);
			return;
		}
		panel.armedAction = action.id;
		armTimeout.restart();
	}

	Component {
		id: sessionButtonDelegate

		Rectangle {
			id: btn
			required property var modelData
			property bool hovered: false
			readonly property bool armed: panel.armedAction === modelData.id

			implicitWidth: 24
			implicitHeight: 24
			radius: 6
			color: armed ? Qt.alpha(colors.red, hovered ? 0.5 : 0.35) : (hovered ? colors.surface0 : "transparent")

			Behavior on color {
				ColorAnimation { duration: 100 }
			}

			Text {
				anchors.centerIn: parent
				text: modelData.icon
				color: btn.armed ? colors.red : colors.text
				font.pixelSize: 13
				font.family: "IosevkaTerm Nerd Font"
			}

			MouseArea {
				anchors.fill: parent
				hoverEnabled: true
				cursorShape: Qt.PointingHandCursor
				onEntered: btn.hovered = true
				onExited: btn.hovered = false
				onClicked: panel.selectAction(modelData)
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

		RowLayout {
			id: headerRow
			Layout.fillWidth: true
			spacing: 8

			Text {
				text: "󰒓"
				color: colors.text
				font.pixelSize: 14
				font.family: "IosevkaTerm Nerd Font"
			}

			Text {
				Layout.fillWidth: true
				text: "Settings"
				color: colors.text
				font.pixelSize: 14
			}

			RowLayout {
				spacing: panel.iconButtonSpacing

				Repeater {
					model: panel.actions
					delegate: sessionButtonDelegate
				}
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.dividerHeight
			color: colors.surface0
		}

		Text {
			id: nightLabel
			text: "Night Light"
			color: colors.subtext0
			font.pixelSize: 12
		}

		RowLayout {
			id: nightToggleRow
			Layout.fillWidth: true
			spacing: 8

			Text {
				text: panel.nightLightEnabled ? "󰖔" : "󰖙"
				color: colors.text
				font.pixelSize: 14
				font.family: "IosevkaTerm Nerd Font"
			}

			Text {
				Layout.fillWidth: true
				text: panel.nightLightEnabled ? Math.round(panel.temperature) + "K" : "Off"
				color: colors.text
				font.pixelSize: 14
			}

			// Master on/off switch -- same affordance as ../wifi's, for
			// the same reason: a bare status icon didn't read as a toggle.
			Rectangle {
				implicitWidth: 34
				implicitHeight: 18
				radius: height / 2
				color: panel.nightLightEnabled ? colors.mauve : colors.surface0

				Behavior on color {
					ColorAnimation { duration: 120 }
				}

				Rectangle {
					width: 14
					height: 14
					radius: 7
					color: colors.base
					anchors.verticalCenter: parent.verticalCenter
					x: panel.nightLightEnabled ? parent.width - width - 2 : 2

					Behavior on x {
						NumberAnimation { duration: 120; easing.type: Easing.OutQuad }
					}
				}

				MouseArea {
					anchors.fill: parent
					anchors.margins: -6
					cursorShape: Qt.PointingHandCursor
					onClicked: panel.toggleNightLight()
				}
			}
		}

		RowLayout {
			id: sliderRow
			Layout.fillWidth: true
			Layout.preferredHeight: panel.sliderRowHeight
			spacing: 8
			enabled: panel.nightLightEnabled
			opacity: panel.nightLightEnabled ? 1 : 0.4

			Text {
				text: "󰖔"
				color: colors.subtext0
				font.pixelSize: 13
				font.family: "IosevkaTerm Nerd Font"
			}

			Slider {
				id: tempSlider
				Layout.fillWidth: true
				from: panel.minTemp
				to: panel.maxTemp
				stepSize: 100
				value: panel.temperature
				onMoved: panel.temperature = value
				onPressedChanged: if (!pressed)
					panel.applyNightLightState()
			}

			Text {
				text: "󰖙"
				color: colors.subtext0
				font.pixelSize: 13
				font.family: "IosevkaTerm Nerd Font"
			}
		}
	}
}
