// SPDX-License-Identifier: GPL-3.0-only
// 2ByteASR component updater.
//
// The program downloads and verifies changed components into a staging folder,
// writes an explicit plan and starts this helper from a copy outside the
// install folder.  The helper waits until the program has exited, then replaces
// only the planned program files.  Every replaced or removed file is first
// renamed into a backup folder and journaled, so any failure restores the
// previous program.  User data, models, environments and the three factory
// configuration files are never touched; the install root is never emptied.
//
// Modes:
//   --apply <plan.txt> [--quiet]
//   --rollback <install_root> [--quiet]           undo an unfinished journal
//   --prune <install_root> <previous_manifest>    after Setup: remove files the
//                                                 previous version listed but the
//                                                 new one no longer ships
//   --remove-listed <install_root>                at uninstall: remove listed
//                                                 program files the updater added
//   --version
// Exit codes: 0 applied (and confirmed when restarting), 10 applied but the new
// program did not confirm its start in time, 2 failed and fully rolled back,
// 3 rollback incomplete (Setup repair needed), 4 invalid input.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class UpdateFailure : Exception
{
    internal UpdateFailure(string message) : base(message) { }
}

internal sealed class Plan
{
    internal string InstallRoot;
    internal string StagingRoot;
    internal string FromVersion = "";
    internal string ToVersion = "";
    internal int WaitPid;
    internal bool Restart;
    internal int ConfirmSeconds = 120;
    internal int WaitPidSeconds = 180;
    internal int ProcessWaitSeconds = 60;
    internal long ReserveBytes = 64L * 1024 * 1024;
    internal string LogPath;
    internal string ResultPath;
    internal string RestartExe = "2ByteASR.exe";
    internal readonly List<string> Replace = new List<string>();
    internal readonly List<string> Remove = new List<string>();
    internal string Manifest;
}

internal static class Updater
{
    internal const string Version = "1";
    private static readonly string[] Preserved = { "2byteasr_settings.json", "game_profiles.json", "glossary.txt" };
    private const string StateDir = ".update-state";
    private const string BackupDir = ".update-backup";
    private static string logPath;
    private static bool quiet;
    private static ProgressWindow window;

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length >= 1 && args[0] == "--version") { Console.WriteLine("2ByteASRUpdater " + Version); return 0; }
            quiet = Array.IndexOf(args, "--quiet") >= 0;
            if (args.Length >= 2 && args[0] == "--apply") return RunApply(args[1]);
            if (args.Length >= 2 && args[0] == "--rollback")
            {
                string root = Path.GetFullPath(args[1]);
                logPath = Path.Combine(root, StateDir, "update-helper.log");
                return RecoverJournal(root, true) ? 0 : 3;
            }
            if (args.Length >= 3 && args[0] == "--prune") return Prune(Path.GetFullPath(args[1]), args[2]);
            if (args.Length >= 2 && args[0] == "--remove-listed") return RemoveListed(Path.GetFullPath(args[1]));
            Console.Error.WriteLine("usage: 2ByteASRUpdater --apply <plan> | --rollback <root> | --prune <root> <manifest> | --remove-listed <root>");
            return 4;
        }
        catch (Exception exc)
        {
            Log("fatal: " + exc);
            return 4;
        }
    }

    // ------------------------------------------------------------------ apply

    private static int RunApply(string planPath)
    {
        Plan plan;
        try { plan = ReadPlan(planPath); }
        catch (Exception exc)
        {
            Log("invalid plan: " + exc.Message);
            WriteResult(null, "invalid-plan", exc.Message);
            Notify("更新计划无效，程序文件未被修改。\n\n" + exc.Message, true);
            return 4;
        }
        logPath = plan.LogPath;
        Log(string.Format("apply {0} -> {1}: {2} replace, {3} remove, root {4}", plan.FromVersion, plan.ToVersion,
            plan.Replace.Count, plan.Remove.Count, plan.InstallRoot));
        if (!quiet)
        {
            window = new ProgressWindow("正在更新兔白字幕 " + plan.ToVersion + "，请稍候…");
            Thread worker = new Thread(delegate () { window.ExitCode = ApplyAndRestart(plan); window.CloseSafe(); });
            worker.IsBackground = true;
            worker.SetApartmentState(ApartmentState.STA);
            worker.Start();
            Application.Run(window);
            worker.Join();
            return window.ExitCode;
        }
        return ApplyAndRestart(plan);
    }

    private static int ApplyAndRestart(Plan plan)
    {
        string txid = DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0, 8);
        string journalPath = Path.Combine(plan.InstallRoot, StateDir, "journal.txt");
        string backupRoot = Path.Combine(plan.InstallRoot, BackupDir, txid);
        try
        {
            if (!RecoverJournal(plan.InstallRoot, false))
                throw new UpdateFailure("上一次未完成的更新无法自动恢复，请用安装包修复。");
            WaitForExit(plan);
            Preflight(plan);
        }
        catch (Exception exc)
        {
            Log("preflight failed: " + exc.Message);
            WriteResult(plan, "not-applied", exc.Message);
            Notify("更新没有执行，程序文件保持原样。\n\n" + exc.Message, true);
            if (plan.Restart) StartProgram(plan, null);
            return 2;
        }
        Journal journal = null;
        try
        {
            journal = Journal.Create(journalPath, txid, backupRoot, plan.FromVersion, plan.ToVersion);
            int step = 0;
            int failAt = FailInjection();
            List<string> ordered = new List<string>(plan.Replace);
            if (plan.Manifest != null) ordered.Add(plan.Manifest);  // manifest last: it describes the new state
            foreach (string rel in ordered)
            {
                if (failAt > 0 && ++step >= failAt) throw new IOException("injected failure at step " + step);
                string target = Target(plan.InstallRoot, rel);
                string source = Path.Combine(plan.StagingRoot, rel.Replace('/', '\\'));
                string temporary = target + ".update-new";
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                File.Copy(source, temporary, true);
                if (File.Exists(target))
                {
                    string backup = Path.Combine(backupRoot, rel.Replace('/', '\\'));
                    Directory.CreateDirectory(Path.GetDirectoryName(backup));
                    File.Move(target, backup);
                    journal.Add("MOVED", rel);
                }
                File.Move(temporary, target);
                journal.Add("PLACED", rel);
            }
            foreach (string rel in plan.Remove)
            {
                if (failAt > 0 && ++step >= failAt) throw new IOException("injected failure at step " + step);
                string target = Target(plan.InstallRoot, rel);
                if (!File.Exists(target)) continue;
                string backup = Path.Combine(backupRoot, rel.Replace('/', '\\'));
                Directory.CreateDirectory(Path.GetDirectoryName(backup));
                File.Move(target, backup);
                journal.Add("MOVED", rel);
            }
            journal.Add("COMMITTED", "");
            Log("committed " + txid);
        }
        catch (Exception exc)
        {
            Log("apply failed: " + exc);
            bool restored = journal == null || RollBack(plan.InstallRoot, journalPath);
            WriteResult(plan, restored ? "rolled-back" : "rollback-incomplete", exc.Message);
            Notify(restored
                ? "更新失败，已恢复到原来的版本，模型和设置未受影响。\n\n" + exc.Message
                : "更新失败且未能完全恢复。请重新运行兔白字幕安装包修复（不要先卸载，模型和设置会保留）。\n\n" + exc.Message, true);
            if (restored && plan.Restart) StartProgram(plan, null);
            return restored ? 2 : 3;
        }
        if (!plan.Restart)
        {
            FinishCommitted(plan.InstallRoot, journalPath, backupRoot);
            WriteResult(plan, "applied", "");
            return 0;
        }
        string confirm = Path.Combine(plan.InstallRoot, StateDir, "confirm-" + txid + ".json");
        Process started = StartProgram(plan, confirm);
        DateTime deadline = DateTime.UtcNow.AddSeconds(Math.Max(5, plan.ConfirmSeconds));
        while (DateTime.UtcNow < deadline)
        {
            if (File.Exists(confirm))
            {
                FinishCommitted(plan.InstallRoot, journalPath, backupRoot);
                TryDelete(confirm);
                WriteResult(plan, "applied", "");
                Log("new version confirmed its start");
                return 0;
            }
            if (started != null && started.HasExited)
            {
                int code = SafeExitCode(started);
                Log("new version exited before confirming start, exit code " + code);
                bool restored = RollBack(plan.InstallRoot, journalPath);
                WriteResult(plan, restored ? "rolled-back-after-start" : "rollback-incomplete",
                    "新版本启动失败，退出码 " + code);
                Notify(restored
                    ? "新版本未能正常启动，已恢复原来的版本。\n退出码 " + code
                    : "新版本未能正常启动，且未能完全恢复。请重新运行安装包修复。", true);
                if (restored) StartProgram(plan, null);
                return restored ? 2 : 3;
            }
            Thread.Sleep(250);
        }
        Log("no start confirmation within " + plan.ConfirmSeconds + " s; keeping backup " + backupRoot);
        WriteResult(plan, "applied-unconfirmed", "新版本仍在启动或未写确认");
        return 10;
    }

    private static int FailInjection()
    {
        string value = Environment.GetEnvironmentVariable("TWOBYTEASR_UPDATER_FAIL_AT");
        int step;
        return int.TryParse(value, out step) ? step : 0;
    }

    private static void FinishCommitted(string root, string journalPath, string backupRoot)
    {
        TryDelete(journalPath);
        TryDeleteTree(backupRoot);
        TryDeleteTree(Path.Combine(root, BackupDir), true);
    }

    private static void WaitForExit(Plan plan)
    {
        if (plan.WaitPid > 0)
        {
            try
            {
                Process process = Process.GetProcessById(plan.WaitPid);
                if (!process.WaitForExit(plan.WaitPidSeconds * 1000)) throw new UpdateFailure("兔白字幕没有按时退出，更新已取消。");
            }
            catch (ArgumentException) { }  // already exited
        }
        DateTime deadline = DateTime.UtcNow.AddSeconds(plan.ProcessWaitSeconds);
        while (true)
        {
            List<string> users = ProcessesInside(plan.InstallRoot);
            if (users.Count == 0) return;
            if (DateTime.UtcNow > deadline)
                throw new UpdateFailure("仍有程序在使用安装目录（" + string.Join("、", users.ToArray()) + "）。请关闭所有兔白字幕窗口后再试。");
            Thread.Sleep(500);
        }
    }

    private static void Preflight(Plan plan)
    {
        long needed = plan.ReserveBytes;
        foreach (string rel in plan.Replace)
        {
            string source = Path.Combine(plan.StagingRoot, rel.Replace('/', '\\'));
            if (!File.Exists(source)) throw new UpdateFailure("暂存文件缺失：" + rel);
            needed += new FileInfo(source).Length;
        }
        if (plan.Manifest != null && !File.Exists(Path.Combine(plan.StagingRoot, plan.Manifest)))
            throw new UpdateFailure("暂存的元件清单缺失");
        long free = FreeBytes(plan.InstallRoot);
        if (free >= 0 && free < needed)
            throw new UpdateFailure(string.Format("安装目录所在磁盘空间不足：需要约 {0:0.0} MB，可用 {1:0.0} MB。",
                needed / 1048576.0, free / 1048576.0));
        string probeDir = Path.Combine(plan.InstallRoot, StateDir);
        try
        {
            Directory.CreateDirectory(probeDir);
            string probe = Path.Combine(probeDir, "write-probe.tmp");
            File.WriteAllText(probe, "probe");
            File.Delete(probe);
        }
        catch (Exception exc) { throw new UpdateFailure("没有写入安装目录的权限：" + exc.Message); }
        List<string> all = new List<string>(plan.Replace);
        all.AddRange(plan.Remove);
        if (plan.Manifest != null) all.Add(plan.Manifest);
        foreach (string rel in all)
        {
            string target = Target(plan.InstallRoot, rel);
            if (!File.Exists(target)) continue;
            try
            {
                if ((File.GetAttributes(target) & FileAttributes.ReadOnly) != 0)
                    throw new UpdateFailure("程序文件为只读，无法更新：" + rel);
                using (FileStream stream = new FileStream(target, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
            }
            catch (UpdateFailure) { throw; }
            catch (UnauthorizedAccessException) { throw new UpdateFailure("没有权限替换：" + rel); }
            catch (IOException) { throw new UpdateFailure("文件仍被占用：" + rel); }
        }
    }

    private static Process StartProgram(Plan plan, string confirmPath)
    {
        try
        {
            string exe = Path.Combine(plan.InstallRoot, plan.RestartExe);
            if (!File.Exists(exe)) return null;
            ProcessStartInfo info = new ProcessStartInfo(exe);
            info.WorkingDirectory = plan.InstallRoot;
            info.UseShellExecute = false;
            if (confirmPath != null) info.EnvironmentVariables["TWOBYTEASR_UPDATE_CONFIRM"] = confirmPath;
            else info.EnvironmentVariables.Remove("TWOBYTEASR_UPDATE_CONFIRM");
            return Process.Start(info);
        }
        catch (Exception exc)
        {
            Log("restart failed: " + exc.Message);
            return null;
        }
    }

    private static int SafeExitCode(Process process)
    {
        try { return process.ExitCode; } catch { return -1; }
    }

    // --------------------------------------------------------------- journal

    private sealed class Journal
    {
        private readonly string path;
        private Journal(string path) { this.path = path; }

        internal static Journal Create(string path, string txid, string backupRoot, string from, string to)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            Directory.CreateDirectory(backupRoot);
            File.WriteAllText(path, "2BYTEASR-UPDATE-JOURNAL\t1\nTXID\t" + txid + "\nBACKUP\t" + backupRoot +
                "\nFROM\t" + from + "\nTO\t" + to + "\n", new UTF8Encoding(false));
            return new Journal(path);
        }

        internal void Add(string kind, string rel)
        {
            using (FileStream stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read))
            {
                byte[] line = new UTF8Encoding(false).GetBytes(kind + "\t" + rel + "\n");
                stream.Write(line, 0, line.Length);
                stream.Flush(true);
            }
        }
    }

    /// <summary>Undo an unfinished (uncommitted) journal left by an interrupted helper.</summary>
    private static bool RecoverJournal(string root, bool includeCommitted)
    {
        string journalPath = Path.Combine(root, StateDir, "journal.txt");
        if (!File.Exists(journalPath)) return true;
        string[] lines = File.ReadAllLines(journalPath, Encoding.UTF8);
        bool committed = Array.Exists(lines, delegate (string l) { return l.StartsWith("COMMITTED\t"); });
        if (committed && !includeCommitted)
        {
            // A committed update whose start was never confirmed: the new
            // program is the current one now; only drop its backup.
            string backup = ReadField(lines, "BACKUP");
            Log("previous committed journal found; keeping its result and removing backup");
            TryDelete(journalPath);
            if (backup != null) TryDeleteTree(backup);
            return true;
        }
        Log("rolling back an unfinished journal");
        return RollBack(root, journalPath);
    }

    private static string ReadField(string[] lines, string key)
    {
        foreach (string line in lines)
            if (line.StartsWith(key + "\t")) return line.Substring(key.Length + 1);
        return null;
    }

    private static bool RollBack(string root, string journalPath)
    {
        string[] lines;
        try { lines = File.ReadAllLines(journalPath, Encoding.UTF8); }
        catch (Exception exc) { Log("cannot read journal: " + exc.Message); return false; }
        string backupRoot = ReadField(lines, "BACKUP");
        bool ok = true;
        for (int i = lines.Length - 1; i >= 0; i--)
        {
            string[] parts = lines[i].Split('\t');
            if (parts.Length != 2) continue;
            string rel = parts[1];
            try
            {
                if (parts[0] == "PLACED")
                {
                    string target = Target(root, rel);
                    if (File.Exists(target)) File.Delete(target);
                }
                else if (parts[0] == "MOVED")
                {
                    string target = Target(root, rel);
                    string backup = Path.Combine(backupRoot, rel.Replace('/', '\\'));
                    if (File.Exists(backup))
                    {
                        if (File.Exists(target)) File.Delete(target);
                        Directory.CreateDirectory(Path.GetDirectoryName(target));
                        File.Move(backup, target);
                    }
                    else if (!File.Exists(target))
                    {
                        Log("rollback: backup missing for " + rel);
                        ok = false;
                    }
                }
            }
            catch (Exception exc)
            {
                Log("rollback step failed for " + rel + ": " + exc.Message);
                ok = false;
            }
        }
        foreach (string line in lines)
        {
            string[] parts = line.Split('\t');
            if (parts.Length == 2 && (parts[0] == "PLACED" || parts[0] == "MOVED"))
                TryDelete(Target(root, parts[1]) + ".update-new");
        }
        if (ok)
        {
            TryDelete(journalPath);
            if (backupRoot != null) TryDeleteTree(backupRoot);
            Log("rollback complete");
        }
        return ok;
    }

    // ----------------------------------------------------- prune / uninstall

    private static int Prune(string root, string previousManifest)
    {
        logPath = Path.Combine(root, StateDir, "update-helper.log");
        if (!File.Exists(previousManifest)) { Log("prune: no previous manifest"); return 0; }
        Dictionary<string, string[]> previous = ManifestFiles(previousManifest);
        string currentPath = Path.Combine(root, "2byteasr_components.json");
        if (!File.Exists(currentPath)) { Log("prune: current manifest missing, nothing removed"); return 0; }
        Dictionary<string, string[]> current = ManifestFiles(currentPath);
        int removed = 0;
        foreach (KeyValuePair<string, string[]> item in previous)
        {
            if (current.ContainsKey(item.Key)) continue;
            string target;
            try { target = Target(root, item.Key); } catch (UpdateFailure) { continue; }
            if (!File.Exists(target)) continue;
            if (new FileInfo(target).Length != Convert.ToInt64(item.Value[0]) || !Sha256Equals(target, item.Value[1]))
            {
                Log("prune: kept changed file " + item.Key);
                continue;
            }
            try { File.Delete(target); removed++; RemoveEmptyParents(root, target); }
            catch (Exception exc) { Log("prune: could not remove " + item.Key + ": " + exc.Message); }
        }
        TryDelete(previousManifest);
        Log("prune removed " + removed + " retired program files");
        return 0;
    }

    private static int RemoveListed(string root)
    {
        logPath = Path.Combine(Path.GetTempPath(), "2byteasr-uninstall-helper.log");
        string currentPath = Path.Combine(root, "2byteasr_components.json");
        string self = Path.GetFullPath(Application.ExecutablePath);
        int removed = 0;
        if (File.Exists(currentPath))
        {
            foreach (KeyValuePair<string, string[]> item in ManifestFiles(currentPath))
            {
                string target;
                try { target = Target(root, item.Key); } catch (UpdateFailure) { continue; }
                if (string.Equals(target, self, StringComparison.OrdinalIgnoreCase) || !File.Exists(target)) continue;
                if (new FileInfo(target).Length != Convert.ToInt64(item.Value[0])) continue;
                try { File.Delete(target); removed++; RemoveEmptyParents(root, target); }
                catch (Exception exc) { Log("uninstall: could not remove " + item.Key + ": " + exc.Message); }
            }
        }
        TryDeleteTree(Path.Combine(root, BackupDir));
        TryDeleteTree(Path.Combine(root, StateDir));
        Log("uninstall removed " + removed + " listed program files under " + root);
        return 0;
    }

    private static Dictionary<string, string[]> ManifestFiles(string path)
    {
        JavaScriptSerializer serializer = new JavaScriptSerializer();
        serializer.MaxJsonLength = int.MaxValue;
        Dictionary<string, object> document = serializer.DeserializeObject(File.ReadAllText(path, Encoding.UTF8))
            as Dictionary<string, object>;
        if (document == null || !"2byteasr-components/1".Equals(document["schema"]))
            throw new UpdateFailure("component manifest has an unsupported format");
        Dictionary<string, string[]> files = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase);
        Dictionary<string, object> components = (Dictionary<string, object>)document["components"];
        foreach (KeyValuePair<string, object> component in components)
        {
            Dictionary<string, object> record = (Dictionary<string, object>)component.Value;
            foreach (object row in (IEnumerable)record["files"])
            {
                object[] cells = (object[])row;
                string rel = Convert.ToString(cells[0]);
                if (IsProtected(rel)) continue;
                files[rel] = new string[] { Convert.ToString(cells[1]), Convert.ToString(cells[2]) };
            }
        }
        return files;
    }

    private static bool Sha256Equals(string path, string expected)
    {
        using (System.Security.Cryptography.SHA256 sha = System.Security.Cryptography.SHA256.Create())
        using (FileStream stream = File.OpenRead(path))
        {
            StringBuilder hex = new StringBuilder(64);
            foreach (byte b in sha.ComputeHash(stream)) hex.Append(b.ToString("x2"));
            return string.Equals(hex.ToString(), expected, StringComparison.OrdinalIgnoreCase);
        }
    }

    private static void RemoveEmptyParents(string root, string file)
    {
        string rootFull = Path.GetFullPath(root).TrimEnd('\\');
        string dir = Path.GetDirectoryName(file);
        while (dir != null && dir.Length > rootFull.Length &&
               dir.StartsWith(rootFull + "\\", StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                if (Directory.GetFileSystemEntries(dir).Length != 0) return;
                Directory.Delete(dir);
            }
            catch { return; }
            dir = Path.GetDirectoryName(dir);
        }
    }

    // ------------------------------------------------------------- helpers

    private static Plan ReadPlan(string planPath)
    {
        string[] lines = File.ReadAllLines(planPath, Encoding.UTF8);
        if (lines.Length < 2 || lines[0] != "2BYTEASR-UPDATE-PLAN\t1") throw new UpdateFailure("unsupported plan header");
        Plan plan = new Plan();
        int operations = 0;
        bool ended = false;
        foreach (string raw in lines)
        {
            if (raw.Length == 0) continue;
            int tab = raw.IndexOf('\t');
            if (tab <= 0) throw new UpdateFailure("malformed plan line");
            string key = raw.Substring(0, tab);
            string value = raw.Substring(tab + 1);
            switch (key)
            {
                case "2BYTEASR-UPDATE-PLAN": break;
                case "install_root": plan.InstallRoot = Path.GetFullPath(value).TrimEnd('\\'); break;
                case "staging_root": plan.StagingRoot = Path.GetFullPath(value).TrimEnd('\\'); break;
                case "from_version": plan.FromVersion = value; break;
                case "to_version": plan.ToVersion = value; break;
                case "wait_pid": plan.WaitPid = int.Parse(value); break;
                case "restart": plan.Restart = value == "1"; break;
                case "restart_exe": plan.RestartExe = CheckRelative(value); break;
                case "confirm_seconds": plan.ConfirmSeconds = int.Parse(value); break;
                case "wait_pid_seconds": plan.WaitPidSeconds = int.Parse(value); break;
                case "process_wait_seconds": plan.ProcessWaitSeconds = int.Parse(value); break;
                case "reserve_bytes": plan.ReserveBytes = long.Parse(value); break;
                case "log": plan.LogPath = value; break;
                case "result": plan.ResultPath = value; break;
                case "REPLACE": plan.Replace.Add(CheckRelative(value)); operations++; break;
                case "REMOVE": plan.Remove.Add(CheckRelative(value)); operations++; break;
                case "MANIFEST": plan.Manifest = CheckRelative(value); operations++; break;
                case "END":
                    if (int.Parse(value) != operations) throw new UpdateFailure("plan is truncated");
                    ended = true;
                    break;
                default: throw new UpdateFailure("unknown plan key " + key);
            }
        }
        if (!ended || plan.InstallRoot == null || plan.StagingRoot == null) throw new UpdateFailure("incomplete plan");
        if (!File.Exists(Path.Combine(plan.InstallRoot, "2byteasr_components.json")))
            throw new UpdateFailure("install root has no component manifest: " + plan.InstallRoot);
        if (plan.StagingRoot.StartsWith(plan.InstallRoot + "\\", StringComparison.OrdinalIgnoreCase))
            throw new UpdateFailure("staging folder must be outside the install folder");
        if (plan.Manifest != null && !string.Equals(plan.Manifest, "2byteasr_components.json", StringComparison.OrdinalIgnoreCase))
            throw new UpdateFailure("unexpected manifest path");
        if (plan.LogPath == null) plan.LogPath = Path.Combine(plan.InstallRoot, StateDir, "update-helper.log");
        foreach (string rel in plan.Replace) Target(plan.InstallRoot, rel);
        foreach (string rel in plan.Remove) Target(plan.InstallRoot, rel);
        return plan;
    }

    private static string CheckRelative(string rel)
    {
        if (string.IsNullOrEmpty(rel) || rel.StartsWith("/") || rel.StartsWith("\\") || rel.Contains(":") || rel.Contains("\\"))
            throw new UpdateFailure("unsafe path: " + rel);
        foreach (string part in rel.Split('/'))
            if (part.Length == 0 || part == "." || part == "..") throw new UpdateFailure("unsafe path: " + rel);
        if (IsProtected(rel)) throw new UpdateFailure("protected path: " + rel);
        return rel;
    }

    private static bool IsProtected(string rel)
    {
        string lowered = rel.ToLowerInvariant();
        foreach (string name in Preserved) if (lowered == name) return true;
        return lowered.StartsWith(StateDir + "/") || lowered.StartsWith(BackupDir + "/");
    }

    private static string Target(string root, string rel)
    {
        CheckRelative(rel);
        string rootFull = Path.GetFullPath(root).TrimEnd('\\');
        string full = Path.GetFullPath(Path.Combine(rootFull, rel.Replace('/', '\\')));
        if (!full.StartsWith(rootFull + "\\", StringComparison.OrdinalIgnoreCase))
            throw new UpdateFailure("path escapes install root: " + rel);
        return full;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool QueryFullProcessImageName(IntPtr process, int flags, StringBuilder name, ref int size);
    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool GetDiskFreeSpaceEx(string directory, out ulong available, out ulong total, out ulong free);

    private static List<string> ProcessesInside(string root)
    {
        List<string> found = new List<string>();
        string prefix = Path.GetFullPath(root).TrimEnd('\\') + "\\";
        int self = Process.GetCurrentProcess().Id;
        foreach (Process process in Process.GetProcesses())
        {
            if (process.Id == self || process.Id == 0) continue;
            IntPtr handle = OpenProcess(0x1000, false, process.Id);  // QUERY_LIMITED_INFORMATION
            if (handle == IntPtr.Zero) continue;
            try
            {
                StringBuilder name = new StringBuilder(1024);
                int size = name.Capacity;
                if (QueryFullProcessImageName(handle, 0, name, ref size) &&
                    name.ToString().StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                    found.Add(Path.GetFileName(name.ToString()) + "#" + process.Id);
            }
            finally { CloseHandle(handle); }
        }
        return found;
    }

    private static long FreeBytes(string directory)
    {
        ulong available, total, free;
        return GetDiskFreeSpaceEx(directory, out available, out total, out free) ? (long)available : -1;
    }

    private static void WriteResult(Plan plan, string status, string detail)
    {
        if (plan == null || string.IsNullOrEmpty(plan.ResultPath)) return;
        try
        {
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            Dictionary<string, object> result = new Dictionary<string, object>();
            result["schema"] = "2byteasr-update-result/1";
            result["status"] = status;
            result["detail"] = detail;
            result["from_version"] = plan.FromVersion;
            result["to_version"] = plan.ToVersion;
            result["finished_utc"] = DateTime.UtcNow.ToString("o");
            Directory.CreateDirectory(Path.GetDirectoryName(plan.ResultPath));
            File.WriteAllText(plan.ResultPath, serializer.Serialize(result), new UTF8Encoding(false));
        }
        catch (Exception exc) { Log("cannot write result: " + exc.Message); }
    }

    private static void Notify(string message, bool error)
    {
        Log((error ? "error: " : "info: ") + message.Replace("\n", " "));
        if (quiet) return;
        MessageBox.Show(message, "兔白字幕更新", MessageBoxButtons.OK, error ? MessageBoxIcon.Error : MessageBoxIcon.Information);
    }

    private static void Log(string message)
    {
        if (string.IsNullOrEmpty(logPath)) return;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(logPath));
            File.AppendAllText(logPath, "[" + DateTime.Now.ToString("o") + "] " + message + Environment.NewLine, new UTF8Encoding(false));
        }
        catch { }
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
    }

    private static void TryDeleteTree(string path)
    {
        TryDeleteTree(path, false);
    }

    private static void TryDeleteTree(string path, bool onlyIfEmpty)
    {
        try
        {
            if (!Directory.Exists(path)) return;
            if (onlyIfEmpty && Directory.GetFileSystemEntries(path).Length != 0) return;
            Directory.Delete(path, !onlyIfEmpty);
        }
        catch { }
    }
}

internal sealed class ProgressWindow : Form
{
    internal int ExitCode;

    internal ProgressWindow(string text)
    {
        Text = "兔白字幕更新";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ControlBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new System.Drawing.Size(420, 110);
        Font = new System.Drawing.Font("Microsoft YaHei UI", 9F);
        Label label = new Label();
        label.Text = text;
        label.AutoSize = false;
        label.SetBounds(20, 18, 380, 40);
        Controls.Add(label);
        ProgressBar bar = new ProgressBar();
        bar.Style = ProgressBarStyle.Marquee;
        bar.SetBounds(20, 64, 380, 18);
        Controls.Add(bar);
    }

    internal void CloseSafe()
    {
        try
        {
            if (IsHandleCreated) BeginInvoke(new MethodInvoker(Close));
            else { Load += delegate { Close(); }; }
        }
        catch { }
    }
}
