// Opt-in, out-of-process last-chance exception capture. No code runs in the
// failing Python/Qt process. Dumps stay local and are never put in support ZIPs.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

class NativeCrashProbe {
    static int CaptureNumber=0;
    [StructLayout(LayoutKind.Sequential)] struct ExceptionRecord {
        public uint Code, Flags;
        public IntPtr Nested, Address;
        public uint Parameters;
        public uint Padding;
        public ulong I0,I1,I2,I3,I4,I5,I6,I7,I8,I9,I10,I11,I12,I13,I14;
    }
    [StructLayout(LayoutKind.Explicit, Size=176)] struct DebugEvent {
        [FieldOffset(0)] public uint Kind;
        [FieldOffset(4)] public uint ProcessId;
        [FieldOffset(8)] public uint ThreadId;
        [FieldOffset(16)] public ExceptionRecord Exception;
        [FieldOffset(168)] public uint FirstChance;
        [FieldOffset(16)] public IntPtr FileHandle;
    }
    [StructLayout(LayoutKind.Sequential)] struct ExceptionPointers { public IntPtr Record, Context; }
    [StructLayout(LayoutKind.Sequential, Pack=4)] struct DumpException { public uint ThreadId; public IntPtr Pointers; public int ClientPointers; }
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool DebugActiveProcess(uint id);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool DebugActiveProcessStop(uint id);
    [DllImport("kernel32.dll")] static extern bool DebugSetProcessKillOnExit(bool kill);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool WaitForDebugEvent(out DebugEvent e,uint milliseconds);
    [DllImport("kernel32.dll")] static extern bool ContinueDebugEvent(uint pid,uint tid,uint status);
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint id);
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenThread(uint access,bool inherit,uint id);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetThreadContext(IntPtr thread,IntPtr context);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("dbghelp.dll",SetLastError=true)] static extern bool MiniDumpWriteDump(IntPtr process,uint pid,IntPtr file,uint type,ref DumpException info,IntPtr streams,IntPtr callbacks);
    [DllImport("dbghelp.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool SymInitializeW(IntPtr process,string search,bool invade);
    [DllImport("dbghelp.dll")] static extern bool SymCleanup(IntPtr process);
    [DllImport("dbghelp.dll",SetLastError=true)] static extern bool StackWalk64(uint machine,IntPtr process,IntPtr thread,IntPtr frame,IntPtr context,IntPtr read,IntPtr table,IntPtr module,IntPtr translate);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern IntPtr GetModuleHandleW(string name);
    [DllImport("kernel32.dll",CharSet=CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr module,string name);
    static string Frames(IntPtr process,IntPtr thread,IntPtr original,uint pid) {
        IntPtr frame=Marshal.AllocHGlobal(512),context=Marshal.AllocHGlobal(1280);
        IntPtr aligned=new IntPtr((context.ToInt64()+15)&~15L);
        var frames=new System.Collections.Generic.List<string>();
        try {
            byte[] buffer=new byte[1232];Marshal.Copy(original,buffer,0,buffer.Length);Marshal.Copy(buffer,0,aligned,buffer.Length);
            Marshal.Copy(new byte[512],0,frame,512);
            Marshal.WriteInt64(frame,0,Marshal.ReadInt64(aligned,248));Marshal.WriteInt32(frame,12,3);
            Marshal.WriteInt64(frame,32,Marshal.ReadInt64(aligned,160));Marshal.WriteInt32(frame,44,3);
            Marshal.WriteInt64(frame,48,Marshal.ReadInt64(aligned,152));Marshal.WriteInt32(frame,60,3);
            if(!SymInitializeW(process,"",true))return "[]";
            IntPtr dbg=GetModuleHandleW("dbghelp.dll");
            ulong previous=0;
            for(int i=0;i<96;i++) {
                ulong address=unchecked((ulong)Marshal.ReadInt64(frame,0));
                if(address==0 || (i>1 && address==previous))break;
                string label="0x"+address.ToString("x");
                try {foreach(ProcessModule m in Process.GetProcessById((int)pid).Modules) {
                    ulong start=unchecked((ulong)m.BaseAddress.ToInt64());
                    if(address>=start && address<start+(ulong)m.ModuleMemorySize) {label=m.ModuleName+"+0x"+(address-start).ToString("x");break;}
                }} catch(Exception) {}
                if(address!=previous)frames.Add(Json(label));previous=address;
                if(!StackWalk64(0x8664,process,thread,frame,aligned,IntPtr.Zero,
                    GetProcAddress(dbg,"SymFunctionTableAccess64"),GetProcAddress(dbg,"SymGetModuleBase64"),IntPtr.Zero))break;
            }
        } finally {SymCleanup(process);Marshal.FreeHGlobal(frame);Marshal.FreeHGlobal(context);}
        return "["+String.Join(",",frames.ToArray())+"]";
    }
    static string Json(string value) { return "\""+value.Replace("\\","\\\\").Replace("\"","\\\"")+"\""; }
    static void Capture(DebugEvent e,string output) {
        string stem=Path.Combine(output,"native-"+e.ProcessId+"-"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fffffff")+"-"+(++CaptureNumber));
        ulong address=unchecked((ulong)e.Exception.Address.ToInt64()),offset=0;
        string module="unknown",version="unknown";
        try { foreach(ProcessModule m in Process.GetProcessById((int)e.ProcessId).Modules) {
            ulong start=unchecked((ulong)m.BaseAddress.ToInt64());
            if(address>=start && address<start+(ulong)m.ModuleMemorySize) {
                module=m.ModuleName;offset=address-start;version=m.FileVersionInfo.FileVersion;break;
            }
        }} catch(Exception) {}
        IntPtr process=OpenProcess(0x410,false,e.ProcessId),thread=OpenThread(0x48,false,e.ThreadId);
        IntPtr allocation=Marshal.AllocHGlobal(1280),record=Marshal.AllocHGlobal(152),pointers=Marshal.AllocHGlobal(16);
        IntPtr context=new IntPtr((allocation.ToInt64()+15)&~15L);
        bool dumped=false,contextRead=false;int error=0;string frames="[]";
        try {
            Marshal.Copy(new byte[1232],0,context,1232);Marshal.WriteInt32(context,48,0x10001f);
            contextRead=thread!=IntPtr.Zero && GetThreadContext(thread,context);
            if(contextRead)frames=Frames(process,thread,context,e.ProcessId);
            Marshal.StructureToPtr(e.Exception,record,false);
            Marshal.StructureToPtr(new ExceptionPointers {Record=record,Context=context},pointers,false);
            DumpException info=new DumpException {ThreadId=e.ThreadId,Pointers=pointers,ClientPointers=0};
            using(FileStream file=new FileStream(stem+".dmp",FileMode.CreateNew,FileAccess.Write,FileShare.Read)) {
                dumped=contextRead && MiniDumpWriteDump(process,e.ProcessId,file.SafeFileHandle.DangerousGetHandle(),0x1040,ref info,IntPtr.Zero,IntPtr.Zero);
                error=Marshal.GetLastWin32Error();
            }
        } finally {
            if(process!=IntPtr.Zero)CloseHandle(process);if(thread!=IntPtr.Zero)CloseHandle(thread);
            Marshal.FreeHGlobal(allocation);Marshal.FreeHGlobal(record);Marshal.FreeHGlobal(pointers);
        }
        File.WriteAllText(stem+".json","{\"pid\":"+e.ProcessId+",\"tid\":"+e.ThreadId+
            ",\"exception_code\":"+Json("0x"+e.Exception.Code.ToString("x8"))+
            ",\"fault_module\":"+Json(module)+",\"module_version\":"+Json(version??"")+
            ",\"fault_offset\":"+Json("0x"+offset.ToString("x"))+
            ",\"first_chance\":"+(e.FirstChance!=0).ToString().ToLower()+
            ",\"access_kind\":"+e.Exception.I0+",\"access_address\":"+Json("0x"+e.Exception.I1.ToString("x"))+
            ",\"context_captured\":"+contextRead.ToString().ToLower()+",\"dump_written\":"+dumped.ToString().ToLower()+
            ",\"win32_error\":"+error+",\"native_frames\":"+frames+",\"private_local_artifact\":true}",Encoding.UTF8);
    }
    static int Main(string[] args) {
        if((args.Length!=2 && args.Length!=3) || IntPtr.Size!=8)return 2;
        bool firstAccess=args.Length==3 && args[2]=="--first-access";
        if(args.Length==3 && !firstAccess)return 2;
        int firstAccessCaptures=0;
        uint pid=uint.Parse(args[0]);string output=Path.GetFullPath(args[1]);Directory.CreateDirectory(output);
        if(!DebugActiveProcess(pid)) {File.WriteAllText(Path.Combine(output,"attach-error.txt"),Marshal.GetLastWin32Error().ToString());return 3;}
        DebugSetProcessKillOnExit(false);
        File.WriteAllText(Path.Combine(output,"attached.json"),"{\"pid\":"+pid+",\"last_chance_only\":"+(!firstAccess).ToString().ToLower()+",\"first_access_limit\":3}");
        try {
            while(true) {
                DebugEvent e;if(!WaitForDebugEvent(out e,1000)) {try {if(Process.GetProcessById((int)pid).HasExited)break;}catch(ArgumentException){break;}continue;}
                File.AppendAllText(Path.Combine(output,"debug-events.txt"),e.Kind+" "+e.Exception.Code.ToString("x8")+" "+e.FirstChance+Environment.NewLine);
                uint status=0x10002;
                if(e.Kind==1) {
                    status=e.Exception.Code==0x80000003 ? 0x10002U : 0x80010001U;
                    bool first=firstAccess && e.FirstChance!=0 && e.Exception.Code==0xc0000005 && firstAccessCaptures<3;
                    if(first)firstAccessCaptures++;
                    if(first || e.FirstChance==0 || e.Exception.Code==0xc0000602 || e.Exception.Code==0xc0000409 || e.Exception.Code==0xc0000374) {try {Capture(e,output);}catch(Exception ex){File.WriteAllText(Path.Combine(output,"capture-error.txt"),ex.ToString());}}
                }
                if((e.Kind==3 || e.Kind==6) && e.FileHandle!=IntPtr.Zero)CloseHandle(e.FileHandle);
                ContinueDebugEvent(e.ProcessId,e.ThreadId,status);
                if(e.Kind==5)break;
            }
        } finally {DebugActiveProcessStop(pid);}
        return 0;
    }
}
