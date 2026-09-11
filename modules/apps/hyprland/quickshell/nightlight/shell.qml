import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

// Night light quick panel, opened from waybar's custom/nightlight module
// (on-click: `quickshell-toggle nightlight`). Controls hyprsunset, which
// unlike Pipewire/NetworkManager/BlueZ/UPower has no Quickshell service
// binding (or any DBus interface at all) -- it's a small Hyprland-specific
// daemon controlled over its own unix socket via `hyprctl hyprsunset ...`.
//
// That socket protocol turns out to have an undocumented read side: `hyprctl
// hyprsunset` only lists set-style requests (temperature/identity/gamma),
// but sending the bare word "temperature" over the raw socket (confirmed
// live with socat) returns the last temperature it was set to, rather than
// setting anything. There's no equivalent way to read back *whether* a
// filter is currently applied vs. reset to identity, though -- "identity"
// bare is a set-only reset, always answering "ok". So on/off state here is
// tracked in our own state file (see stateFile below) rather than queried
// from hyprsunset, and drifts if something outside this panel changes it
// (hyprsunset's own day/night `profile` blocks in hyprsunset.conf, e.g.).
//
// title is a distinct hook for conf/rules.lua to position this window (top
// right, under waybar), the same mechanism the other panels use.
FloatingWindow {
	id: panel
	title: "quickshell-nightlight"

	// See ../audio/shell.qml's identical note: without this, closing the
	// window (defocus, or `quickshell-toggle` clicking the bar icon again)
	// doesn't end the process -- Quickshell expects to keep running as a
	// shell with zero or more windows otherwise.
	onClosed: Qt.quit()

	readonly property int contentMargin: 10
	readonly property int contentSpacing: 6
	readonly property int dividerHeight: 1
	readonly property int sliderRowHeight: 32
	readonly property int minTemp: 2500
	readonly property int maxTemp: 6500

	implicitWidth: 300
	implicitHeight: contentMargin * 2 + headerColumn.height + contentSpacing + dividerHeight + contentSpacing + sliderRowHeight
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
	// have a socket to talk to (confirmed live: it fails outright
	// otherwise) -- same lazy-start idiom as ../session's lock action
	// (`pidof X || X`), just with a beat afterward for hyprsunset's
	// Wayland protocol bind to finish before the first real command hits
	// it.
	function applyState() {
		const command = panel.nightLightEnabled ? "hyprctl hyprsunset temperature " + Math.round(panel.temperature) : "hyprctl hyprsunset identity";
		Quickshell.execDetached(["bash", "-c", "pidof hyprsunset >/dev/null || { hyprsunset & sleep 0.3; }; " + command]);
		panel.saveState();
	}

	function toggleNightLight() {
		panel.nightLightEnabled = !panel.nightLightEnabled;
		panel.applyState();
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
					text: panel.nightLightEnabled ? "\udb81\udd94" : "\udb81\udd99"
					color: colors.text
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}

				Text {
					Layout.fillWidth: true
					text: "Night Light"
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

			Text {
				Layout.fillWidth: true
				text: panel.nightLightEnabled ? Math.round(panel.temperature) + "K" : "Off"
				color: colors.subtext0
				font.pixelSize: 12
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.dividerHeight
			color: colors.surface0
		}

		RowLayout {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.sliderRowHeight
			spacing: 8
			enabled: panel.nightLightEnabled
			opacity: panel.nightLightEnabled ? 1 : 0.4

			Text {
				text: "\udb81\udd94"
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
					panel.applyState()
			}

			Text {
				text: "\udb81\udd99"
				color: colors.subtext0
				font.pixelSize: 13
				font.family: "IosevkaTerm Nerd Font"
			}
		}
	}
}
