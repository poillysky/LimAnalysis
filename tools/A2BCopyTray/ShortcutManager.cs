using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace A2BCopyTray;

/// <summary>
/// 桌面快捷方式：创建 / 检测 / 删除。
///
/// 走系统自带的 IShellLink + IPersistFile，不依赖 WScript.Shell
/// （wshom.ocx 在部分被加固过的现场机器上会被组策略注销）。
/// </summary>
internal static class ShortcutManager
{
    /// <summary>快捷方式显示名，同时也是 .lnk 文件名。</summary>
    public const string ShortcutName = "A2B 增量复制";

    private const string Description = "A2B 增量复制 —— 站点图片同步（托盘运行）";

    /// <summary>当前用户桌面目录。</summary>
    public static string DesktopDir =>
        Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);

    /// <summary>桌面快捷方式完整路径。桌面目录可注入，便于测试。</summary>
    public static string PathIn(string desktopDir) =>
        System.IO.Path.Combine(desktopDir, ShortcutName + ".lnk");

    public static string DesktopPath => PathIn(DesktopDir);

    public static bool Exists => File.Exists(DesktopPath);

    /// <summary>当前进程对应的 EXE 路径（单文件发布下就是用户手里那个 exe）。</summary>
    public static string ExecutablePath
    {
        get
        {
            try
            {
                var p = Environment.ProcessPath;
                if (!string.IsNullOrWhiteSpace(p)) return p;
            }
            catch { /* ignore */ }
            try
            {
                return Process.GetCurrentProcess().MainModule?.FileName ?? "";
            }
            catch
            {
                return "";
            }
        }
    }

    /// <summary>创建（或覆盖）快捷方式。成功返回 null，否则返回可直接展示的错误说明。</summary>
    public static string? Create(string? exePath = null, string? linkPath = null)
    {
        try
        {
            var exe = string.IsNullOrWhiteSpace(exePath) ? ExecutablePath : exePath!;
            if (string.IsNullOrWhiteSpace(exe) || !File.Exists(exe))
                return "找不到程序自身路径，无法创建快捷方式。";

            var link = string.IsNullOrWhiteSpace(linkPath) ? DesktopPath : linkPath!;
            var dir = System.IO.Path.GetDirectoryName(link);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

            var shellLink = CreateShellLink();
            shellLink.SetPath(exe);
            shellLink.SetWorkingDirectory(System.IO.Path.GetDirectoryName(exe) ?? "");
            // 图标取 EXE 内嵌图标（索引 0），快捷方式显示的就是程序本体图标
            shellLink.SetIconLocation(exe, 0);
            shellLink.SetDescription(Description);
            ((IPersistFile)shellLink).Save(link, true);

            return File.Exists(link) ? null : "快捷方式写入后未找到文件，请检查桌面目录权限。";
        }
        catch (Exception ex)
        {
            return $"创建快捷方式失败：{ex.Message}";
        }
    }

    /// <summary>删除桌面快捷方式。成功或本来就不存在都返回 true。</summary>
    public static bool Remove(string? linkPath = null)
    {
        try
        {
            var link = string.IsNullOrWhiteSpace(linkPath) ? DesktopPath : linkPath!;
            if (File.Exists(link)) File.Delete(link);
            return true;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>读回快捷方式指向的目标（供自检 / 测试用）。失败返回 null。</summary>
    public static string? ReadTarget(string? linkPath = null)
    {
        try
        {
            var link = string.IsNullOrWhiteSpace(linkPath) ? DesktopPath : linkPath!;
            if (!File.Exists(link)) return null;

            var shellLink = CreateShellLink();
            ((IPersistFile)shellLink).Load(link, 0 /* STGM_READ */);

            var sb = new StringBuilder(1024);
            shellLink.GetPath(sb, sb.Capacity, IntPtr.Zero, 0 /* SLGP_RAWPATH */);
            return sb.ToString();
        }
        catch
        {
            return null;
        }
    }

    private static IShellLinkW CreateShellLink()
    {
        var clsid = new Guid("00021401-0000-0000-C000-000000000046");   // CLSID_ShellLink
        var type = Type.GetTypeFromCLSID(clsid);
        if (type is null) throw new NotSupportedException("系统未注册 ShellLink 组件");
        var obj = Activator.CreateInstance(type);
        if (obj is null) throw new NotSupportedException("ShellLink 组件创建失败");
        return (IShellLinkW)obj;
    }

    // —— COM 互操作声明（顺序必须与 shobjidl.h 完全一致）——

    [ComImport]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cch, IntPtr pfd, uint fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cch);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cch);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cch);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cch, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
        void Resolve(IntPtr hwnd, uint fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport]
    [Guid("0000010b-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPersistFile
    {
        void GetClassID(out Guid pClassID);
        [PreserveSig] int IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, [MarshalAs(UnmanagedType.Bool)] bool fRemember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out IntPtr ppszFileName);
    }
}
