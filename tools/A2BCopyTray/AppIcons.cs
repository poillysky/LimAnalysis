namespace A2BCopyTray;

/// <summary>
/// 应用图标。优先级：
/// ① 程序集内嵌的 app.ico（与 &lt;ApplicationIcon&gt; 是同一份文件，但可按需要挑尺寸那一帧）
/// ② 从 EXE 抽取关联图标
/// ③ 程序目录旁的 app.ico
/// ④ 系统默认图标（保证永远不为空）
/// </summary>
internal static class AppIcons
{
    private const string ResourceName = "A2BCopyTray.app.ico";

    private static Icon? _app;

    public static Icon App
    {
        get
        {
            if (_app is not null) return _app;
            _app = FromEmbedded(new Size(32, 32)) ?? FromExe() ?? FromBesideExe() ?? SystemIcons.Application;
            return _app;
        }
    }

    private static Icon? FromEmbedded(Size size)
    {
        try
        {
            using var stream = typeof(AppIcons).Assembly.GetManifestResourceStream(ResourceName);
            if (stream is null) return null;
            // 多尺寸 ico 走这个构造会挑最接近 size 的那一帧，边缘比缩放更干净
            return new Icon(stream, size);
        }
        catch
        {
            return null;
        }
    }

    private static Icon? FromExe()
    {
        try
        {
            var exe = Environment.ProcessPath ?? Application.ExecutablePath;
            if (!string.IsNullOrWhiteSpace(exe) && File.Exists(exe))
                return Icon.ExtractAssociatedIcon(exe);
        }
        catch { /* ignore */ }
        return null;
    }

    private static Icon? FromBesideExe()
    {
        try
        {
            var beside = Path.Combine(AppPaths.AppDir, "app.ico");
            if (File.Exists(beside)) return new Icon(beside);
        }
        catch { /* ignore */ }
        return null;
    }
}
