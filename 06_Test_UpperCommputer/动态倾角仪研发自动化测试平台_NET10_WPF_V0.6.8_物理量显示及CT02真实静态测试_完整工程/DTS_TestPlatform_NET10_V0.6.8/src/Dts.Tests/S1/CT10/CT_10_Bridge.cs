using Dts.TestEngine;

namespace Dts.Tests.S1.CT10;

/// <summary>
/// One-time bridge registration in the host after a REAL streaming adapter is built.
/// This keeps the test module separate from vendor COM/serial drivers. Registration alone
/// never enables a test: the adapter must report IsRealDynamicCaptureReady=true.
/// </summary>
public static class Ct10DynamicBridge
{
    private static readonly object Sync = new();
    private static readonly Dictionary<IStaticAngleHardware, ICt10DynamicHardware> Providers = new();

    public static void Register(IStaticAngleHardware host, ICt10DynamicHardware dynamicProvider)
    {
        ArgumentNullException.ThrowIfNull(host);
        ArgumentNullException.ThrowIfNull(dynamicProvider);
        lock (Sync) Providers[host] = dynamicProvider;
    }
    public static void Unregister(IStaticAngleHardware host)
    {
        lock (Sync) Providers.Remove(host);
    }
    public static ICt10DynamicHardware? Resolve(IStaticAngleHardware host)
    {
        if (host is ICt10DynamicHardware direct) return direct;
        lock (Sync) return Providers.TryGetValue(host, out var provider) ? provider : null;
    }
}
