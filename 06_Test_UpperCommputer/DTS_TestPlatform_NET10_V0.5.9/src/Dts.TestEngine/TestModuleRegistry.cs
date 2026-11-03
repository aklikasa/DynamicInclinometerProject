using System.Reflection;
using System.Runtime.Loader;
using Dts.Core;

namespace Dts.TestEngine;

/// <summary>
/// 扫描 Dts.Tests 程序集和可选的 plugins/*.dll：无需每项手动注册。
/// 注意：DLL 中代码具有本机程序权限；只能加载研发人员审核过的受信任插件。
/// </summary>
public sealed class TestModuleRegistry
{
    private readonly Dictionary<string, ITestModule> _modules = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _warnings = [];
    public IReadOnlyCollection<ITestModule> Modules => _modules.Values;
    public IReadOnlyList<string> Warnings => _warnings;
    public ITestModule? Find(string testId) => _modules.GetValueOrDefault(testId);

    public static TestModuleRegistry Discover(Assembly builtInAssembly, string? pluginFolder = null)
    {
        var registry = new TestModuleRegistry();
        registry.AddAssembly(builtInAssembly, "内置测试项目");
        if (string.IsNullOrWhiteSpace(pluginFolder) || !Directory.Exists(pluginFolder)) return registry;
        foreach (string path in Directory.EnumerateFiles(pluginFolder, "*.dll", SearchOption.TopDirectoryOnly)
                     .OrderBy(p => p, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var fullPath = Path.GetFullPath(path);
                Assembly assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(fullPath);
                registry.AddAssembly(assembly, Path.GetFileName(path));
            }
            catch (Exception ex) when (ex is BadImageFormatException or TypeLoadException or
                   ReflectionTypeLoadException or InvalidOperationException or IOException or UnauthorizedAccessException)
            { registry._warnings.Add($"插件加载失败：{Path.GetFileName(path)}：{ex.Message}"); }
        }
        return registry;
    }

    private void AddAssembly(Assembly assembly, string source)
    {
        Type[] types;
        try { types = assembly.GetTypes(); }
        catch (ReflectionTypeLoadException ex)
        {
            types = ex.Types.OfType<Type>().ToArray();
            _warnings.Add($"{source} 部分类型加载失败：{ex.Message}");
        }
        foreach (var type in types.Where(t => !t.IsAbstract && !t.IsInterface &&
                   typeof(ITestModule).IsAssignableFrom(t)).OrderBy(t => t.FullName))
        {
            try
            {
                if (type.GetConstructor(Type.EmptyTypes) is null)
                {
                    _warnings.Add($"{type.FullName} 无公共无参构造函数，跳过");
                    continue;
                }
                var module = (ITestModule)Activator.CreateInstance(type)!;
                if (string.IsNullOrWhiteSpace(module.TestId) ||
                    !new[] { "S0", "S1", "S2", "S3", "S4" }.Contains(module.Stage, StringComparer.OrdinalIgnoreCase))
                {
                    _warnings.Add($"{type.FullName} 编号/阶段无效，跳过");
                    continue;
                }
                if (_modules.TryGetValue(module.TestId, out var old))
                {
                    if (!old.IsExecutable && module.IsExecutable)
                    {
                        _modules[module.TestId] = module;
                        _warnings.Add($"{module.TestId} 由已审核的外部实现替换安全占位类（来源 {source}）");
                    }
                    else _warnings.Add($"重复编号 {module.TestId}（{source}），保留原模块，防止覆盖已实现测试");
                }
                else _modules.Add(module.TestId, module);
            }
            catch (Exception ex)
            { _warnings.Add($"{type.FullName} 创建失败：{ex.Message}"); }
        }
    }

    /// <summary>已有 84 项以 tests.json 为准；新编号可仅凭一个 .cs 模块自动生成按钮。</summary>
    public IReadOnlyList<TestDefinition> MergeDefinitions(IReadOnlyList<TestDefinition> definitions)
    {
        var result = definitions.ToList();
        var seen = definitions.Select(x => x.Id).ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var module in Modules.OrderBy(x => x.Stage).ThenBy(x => x.TestId))
        {
            if (!seen.Add(module.TestId)) continue;
            result.Add(new TestDefinition
            {
                Id = module.TestId, Stage = module.Stage, Name = module.Name,
                Purpose = module.Purpose, Procedure = module.Procedure, Priority = module.Priority,
                Category = "新增模块", Equipment = "由该测试执行类决定", Metrics = "待测试类定义"
            });
        }
        return result;
    }
}
