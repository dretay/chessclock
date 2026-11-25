// App Preview: the previewer's window on the Mac (tools/preview/preview.py builds and starts it).
//
//   "App Preview" --fb FILE --pipe FIFO --port N
//
// Shows the app's screen (FILE: 800x480, 32-bit BGRX, the file the app draws into) at its own frame
// rate, and turns the mouse into the touchscreen ("down/move/up X Y" lines into FIFO). The menus
// drive preview.py's engine over its local HTTP API (port N): the app, the time of day, the date,
// the app's live data, restart; and the log, screenshots, size and keep-on-top here.
import AppKit
import Foundation
import WebKit

let W = 800, H = 480

// ------------------------------------------------------------------ the screen file
final class Screen {
    let ptr: UnsafeMutableRawPointer
    init?(path: String) {
        let fd = open(path, O_RDONLY)
        guard fd >= 0 else { return nil }
        let p = mmap(nil, W * H * 4, PROT_READ, MAP_SHARED, fd, 0)
        close(fd)
        guard let p, p != MAP_FAILED else { return nil }
        ptr = p
    }
    func image() -> CGImage? {
        guard let data = CFDataCreate(nil, ptr.assumingMemoryBound(to: UInt8.self), W * H * 4),
              let provider = CGDataProvider(data: data) else { return nil }
        // B, G, R, X in memory: a little-endian 32-bit XRGB word
        let info = CGBitmapInfo(rawValue: CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.noneSkipFirst.rawValue)
        return CGImage(width: W, height: H, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: W * 4,
                       space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: info, provider: provider,
                       decode: nil, shouldInterpolate: false, intent: .defaultIntent)
    }
}

// ------------------------------------------------------------------ the view: screen and touch
final class ScreenView: NSView {
    var touch: (String) -> Void = { _ in }
    var lastMove = 0.0
    // erasing lights (the Controls panel): a drag is a brush, not a touch; on release, its circles go to onStroke
    var erasing = false, adding = false
    var onStroke: ([[Int]]) -> Void = { _ in }
    var onAdd: (Int, Int) -> Void = { _, _ in }
    var onDropFile: (URL) -> Void = { _ in }
    var onZoom: (CGFloat) -> Void = { _ in }
    // laying out (the Scene Builder): "cards" (drag the countdown's outline) or "horizon" (drag the line)
    var layoutMode = ""
    var cardW = 138, cardH = 192, cardGap = 12
    var onLayout: ([String: Any]) -> Void = { _ in }
    let guideLayer = CAShapeLayer()
    var stroke: [[Int]] = []
    var brush = 10
    var brushTarget = "erase"                        // "erase" (the orb's lights), "wpaint" / "werase" (window glass), "qpaint" / "qerase" (water)
    var onPaint: (String, [[Int]]) -> Void = { _, _ in }
    private var boxStart: (Int, Int)? = nil
    let strokeLayer = CAShapeLayer()
    // zoom: the part of the screen shown (in its own pixels), magnified; pinch, two-finger scroll, the View menu
    private(set) var zoom: CGFloat = 1
    private var vx0: CGFloat = 0, vy0: CGFloat = 0
    private var lastImage: CGImage?
    // what "find automatically" found, over the picture for a moment (an 800x480 picture, faded out)
    let flashLayer = CALayer()
    private var flashImage: CGImage?

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.contentsGravity = .resize
        layer?.magnificationFilter = .nearest            // (the device's own pixels, crisp)
        layer?.backgroundColor = NSColor.black.cgColor
        flashLayer.contentsGravity = .resize; flashLayer.magnificationFilter = .nearest; flashLayer.opacity = 0
        layer?.addSublayer(flashLayer)
        strokeLayer.fillColor = NSColor(red: 1, green: 0.24, blue: 0.24, alpha: 0.35).cgColor
        layer?.addSublayer(strokeLayer)
        guideLayer.fillColor = NSColor(red: 0.89, green: 0.75, blue: 0.47, alpha: 0.18).cgColor
        guideLayer.strokeColor = NSColor(red: 0.89, green: 0.75, blue: 0.47, alpha: 0.95).cgColor
        guideLayer.lineWidth = 2
        layer?.addSublayer(guideLayer)
        registerForDraggedTypes([.fileURL])
    }
    required init?(coder: NSCoder) { fatalError() }
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // a photo dropped on the picture: the Scene Builder makes a trial of it
    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        sender.draggingPasteboard.canReadObject(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) ? .copy : []
    }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        guard let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL],
              let u = urls.first else { return false }
        onDropFile(u); return true
    }
    override func layout() { super.layout(); for l in [strokeLayer, guideLayer, flashLayer] as [CALayer] { l.frame = bounds } }

    // ---------------------------------------------------------------- the picture, and the zoom
    private var visW: CGFloat { CGFloat(W) / zoom }
    private var visH: CGFloat { CGFloat(H) / zoom }
    private var visible: CGRect { CGRect(x: vx0, y: vy0, width: visW, height: visH) }   // (the screen's pixels, top-left origin)
    private func crop(_ img: CGImage?) -> CGImage? {
        guard let img else { return nil }
        if zoom <= 1.001 { return img }
        let sx = CGFloat(img.width) / CGFloat(W), sy = CGFloat(img.height) / CGFloat(H)
        return img.cropping(to: CGRect(x: vx0 * sx, y: vy0 * sy, width: visW * sx, height: visH * sy).integral)
    }
    func show(_ image: CGImage) { lastImage = image; layer?.contents = crop(image) }
    private func redisplay() {
        CATransaction.begin(); CATransaction.setDisableActions(true)
        if let img = lastImage { layer?.contents = crop(img) }
        flashLayer.contents = crop(flashImage)
        CATransaction.commit()
        drawStroke(); guideLayer.path = nil
        onZoom(zoom)
    }
    /* zoom to z (1 to 8), keeping the screen point (sx, sy) where it is in the view */
    func setZoom(_ z: CGFloat, around: (CGFloat, CGFloat)? = nil) {
        let nz = max(1, min(8, z))
        let (sx, sy) = around ?? (vx0 + visW / 2, vy0 + visH / 2)
        let fx = (sx - vx0) / visW, fy = (sy - vy0) / visH
        zoom = nz
        vx0 = sx - fx * visW; vy0 = sy - fy * visH
        clampView(); redisplay()
    }
    private func clampView() { vx0 = max(0, min(CGFloat(W) - visW, vx0)); vy0 = max(0, min(CGFloat(H) - visH, vy0)) }
    override func magnify(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        setZoom(zoom * (1 + event.magnification), around: screenXY(p))
    }
    override func scrollWheel(with event: NSEvent) {
        // a mouse wheel (deltas in lines, not points): zoom, around the pointer; the middle button moves around
        if !event.hasPreciseScrollingDeltas {
            let dy = event.scrollingDeltaY
            if dy == 0 { return }
            let p = convert(event.locationInWindow, from: nil)
            setZoom(zoom * (dy > 0 ? 1.25 : 0.8), around: screenXY(p))
            return
        }
        // a trackpad: two fingers move a zoomed picture (it follows the fingers, as everywhere on a Mac); pinch zooms
        if zoom <= 1.001 { super.scrollWheel(with: event); return }
        pan(by: -event.scrollingDeltaX, event.scrollingDeltaY)
    }
    /* move the zoomed view by (dx, dy) view points, the picture following the pointer */
    func pan(by dx: CGFloat, _ dy: CGFloat) {
        if zoom <= 1.001 { return }
        vx0 += dx / k; vy0 -= dy / k
        clampView(); redisplay()
    }
    // the arrow keys move around too
    override func keyDown(with event: NSEvent) {
        let step: CGFloat = 40
        switch event.keyCode {
        case 123: pan(by: -step, 0)                     // (left)
        case 124: pan(by: step, 0)                      // (right)
        case 125: pan(by: 0, -step)                     // (down)
        case 126: pan(by: 0, step)                      // (up)
        default: super.keyDown(with: event)
        }
    }

    // ---------------------------------------------------------------- screen pixels <-> the view
    private func screenXY(_ p: CGPoint) -> (CGFloat, CGFloat) {
        (vx0 + p.x / bounds.width * visW, vy0 + (bounds.height - p.y) / bounds.height * visH)
    }
    private func screenPoint(_ event: NSEvent) -> (Int, Int) {
        let (x, y) = screenXY(convert(event.locationInWindow, from: nil))
        return (max(0, min(W - 1, Int(x))), max(0, min(H - 1, Int(y))))
    }
    private func toView(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
        CGPoint(x: (x - vx0) * bounds.width / visW, y: bounds.height - (y - vy0) * bounds.height / visH)
    }
    private var k: CGFloat { bounds.width / visW }    // (view points per screen pixel)

    // ---------------------------------------------------------------- what was found, for a moment
    func flash(_ image: CGImage) {
        flashImage = image
        CATransaction.begin(); CATransaction.setDisableActions(true)
        flashLayer.removeAllAnimations(); flashLayer.contents = crop(image); flashLayer.opacity = 0
        CATransaction.commit()
        let fade = CAKeyframeAnimation(keyPath: "opacity")
        fade.values = [0, 1, 1, 0]; fade.keyTimes = [0, 0.08, 0.45, 1]; fade.duration = 4.0
        flashLayer.add(fade, forKey: "flash")
    }

    // ---------------------------------------------------------------- the guides and the brush
    private func drawGuide(_ x: Int, _ y: Int) {
        let path = CGMutablePath()
        if layoutMode == "wrect" || layoutMode == "qrect", let (sx, sy) = boxStart {   // (a window's or water's box, from where the drag began)
            let a = toView(CGFloat(min(sx, x)), CGFloat(min(sy, y))), b = toView(CGFloat(max(sx, x) + 1), CGFloat(max(sy, y) + 1))
            path.addRect(CGRect(x: a.x, y: b.y, width: b.x - a.x, height: a.y - b.y))
        } else if layoutMode == "cards" {                // (two digits' row, centred where the pointer is)
            let w = CGFloat(2 * cardW + cardGap) * k, h = CGFloat(cardH) * k, c = toView(CGFloat(x), CGFloat(y))
            path.addRect(CGRect(x: c.x - w / 2, y: c.y - h / 2, width: w, height: h))
        } else if layoutMode == "horizon" {
            let c = toView(0, CGFloat(y))
            path.move(to: CGPoint(x: 0, y: c.y)); path.addLine(to: CGPoint(x: bounds.width, y: c.y))
        }
        guideLayer.path = path
    }
    private func layoutDone(_ x: Int, _ y: Int) {
        guideLayer.path = nil
        if layoutMode == "wrect" || layoutMode == "qrect", let (sx, sy) = boxStart {
            boxStart = nil
            if abs(x - sx) >= 1 && abs(y - sy) >= 1 { onLayout([layoutMode == "wrect" ? "winrect" : "waterrect": [sx, sy, x, y]]) }
        } else if layoutMode == "cards" { onLayout(["cards": ["center_x": x, "top": max(0, y - cardH / 2)]]) }
        else if layoutMode == "horizon" { onLayout(["horizon": y]) }
    }
    func strokeColour() {
        strokeLayer.fillColor = (brushTarget == "wpaint" ? NSColor(red: 1, green: 0.72, blue: 0.3, alpha: 0.45)
                               : brushTarget == "qpaint" ? NSColor(red: 0.3, green: 0.8, blue: 1, alpha: 0.4)
                                                          : NSColor(red: 1, green: 0.24, blue: 0.24, alpha: 0.35)).cgColor
    }
    private func drawStroke() {
        let path = CGMutablePath()
        for c in stroke {
            let r = CGFloat(c[2]) * k, p = toView(CGFloat(c[0]) + 0.5, CGFloat(c[1]) + 0.5)
            path.addEllipse(in: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r))
        }
        strokeLayer.path = path
    }

    // ---------------------------------------------------------------- the mouse
    private func send(_ kind: String, _ event: NSEvent) { let (x, y) = screenPoint(event); touch("\(kind) \(x) \(y)") }
    // moving around a zoomed picture: a drag with nothing else to do (no brush, box or guide), or with
    // Option held (in any mode); a click without moving is still a tap
    private var panFrom: CGPoint? = nil, panMoved = false, panPending: NSEvent? = nil
    private func wantsPan(_ event: NSEvent) -> Bool {
        zoom > 1.001 && (event.modifierFlags.contains(.option) || (layoutMode.isEmpty && !erasing && !adding))
    }
    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        if wantsPan(event) {
            panFrom = convert(event.locationInWindow, from: nil); panMoved = false
            panPending = event.modifierFlags.contains(.option) ? nil : event      // (a tap, if it doesn't move)
            return
        }
        if !layoutMode.isEmpty { let (x, y) = screenPoint(event); if layoutMode == "wrect" || layoutMode == "qrect" { boxStart = (x, y) }; drawGuide(x, y); return }
        if adding { return }
        if erasing { let (x, y) = screenPoint(event); stroke = [[x, y, brush]]; drawStroke(); return }
        send("down", event)
    }
    override func mouseUp(with event: NSEvent) {
        if panFrom != nil {
            panFrom = nil; NSCursor.arrow.set()
            if !panMoved, let down = panPending { send("down", down); send("up", event) }   // (it didn't move: a tap)
            panPending = nil
            return
        }
        if !layoutMode.isEmpty { let (x, y) = screenPoint(event); layoutDone(x, y); return }
        if adding { let (x, y) = screenPoint(event); onAdd(x, y); return }
        if erasing {
            let s = stroke; stroke = []; drawStroke()
            if !s.isEmpty { if brushTarget == "erase" { onStroke(s) } else { onPaint(brushTarget, s) } }
            return
        }
        send("up", event)
    }
    // the middle button: moving around a zoomed picture, in any mode (the left button stays the brush)
    private var middleFrom: CGPoint? = nil
    override func otherMouseDown(with event: NSEvent) {
        if event.buttonNumber == 2 && zoom > 1.001 { middleFrom = convert(event.locationInWindow, from: nil); NSCursor.closedHand.set() }
        else { super.otherMouseDown(with: event) }
    }
    override func otherMouseDragged(with event: NSEvent) {
        guard let from = middleFrom else { super.otherMouseDragged(with: event); return }
        let p = convert(event.locationInWindow, from: nil)
        pan(by: from.x - p.x, from.y - p.y); middleFrom = p
    }
    override func otherMouseUp(with event: NSEvent) {
        if middleFrom != nil { middleFrom = nil; NSCursor.arrow.set() } else { super.otherMouseUp(with: event) }
    }
    override func mouseDragged(with event: NSEvent) {
        if let from = panFrom {
            let p = convert(event.locationInWindow, from: nil)
            if !panMoved && hypot(p.x - from.x, p.y - from.y) < 3 { return }
            panMoved = true
            pan(by: from.x - p.x, from.y - p.y); panFrom = p
            NSCursor.closedHand.set()
            return
        }
        if !layoutMode.isEmpty { let (x, y) = screenPoint(event); drawGuide(x, y); return }
        if adding { return }
        if erasing {
            let (x, y) = screenPoint(event)
            if let last = stroke.last {                  // (fill in between, so a quick stroke leaves no gaps)
                let dx = x - last[0], dy = y - last[1], n = max(abs(dx), abs(dy)) / max(1, brush / 2)
                if n > 1 { for i in 1..<n { stroke.append([last[0] + dx * i / n, last[1] + dy * i / n, brush]) } }
            }
            stroke.append([x, y, brush]); drawStroke(); return
        }
        if event.timestamp - lastMove > 0.04 { lastMove = event.timestamp; send("move", event) }
    }
}

// ------------------------------------------------------------------ the app
final class Controller: NSObject, NSApplicationDelegate, NSWindowDelegate, WKScriptMessageHandler, WKUIDelegate {
    let fbPath: String, pipePath: String, port: Int
    var screen: Screen?
    var pipeFD: Int32 = -1
    var window: NSWindow!
    var view: ScreenView!
    var logPanel: NSPanel!
    var logView: NSTextView!
    var controlPanel: NSPanel!
    var builderPanel: NSPanel!, builder: WKWebView!
    var hourSlider: NSSlider!, hourLabel: NSTextField!, liveBox: NSButton!
    var hourSent: TimeInterval = 0
    var eraseBox: NSPopUpButton!, eraseNote: NSTextField!, patternMenu: NSPopUpButton!
    let appMenu = NSMenu(title: "App"), timeMenu = NSMenu(title: "Time")
    var liveDataItem: NSMenuItem!, onTopItem: NSMenuItem!
    var state: [String: Any] = [:]
    var appsShown: [String] = []
    var lastLog = ""

    init(fb: String, pipe: String, port: Int) { fbPath = fb; pipePath = pipe; self.port = port }

    func applicationDidFinishLaunching(_ note: Notification) {
        screen = Screen(path: fbPath)
        pipeFD = open(pipePath, O_WRONLY | O_NONBLOCK)
        view = ScreenView(frame: NSRect(x: 0, y: 0, width: W, height: H))
        view.touch = { [weak self] line in self?.writeTouch(line) }
        view.onStroke = { [weak self] s in self?.erase(["erase": s]) }
        view.onAdd = { [weak self] x, y in self?.erase(["add": [[x, y]]]) }
        view.onDropFile = { [weak self] u in self?.uploadPhoto(u) }
        view.onZoom = { [weak self] z in self?.showZoom(z) }
        view.onLayout = { [weak self] change in
            if let r = change["winrect"] { self?.region("windows", ["rect": r]) }
            else if let r = change["waterrect"] { self?.region("water", ["rect": r]) }
            else { self?.layout(change) }
        }
        view.onPaint = { [weak self] target, s in
            self?.region(target.hasPrefix("q") ? "water" : "windows", [target.hasSuffix("paint") ? "paint" : "erase": s])
        }
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: W, height: H),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.contentView = view
        window.contentAspectRatio = NSSize(width: W, height: H)
        window.contentMinSize = NSSize(width: W / 2, height: H / 2)
        window.title = "App Preview"
        window.delegate = self
        window.setFrameAutosaveName("AppPreviewWindow")
        if !window.setFrameUsingName("AppPreviewWindow") { window.center() }
        window.makeKeyAndOrderFront(nil)
        makeLogPanel()
        makeControlPanel()
        makeBuilderPanel()
        makeMenus()
        Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in self?.frame() }
        Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.poll() }
        poll()
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ note: Notification) { if (note.object as? NSWindow) === window { NSApp.terminate(nil) } }

    func frame() {
        if screen == nil { screen = Screen(path: fbPath) }
        if let img = screen?.image() { view.show(img) }
    }

    func writeTouch(_ line: String) {
        if pipeFD < 0 { pipeFD = open(pipePath, O_WRONLY | O_NONBLOCK) }
        let data = Array((line + "\n").utf8)
        _ = data.withUnsafeBufferPointer { write(pipeFD, $0.baseAddress, $0.count) }
    }

    // ---------------------------------------------------------------- the engine (preview.py)
    func url(_ path: String) -> URL { URL(string: "http://127.0.0.1:\(port)\(path)")! }

    func control(_ body: [String: Any]) {
        var req = URLRequest(url: url("/control"))
        req.httpMethod = "POST"
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self?.poll() }
        }.resume()
    }

    func poll() {
        URLSession.shared.dataTask(with: url("/state")) { [weak self] data, _, _ in
            guard let data, let s = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            DispatchQueue.main.async { self?.update(s) }
        }.resume()
    }

    func update(_ s: [String: Any]) {
        state = s
        let apps = (s["apps"] as? [[String]]) ?? []
        let current = s["app"] as? String ?? ""
        let name = apps.first(where: { $0.first == current })?.last ?? current
        window.title = "App Preview — \(name)" + (view.zoom > 1.01 ? " — \(Int((view.zoom * 100).rounded()))%" : "")
        let ids = apps.map { $0.joined(separator: "=") }
        if ids != appsShown { appsShown = ids; rebuildAppMenu(apps) }
        for item in appMenu.items where item.representedObject is String {
            item.state = (item.representedObject as? String) == current ? .on : .off
        }
        let hour = s["hour"] as? String ?? ""
        let countdown = s["countdown"] as? Bool ?? false
        if NSApp.currentEvent?.type != .leftMouseDragged {        // (the slider and box follow the menu, not fight a drag)
            liveBox.state = hour.isEmpty ? .on : .off
            if let h = Double(hour) { hourSlider.doubleValue = h }
            showHour()
        }
        hourSlider.isEnabled = countdown
        for item in timeMenu.items {
            if let h = item.representedObject as? String { item.state = h == hour ? .on : .off }
            item.isEnabled = countdown
        }
        liveDataItem.state = (s["service"] as? Bool ?? false) ? .on : .off
        liveDataItem.isEnabled = s["has_service"] as? Bool ?? false
        let log = ((s["log"] as? [String]) ?? []).joined(separator: "\n")
        if log != lastLog {
            lastLog = log
            let atEnd = (logView.enclosingScrollView?.verticalScroller?.floatValue ?? 1) > 0.98
            logView.string = log
            if atEnd { logView.scrollToEndOfDocument(nil) }
        }
    }

    // ---------------------------------------------------------------- menus
    func item(_ title: String, _ action: Selector, _ key: String = "", _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
        i.keyEquivalentModifierMask = mods
        i.target = self
        return i
    }

    func makeMenus() {
        let main = NSMenu()
        let top = NSMenuItem(); main.addItem(top)
        let appSide = NSMenu()
        appSide.addItem(withTitle: "Hide App Preview", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appSide.addItem(.separator())
        appSide.addItem(withTitle: "Quit App Preview", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        top.submenu = appSide

        let appTop = NSMenuItem(); main.addItem(appTop); appTop.submenu = appMenu
        rebuildAppMenu([])

        let timeTop = NSMenuItem(); main.addItem(timeTop); timeTop.submenu = timeMenu
        for (title, hour) in [("Live (this Mac's clock)", ""), ("Morning (9 AM)", "9"), ("Noon", "12"),
                              ("Dusk (6:30 PM)", "18.5"), ("Evening (8 PM)", "20"), ("Night (10 PM)", "22")] {
            let i = item(title, #selector(setHour(_:))); i.representedObject = hour; timeMenu.addItem(i)
        }
        timeMenu.addItem(.separator())
        timeMenu.addItem(item("Pretend It's…", #selector(pretendDate), "d"))
        timeMenu.addItem(item("Today", #selector(today)))

        let dataMenu = NSMenu(title: "Data"); let dataTop = NSMenuItem(); main.addItem(dataTop); dataTop.submenu = dataMenu
        liveDataItem = item("Live Data (its background job)", #selector(toggleLiveData), "l")
        dataMenu.addItem(liveDataItem)
        dataMenu.addItem(item("Open Data Folder", #selector(openData)))

        let viewMenu = NSMenu(title: "View"); let viewTop = NSMenuItem(); main.addItem(viewTop); viewTop.submenu = viewMenu
        viewMenu.addItem(item("Actual Size", #selector(actualSize), "0"))
        viewMenu.addItem(item("Double Size", #selector(doubleSize), "="))
        onTopItem = item("Keep on Top", #selector(toggleOnTop), "t")
        viewMenu.addItem(onTopItem)
        viewMenu.addItem(.separator())
        viewMenu.addItem(item("Show Log", #selector(toggleLog), "j"))
        viewMenu.addItem(item("Show Controls", #selector(toggleControls), "k"))
        viewMenu.addItem(item("Scene Builder", #selector(toggleBuilder), "b"))
        viewMenu.addItem(.separator())
        viewMenu.addItem(item("Zoom In", #selector(zoomIn), "=", [.command, .option]))
        viewMenu.addItem(item("Zoom Out", #selector(zoomOut), "-", [.command, .option]))
        viewMenu.addItem(item("Zoom to Fit", #selector(zoomFit), "0", [.command, .option]))
        viewMenu.addItem(item("Save Screenshot to Desktop", #selector(screenshot), "s"))
        NSApp.mainMenu = main
    }

    func rebuildAppMenu(_ apps: [[String]]) {
        appMenu.removeAllItems()
        for (n, a) in apps.enumerated() where a.count == 2 {
            let i = item(a[1], #selector(pickApp(_:)), n < 9 ? "\(n + 1)" : "")
            i.representedObject = a[0]; appMenu.addItem(i)
        }
        appMenu.addItem(.separator())
        appMenu.addItem(item("Restart", #selector(restart), "r"))
    }

    @objc func pickApp(_ sender: NSMenuItem) { if let id = sender.representedObject as? String { control(["app": id]) } }
    @objc func restart() { control([:]) }
    @objc func setHour(_ sender: NSMenuItem) { control(["hour": sender.representedObject as? String ?? ""]) }
    @objc func today() { control(["now": ""]) }
    @objc func toggleLiveData() { control(["service": !((state["service"] as? Bool) ?? false)]) }

    @objc func pretendDate() {
        let alert = NSAlert()
        alert.messageText = "Pretend it's…"
        alert.informativeText = "A date and time, e.g. 2027-02-15T20:30 (the trip's last evening)."
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 240, height: 24))
        field.stringValue = (state["now"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "2027-02-15T20:30"
        alert.accessoryView = field
        alert.addButton(withTitle: "Set"); alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = field
        if alert.runModal() == .alertFirstButtonReturn { control(["now": field.stringValue.trimmingCharacters(in: .whitespaces)]) }
    }

    @objc func openData() {
        let dir = URL(fileURLWithPath: fbPath).deletingLastPathComponent().appendingPathComponent("data")
            .appendingPathComponent(state["app"] as? String ?? "")
        NSWorkspace.shared.open(dir)
    }

    func resize(_ scale: CGFloat) {
        var f = window.frame
        let content = NSSize(width: CGFloat(W) * scale, height: CGFloat(H) * scale)
        let r = window.frameRect(forContentRect: NSRect(origin: .zero, size: content))
        f.origin.y += f.size.height - r.size.height
        f.size = r.size
        window.setFrame(f, display: true, animate: true)
    }
    @objc func actualSize() { resize(1) }
    @objc func doubleSize() { resize(2) }
    @objc func toggleOnTop() {
        window.level = window.level == .floating ? .normal : .floating
        onTopItem.state = window.level == .floating ? .on : .off
    }

    func makeLogPanel() {
        logPanel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 720, height: 280),
                           styleMask: [.titled, .closable, .resizable, .utilityWindow], backing: .buffered, defer: true)
        logPanel.title = "Log"
        logPanel.hidesOnDeactivate = false
        logPanel.setFrameAutosaveName("AppPreviewLog")
        let scroll = NSScrollView(frame: logPanel.contentView!.bounds)
        scroll.autoresizingMask = [.width, .height]
        scroll.hasVerticalScroller = true
        logView = NSTextView(frame: scroll.bounds)
        logView.isEditable = false
        logView.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        logView.autoresizingMask = [.width]
        scroll.documentView = logView
        logPanel.contentView = scroll
    }
    // ---------------------------------------------------------------- the controls: time of day, fireworks
    func makeControlPanel() {
        controlPanel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 300, height: 286),
                               styleMask: [.titled, .closable, .utilityWindow], backing: .buffered, defer: false)
        controlPanel.title = "Controls"
        controlPanel.hidesOnDeactivate = false
        controlPanel.setFrameAutosaveName("AppPreviewControls")
        let v = NSView(frame: controlPanel.contentView!.bounds)
        hourLabel = NSTextField(labelWithString: "Time of day")
        hourLabel.frame = NSRect(x: 14, y: 256, width: 272, height: 18)
        hourSlider = NSSlider(value: 12, minValue: 0, maxValue: 24, target: self, action: #selector(hourMoved(_:)))
        hourSlider.isContinuous = true
        hourSlider.frame = NSRect(x: 12, y: 228, width: 276, height: 24)
        liveBox = NSButton(checkboxWithTitle: "This Mac's clock", target: self, action: #selector(liveClock(_:)))
        liveBox.frame = NSRect(x: 12, y: 202, width: 200, height: 20)
        let fw = NSButton(title: "Fireworks", target: self, action: #selector(fireworks))
        fw.frame = NSRect(x: 10, y: 140, width: 110, height: 30)
        let show = NSButton(title: "Nightly show", target: self, action: #selector(nightlyShow))
        show.frame = NSRect(x: 124, y: 140, width: 130, height: 30)
        let showLabel = NSTextField(labelWithString: "Lights' show")
        showLabel.frame = NSRect(x: 14, y: 112, width: 100, height: 18)
        patternMenu = NSPopUpButton(frame: NSRect(x: 110, y: 106, width: 180, height: 28), pullsDown: false)
        for (title, id) in [("All in turn", -1), ("Spin", 3), ("Rise", 4), ("Spiral", 7), ("Comet", 8), ("Wash", 5), ("Heartbeat", 9),
                            ("Sparkle", 6), ("Waves", 0), ("Rings", 1), ("Blink", 2)] {
            patternMenu.addItem(withTitle: title); patternMenu.lastItem?.tag = id
        }
        patternMenu.target = self; patternMenu.action = #selector(patternPicked(_:))
        let editLabel = NSTextField(labelWithString: "Edit lights")
        editLabel.frame = NSRect(x: 14, y: 82, width: 100, height: 18)
        eraseBox = NSPopUpButton(frame: NSRect(x: 110, y: 76, width: 110, height: 28), pullsDown: false)
        eraseBox.addItems(withTitles: ["Off", "Erase", "Add"])
        eraseBox.target = self; eraseBox.action = #selector(editMode(_:))
        let undo = NSButton(title: "Undo", target: self, action: #selector(undoErase))
        undo.frame = NSRect(x: 222, y: 74, width: 70, height: 30)
        eraseNote = NSTextField(labelWithString: "")
        eraseNote.frame = NSRect(x: 14, y: 12, width: 272, height: 34)
        eraseNote.font = NSFont.systemFont(ofSize: 11); eraseNote.textColor = .secondaryLabelColor
        eraseNote.maximumNumberOfLines = 2; eraseNote.lineBreakMode = .byWordWrapping
        let stay = NSButton(checkboxWithTitle: "Stay on the scene (screens wait)", target: self, action: #selector(stayOnScene(_:)))
        stay.frame = NSRect(x: 12, y: 178, width: 270, height: 20); stay.state = .on
        for c in [hourLabel!, hourSlider!, liveBox!, stay, fw, show, showLabel, patternMenu!, editLabel, eraseBox!, undo, eraseNote!] as [NSView] { v.addSubview(c) }
        controlPanel.contentView = v
        if !controlPanel.setFrameUsingName("AppPreviewControls") {
            let f = window.frame
            controlPanel.setFrameTopLeftPoint(NSPoint(x: f.maxX + 8, y: f.maxY))
        }
        controlPanel.orderFront(nil)
    }
    func clock(_ h: Double) -> String {
        let m = Int((h * 60).rounded()) % 1440
        return String(format: "%d:%02d %@", (m / 60) % 12 == 0 ? 12 : (m / 60) % 12, m % 60, m >= 720 ? "PM" : "AM")
    }
    func showHour() { hourLabel.stringValue = "Time of day: " + (liveBox.state == .on ? "now" : clock(hourSlider.doubleValue)) }
    @objc func hourMoved(_ sender: NSSlider) {       // (as it's dragged: the scene follows, no restart)
        liveBox.state = .off; showHour()
        let t = Date().timeIntervalSince1970
        let done = NSApp.currentEvent?.type == .leftMouseUp
        if done || t - hourSent > 0.08 { hourSent = t; control(["hour": String(format: "%.2f", sender.doubleValue)]) }
    }
    @objc func liveClock(_ sender: NSButton) {
        showHour(); control(["hour": sender.state == .on ? "" : String(format: "%.2f", hourSlider.doubleValue)])
    }
    @objc func fireworks() { control(["fireworks": true]) }
    @objc func stayOnScene(_ sender: NSButton) { control(["stay": sender.state == .on]) }
    func toNight() { liveBox.state = .off; hourSlider.doubleValue = 22; showHour(); control(["hour": "22"]) }
    @objc func editMode(_ sender: NSPopUpButton) {      // (at night, so the lights show)
        view.erasing = sender.indexOfSelectedItem == 1; view.adding = sender.indexOfSelectedItem == 2
        if view.erasing || view.adding { toNight() }
        eraseNote.stringValue = view.erasing ? "Drag over lights to rub them out; Undo takes the last edit back."
                              : view.adding ? "Click where a light should go; Undo takes the last edit back." : ""
    }
    @objc func patternPicked(_ sender: NSPopUpButton) {
        let id = sender.selectedItem?.tag ?? -1
        if id >= 0 { toNight() }
        control(["pattern": id])
    }
    @objc func undoErase() { erase(["undo": true]) }
    func erase(_ body: [String: Any]) {
        var req = URLRequest(url: url("/lights"))
        req.httpMethod = "POST"
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { [weak self] data, _, _ in
            guard let data, let r = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            DispatchQueue.main.async {
                if let e = r["error"] as? String { self?.eraseNote.stringValue = e }
                else { self?.eraseNote.stringValue = "\(r["lights"] ?? "?") lights · \(r["edits"] ?? 0) edits" }
                if let js = String(data: data, encoding: .utf8) { self?.builder?.evaluateJavaScript("window.lightsChanged && window.lightsChanged(\(js))") }
            }
        }.resume()
    }

    // ---------------------------------------------------------------- the Scene Builder (builder.html, in a panel)
    func makeBuilderPanel() {
        builderPanel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 360, height: 680),
                               styleMask: [.titled, .closable, .resizable, .utilityWindow], backing: .buffered, defer: false)
        builderPanel.title = "Scene Builder"
        builderPanel.hidesOnDeactivate = false
        builderPanel.setFrameAutosaveName("AppPreviewBuilder")
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "preview")
        builder = WKWebView(frame: builderPanel.contentView!.bounds, configuration: config)
        builder.autoresizingMask = [.width, .height]
        builder.uiDelegate = self
        builderPanel.contentView = builder
        builder.load(URLRequest(url: url("/builder")))
        if !builderPanel.setFrameUsingName("AppPreviewBuilder") {
            let f = window.frame
            builderPanel.setFrameTopLeftPoint(NSPoint(x: f.maxX + 8 + 308, y: f.maxY))
        }
        builderPanel.orderFront(nil)
    }
    @objc func toggleBuilder() { if builderPanel.isVisible { builderPanel.orderOut(nil) } else { builderPanel.orderFront(nil); builder.reload() } }
    // the page's messages: the picture's editing mode
    func userContentController(_ uc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        if let z = body["zoom"] as? String { if z == "in" { zoomIn() } else if z == "out" { zoomOut() } else { zoomFit() }; return }
        if let kind = body["flash"] as? String { flash(kind); return }
        if body["askPassphrase"] != nil { askPassphrase(); return }
        guard let mode = body["editMode"] as? String else { return }
        view.erasing = ["erase", "wpaint", "werase", "qpaint", "qerase"].contains(mode); view.adding = mode == "add"
        view.brushTarget = view.erasing ? mode : "erase"; view.strokeColour()
        if let b = body["brush"] as? Int { view.brush = mode == "erase" ? 10 : b }
        view.layoutMode = ["cards", "horizon", "wrect", "qrect"].contains(mode) ? mode : ""
        if let w = body["cardW"] as? Int { view.cardW = w }
        if let h = body["cardH"] as? Int { view.cardH = h }
        if let g = body["gap"] as? Int { view.cardGap = g }
        eraseBox.selectItem(at: mode == "erase" ? 1 : mode == "add" ? 2 : 0)
    }
    // window glass painted, rubbed out or boxed on the picture
    func region(_ kind: String, _ body: [String: Any]) {
        var req = URLRequest(url: url("/" + kind))
        req.httpMethod = "POST"; req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.async { self?.builder.evaluateJavaScript("window.layoutChanged && window.layoutChanged()") }
        }.resume()
    }
    // a drag's result: the countdown's place, or the horizon, for the scene showing
    func layout(_ change: [String: Any]) {
        var body = change; body["action"] = "layout"
        var req = URLRequest(url: url("/builder/do"))
        req.httpMethod = "POST"; req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.async { self?.builder.evaluateJavaScript("window.layoutChanged && window.layoutChanged()") }
        }.resume()
    }
    // ---------------------------------------------------------------- zoom, and what was found
    @objc func zoomIn() { view.setZoom(view.zoom * 1.6) }
    @objc func zoomOut() { view.setZoom(view.zoom / 1.6) }
    @objc func zoomFit() { view.setZoom(1) }
    func showZoom(_ z: CGFloat) {
        let name = window.title.components(separatedBy: " — ").prefix(2).joined(separator: " — ")
        window.title = z > 1.01 ? "\(name) — \(Int((z * 100).rounded()))%" : name
    }
    /* what "find automatically" found (kind: sky, orb, windows, water), over the picture for a few seconds */
    func flash(_ kind: String) {
        URLSession.shared.dataTask(with: url("/builder/outline?kind=\(kind)")) { [weak self] data, _, _ in
            guard let data, let img = NSImage(data: data), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return }
            DispatchQueue.main.async { self?.view.flash(cg) }
        }.resume()
    }
    /* the signing key's passphrase, for Install (signed): a dialog with its text hidden; the answer to the page
       (window.passphraseGiven: the text, or null if cancelled), used for that install and kept nowhere */
    func askPassphrase() {
        let alert = NSAlert()
        alert.messageText = "Passphrase for your signing key"
        alert.informativeText = "To sign the app for the device (~/.config/licheepi-nano/module-signing.pem)."
        let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 260, height: 24))
        alert.accessoryView = field; alert.addButton(withTitle: "Install"); alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = field
        alert.beginSheetModal(for: builderPanel) { [weak self] r in
            var js = "null"
            if r == .alertFirstButtonReturn, let d = try? JSONSerialization.data(withJSONObject: [field.stringValue]),
               let s = String(data: d, encoding: .utf8) { js = String(s.dropFirst().dropLast()) }   // (a JSON string: quotes escaped)
            field.stringValue = ""
            self?.builder.evaluateJavaScript("window.passphraseGiven(\(js))")
        }
    }
    // the page's confirm(), alert() and prompt(): a web view shows them only if its app does (else confirm
    // answers "no" at once: Delete and Keep did nothing)
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message
        alert.addButton(withTitle: "OK"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: builderPanel) { r in completionHandler(r == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle: "OK")
        alert.beginSheetModal(for: builderPanel) { _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert(); alert.messageText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 240, height: 24)); field.stringValue = defaultText ?? ""
        alert.accessoryView = field; alert.addButton(withTitle: "OK"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: builderPanel) { r in completionHandler(r == .alertFirstButtonReturn ? field.stringValue : nil) }
    }
    // the page's "choose a photo": the Mac's open panel
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.allowsMultipleSelection = false
        panel.begin { r in completionHandler(r == .OK ? panel.urls : nil) }
    }
    // a photo dropped on the picture: uploaded as the page would (finding lights on a sphere if its box is ticked)
    func uploadPhoto(_ u: URL) {
        guard let data = try? Data(contentsOf: u) else { return }
        builder.evaluateJavaScript("document.getElementById('findorb') ? document.getElementById('findorb').checked : false") { [weak self] v, _ in
            guard let self else { return }
            let orb = (v as? Bool) == true ? "auto" : ""
            let name = u.lastPathComponent.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "photo.jpg"
            var req = URLRequest(url: self.url("/builder/upload?name=\(name)&orb=\(orb)"))
            req.httpMethod = "POST"; req.httpBody = data
            URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
                DispatchQueue.main.async { self?.builder.evaluateJavaScript("window.builderUpload && window.builderUpload()") }
            }.resume()
            if !self.builderPanel.isVisible { self.builderPanel.orderFront(nil) }
        }
    }
    @objc func nightlyShow() { control(["show": true]) }
    @objc func toggleControls() { if controlPanel.isVisible { controlPanel.orderOut(nil) } else { controlPanel.orderFront(nil) } }

    @objc func toggleLog() {
        if logPanel.isVisible { logPanel.orderOut(nil); return }
        if !logPanel.setFrameUsingName("AppPreviewLog") {
            let f = window.frame
            logPanel.setFrameTopLeftPoint(NSPoint(x: f.minX, y: f.minY - 8))
        }
        logPanel.orderFront(nil)
        logView.scrollToEndOfDocument(nil)
    }

    @objc func screenshot() {
        guard let img = screen?.image() else { return }
        let rep = NSBitmapImageRep(cgImage: img)
        guard let png = rep.representation(using: .png, properties: [:]) else { return }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd 'at' HH.mm.ss"
        let name = "\(window.title.replacingOccurrences(of: "App Preview — ", with: "")) \(f.string(from: Date())).png"
        let out = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Desktop").appendingPathComponent(name)
        try? png.write(to: out)
        NSSound(named: "Grab")?.play()
    }
}

// ------------------------------------------------------------------ start
var fb = "", pipe = "", port = 8800
var args = Array(CommandLine.arguments.dropFirst())
while !args.isEmpty {
    let a = args.removeFirst()
    if a == "--fb", !args.isEmpty { fb = args.removeFirst() }
    else if a == "--pipe", !args.isEmpty { pipe = args.removeFirst() }
    else if a == "--port", !args.isEmpty { port = Int(args.removeFirst()) ?? 8800 }
}
if fb.isEmpty || pipe.isEmpty { FileHandle.standardError.write("usage: App Preview --fb FILE --pipe FIFO --port N\n".data(using: .utf8)!); exit(2) }
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let controller = Controller(fb: fb, pipe: pipe, port: port)
app.delegate = controller
app.run()
