// Native Direct3D9 pixel shader: intentionally targets ps_3_0 for WPF ShaderEffect.
// Sampler s0 is WPF's implicit surface, here filled by a VisualBrush of the real
// content behind the glass pane. Therefore its distortion refracts actual pixels
// rather than faking the effect with an alpha-only overlay.
// c0 = Time, c1 = Distortion (0..1), c2.xy = mouse light position (0..1).

sampler2D Input : register(s0);
float Time : register(c0);
float Distortion : register(c1);
float2 Light : register(c2);

float4 main(float2 uv : TEXCOORD) : COLOR
{
    float2 center = uv * 2.0 - 1.0;
    float2 edge2 = abs(center);
    // Blend between a thick peripheral refractive rim and the flatter center.
    float edge = saturate(pow(max(edge2.x, edge2.y), 3.0));
    float t = Time * 0.72;
    float wave = sin(uv.x * 18.0 + t) * cos(uv.y * 23.0 - t * 0.73);
    float2 normal = float2(
        sin(uv.y * 31.0 + t * 0.8) + wave * 0.24,
        cos(uv.x * 26.0 - t * 0.6) - wave * 0.16);
    float2 shift = Distortion * (
        center * (0.006 + 0.018 * edge) + normal * 0.0048);
    float2 pos = saturate(uv + shift);

    // Physical-style wavelength dispersion at the rim: separate sampling
    // coordinates for R/G/B. The source remains the actual background texture.
    float2 chroma = center * (edge * 0.0037 * Distortion);
    float red = tex2D(Input, saturate(pos + chroma)).r;
    float green = tex2D(Input, pos).g;
    float blue = tex2D(Input, saturate(pos - chroma)).b;
    float3 glass = float3(red, green, blue);

    // Lens scattering, moving specular glint and cyan-blue edge tint.
    float diffuse = 0.075 + edge * 0.055;
    float2 fromLight = uv - Light;
    float spec = pow(saturate(1.0 - length(fromLight) * 1.52), 8.0);
    float upperRim = pow(saturate(1.0 - uv.y), 11.0);
    float stroke = pow(edge, 13.0);
    float3 tint = float3(0.73, 0.94, 1.0);
    glass = lerp(glass, tint, diffuse);
    glass += float3(1.0, 0.98, 0.94) * (0.16 * spec + 0.10 * upperRim);
    glass += float3(0.36, 0.69, 0.93) * (0.055 * stroke);
    return float4(saturate(glass), 1.0);
}
