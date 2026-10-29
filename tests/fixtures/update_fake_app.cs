// Test stand-in for 2ByteASR.exe used by tests/test_update_helper.py.
// TWOBYTEASR_FAKE_BEHAVIOR: "confirm" writes the update confirmation file,
// "crash" exits 3 before confirming, "sleep:<seconds>" just waits.
using System;
using System.IO;
using System.Threading;

internal static class FakeApp
{
    private static int Main()
    {
        string behavior = Environment.GetEnvironmentVariable("TWOBYTEASR_FAKE_BEHAVIOR") ?? "confirm";
        string confirm = Environment.GetEnvironmentVariable("TWOBYTEASR_UPDATE_CONFIRM");
        string marker = Environment.GetEnvironmentVariable("TWOBYTEASR_FAKE_STARTED");
        if (!string.IsNullOrEmpty(marker)) File.AppendAllText(marker, (confirm ?? "<none>") + Environment.NewLine);
        if (behavior.StartsWith("sleep:")) { Thread.Sleep(int.Parse(behavior.Substring(6)) * 1000); return 0; }
        if (behavior == "crash" && !string.IsNullOrEmpty(confirm)) return 3;
        if (!string.IsNullOrEmpty(confirm)) File.WriteAllText(confirm, "{\"ok\":true}");
        return 0;
    }
}
