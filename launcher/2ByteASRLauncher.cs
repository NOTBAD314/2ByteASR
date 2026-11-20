using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

internal static class TwoByteAsrLauncher
{
    private const string AppUserModelId = "2ByteASR.Desktop.2026";
    private const string SetupMarkerName = "2byteasr.setup-complete";

    [DllImport("shell32.dll", SetLastError = true)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(
        [MarshalAs(UnmanagedType.LPWStr)] string appId);

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            SetCurrentProcessExplicitAppUserModelID(AppUserModelId);
        }
        catch
        {
            // Older Windows builds may not expose taskbar application identities.
        }

        string executable = Assembly.GetExecutingAssembly().Location;
        string root = Path.GetDirectoryName(executable) ?? Environment.CurrentDirectory;
        string packagedApp = Path.Combine(root, "dist", "2ByteASR", "2ByteASR.exe");
        string pythonw = Path.Combine(root, ".venv-main", "Scripts", "pythonw.exe");
        string entrypoint = Path.Combine(root, "quick_start.py");
        string configurator = Path.Combine(root, "2ByteASR-Configure.exe");
        string setupFallback = Path.Combine(root, "setup_2byteasr.bat");
        if (File.Exists(packagedApp))
        {
            // Official user entry: the frozen PyInstaller build. Task Manager
            // shows 2ByteASR.exe, never a host python.exe. This bootstrapper
            // exits immediately after handing off to the packaged process.
            // Presence of quick_start.py in a source checkout must not steal
            // the desktop/start-menu entry back to python.exe.
            try
            {
                StringBuilder packagedArguments = new StringBuilder();
                foreach (string argument in args)
                {
                    packagedArguments.Append(' ');
                    packagedArguments.Append(Quote(argument));
                }
                ProcessStartInfo packagedInfo = new ProcessStartInfo();
                packagedInfo.FileName = packagedApp;
                packagedInfo.Arguments = packagedArguments.ToString().TrimStart();
                packagedInfo.WorkingDirectory = Path.GetDirectoryName(packagedApp);
                packagedInfo.EnvironmentVariables["TWOBYTEASR_INVOKER_CWD"] = Environment.CurrentDirectory;
                packagedInfo.UseShellExecute = false;
                packagedInfo.CreateNoWindow = true;
                packagedInfo.EnvironmentVariables["TWOBYTEASR_PROCESS_START_MS"] =
                    DateTimeOffset.UtcNow.ToUnixTimeMilliseconds().ToString();
                packagedInfo.EnvironmentVariables["TWOBYTEASR_STARTUP_RUN_ID"] =
                    Guid.NewGuid().ToString("N");
                packagedInfo.EnvironmentVariables["TWOBYTEASR_LAUNCH_MODE"] = "packaged";
                // 2026-11-19: Home's skeleton is on the screen at once and moves until the
                // app's real window has painted (LaunchCover.cs); none when anything is unusual.
                LaunchCover packagedCover = LaunchCover.TryCreate(root, args);
                if (packagedCover != null)
                {
                    packagedInfo.EnvironmentVariables["TWOBYTEASR_LAUNCH_COVER"] = packagedCover.EventName;
                }
                Process child = LaunchProcess(packagedInfo);
                if (child == null)
                {
                    throw new InvalidOperationException("无法启动 2ByteASR 主程序。");
                }
                if (packagedCover != null)
                {
                    packagedCover.Run(child);
                }
                child.Dispose();
                return 0;
            }
            catch (Exception exc)
            {
                MessageBox.Show(
                    "工作台没有成功启动：\n" + exc.Message,
                    "2ByteASR 启动失败",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return 3;
            }
        }
        if (!IsReady(root, pythonw, entrypoint))
        {
            string message;
            if (File.Exists(pythonw))
            {
                // Venv exists but setup did not finish (interrupted download).
                // Running setup again resumes from the local cache; nothing
                // already downloaded is repeated.
                message = "2ByteASR 上次配置没有完成（可能中途中断）。\n\n" +
                          "现在继续配置吗？已下载的内容会自动续传，不会重复下载。";
            }
            else if (HasBundledModels(root))
            {
                message = "2ByteASR 还没有完成首次配置。\n\n" +
                          "现在自动安装运行环境吗？模型已包含在便携包内，无需联网下载。";
            }
            else
            {
                message = "2ByteASR 还没有完成首次配置。\n\n" +
                          "现在自动安装运行环境并下载模型吗（约 7 GB，可断点续传）？\n" +
                          "安装过程中需要保持网络连接。";
            }
            if (!HasBundledModels(root))
            {
                message = "2ByteASR 还没有完成首次运行环境配置。\n\n现在安装运行环境吗？模型不会在这里强制下载，启动软件后可在模型工坊按需选择。";
            }
            DialogResult answer = MessageBox.Show(
                message,
                "2ByteASR 首次配置",
                File.Exists(configurator) || File.Exists(setupFallback) ? MessageBoxButtons.YesNo : MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            if (answer == DialogResult.No)
            {
                MessageBox.Show(
                    "配置可稍后进行：双击 2ByteASR-Configure.exe 即可继续。",
                    "2ByteASR",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
                return 2;
            }
            if (answer == DialogResult.Yes && (File.Exists(configurator) || File.Exists(setupFallback)))
            {
                ProcessStartInfo setupInfo = new ProcessStartInfo();
                setupInfo.FileName = File.Exists(configurator) ? configurator : setupFallback;
                setupInfo.WorkingDirectory = root;
                setupInfo.UseShellExecute = true;
                try
                {
                    Process setupProcess = LaunchProcess(setupInfo);
                    if (setupProcess != null)
                    {
                        setupProcess.Dispose();
                        return 0;
                    }
                }
                catch (Exception exc)
                {
                    MessageBox.Show(
                        "无法启动配置程序：\n" + exc.Message,
                        "2ByteASR 首次配置",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                    return 4;
                }
            }
            return 2;
        }

        StringBuilder arguments = new StringBuilder();
        arguments.Append(Quote(entrypoint));
        foreach (string argument in args)
        {
            arguments.Append(' ');
            arguments.Append(Quote(argument));
        }

        ProcessStartInfo startInfo = new ProcessStartInfo();
        startInfo.FileName = pythonw;
        startInfo.Arguments = arguments.ToString();
        startInfo.WorkingDirectory = root;
        startInfo.UseShellExecute = false;
        startInfo.CreateNoWindow = true;
        startInfo.EnvironmentVariables["TWOBYTEASR_INVOKER_CWD"] = Environment.CurrentDirectory;
        startInfo.EnvironmentVariables["TWOBYTEASR_PROCESS_START_MS"] =
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds().ToString();
        startInfo.EnvironmentVariables["TWOBYTEASR_STARTUP_RUN_ID"] =
            Guid.NewGuid().ToString("N");
        // Developer / source mode: the packaged build is absent, so this tree
        // falls back to the venv interpreter explicitly labelled as dev.
        startInfo.EnvironmentVariables["TWOBYTEASR_LAUNCH_MODE"] = "source-dev";
        LaunchCover cover = LaunchCover.TryCreate(root, args);
        if (cover != null)
        {
            startInfo.EnvironmentVariables["TWOBYTEASR_LAUNCH_COVER"] = cover.EventName;
        }

        try
        {
            Process child = LaunchProcess(startInfo);
            if (child == null)
            {
                throw new InvalidOperationException("无法创建 Python 工作台进程。");
            }
            if (cover != null)
            {
                cover.Run(child);
            }
            // The Qt process owns the visible window and sets the same AppID.
            // Let this tiny bootstrapper exit as soon as it is not needed (at once,
            // or when the cover has faded) so no second process stays around.
            child.Dispose();
            return 0;
        }
        catch (Exception exc)
        {
            MessageBox.Show(
                "工作台没有成功启动：\n" + exc.Message,
                "2ByteASR 启动失败",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 3;
        }
    }

    private static bool IsReady(string root, string pythonw, string entrypoint)
    {
        if (!File.Exists(pythonw) || !File.Exists(entrypoint))
        {
            return false;
        }
        if (File.Exists(Path.Combine(root, SetupMarkerName)))
        {
            return true;
        }
        // Legacy installs configured before the marker was introduced. The
        // app package itself lives at the project root, so probe for the Qt
        // binding that only a completed base install produces. ASR engines,
        // torch and the separate MOSS venv are installed later on demand.
        string sitePackages = Path.Combine(root, ".venv-main", "Lib", "site-packages");
        return Directory.Exists(Path.Combine(sitePackages, "PySide6"));
    }

    private static bool HasBundledModels(string root)
    {
        string modelsDir = Path.Combine(root, "models");
        if (!Directory.Exists(modelsDir))
        {
            return false;
        }
        try
        {
            foreach (string file in Directory.EnumerateFiles(modelsDir, "*", SearchOption.AllDirectories))
            {
                string extension = Path.GetExtension(file);
                if (extension == ".safetensors" || extension == ".pth"
                    || extension == ".ckpt" || extension == ".tar" || extension == ".pt")
                {
                    return true;
                }
            }
        }
        catch
        {
            // An unreadable models directory should not block the setup dialog.
        }
        return false;
    }

    private static Process LaunchProcess(ProcessStartInfo info)
    {
        // UseShellExecute=false launches the executable directly; arguments
        // are encoded for CommandLineToArgvW and never interpreted by cmd.exe.
        return Process.Start(info);
    }

    private static string Quote(string value)
    {
        if (value == null)
        {
            return "\"\"";
        }
        StringBuilder quoted = new StringBuilder("\"");
        int slashes = 0;
        foreach (char current in value)
        {
            if (current == '\\')
            {
                slashes++;
                continue;
            }
            if (current == '"')
            {
                quoted.Append('\\', slashes * 2 + 1);
            }
            else
            {
                quoted.Append('\\', slashes);
            }
            quoted.Append(current);
            slashes = 0;
        }
        quoted.Append('\\', slashes * 2);
        quoted.Append('"');
        return quoted.ToString();
    }
}
