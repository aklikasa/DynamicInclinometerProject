using System.Collections.Generic;

namespace Dts.Tests.S1.CT01;

public sealed record Ct01AxisMetric(
    string Axis, string Unit, long Samples,
    double BeforeMean, double BeforeStd,
    double AfterMean, double AfterStd,
    double MeanShift, double TransformRms, double MaxAbsShift,
    double MaxRecomputeAbsError);

public sealed record Ct01VerificationResult(
    string TestId, string UidHex, string DeviceNumber, string Mode,
    string IdentityProof, string CaptureFolder,
    string StartedUtc, string EndedUtc,
    int Samples, int Batches, int DistinctMcuTicks,
    int SensorOkSamples, int SensorUnverifiedSamples,
    int ProcessedSamples,
    double MaxPhysicalConversionAbsError,
    double MaxRecomputeAbsError,
    IReadOnlyList<Ct01AxisMetric> Metrics,
    string Assessment, string Limitation);
