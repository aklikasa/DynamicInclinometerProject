using System.IO;
using System.Windows;
using System.Windows.Threading;

namespace DynamicInclinometer.App;

public partial class App : System.Windows.Application
{
    internal static string DiagnosticsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "DynamicInclinometerLab", "errors.log");

    internal static void Log(string context, Exception? error = null)
    {
        try
        {
            var path = DiagnosticsPath;
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var message = $"[{DateTimeOffset.Now:O}] {context}";
            if (error is not null) message += Environment.NewLine + error;
            File.AppendAllText(path, message + Environment.NewLine, System.Text.Encoding.UTF8);
        }
        catch { /* logging must not cause a second crash */ }
    }

    protected override void OnStartup(StartupEventArgs e)
    {
        // Register before WPF materializes the StartupUri window.
        AppDomain.CurrentDomain.UnhandledException += (s, args) =>
            Log("APPDOMAIN UNHANDLED; terminating=" + args.IsTerminating, args.ExceptionObject as Exception);
        DispatcherUnhandledException += OnUiUnhandled;
        TaskScheduler.UnobservedTaskException += (s, args) =>
        {
            Log("UNOBSERVED TASK", args.Exception);
            args.SetObserved();
        };
        Log($"STARTUP .NET={Environment.Version}; OS={Environment.OSVersion}; BaseDir={AppContext.BaseDirectory}");
        try
        {
            base.OnStartup(e);
            var window = new MainWindow();
            MainWindow = window;
            window.Show();
        }
        catch (Exception ex)
        {
            Log("STARTUP FAILED", ex);
            try
            {
                MessageBox.Show("上位机启动失败，已生成故障日志：\n" + DiagnosticsPath +
                    "\n\n" + ex.Message,
                    "动态倾角仪启动失败", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            catch { }
            Shutdown(1);
        }
    }

    private void OnUiUnhandled(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        Log("WPF DISPATCHER UNHANDLED", e.Exception);
        // A recoverable UI callback exception should not silently close the application.
        // Native AccessViolation / stack corruption cannot be made safe by this handler.
        try
        {
            MessageBox.Show(MainWindow,
                "界面出现异常，详情已保存到：\n" + DiagnosticsPath +
                "\n\n" + e.Exception.Message +
                "\n\n请先停止采集并检查设备状态。",
                "动态倾角仪运行异常", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        catch { }
        e.Handled = true;
    }

    protected override void OnExit(ExitEventArgs e)
    {
        Log("EXIT; code=" + e.ApplicationExitCode);
        base.OnExit(e);
    }
}
