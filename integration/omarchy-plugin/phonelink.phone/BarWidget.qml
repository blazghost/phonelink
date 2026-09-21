import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// The phone in the Omarchy bar: battery, cellular signal, and how many
// conversations are waiting for an answer.
//
// `phonelink bar` does the talking and prints one line of JSON; this widget
// only polls it and draws. That keeps D-Bus out of the shell process, so a
// phone that has gone quiet can never stall the bar -- the worst case is a
// check that times out on its own and a widget that keeps its last reading.
BarWidget {
  id: root
  moduleName: "phonelink.phone"

  // ------------------------------------------------------------- settings
  readonly property int interval: Math.max(5, Math.round(Number(setting("interval", 20)) || 20))
  readonly property bool showBattery: setting("showBattery", true) !== false
  readonly property bool showSignal: setting("showSignal", true) !== false
  readonly property bool showWaiting: setting("showWaiting", true) !== false
  // Normally just "phonelink" off PATH; a checkout that is not installed
  // can be pointed at here instead.
  readonly property string program: String(setting("command", "phonelink")).trim() || "phonelink"
  readonly property int lowBattery: Math.max(0, Math.min(100, Math.round(Number(setting("lowBattery", 20)) || 20)))

  // ---------------------------------------------------------------- state
  property string state: "unknown"      // ok | away | hung | gone | unknown
  property string device: ""
  property int battery: -1
  property bool charging: false
  property int bars: -1
  property string network: ""
  property int waiting: 0
  property var waitingFrom: []

  // The bar checks this before showing the tooltip it was asked for.
  property bool tooltipHovered: false

  readonly property bool connected: state === "ok"
  readonly property bool broken: state === "hung" || state === "gone"

  // A phone glyph while all is well, a warning triangle when KDE Connect
  // itself is the problem -- the same signal the toast service gives.
  readonly property string glyph: broken ? "󰀦" : (connected ? "󰄜" : "󰄞")
  readonly property color normalColor: bar ? bar.barForeground : Color.foreground
  readonly property color dimColor: Qt.darker(normalColor, 1.55)
  readonly property color urgentColor: bar ? bar.urgent : Color.urgent

  readonly property string batteryText: battery >= 0 ? battery + "%" : ""
  readonly property string signalText: bars >= 0 ? "▂".repeat(Math.max(1, bars)) : ""
  readonly property string tooltipText: {
    if (state === "gone") return "KDE Connect isn't running"
    if (state === "hung") return "KDE Connect isn't answering"
    if (state === "away") return "No phone reachable"
    if (!connected) return "phonelink"
    var parts = [device]
    if (battery >= 0) parts.push(battery + "%" + (charging ? ", charging" : ""))
    if (bars >= 0) parts.push((network || "signal") + " " + bars + "/4")
    if (waiting > 0) parts.push(waiting + (waiting === 1 ? " conversation waiting" : " conversations waiting"))
    if (waitingFrom.length > 0) parts.push(waitingFrom.join(", "))
    return parts.join(" · ")
  }

  // The bar API a plugin is handed has `run` but no shell quoting of its own,
  // so do it here: a phonelink kept somewhere with a space in the path would
  // otherwise arrive as two words.
  function quoted(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'"
  }

  function consume(line) {
    var text = String(line || "").trim()
    if (text === "") return
    var data
    try {
      data = JSON.parse(text)
    } catch (e) {
      root.state = "unknown"
      return
    }
    root.state = String(data.state || "unknown")
    root.device = String(data.device || "")
    root.battery = (typeof data.battery === "number") ? data.battery : -1
    root.charging = data.charging === true
    root.bars = (typeof data.bars === "number") ? data.bars : -1
    root.network = String(data.network || "")
    root.waiting = (typeof data.waiting === "number") ? data.waiting : 0
    root.waitingFrom = (data.from instanceof Array) ? data.from : []
  }

  implicitWidth: vertical ? barSize : row.implicitWidth + Style.space(14)
  implicitHeight: vertical ? column.implicitHeight + Style.space(10) : barSize

  Process {
    id: poll
    command: [root.program, "bar"]
    stdout: SplitParser {
      onRead: function(line) { root.consume(line) }
    }
  }

  Timer {
    running: root.visible
    interval: root.interval * 1000
    repeat: true
    triggeredOnStart: true
    onTriggered: if (!poll.running) poll.running = true
  }

  // ---------------------------------------------------------------- drawing

  Row {
    id: row
    visible: !root.vertical
    anchors.centerIn: parent
    spacing: Style.space(6)

    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.glyph
      color: root.broken ? root.urgentColor : (root.connected ? root.normalColor : root.dimColor)
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.showBattery && root.connected && root.batteryText !== ""
      text: root.batteryText
      color: root.battery >= 0 && root.battery <= root.lowBattery && !root.charging
             ? root.urgentColor : root.normalColor
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.showBattery && root.connected && root.charging
      text: "󰂄"  // a bolt, so a charging phone reads at a glance
      color: root.normalColor
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.caption
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.showSignal && root.connected && root.signalText !== ""
      text: root.signalText
      color: root.dimColor
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
    }

    Rectangle {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.showWaiting && root.connected && root.waiting > 0
      radius: height / 2
      color: root.urgentColor
      implicitWidth: Math.max(height, count.implicitWidth + Style.space(8))
      implicitHeight: count.implicitHeight + Style.space(2)

      Text {
        id: count
        anchors.centerIn: parent
        text: root.waiting
        color: root.bar ? root.bar.background : Color.background
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }
  }

  // The bar can stand on its side, and then the pieces stack instead.
  Column {
    id: column
    visible: root.vertical
    anchors.centerIn: parent
    spacing: Style.space(2)

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: root.glyph
      color: root.broken ? root.urgentColor : (root.connected ? root.normalColor : root.dimColor)
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      visible: root.showBattery && root.connected && root.battery >= 0
      text: root.battery
      color: root.battery <= root.lowBattery && !root.charging ? root.urgentColor : root.normalColor
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.caption
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      visible: root.showWaiting && root.connected && root.waiting > 0
      text: root.waiting
      color: root.urgentColor
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.caption
      font.bold: true
    }
  }

  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
    cursorShape: Qt.PointingHandCursor
    hoverEnabled: true

    // Left opens the texts, which is what a phone in a bar is for. Right
    // answers the newest notification; middle restarts KDE Connect, since a
    // widget showing the warning glyph is exactly when you want that.
    onClicked: function(mouse) {
      if (!root.bar) return
      if (mouse.button === Qt.RightButton) {
        root.bar.run(root.quoted(root.program) + " reply")
      } else if (mouse.button === Qt.MiddleButton) {
        root.bar.run(root.quoted(root.program) + " kde restart")
      } else {
        root.bar.run(root.quoted(root.program) + " messages")
      }
      poll.running = true
    }

    // The bar owns one shared tooltip popup; widgets ask it to show theirs.
    onEntered: {
      root.tooltipHovered = true
      if (root.bar && root.tooltipText !== "") root.bar.showTooltip(root, root.tooltipText)
    }
    onExited: {
      root.tooltipHovered = false
      if (root.bar) root.bar.hideTooltip(root)
    }
  }
}
