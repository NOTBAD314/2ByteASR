using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

internal sealed class SetupWindow : Form
{
    private readonly string root;
    private readonly string setupScript;
    private readonly string logPath;
    private readonly TextBox output;
    private readonly Label status;
    private readonly CheckBox includeQwen;
    private readonly CheckBox minimalModels;
    private readonly Button startButton;
    private readonly Button stopButton;
    private readonly Button launchButton;
    private readonly ProgressBar progress;
    private Process setupProcess;
    private bool allowClose;
    private volatile bool mossNetworkFailure;
    private volatile bool gpuUnavailable;

    internal SetupWindow()
    {
        root = Path.GetDirectoryName(Application.ExecutablePath) ?? Environment.CurrentDirectory;
        setupScript = Path.Combine(root, "scripts", "bootstrap_install.ps1");
        logPath = Path.Combine(Path.GetTempPath(), "2byteasr-setup.log");

        Text = "2ByteASR 运行环境配置";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(760, 560);
        Size = new Size(900, 680);
        Font = new Font("Microsoft YaHei UI", 9F);

        Label title = new Label();
        title.Text = "配置 2ByteASR 运行环境";
        title.Font = new Font(Font.FontFamily, 16F, FontStyle.Bold);
        title.AutoSize = true;
        title.Location = new Point(22, 18);
        Controls.Add(title);

        Label hint = new Label();
        hint.Text = "窗口会一直保留并显示实时日志。失败后可直接继续重试，不需要重新安装。";
        hint.AutoSize = true;
        hint.ForeColor = Color.FromArgb(70, 70, 70);
        hint.Location = new Point(25, 55);
        Controls.Add(hint);

        includeQwen = new CheckBox();
        includeQwen.Text = "下载本地 Qwen3-ASR（约 4.7 GB；精度更高；不勾选则使用更快的 API，需自行配置 Key）";
        includeQwen.AutoSize = true;
        includeQwen.Location = new Point(26, 88);
        Controls.Add(includeQwen);

        minimalModels = new CheckBox();
        minimalModels.Text = "精简安装（约 2 GB；关闭 FireRed 字级时间轴，可稍后补）";
        minimalModels.AutoSize = true;
        minimalModels.Location = new Point(26, 116);
        minimalModels.CheckedChanged += delegate
        {
            if (minimalModels.Checked)
            {
                includeQwen.Checked = false;
                includeQwen.Enabled = false;
            }
            else if (setupProcess == null)
            {
                includeQwen.Enabled = true;
            }
        };
        Controls.Add(minimalModels);

        includeQwen.Visible = false;
        minimalModels.Visible = false;
        Label modelChoiceHint = new Label();
        modelChoiceHint.Text = "这里只安装运行环境。模型将在首次启动后由你在模型工坊中选择，不会强制下载 MOSS 或 FireRed。";
        modelChoiceHint.AutoSize = false;
        modelChoiceHint.Size = new Size(ClientSize.Width - 52, 42);
        modelChoiceHint.Location = new Point(26, 88);
        modelChoiceHint.ForeColor = Color.FromArgb(70, 70, 70);
        Controls.Add(modelChoiceHint);

        status = new Label();
        status.Text = "准备就绪：只安装轻量工作台环境，不会下载任何模型。";
        status.AutoEllipsis = true;
        status.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        status.Location = new Point(26, 151);
        status.Size = new Size(ClientSize.Width - 52, 24);
        Controls.Add(status);

        progress = new ProgressBar();
        progress.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        progress.Location = new Point(26, 178);
        progress.Size = new Size(ClientSize.Width - 52, 8);
        progress.Style = ProgressBarStyle.Continuous;
        Controls.Add(progress);

        output = new TextBox();
        output.Multiline = true;
        output.ReadOnly = true;
        output.ScrollBars = ScrollBars.Both;
        output.WordWrap = false;
        output.BackColor = Color.FromArgb(24, 26, 31);
        output.ForeColor = Color.FromArgb(224, 228, 235);
        output.Font = new Font("Consolas", 9F);
        output.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        output.Location = new Point(26, 198);
        output.Size = new Size(ClientSize.Width - 52, ClientSize.Height - 268);
        Controls.Add(output);

        startButton = new Button();
        startButton.Text = File.Exists(Path.Combine(root, "2byteasr.setup-complete"))
            ? "重新检查"
            : "开始配置";
        startButton.Size = new Size(116, 34);
        startButton.Anchor = AnchorStyles.Bottom | AnchorStyles.Left;
        startButton.Location = new Point(26, ClientSize.Height - 55);
        startButton.Click += delegate { StartSetup(); };
        Controls.Add(startButton);

        stopButton = new Button();
        stopButton.Text = "停止";
        stopButton.Size = new Size(82, 34);
        stopButton.Enabled = false;
        stopButton.Anchor = AnchorStyles.Bottom | AnchorStyles.Left;
        stopButton.Location = new Point(150, ClientSize.Height - 55);
        stopButton.Click += delegate { StopSetup(true); };
        Controls.Add(stopButton);

        Button logButton = new Button();
        logButton.Text = "打开日志";
        logButton.Size = new Size(96, 34);
        logButton.Anchor = AnchorStyles.Bottom | AnchorStyles.Left;
        logButton.Location = new Point(240, ClientSize.Height - 55);
        logButton.Click += delegate { OpenLog(); };
        Controls.Add(logButton);

        launchButton = new Button();
        launchButton.Text = "启动 2ByteASR";
        launchButton.Size = new Size(126, 34);
        launchButton.Enabled = File.Exists(Path.Combine(root, "2byteasr.setup-complete"));
        launchButton.Anchor = AnchorStyles.Bottom | AnchorStyles.Right;
        launchButton.Location = new Point(ClientSize.Width - 256, ClientSize.Height - 55);
        launchButton.Click += delegate { LaunchApplication(); };
        Controls.Add(launchButton);

        Button closeButton = new Button();
        closeButton.Text = "关闭";
        closeButton.Size = new Size(96, 34);
        closeButton.Anchor = AnchorStyles.Bottom | AnchorStyles.Right;
        closeButton.Location = new Point(ClientSize.Width - 122, ClientSize.Height - 55);
        closeButton.Click += delegate { Close(); };
        Controls.Add(closeButton);

        FormClosing += OnFormClosing;
    }

    private void StartSetup()
    {
        if (setupProcess != null)
        {
            return;
        }
        if (!File.Exists(setupScript))
        {
            MessageBox.Show("配置脚本不存在：\n" + setupScript, Text,
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        output.Clear();
        mossNetworkFailure = false;
        gpuUnavailable = false;
        AppendLine("[GUI] 配置开始。已下载内容和已创建环境会自动复用。\r\n");
        status.Text = "正在配置，请保持此窗口打开……";
        startButton.Enabled = false;
        stopButton.Enabled = true;
        launchButton.Enabled = false;
        includeQwen.Enabled = false;
        minimalModels.Enabled = false;
        progress.Style = ProgressBarStyle.Marquee;
        progress.MarqueeAnimationSpeed = 25;

        string powershell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.System),
            "WindowsPowerShell\\v1.0\\powershell.exe");
        if (!File.Exists(powershell))
        {
            powershell = "powershell.exe";
        }

        StringBuilder arguments = new StringBuilder();
        arguments.Append("-NoProfile -ExecutionPolicy Bypass -File ");
        arguments.Append(Quote(setupScript));
        arguments.Append(" -InstallPrerequisites -NoLaunch -NonInteractive");
        if (File.Exists(Path.Combine(root, "2byteasr.setup-complete")))
        {
            arguments.Append(" -Repair");
            AppendLine("[GUI] Repair Mode：将检查并修复不兼容的运行环境，不会因已配置标记跳过。\r\n");
        }

        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = powershell;
        info.Arguments = arguments.ToString();
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.StandardOutputEncoding = Encoding.UTF8;
        info.StandardErrorEncoding = Encoding.UTF8;

        try
        {
            setupProcess = new Process();
            setupProcess.StartInfo = info;
            setupProcess.OutputDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
            {
                if (eventArgs.Data != null)
                {
                    DetectMossNetworkFailure(eventArgs.Data);
                    DetectGpuUnavailable(eventArgs.Data);
                    AppendLine(eventArgs.Data);
                }
            };
            setupProcess.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
            {
                // uv/hf/tqdm routinely write normal progress to stderr. The process exit
                // code and final PowerShell exception determine failure; do not paint every
                // dependency or download progress line as an error.
                if (eventArgs.Data != null)
                {
                    DetectMossNetworkFailure(eventArgs.Data);
                    DetectGpuUnavailable(eventArgs.Data);
                    AppendLine(eventArgs.Data);
                }
            };
            setupProcess.Start();
            setupProcess.BeginOutputReadLine();
            setupProcess.BeginErrorReadLine();
            ThreadPool.QueueUserWorkItem(delegate
            {
                Process process = setupProcess;
                process.WaitForExit();
                int exitCode = process.ExitCode;
                BeginInvoke(new Action<int>(FinishSetup), exitCode);
            });
        }
        catch (Exception exception)
        {
            AppendLine("[GUI 错误] 无法启动配置：" + exception.Message);
            FinishSetup(-1);
        }
    }

    private void FinishSetup(int exitCode)
    {
        if (setupProcess != null)
        {
            setupProcess.Dispose();
            setupProcess = null;
        }
        progress.MarqueeAnimationSpeed = 0;
        progress.Style = ProgressBarStyle.Continuous;
        stopButton.Enabled = false;
        minimalModels.Enabled = true;
        includeQwen.Enabled = !minimalModels.Checked;

        if (exitCode == 0 && File.Exists(Path.Combine(root, "2byteasr.setup-complete")))
        {
            startButton.Text = "重新检查";
            startButton.Enabled = true;
            launchButton.Enabled = true;
            if (gpuUnavailable)
            {
                status.Text = "配置完成。未检测到 NVIDIA GPU，可选择 CPU 或在线 API 模型。";
                AppendLine("\r\n[GUI 提示] 运行环境已安装。MOSS/FireRed/Qwen 本地模型需要 NVIDIA CUDA；CPU 与在线 API 模型不需要。");
                MessageBox.Show(
                    "2ByteASR 运行环境已经安装完成。\n\n" +
                    "当前未检测到 NVIDIA CUDA GPU：你仍可在首次启动时选择 SenseVoice、Paraformer 等 CPU 模型，或选择在线 ASR API。\n\n" +
                    "如果要使用推荐的 MOSS + FireRed + Qwen 本地组合，请先安装或更新 NVIDIA 显卡驱动；通常不需要单独安装完整 CUDA Toolkit。",
                    "2ByteASR 配置完成",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }
            else
            {
                status.Text = "配置完成，可以启动 2ByteASR。";
                AppendLine("\r\n[GUI] 全部配置成功。");
                MessageBox.Show("运行环境已经准备好。启动后可在模型工坊按需选择并下载模型。", "2ByteASR 配置完成",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            return;
        }

        status.Text = mossNetworkFailure
            ? "MOSS 下载源当前不可用；不需要重装，可恢复网络后继续重试。"
            : "配置未完成。修复网络或磁盘问题后可直接继续重试。";
        startButton.Text = "继续重试";
        startButton.Enabled = true;
        AppendLine("\r\n[GUI] 配置失败，退出码：" + exitCode);
        AppendLine("[GUI] 完整日志：" + logPath);
        if (mossNetworkFailure)
        {
            MessageBox.Show(
                "MOSS 大模型无法从当前下载源持续传输。\n\n" +
                "不需要重新安装，已完成分片已经保留。你可以：\n" +
                "1. 稍后点击“继续重试”；\n" +
                "2. 临时开启可访问 Hugging Face 的代理后重试；\n" +
                "3. 检查 ModelScope 官方 OpenMOSS 仓库是否正在维护或限流。\n\n" +
                "完整日志：\n" + logPath,
                "MOSS 模型下载未完成",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
        }
        else
        {
            MessageBox.Show(
                "配置没有完成（退出码 " + exitCode + "）。\n\n" +
                "不需要重新安装。请查看窗口末尾错误，修复后点击“继续重试”；" +
                "已安装环境和已下载模型会自动复用。\n\n完整日志：\n" + logPath,
                "2ByteASR 配置失败",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
    }

    private void DetectMossNetworkFailure(string line)
    {
        if (line.IndexOf("MOSS 大模型在当前网络下无法", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            mossNetworkFailure = true;
        }
    }

    private void DetectGpuUnavailable(string line)
    {
        if (line.IndexOf("未检测到 NVIDIA GPU 驱动", StringComparison.OrdinalIgnoreCase) >= 0 ||
            line.IndexOf("nvidia-smi 不可用", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            gpuUnavailable = true;
        }
    }

    private void StopSetup(bool askForConfirmation)
    {
        if (setupProcess == null) return;
        if (askForConfirmation && MessageBox.Show("停止当前配置吗？已下载文件会保留，下次可以继续。", Text,
                MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
        {
            return;
        }
        try
        {
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "taskkill.exe");
            info.Arguments = "/PID " + setupProcess.Id + " /T /F";
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            using (Process killer = Process.Start(info))
            {
                if (killer != null) killer.WaitForExit();
            }
        }
        catch (Exception exception)
        {
            MessageBox.Show("停止失败：" + exception.Message, Text,
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void OpenLog()
    {
        try
        {
            if (!File.Exists(logPath))
            {
                MessageBox.Show("日志尚未生成：\n" + logPath, Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = logPath;
            info.UseShellExecute = true;
            Process.Start(info);
        }
        catch (Exception exception)
        {
            MessageBox.Show("无法打开日志：" + exception.Message, Text,
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void LaunchApplication()
    {
        string launcher = Path.Combine(root, "2ByteASR.exe");
        try
        {
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = launcher;
            info.WorkingDirectory = root;
            info.UseShellExecute = true;
            Process.Start(info);
            // The workbench now owns the visible flow (including model
            // downloads).  Do not leave the configurator looking like a
            // second downloader behind it.
            allowClose = true;
            Close();
        }
        catch (Exception exception)
        {
            MessageBox.Show("无法启动 2ByteASR：" + exception.Message, Text,
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void AppendLine(string line)
    {
        if (IsDisposed) return;
        if (InvokeRequired)
        {
            BeginInvoke(new Action<string>(AppendLine), line);
            return;
        }
        output.AppendText(line + Environment.NewLine);
        output.SelectionStart = output.TextLength;
        output.ScrollToCaret();
    }

    private void OnFormClosing(object sender, FormClosingEventArgs eventArgs)
    {
        if (setupProcess == null || allowClose) return;
        if (MessageBox.Show("配置仍在运行。停止并关闭吗？已下载内容会保留。", Text,
                MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
        {
            eventArgs.Cancel = true;
            return;
        }
        allowClose = true;
        StopSetup(false);
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}

internal static class TwoByteAsrConfigure
{
    [STAThread]
    private static void Main()
    {
        try
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupWindow());
        }
        catch (Exception exception)
        {
            string crashLog = Path.Combine(Path.GetTempPath(), "2byteasr-configurator-crash.log");
            try
            {
                File.WriteAllText(crashLog, exception.ToString(), Encoding.UTF8);
            }
            catch
            {
                // The message box still reports the original exception.
            }
            MessageBox.Show(
                "配置窗口启动失败：\n" + exception.Message + "\n\n日志：\n" + crashLog,
                "2ByteASR 配置器",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
    }
}
