import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire

// Audio quick panel, opened from waybar's pulseaudio module (on-click: `qs -c
// audio`). Built on Quickshell's native PipeWire binding
// (Quickshell.Services.Pipewire) rather than shelling out to wpctl/pamixer:
// volume/mute/default-device are real reactive properties here (writes are
// instant, no polling lag), and PwNodePeakMonitor gives genuine real-time
// loudness -- none of that is available by scraping CLI text.
//
// title is a distinct hook for conf/rules.lua to position this window (top
// right, under waybar) without it being caught by the generic center-quickshell
// rule that app-launcher/clipboard-picker want instead.
FloatingWindow {
	id: panel
	title: "quickshell-audio"

	readonly property int contentMargin: 10
	readonly property int contentSpacing: 6 // must match the ColumnLayout's own `spacing` below -- implicitHeight is computed by hand, not measured
	readonly property int rowHeight: 32
	readonly property int dividerHeight: 1
	readonly property int rowSpacing: 2
	readonly property int meterHeight: 4
	readonly property int scrollGutter: 10 // gap reserved on a device row's right edge so its background doesn't run under the list's ScrollBar
	// The device lists only exist after the first refresh from Pipewire.nodes,
	// well after this window is first shown -- and a FloatingWindow's
	// implicitHeight, unlike a plain Item's, only gets applied once at creation
	// and never reapplied as content changes afterward (verified directly: a
	// pure-QML implicitHeight-changes-over-time test never resized the mapped
	// window either). So the window is sized for a fixed number of rows up
	// front (matching ../app-launcher and ../clipboard-picker's approach) and
	// each list scrolls past that rather than growing to fit.
	readonly property int visibleSinkRows: 2
	readonly property int visibleSourceRows: 2
	readonly property int sinkListHeight: visibleSinkRows * rowHeight + Math.max(0, visibleSinkRows - 1) * rowSpacing
	readonly property int sourceListHeight: visibleSourceRows * rowHeight + Math.max(0, visibleSourceRows - 1) * rowSpacing

	implicitWidth: 420
	implicitHeight: contentMargin * 2 + volumeRow.height + contentSpacing + meterHeight + contentSpacing + dividerHeight + contentSpacing + outputLabel.height + contentSpacing + sinkListHeight + contentSpacing + inputLabel.height + contentSpacing + meterHeight + contentSpacing + sourceListHeight
	color: colors.base

	property real volumePercent: 0
	property bool muted: false
	property var sinkNodes: []
	property var sourceNodes: []

	// Locked in once, from the first non-empty node refresh after this window
	// opens (a fresh window per `qs -c audio` invocation, so this naturally
	// resets on every reopen without any explicit reset logic). Switching the
	// default mid-session re-sorts nothing -- the row just moves its
	// highlight -- so clicking a device doesn't make the list jump under the
	// cursor. Stores PwNode ids (uint), not the nodes themselves.
	property var sinkOrder: []
	property var sourceOrder: []

	// Catppuccin Macchiato, duplicated by hand -- see the same note in
	// ../app-launcher/shell.qml for why this isn't a shared import.
	QtObject {
		id: colors
		readonly property color base: "#24273a"
		readonly property color text: "#cad3f5"
		readonly property color subtext0: "#a5adcb"
		readonly property color surface0: "#363a4f"
		readonly property color mauve: "#c6a0f6"
		readonly property color green: "#a6da95"
		readonly property color yellow: "#eed49f"
		readonly property color red: "#ed8796"
	}

	function levelColor(level) {
		if (level > 0.9)
			return colors.red;
		if (level > 0.7)
			return colors.yellow;
		return colors.green;
	}

	function setVolume(pct) {
		pct = Math.max(0, Math.min(100, pct));
		panel.volumePercent = pct;
		if (Pipewire.defaultAudioSink && Pipewire.defaultAudioSink.audio)
			Pipewire.defaultAudioSink.audio.volume = pct / 100;
	}

	function toggleMute() {
		const audio = Pipewire.defaultAudioSink && Pipewire.defaultAudioSink.audio;
		if (!audio)
			return;
		audio.muted = !audio.muted;
		panel.muted = audio.muted;
	}

	// Mirrors the current default sink's volume/mute into the plain
	// properties the UI binds to -- called on open and whenever the default
	// sink itself changes (switching device should immediately reflect *its*
	// level, not linger on the previous device's).
	function syncFromDefaultSink() {
		const audio = Pipewire.defaultAudioSink && Pipewire.defaultAudioSink.audio;
		if (!audio)
			return;
		panel.muted = audio.muted;
		if (!volumeSlider.pressed) {
			panel.volumePercent = Math.round(audio.volume * 100);
			volumeSlider.value = panel.volumePercent;
		}
	}

	// Pipewire.preferredDefaultAudioSink/Source (the native property write)
	// looked like the obvious way to do this, but Quickshell validates the
	// target's own PwNodeType before allowing it -- and at least one real
	// device on this system (a Scarlett 2i2's combined multi-channel capture
	// node) reports type "Untracked" to Quickshell's classifier even though
	// wpctl's own (looser) Sources: listing recognizes it fine, so the native
	// write is flatly refused for it ("Cannot change default source to a
	// node that is not a source"). wpctl set-default doesn't share that
	// restriction and works for every node this panel lists, sink or source
	// alike, so switching goes through it instead -- consistent regardless
	// of how strictly Quickshell happens to classify a given node.
	function selectDevice(node) {
		Quickshell.execDetached(["wpctl", "set-default", String(node.id)]);
	}

	// Applied to a freshly-read node list to make it match a previously
	// locked-in id order: known ids come first, in that locked order; any id
	// not in the lock (a device that showed up after this window opened)
	// falls in afterward, in whatever order Pipewire.nodes reported it.
	function applyStableOrder(nodes, order) {
		const byId = new Map(nodes.map(n => [n.id, n]));
		const ordered = [];

		for (const id of order) {
			if (byId.has(id)) {
				ordered.push(byId.get(id));
				byId.delete(id);
			}
		}
		for (const n of nodes) {
			if (byId.has(n.id))
				ordered.push(n);
		}

		return ordered;
	}

	// First refresh after open: current default device first, so the thing
	// you probably came here to check on is right at the top without hunting
	// for it.
	function lockInitialOrder(nodes, defaultNode) {
		const defId = defaultNode ? defaultNode.id : null;
		const rest = nodes.filter(n => n.id !== defId).map(n => n.id);
		return (defId !== null ? [defId] : []).concat(rest);
	}

	function deviceName(node) {
		return node.description || node.nickname || node.name;
	}

	// Classifying real device nodes purely from PwNodeType flags looked right
	// (AudioSink/AudioSource are documented as the hardware/virtual device
	// classes, distinct from the AudioOutStream/AudioInStream flags app
	// playback/capture connections use) but wasn't: verified live via a
	// screenshot that a Focusrite Scarlett's per-channel nodes carry *both*
	// the AudioSink and AudioSource bits at once, so that filter put an input
	// channel in the Output list and the real output in Input. wpctl status's
	// own Sinks:/Sources:/Filters: sectioning gets this right (confirmed
	// against the same device), so classification goes through it -- polled
	// on a slow timer below purely for *which ids belong in which list*, not
	// for their name/volume/mute/peak, which stay on the native Pipewire
	// properties above (reactive, no polling lag).
	property var sinkIds: new Set()
	property var sourceIds: new Set()

	// wpctl has no structured output mode, so this scrapes `wpctl status`'s
	// tree-drawing text. The regex ignores whatever box-drawing prefix
	// precedes each entry rather than trying to match it, since that prefix
	// depends on where the line falls in the tree.
	function parseSectionIds(lines, headerRegex) {
		const ids = [];
		let inSection = false;

		for (const line of lines) {
			if (headerRegex.test(line)) {
				inSection = true;
				continue;
			}
			if (inSection && /^\s*(├─|└─)/.test(line) && !headerRegex.test(line))
				break;
			if (!inSection)
				continue;

			const m = line.match(/(\d+)\.\s+.*?\[vol:\s*[\d.]+(\s+MUTED)?\]/);
			if (m)
				ids.push(Number(m[1]));
		}

		return ids;
	}

	// A device with multiple physical inputs (e.g. an audio interface with
	// several line/mic ins) shows up in `wpctl status` as one combined node
	// under Sources:, plus each individual input separately under Filters: as
	// a PipeWire loopback -- e.g. a Scarlett 2i2's two line-ins appear as
	// "Mic1_source"/"Mic2_source" there, not under Sources: at all. Filters
	// entries also pair each real "Audio/Source" node with an internal
	// "Stream/Input/Audio/Internal" ".split" companion and have no [vol: ...]
	// (so parseSectionIds's regex doesn't match them); this scrapes those
	// real Audio/Source entries specifically.
	function parseFilterSourceIds(lines) {
		const ids = [];
		let inFilters = false;

		for (const line of lines) {
			if (/Filters:/.test(line)) {
				inFilters = true;
				continue;
			}
			if (inFilters && /^\s*(├─|└─)/.test(line) && !/Filters:/.test(line))
				break;
			if (!inFilters)
				continue;

			const m = line.match(/(\d+)\.\s+.*?\[([^\]]+)\]\s*$/);
			if (m && m[2].trim() === "Audio/Source")
				ids.push(Number(m[1]));
		}

		return ids;
	}

	function refreshNodes() {
		const all = [...Pipewire.nodes.values];
		// wpctl's Sources:/Sinks: listing includes at least one node that
		// isn't actually selectable: a Scarlett 2i2's combined multi-channel
		// capture node has media.class "Audio/Source/Internal" -- it's an
		// implementation-detail node the real per-channel sources (Mic1/Mic2)
		// are derived from, not a real endpoint, and both wpctl set-default
		// and Pipewire.preferredDefaultAudioSource explicitly refuse to set
		// it as default ("not a device node" / "not a source"). Quickshell's
		// own classifier already can't place such nodes into any real
		// PwNodeType category (type reads back 0/Untracked, vs. e.g. 9 for a
		// genuine AudioSource), which is a reliable enough signal to exclude
		// them here rather than list a device that silently does nothing
		// when clicked.
		const sinks = all.filter(n => panel.sinkIds.has(n.id) && n.type !== PwNodeType.Untracked);
		const sources = all.filter(n => panel.sourceIds.has(n.id) && n.type !== PwNodeType.Untracked);

		if (panel.sinkOrder.length === 0 && sinks.length > 0)
			panel.sinkOrder = panel.lockInitialOrder(sinks, Pipewire.defaultAudioSink);
		if (panel.sourceOrder.length === 0 && sources.length > 0)
			panel.sourceOrder = panel.lockInitialOrder(sources, Pipewire.defaultAudioSource);

		panel.sinkNodes = panel.applyStableOrder(sinks, panel.sinkOrder);
		panel.sourceNodes = panel.applyStableOrder(sources, panel.sourceOrder);
	}

	// Cursor-warp-on-open and close-on-defocus both live in Hyprland's own
	// Lua config now (conf/rules.lua), not here: QML's own hover tracking was
	// unreliable for "is the pointer still anywhere over this window" (a
	// HoverHandler behind the real controls flickered false whenever the
	// pointer crossed onto the volume slider or a device row, since those
	// MouseAreas occlude it), and shelling out to `hyprctl clients`/`jq` from
	// here to work around it raced Component.onCompleted against the window
	// actually being registered with the compositor. Hyprland's own
	// window.open/window.active events fire with the real window object
	// (position, size, title) already resolved, with none of those problems.

	Component.onCompleted: {
		panel.syncFromDefaultSink();
	}

	Connections {
		target: Pipewire

		function onDefaultAudioSinkChanged() {
			panel.syncFromDefaultSink();
		}
		function onReadyChanged() {
			if (Pipewire.ready)
				panel.refreshNodes();
		}
	}

	// Catches external volume/mute changes on whichever sink is currently
	// default (hardware keys, swayosd, another client) -- retargets itself
	// whenever the default sink changes, since Connections.target is live.
	Connections {
		target: Pipewire.defaultAudioSink ? Pipewire.defaultAudioSink.audio : null

		function onVolumeChanged() {
			panel.syncFromDefaultSink();
		}
		function onMutedChanged() {
			panel.syncFromDefaultSink();
		}
	}

	// Classification (which ids are sinks vs. sources) and hotplug both change
	// rarely enough that a slow poll is fine -- the parts that actually need
	// to feel instant (volume, mute, default switching, peak level) are all
	// native reactive properties above, not this.
	Process {
		id: classifyProc
		property string collected: ""
		command: ["wpctl", "status"]
		stdout: SplitParser {
			onRead: line => (classifyProc.collected += line + "\n")
		}
		onExited: {
			const lines = classifyProc.collected.split("\n");
			classifyProc.collected = "";

			panel.sinkIds = new Set(panel.parseSectionIds(lines, /Sinks:/));
			panel.sourceIds = new Set(panel.parseSectionIds(lines, /Sources:/).concat(panel.parseFilterSourceIds(lines)));
			panel.refreshNodes();
		}
	}

	Timer {
		interval: 2000
		running: true
		repeat: true
		triggeredOnStart: true
		onTriggered: classifyProc.running = true
	}

	PwNodePeakMonitor {
		id: outputPeak
		node: Pipewire.defaultAudioSink
		enabled: true
	}

	PwNodePeakMonitor {
		id: inputPeak
		node: Pipewire.defaultAudioSource
		enabled: true
	}

	// Shared by the Output and Input lists -- selectDevice() works for either,
	// told which one via the owning ListView's `isSink`.
	Component {
		id: deviceDelegate

		Rectangle {
			required property var modelData
			property bool hovered: false
			// ListView.view resolves fine in bindings on this root item (used
			// right below), but is null from the nested MouseArea's onClicked
			// handler -- attached properties only populate on the delegate
			// root itself, not its children. Cached here so onClicked has
			// something that actually works.
			readonly property bool isSinkList: ListView.view ? ListView.view.isSink : false
			readonly property bool isDefault: modelData === (isSinkList ? Pipewire.defaultAudioSink : Pipewire.defaultAudioSource)
			width: ListView.view.width - panel.scrollGutter
			height: panel.rowHeight
			radius: 6
			color: isDefault ? Qt.alpha(colors.mauve, hovered ? 0.35 : 0.25) : (hovered ? colors.surface0 : "transparent")

			Behavior on color {
				ColorAnimation { duration: 100 }
			}

			RowLayout {
				anchors.fill: parent
				anchors.leftMargin: 10
				anchors.rightMargin: 10
				spacing: 10

				Item {
					id: nameClip
					Layout.fillWidth: true
					height: nameText.implicitHeight
					clip: true

					readonly property real overflowAmount: Math.max(0, nameText.implicitWidth - nameClip.width)

					Text {
						id: nameText
						text: panel.deviceName(modelData)
						color: colors.text
						font.pixelSize: 14
					}

					// Ticker: sit, scroll left just far enough to reveal the
					// clipped tail, sit again, scroll back. Only runs at all
					// when the name is actually too wide for its row.
					SequentialAnimation {
						running: nameClip.overflowAmount > 0
						loops: Animation.Infinite
						onRunningChanged: if (!running)
							nameText.x = 0

						PauseAnimation { duration: 1200 }
						NumberAnimation {
							target: nameText
							property: "x"
							to: -nameClip.overflowAmount
							duration: Math.max(600, nameClip.overflowAmount * 30)
							easing.type: Easing.Linear
						}
						PauseAnimation { duration: 900 }
						NumberAnimation {
							target: nameText
							property: "x"
							to: 0
							duration: Math.max(600, nameClip.overflowAmount * 30)
							easing.type: Easing.Linear
						}
					}
				}

				Text {
					// U+F00C = Font Awesome "check". Literal glyphs (typed
					// directly as UTF-8) get silently dropped somewhere in
					// this tool's edit/write path -- \u escapes survive
					// because they're plain ASCII in the source text.
					text: isDefault ? "" : ""
					color: colors.mauve
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}
			}

			MouseArea {
				anchors.fill: parent
				hoverEnabled: true
				cursorShape: Qt.PointingHandCursor
				onEntered: parent.hovered = true
				onExited: parent.hovered = false
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

		RowLayout {
			id: volumeRow
			Layout.fillWidth: true
			spacing: 8

			Rectangle {
				id: muteButton
				property bool hovered: false
				implicitWidth: muteIcon.implicitWidth + 12
				implicitHeight: muteIcon.implicitHeight + 8
				radius: 6
				color: hovered ? colors.surface0 : "transparent"

				Behavior on color {
					ColorAnimation { duration: 100 }
				}

				Text {
					id: muteIcon
					anchors.centerIn: parent
					text: panel.muted ? "" : panel.volumePercent < 1 ? "" : panel.volumePercent < 34 ? "" : panel.volumePercent < 67 ? "" : ""
					color: colors.text
					font.pixelSize: 14
					font.family: "IosevkaTerm Nerd Font"
				}

				MouseArea {
					anchors.fill: parent
					hoverEnabled: true
					cursorShape: Qt.PointingHandCursor
					onEntered: muteButton.hovered = true
					onExited: muteButton.hovered = false
					onClicked: panel.toggleMute()
				}
			}

			Slider {
				id: volumeSlider
				Layout.fillWidth: true
				from: 0
				to: 100
				stepSize: 1
				value: panel.volumePercent
				onPressedChanged: {
					if (!pressed)
						panel.setVolume(Math.round(value));
				}
				onMoved: panel.volumePercent = value
			}

			Text {
				text: (panel.muted ? "muted" : Math.round(panel.volumePercent) + "%")
				color: colors.subtext0
				font.pixelSize: 12
				Layout.preferredWidth: 48
				horizontalAlignment: Text.AlignRight
			}
		}

		Rectangle {
			Layout.fillWidth: true
			Layout.preferredHeight: panel.dividerHeight
			color: colors.surface0
		}

		Text {
			id: outputLabel
			text: "Output"
			color: colors.subtext0
			font.pixelSize: 12
		}

		Rectangle {
			id: outputMeterTrack
			Layout.fillWidth: true
			Layout.preferredHeight: panel.meterHeight
			radius: panel.meterHeight / 2
			color: colors.surface0

			Rectangle {
				width: outputMeterTrack.width * Math.min(1, outputPeak.peak)
				height: parent.height
				radius: parent.radius
				color: panel.levelColor(outputPeak.peak)
				Behavior on width {
					NumberAnimation { duration: 60 }
				}
			}
		}

		ListView {
			id: sinkList
			readonly property bool isSink: true
			Layout.fillWidth: true
			Layout.preferredHeight: panel.sinkListHeight
			clip: true
			spacing: panel.rowSpacing
			model: panel.sinkNodes
			delegate: deviceDelegate

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

		Text {
			id: inputLabel
			text: "Input"
			color: colors.subtext0
			font.pixelSize: 12
		}

		Rectangle {
			id: inputMeterTrack
			Layout.fillWidth: true
			Layout.preferredHeight: panel.meterHeight
			radius: panel.meterHeight / 2
			color: colors.surface0

			Rectangle {
				width: inputMeterTrack.width * Math.min(1, inputPeak.peak)
				height: parent.height
				radius: parent.radius
				color: panel.levelColor(inputPeak.peak)
				Behavior on width {
					NumberAnimation { duration: 60 }
				}
			}
		}

		ListView {
			id: sourceList
			readonly property bool isSink: false
			Layout.fillWidth: true
			Layout.preferredHeight: panel.sourceListHeight
			clip: true
			spacing: panel.rowSpacing
			model: panel.sourceNodes
			delegate: deviceDelegate

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
