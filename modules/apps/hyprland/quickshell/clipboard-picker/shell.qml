import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

// Clipboard history picker, replacing `cliphist list | rofi -dmenu | cliphist
// decode | wl-copy`. Purpose-built for cliphist rather than a generic dmenu
// bridge: cliphist's own id-prefixed lines are the natural list items, and
// the selection goes straight into `cliphist decode | wl-copy` here instead
// of round-tripping through stdout for an external pipeline.
FloatingWindow {
	id: picker

	readonly property int rowHeight: 44
	readonly property int visibleRows: 8
	readonly property int contentMargin: 12
	readonly property int listSpacing: 8
	readonly property int dividerHeight: 1

	implicitWidth: 500
	implicitHeight: contentMargin * 2 + input.height + listSpacing * 2 + dividerHeight + visibleRows * rowHeight
	color: colors.base

	property string query: ""
	property var entries: []

	// Catppuccin Macchiato, duplicated by hand -- see the same note in
	// ../app-launcher/shell.qml for why this isn't a shared import.
	QtObject {
		id: colors
		readonly property color base: "#24273a"
		readonly property color text: "#cad3f5"
		readonly property color surface0: "#363a4f"
		readonly property color mauve: "#c6a0f6"
	}

	Process {
		id: listProc
		property string collected: ""
		command: ["cliphist", "list"]
		stdout: SplitParser {
			onRead: line => (listProc.collected += line + "\n")
		}
		onExited: {
			picker.entries = listProc.collected.split("\n").filter(l => l.length > 0);
		}
	}

	// POSIX single-quote escaping for embedding in a shell command --
	// JSON.stringify is the wrong tool here: it renders the real tab between
	// cliphist's id and preview text as the two literal characters "\t",
	// which bash's -c (given a plain double-quoted string) does not
	// interpret back into a tab. cliphist decode then can't find the id
	// separator, fails, and wl-copy happily copies its empty output --
	// which reads as "nothing happens" and "clipboard got cleared".
	function shellQuote(str) {
		return "'" + str.replace(/'/g, "'\\''") + "'";
	}

	function selectEntry(line) {
		if (!line)
			return;
		Quickshell.execDetached(["bash", "-c", "cliphist decode <<< " + shellQuote(line) + " | wl-copy"]);
		Qt.quit();
	}

	Component.onCompleted: {
		input.forceActiveFocus();
		listProc.running = true;
	}

	ColumnLayout {
		anchors.fill: parent
		anchors.margins: picker.contentMargin
		spacing: picker.listSpacing

		TextField {
			id: input
			Layout.fillWidth: true
			placeholderText: "Search clipboard history…"
			font.pixelSize: 20
			color: colors.text
			padding: 12

			background: Rectangle {
				color: colors.surface0
				radius: 6
			}

			onTextChanged: {
				picker.query = text;
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
					picker.selectEntry(list.currentItem ? list.currentItem.modelData : "");
				}
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: picker.dividerHeight
			color: colors.surface0
		}

		ScriptModel {
			id: filtered
			values: {
				const q = picker.query.trim().toLowerCase();
				if (q === "")
					return picker.entries;
				return picker.entries.filter(l => l.toLowerCase().includes(q));
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
				height: picker.rowHeight

				MouseArea {
					anchors.fill: parent
					onClicked: list.currentIndex = entry.index
					onDoubleClicked: picker.selectEntry(entry.modelData)
				}

				Text {
					anchors.verticalCenter: parent.verticalCenter
					anchors.left: parent.left
					anchors.right: parent.right
					anchors.margins: 8
					color: colors.text
					text: entry.modelData
					font.pixelSize: 16
					elide: Text.ElideRight
				}
			}
		}
	}
}
