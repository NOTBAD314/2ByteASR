using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// 2026-11-19 (user: right after opening there is a placeholder before Home; they picked option B
// of the preview: a skeleton of Home). The launcher is a small program of its own, so its window
// can be on the screen about 0.15 s after the double-click and keep moving while the Python process
// imports and builds its main window (that work holds the app's own GUI thread, so nothing drawn by
// the app itself can move meanwhile). The app writes where Home's parts are and the theme's colours
// when it closes (app/launch_picture.py, cover.txt); this draws those parts as soft blocks with a
// light sweeping over them, exactly where the window will open, and fades
// out when the app signals that its real window has painted (named event in TWOBYTEASR_LAUNCH_COVER).
// Anything unexpected - no layout, the app already running, files given to open - and no cover is
// shown: the app then shows its own kept picture (option A).
internal sealed class LaunchCover : Form
{
    private const int FadeMs = 260;
    private const int GiveUpMs = 25000;

    private sealed class Part
    {
        public string Kind;
        public RectangleF Rect;
    }

    private readonly List<Part> parts = new List<Part>();
    private Color background, panel, block, highlight, border;
    private bool maximized;
    private Rectangle client;
    private readonly Stopwatch clock = Stopwatch.StartNew();
    private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
    private EventWaitHandle ready;
    private Process child;
    private long fadeStartedMs = -1;

    public string EventName { get; private set; }

    [DllImport("user32.dll")]
    private static extern IntPtr SetProcessDpiAwarenessContext(IntPtr value);

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    [DllImport("user32.dll")]
    private static extern bool AllowSetForegroundWindow(int processId);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int cx, int cy, uint flags);

    private LaunchCover()
    {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        TopMost = true;
        DoubleBuffered = true;
        Opacity = 0.999;                         // layered from the start: the fade changes nothing else
        Text = "2ByteASR";
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
    }

    protected override bool ShowWithoutActivation
    {
        get { return true; }
    }

    protected override CreateParams CreateParams
    {
        get
        {
            CreateParams value = base.CreateParams;
            value.ExStyle |= 0x00000080 | 0x08000000 | 0x00000008 | 0x00000020;   // TOOLWINDOW, NOACTIVATE, TOPMOST, TRANSPARENT
            return value;
        }
    }

    // ------------------------------------------------------------ deciding
    public static LaunchCover TryCreate(string appRoot, string[] args)
    {
        try
        {
            if (args.Length > 0 || Environment.GetEnvironmentVariable("TWOBYTEASR_LAUNCH_COVER_OFF") == "1")
            {
                return null;                      // files to open: the app goes to Studio, not Home
            }
            try
            {
                SetProcessDpiAwarenessContext(new IntPtr(-4));   // per-monitor v2: physical pixels
            }
            catch
            {
                // Older Windows: the cover is simply placed by system scaling.
            }
            if (AppRunning(appRoot))
            {
                return null;
            }
            string folder = Path.Combine(UserDataRoot(), "cache", "launch-picture");
            string layout = Path.Combine(folder, "cover.txt");
            if (!File.Exists(layout))
            {
                return null;
            }
            LaunchCover cover = new LaunchCover();
            if (!cover.LoadLayout(File.ReadAllLines(layout, Encoding.UTF8)))
            {
                cover.Dispose();
                return null;
            }
            cover.EventName = "Local\\2ByteASR-launch-cover-" + Process.GetCurrentProcess().Id;
            cover.ready = new EventWaitHandle(false, EventResetMode.ManualReset, cover.EventName);
            return cover;
        }
        catch
        {
            return null;
        }
    }

    private static string UserDataRoot()
    {
        string configured = (Environment.GetEnvironmentVariable("2BYTEASR_USER_DATA_ROOT") ?? "").Trim();
        if (configured.Length > 0)
        {
            return Path.Combine(configured, "2ByteASR");
        }
        string local = (Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? "").Trim();
        if (local.Length == 0)
        {
            local = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "Local");
        }
        return Path.Combine(local, "2ByteASR");
    }

    // The app's single-instance mutex (app/single_instance.py): its name is "2ByteASR-" and the first
    // 12 hex digits of the SHA-1 of the app folder's path, lower-cased.
    private static bool AppRunning(string appRoot)
    {
        string packaged = Path.Combine(appRoot, "dist", "2ByteASR");
        foreach (string folder in new[] { packaged, appRoot })
        {
            if (!Directory.Exists(folder))
            {
                continue;
            }
            string identity = Path.GetFullPath(folder).TrimEnd('\\').ToLowerInvariant();
            using (SHA1 sha = SHA1.Create())
            {
                byte[] hash = sha.ComputeHash(Encoding.UTF8.GetBytes(identity));
                StringBuilder hex = new StringBuilder();
                for (int index = 0; index < 6; index++)
                {
                    hex.Append(hash[index].ToString("x2"));
                }
                Mutex existing;
                if (Mutex.TryOpenExisting("Local\\2ByteASR-" + hex + "-gui-owner", out existing))
                {
                    existing.Dispose();
                    return true;
                }
            }
        }
        return false;
    }

    private bool LoadLayout(string[] lines)
    {
        float scale = 1f;
        foreach (string raw in lines)
        {
            string[] f = raw.Trim().Split(' ');
            if (f.Length == 0 || f[0].Length == 0)
            {
                continue;
            }
            switch (f[0])
            {
                case "format":
                    if (f[1] != "1") return false;
                    break;
                case "next_page":
                    if (f[1] != "recognition") return false;
                    break;
                case "client":
                    client = new Rectangle(I(f[1]), I(f[2]), I(f[3]), I(f[4]));
                    break;
                case "scale":
                    scale = F(f[1]);
                    break;
                case "maximized":
                    maximized = f[1] == "1";
                    break;
                case "colors":
                    background = C(f[1]); panel = C(f[2]); block = C(f[3]); highlight = C(f[4]); border = C(f[5]);
                    break;
                case "part":
                    if (f[1] == "mascot") break;  // An earlier layout may still contain the header icon.
                    parts.Add(new Part { Kind = f[1], Rect = new RectangleF(F(f[2]) * scale, F(f[3]) * scale, F(f[4]) * scale, F(f[5]) * scale) });
                    break;
            }
        }
        if (client.Width < 320 || client.Height < 200 || parts.Count < 3)
        {
            return false;
        }
        foreach (Screen screen in Screen.AllScreens)
        {
            if (screen.Bounds.Contains(new Point(client.Left + client.Width / 2, client.Top + client.Height / 2)))
            {
                Bounds = client;
                BackColor = background;
                return true;
            }
        }
        return false;
    }

    private static int I(string value) { return (int)Math.Round(F(value)); }
    private static float F(string value) { return float.Parse(value, CultureInfo.InvariantCulture); }
    private static Color C(string value) { return ColorTranslator.FromHtml(value); }

    // ------------------------------------------------------------ running
    public void Run(Process started)
    {
        child = started;
        try
        {
            // Started from the shortcut this process may bring a window to the front; the app's
            // window must still come to the front although this one stays on the screen meanwhile.
            AllowSetForegroundWindow(started.Id);
        }
        catch
        {
        }
        timer.Interval = 15;
        timer.Tick += Tick;
        Shown += delegate
        {
            int value = 1;
            DwmSetWindowAttribute(Handle, 3, ref value, 4);          // no system open/close animation
            if (!maximized)
            {
                int round = 2;
                DwmSetWindowAttribute(Handle, 33, ref round, 4);     // rounded like the real window
            }
            SetWindowPos(Handle, new IntPtr(-1), client.X, client.Y, client.Width, client.Height, 0x0010);
            timer.Start();
        };
        Application.Run(this);
    }

    private void Tick(object sender, EventArgs e)
    {
        long now = clock.ElapsedMilliseconds;
        bool exited = false;
        try { exited = child == null || child.HasExited; } catch { exited = true; }
        if (fadeStartedMs < 0 && (ready.WaitOne(0) || now > GiveUpMs))
        {
            fadeStartedMs = now;
        }
        if (exited && fadeStartedMs < 0)
        {
            Close();                              // the app ended (forwarded to a running one, or failed)
            return;
        }
        if (fadeStartedMs >= 0)
        {
            double k = Math.Min(1.0, (now - fadeStartedMs) / (double)FadeMs);
            double eased = 1 - Math.Pow(1 - k, 3);                 // ease-out, like FADE_EASE
            if (k >= 1.0)
            {
                Close();
                return;
            }
            Opacity = Math.Max(0.0, 0.999 * (1 - eased));
            return;                               // the picture holds still while it fades
        }
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(background);
        double t = clock.ElapsedMilliseconds / 1000.0;
        float sweepWidth = Width * 0.28f;
        float sweep = (float)((t % 1.6) / 1.6) * (Width + sweepWidth * 2) - sweepWidth;
        foreach (Part part in parts)
        {
            RectangleF r = part.Rect;
            float radius = part.Kind == "bar" ? 0 : Math.Min(10f, Math.Min(r.Width, r.Height) / 2);
            using (GraphicsPath path = Rounded(r, radius))
            {
                if (part.Kind == "dash")
                {
                    using (Pen pen = new Pen(border, 2f) { DashStyle = DashStyle.Dash })
                    {
                        g.DrawPath(pen, path);
                    }
                    continue;
                }
                Color fill = part.Kind == "panel" || part.Kind == "bar" ? panel : block;
                using (SolidBrush brush = new SolidBrush(fill))
                {
                    g.FillPath(brush, path);
                }
                if (part.Kind == "block" || part.Kind == "pill")
                {
                    RectangleF band = new RectangleF(sweep, r.Y, sweepWidth, r.Height);
                    if (band.IntersectsWith(r))
                    {
                        Region clip = g.Clip;
                        g.SetClip(path);
                        using (LinearGradientBrush light = new LinearGradientBrush(
                            new PointF(band.Left, 0), new PointF(band.Right, 0), Color.FromArgb(0, highlight), Color.FromArgb(0, highlight)))
                        {
                            ColorBlend blend = new ColorBlend(3);
                            blend.Colors = new[] { Color.FromArgb(0, highlight), Color.FromArgb(150, highlight), Color.FromArgb(0, highlight) };
                            blend.Positions = new[] { 0f, 0.5f, 1f };
                            light.InterpolationColors = blend;
                            g.FillRectangle(light, band);
                        }
                        g.Clip = clip;
                    }
                }
            }
        }
    }

    private static GraphicsPath Rounded(RectangleF r, float radius)
    {
        GraphicsPath path = new GraphicsPath();
        if (radius <= 0.5f)
        {
            path.AddRectangle(r);
            return path;
        }
        float d = radius * 2;
        path.AddArc(r.X, r.Y, d, d, 180, 90);
        path.AddArc(r.Right - d, r.Y, d, d, 270, 90);
        path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
        path.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        timer.Stop();
        if (ready != null)
        {
            ready.Dispose();
        }
        base.OnFormClosed(e);
    }
}
