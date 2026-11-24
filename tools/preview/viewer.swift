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

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.contentsGravity = .resize
        layer?.magnificationFilter = .nearest            // (the device's own pixels, crisp)
        layer?.backgroundColor = NSColor.black.cgColor
    }
    required init?(coder: NSCoder) { fatalError() }

    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    func show(_ image: CGImage) { layer?.contents = image }

    private func send(_ kind: String, _ event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        let x = max(0, min(W - 1, Int(p.x / bounds.width * CGFloat(W))))
        let y = max(0, min(H - 1, Int((bounds.height - p.y) / bounds.height * CGFloat(H))))
        touch("\(kind) \(x) \(y)")
    }
    override func mouseDown(with event: NSEvent) { send("down", event) }
    override func mouseUp(with event: NSEvent) { send("up", event) }
    override func mouseDragged(with event: NSEvent) {
        if event.timestamp - lastMove > 0.04 { lastMove = event.timestamp; send("move", event) }
    }
}

// ------------------------------------------------------------------ the app
final class Controller: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let fbPath: String, pipePath: String, port: Int
    var screen: Screen?
    var pipeFD: Int32 = -1
    var window: NSWindow!
    var view: ScreenView!
    var logPanel: NSPanel!
    var logView: NSTextView!
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
        window.title = "App Preview — \(name)"
        let ids = apps.map { $0.joined(separator: "=") }
        if ids != appsShown { appsShown = ids; rebuildAppMenu(apps) }
        for item in appMenu.items where item.representedObject is String {
            item.state = (item.representedObject as? String) == current ? .on : .off
        }
        let hour = s["hour"] as? String ?? ""
        let countdown = s["countdown"] as? Bool ?? false
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
