import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

// Minimal app launcher. Toggled by SUPER+SHIFT+SPACE (kill-if-running, else
// launch -- see conf/bindings.lua), so each open is a fresh process rather
// than a persistent daemon with an IPC toggle.
FloatingWindow {
	id: launcher

	readonly property int rowHeight: 44
	readonly property int visibleRows: 6
	readonly property int contentMargin: 12
	readonly property int listSpacing: 8
	readonly property int dividerHeight: 1

	implicitWidth: 280
	// Calculated, not guessed, so the list always cuts off exactly between
	// rows instead of peeking into a partial one: margins + the search
	// field's real rendered height + two layout gaps (search-to-divider,
	// divider-to-list) + the divider + N whole rows.
	implicitHeight: contentMargin * 2 + input.height + listSpacing * 2 + dividerHeight + visibleRows * rowHeight
	color: colors.base

	property string query: ""

	// Catppuccin Macchiato, duplicated by hand from
	// modules/apps/hyprland/default.nix rather than imported: quickshell
	// resolves a config's QML/JS imports through its own packaged file tree,
	// not real relative paths, so a file outside quickshell/ (like
	// ~/.config/theme/) isn't reachable from here without restructuring how
	// this directory is delivered.
	//
	// Named "colors", not "palette": QtQuick Controls' Control type already
	// has a built-in "palette" property, and inside a Control (e.g. the
	// TextField below) an unqualified "palette.text" resolved to that
	// built-in (near-black) one instead of this object, silently swallowing
	// the intended color.
	QtObject {
		id: colors
		readonly property color base: "#24273a"
		readonly property color text: "#cad3f5"
		readonly property color surface0: "#363a4f"
		readonly property color mauve: "#c6a0f6"
	}

	// Populated once by hiddenEntryScan below. DesktopEntries.applications
	// already drops Hidden/NoDisplay entries, but not OnlyShowIn/NotShowIn --
	// this is a Hyprland session, not GNOME, so GNOME-only entries (Settings,
	// Extensions, Tour, dozens of individual Settings panels, ...) would
	// otherwise still show up here.
	property var hiddenIds: ({})

	// Most org.gnome.* apps (Contacts, Logs, Camera, Weather, Calculator, ...)
	// don't set OnlyShowIn/NotShowIn at all -- they're spec-compliant, just
	// unwanted here -- so hidden-entries.sh can't catch them. Blanket-hide the
	// whole namespace instead, with an explicit keep-list for the ones
	// actually wanted (Nautilus/"Files", used as the file manager).
	readonly property var keepGnomeIds: ({
		"org.gnome.Nautilus": true,
	})
	function isUnwantedGnomeApp(entry) {
		return entry.id.startsWith("org.gnome.") && !launcher.keepGnomeIds[entry.id];
	}

	Process {
		id: hiddenEntryScan
		property string collected: ""
		command: [
			"bash",
			Quickshell.env("HOME") + "/.config/quickshell/app-launcher/hidden-entries.sh",
			[Quickshell.env("XDG_CURRENT_DESKTOP"), Quickshell.env("XDG_SESSION_DESKTOP"), Quickshell.env("DESKTOP_SESSION")].filter(v => v && v.length > 0).join(":"),
		]
		stdout: SplitParser {
			onRead: line => (hiddenEntryScan.collected += line + "\n")
		}
		onExited: {
			const next = {};
			for (const id of hiddenEntryScan.collected.split("\n"))
				if (id.trim().length > 0)
					next[id.trim()] = true;
			launcher.hiddenIds = next;
		}
	}

	function launchSelected() {
		if (!list.currentItem || !list.currentItem.modelData)
			return;

		const entry = list.currentItem.modelData;
		// entry.execute() runs the raw Exec= command with no controlling
		// terminal, so a TUI entry (Terminal=true, e.g. htop, nvim) launches
		// into nothing visible and appears to do nothing. Terminal=true means
		// the desktop entry expects the launcher to provide one.
		// --title=FloatTerm matches conf/rules.lua's existing float-floatterm
		// rule (see scripts/launch-floating-terminal), so it floats instead
		// of tiling like a normal window.
		if (entry.runInTerminal)
			Quickshell.execDetached(["ghostty", "--title=FloatTerm", "-e", ...entry.command]);
		else
			entry.execute();
		Qt.quit();
	}

	Component.onCompleted: {
		input.forceActiveFocus();
		hiddenEntryScan.running = true;
	}

	ColumnLayout {
		anchors.fill: parent
		anchors.margins: launcher.contentMargin
		spacing: launcher.listSpacing

		TextField {
			id: input
			Layout.fillWidth: true
			placeholderText: "Search apps…"
			font.pixelSize: 20
			color: colors.text
			padding: 12

			background: Rectangle {
				color: colors.surface0
				radius: 6
			}

			onTextChanged: {
				launcher.query = text;
				list.currentIndex = filtered.values.length > 0 ? 0 : -1;
			}

			Keys.onEscapePressed: Qt.quit()
			Keys.onPressed: event => {
				const ctrl = event.modifiers & Qt.ControlModifier;
				if (event.key === Qt.Key_Down || (ctrl && event.key === Qt.Key_N)) {
					event.accepted = true;
					if (list.currentIndex < list.count - 1)
						list.currentIndex++;
				} else if (event.key === Qt.Key_Up || (ctrl && event.key === Qt.Key_P)) {
					event.accepted = true;
					if (list.currentIndex > 0)
						list.currentIndex--;
				} else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
					event.accepted = true;
					launcher.launchSelected();
				}
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: launcher.dividerHeight
			color: colors.surface0
		}

		ScriptModel {
			id: filtered
			values: {
				const all = [...DesktopEntries.applications.values].filter(d => !launcher.hiddenIds[d.id] && !launcher.isUnwantedGnomeApp(d));
				const q = launcher.query.trim().toLowerCase();
				if (q === "")
					return all;
				return all.filter(d => (d.name && d.name.toLowerCase().includes(q)) || (d.id && d.id.toLowerCase().includes(q)));
			}
		}

		ListView {
			id: list
			Layout.fillWidth: true
			Layout.fillHeight: true
			clip: true
			model: filtered.values
			currentIndex: filtered.values.length > 0 ? 0 : -1
			keyNavigationWraps: true
			highlightMoveDuration: 80

			highlight: Rectangle {
				radius: 6
				color: colors.mauve
				opacity: 0.35
			}

			delegate: Item {
				id: entry
				required property var modelData
				required property int index
				width: ListView.view.width
				height: launcher.rowHeight

				MouseArea {
					anchors.fill: parent
					onClicked: list.currentIndex = entry.index
					onDoubleClicked: launcher.launchSelected()
				}

				Text {
					anchors.verticalCenter: parent.verticalCenter
					anchors.left: parent.left
					anchors.right: parent.right
					anchors.margins: 8
					color: colors.text
					text: entry.modelData.name
					font.pixelSize: 18
					elide: Text.ElideRight
				}
			}
		}
	}
}
