import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

// Session quick panel, opened from waybar's custom/power-menu module
// (on-click: `quickshell-toggle session`). Unlike ../audio, ../wifi,
// ../bluetooth, ../power, there's no live service backing this one --
// lock/log out/hibernate/shutdown are all one-shot external commands, so
// this just shells out via Quickshell.execDetached, matching the exact
// commands conf/bindings.lua's own keybinds use (SUPER+SHIFT+L, SUPER+M)
// for the two that already have one, so this menu and those keybinds never
// disagree about what "lock" or "log out" means.
//
// Log Out/Hibernate/Shutdown require a second click within a few seconds
// to actually fire (see armedAction below) -- those end the session or the
// machine outright, with no undo, so a single mis-click here shouldn't be
// able to do that. Lock has no such guard since it's the one action here
// that's harmless to fire by accident (you just unlock again).
//
// title is a distinct hook for conf/rules.lua to position this window (top
// right, under waybar), the same mechanism the other panels use.
FloatingWindow {
	id: panel
	title: "quickshell-session"

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

	readonly property var actions: [
		{ id: "lock", label: "Lock", icon: "\uf023", confirm: false },
		{ id: "logout", label: "Log Out", icon: "󰍃", confirm: true },
		{ id: "hibernate", label: "Hibernate", icon: "󰒲", confirm: true },
		{ id: "shutdown", label: "Shutdown", icon: "󰐥", confirm: true }
	]
	readonly property int actionsHeight: actions.length * rowHeight + Math.max(0, actions.length - 1) * rowSpacing

	implicitWidth: 420
	implicitHeight: contentMargin * 2 + headerRow.height + contentSpacing + dividerHeight + contentSpacing + actionsHeight
	color: colors.base

	// Catppuccin Macchiato, duplicated by hand -- see the same note in
	// ../audio/shell.qml for why this isn't a shared import.
	QtObject {
		id: colors
		readonly property color base: "#24273a"
		readonly property color text: "#cad3f5"
		readonly property color surface0: "#363a4f"
		readonly property color red: "#ed8796"
	}

	// Which row (by id) is waiting for a confirming second click. Cleared
	// by armTimeout if that click doesn't come, and by clicking a
	// *different* confirm-required row instead (selectAction below arms
	// the new one rather than executing it, so an armed row can't be
	// fired by a click meant for something else).
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
		id: actionDelegate

		Rectangle {
			id: row
			required property var modelData
			property bool hovered: false
			readonly property bool armed: panel.armedAction === modelData.id

			Layout.fillWidth: true
			Layout.preferredHeight: panel.rowHeight
			radius: 6
			color: armed ? Qt.alpha(colors.red, hovered ? 0.35 : 0.25) : (hovered ? colors.surface0 : "transparent")

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
					color: row.armed ? colors.red : colors.text
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
					visible: row.armed
					text: "Click to confirm"
					color: colors.red
					font.pixelSize: 12
				}
			}

			MouseArea {
				anchors.fill: parent
				hoverEnabled: true
				cursorShape: Qt.PointingHandCursor
				onEntered: row.hovered = true
				onExited: row.hovered = false
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
				text: "󰐥"
				color: colors.text
				font.pixelSize: 14
				font.family: "IosevkaTerm Nerd Font"
			}

			Text {
				Layout.fillWidth: true
				text: "Session"
				color: colors.text
				font.pixelSize: 14
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.dividerHeight
			color: colors.surface0
		}

		ColumnLayout {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.actionsHeight
			spacing: panel.rowSpacing

			Repeater {
				model: panel.actions
				delegate: actionDelegate
			}
		}
	}
}
