using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Windows;
using Dts.Core;
using Dts.TestEngine;

namespace Dts.Wpf.TestWindows;

public partial class GenericTestWindow : Window
{
    private readonly TestDefinition _definition;
    private readonly ITestModule? _module;
    private readonly TestRunner _runner;
    private readonly ITestHardware _hardware;
    private CancellationTokenSource? _cts;
    public GenericTestWindow(TestDefinition def,ITestModule? module,TestRunner runner,
        ITestHardware hardware,string root)
    {
        InitializeComponent();
        _definition=def;_module=module;_runner=runner;_hardware=hardware;
        Title=$"{def.Id} - {def.Name}";Header.Text=$"{def.Id} · {def.Name}";
        StageLabel.Text=$"阶段 {def.Stage} / 优先级 {def.Priority}";
        Purpose.Text="目标："+def.Purpose;
        Procedure.Text="试验步骤："+def.Procedure;
        Implementation.Text=module?.ImplementationNote??"没有对应实现文件";
        OutputRoot.Text="报告根目录："+root;
        StartBtn.IsEnabled=module?.IsExecutable==true;
        if(module?.IsExecutable!=true){StartBtn.Content="尚未开发执行模块";Status.Text="只提供方案查看，不生成假测试数据";}
        if(def.Id=="CT-12")Duration.Text="600";
    }
    private async void RunClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null||_module?.IsExecutable!=true)return;
        try
        {
            if(!double.TryParse(Duration.Text,NumberStyles.Float,CultureInfo.InvariantCulture,out double sec)||sec<1||sec>86400)
                throw new InvalidDataException("采样时长必须为1至86400秒");
            if(_hardware.CurrentIdentity is null)
                throw new InvalidOperationException("请在主窗口先连接 IMU 并读取真实 UID");
            if(!_module.RequiresStaticBench)
                throw new NotSupportedException("此项目要求专用机械互锁/操作界面，未安装经过验证的运行窗口");
            if(MessageBox.Show(this,$"真实采集 {_definition.Id}，时长 {sec} 秒；请确认 IMU 固定且转台已停止。\n继续？",
                "确认真实设备测试",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
            _cts=new CancellationTokenSource();StartBtn.IsEnabled=false;StopBtn.IsEnabled=true;
            var p=new Progress<string>(msg=>Status.Text=msg);
            var result=await _runner.RunAsync(_module,new TestExecutionContext(_definition,
                TimeSpan.FromSeconds(sec),_hardware,p),_cts.Token);
            Status.Text=result.Summary;
        }
        catch(OperationCanceledException){Status.Text="已取消；不得认定完成";}
        catch(Exception ex){Status.Text=ex.Message;MessageBox.Show(this,ex.Message,"测试未完成");}
        finally{_cts?.Dispose();_cts=null;StartBtn.IsEnabled=_module?.IsExecutable==true;StopBtn.IsEnabled=false;}
    }
    private void CancelClick(object sender,RoutedEventArgs e)=>_cts?.Cancel();
    private void CloseClick(object sender,RoutedEventArgs e)=>Close();
    private void OnClosing(object? sender,CancelEventArgs e)
    {
        if(_cts is not null){e.Cancel=true;_cts.Cancel();MessageBox.Show("任务仍在取消和保存数据中，结束后才能关闭。");}
    }
}
