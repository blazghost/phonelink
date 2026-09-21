import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// What the phone is playing, in the Omarchy bar: the track, and the buttons
// for it. Audio stays on the phone -- only the controls are here.
//
// `phonelink media --json` does the talking and prints one line of JSON; this
// widget only polls it and draws, the same arrangement as the phone widget, so
// no D-Bus runs inside the shell process and a phone that has gone quiet can
// never stall the bar.
//
// With nothing playing the widget takes no room at all, which is most of the
// day: a media control that is always there, always empty, is clutter.
BarWidget {
  id: root
  moduleName: "phonelink.media"

  // ------------------------------------------------------------- settings
  readonly property int interval: Math.max(2, Math.round(Number(setting("interval", 5)) || 5))
  readonly property bool hideWhenIdle: setting("hideWhenIdle", true) !== false
  readonly property bool showTitle: setting("showTitle", true) !== false
  readonly property int maxWidth: Math.max(60, Math.round(Number(setting("maxWidth", 180)) || 180))
  readonly property int volumeStep: Math.max(1, Math.min(50, Math.round(Number(setting("volumeStep", 5)) || 5)))
  // Normally just "phonelink" off PATH; a checkout that is not installed
  // can be pointed at here instead.
  readonly property string program: String(setting("command", "phonelink")).trim() || "phonelink"

  // ---------------------------------------------------------------- state
  property string state: "unknown"      // ok | away | hung | gone | unknown
  property string status: "idle"        // idle | playing | paused
  property string device: ""
  property string track: ""
  property string artist: ""
  property string album: ""
  property string player: ""
  property int volume: -1

  // The bar checks this before showing the tooltip it was asked for.
  property bool tooltipHovered: false

  readonly property bool loaded: state === "ok" && status !== "idle"
  readonly property bool playing: status === "playing"

  // Playing gets a speaker; paused keeps the same shape, dimmed, so the
  // widget does not jump about as a track pauses.
  readonly property string glyph: playing ? "󰎇" : "󰏤"
  readonly property color normalColor: bar ? bar.barForeground : Color.foreground
  readonly property color dimColor: Qt.darker(normalColor, 1.55)

  readonly property string tooltipText: {
    if (!loaded) return ""
    var parts = [root.track || root.player]
    if (root.artist !== "") parts.push(root.artist)
    if (root.album !== "") parts.push(root.album)
    var where = root.player || root.device
    if (root.volume >= 0) where += " · " + root.volume + "%"
    parts.push(where)
    parts.push(playing ? "Click to pause · right next · middle previous"
                       : "Click to play · right next · middle previous")
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
      root.status = "idle"
      return
    }
    root.state = String(data.state || "unknown")
    root.status = String(data.status || "idle")
    root.device = String(data.device || "")
    root.track = String(data.title || "")
    root.artist = String(data.artist || "")
    root.album = String(data.album || "")
    root.player = String(data.player || "")
    root.volume = (typeof data.volume === "number") ? data.volume : -1
  }

  // A command, then a fresh reading: pressing pause should not leave a play
  // glyph up until the next poll comes around.
  function control(verb) {
    if (!root.bar) return
    root.bar.run(root.quoted(root.program) + " media " + verb)
    settle.restart()
  }

  visible: root.loaded || !root.hideWhenIdle
  implicitWidth: !visible ? 0 : (vertical ? barSize : row.implicitWidth + Style.space(14))
  implicitHeight: !visible ? 0 : (vertical ? column.implicitHeight + Style.space(10) : barSize)

  Process {
    id: poll
    command: [root.program, "media", "--json"]
    stdout: SplitParser {
      onRead: function(line) { root.consume(line) }
    }
  }

  Timer {
    running: true      // keeps polling while hidden, or it could never come back
    interval: root.interval * 1000
    repeat: true
    triggeredOnStart: true
    onTriggered: if (!poll.running) poll.running = true
  }

  // The phone takes a moment to act on a button and report it back.
  Timer {
    id: settle
    interval: 700
    repeat: false
    onTriggered: if (!poll.running) poll.running = true
  }

  // ---------------------------------------------------------------- drawing

  Row {
    id: row
    visible: !root.vertical && root.loaded
    anchors.centerIn: parent
    spacing: Style.space(6)

    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.glyph
      color: root.playing ? root.normalColor : root.dimColor
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.showTitle && root.track !== ""
      text: root.track
      color: root.playing ? root.normalColor : root.dimColor
      elide: Text.ElideRight
      width: Math.min(implicitWidth, root.maxWidth)
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
    }
  }

  // The bar can stand on its side, and then only the glyph fits.
  Column {
    id: column
    visible: root.vertical && root.loaded
    anchors.centerIn: parent
    spacing: Style.space(2)

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: root.glyph
      color: root.playing ? root.normalColor : root.dimColor
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
    }
  }

  MouseArea {
    anchors.fill: parent
    enabled: root.loaded
    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
    cursorShape: Qt.PointingHandCursor
    hoverEnabled: true

    // Left is play/pause, the button anyone reaches for first; right skips
    // on, middle goes back. The wheel is volume, which is what a wheel over a
    // media widget does everywhere else.
    onClicked: function(mouse) {
      if (mouse.button === Qt.RightButton) {
        root.control("next")
      } else if (mouse.button === Qt.MiddleButton) {
        root.control("previous")
      } else {
        root.control("toggle")
      }
    }

    onWheel: function(wheel) {
      var up = wheel.angleDelta.y > 0
      root.control("volume " + (up ? "+" : "-") + root.volumeStep)
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
