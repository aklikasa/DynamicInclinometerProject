using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;

namespace DynamicInclinometer.Core;

/// <summary>
/// Human-readable research comparison for a measured and independently synchronized encoder
/// reference. Does not infer time offset, generate fake encoder data or assign a QC PASS.
/// </summary>
public static class Sst810HtmlReport
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static string F(double x)=>x.ToString("0.####",Ci);
    private sealed record Pair(double T,double MR,double MP,double RR,double RP,double ER,double EP);
    public static string Write(string folder, IReadOnlyList<AnglePoint> measured,
       IReadOnlyList<AnglePoint> encoderReference, string deviceId, string refPath,
       double amplitudeDeg,double frequencyHz,bool timestampsCertified)
    {
        if(encoderReference.Count<2)throw new InvalidDataException("需要同步编码器参考角度，而非计划轨迹");
        Directory.CreateDirectory(folder);
        var r=encoderReference.OrderBy(v=>v.Seconds).ToArray();
        var pairs=new List<Pair>();
        foreach(var m in measured)
        {
            int j=Array.BinarySearch(r,new AnglePoint(m.Seconds,0,0),Comparer<AnglePoint>.Create((a,b)=>a.Seconds.CompareTo(b.Seconds)));
            if(j<0)j=~j;
            if(j<=0||j>=r.Length)continue;
            var a=r[j-1];var b=r[j];
            if(b.Seconds<=a.Seconds||m.Seconds-a.Seconds>.03||b.Seconds-m.Seconds>.03)continue;
            var u=(m.Seconds-a.Seconds)/(b.Seconds-a.Seconds);
            double rr=a.RollDeg+AngleEvaluator.Wrap180(b.RollDeg-a.RollDeg)*u;
            double rp=a.PitchDeg+AngleEvaluator.Wrap180(b.PitchDeg-a.PitchDeg)*u;
            pairs.Add(new Pair(m.Seconds,m.RollDeg,m.PitchDeg,rr,rp,
                AngleEvaluator.Wrap180(m.RollDeg-rr),AngleEvaluator.Wrap180(m.PitchDeg-rp)));
        }
        if(pairs.Count<10)throw new InvalidDataException("对齐有效样本不足，无法形成报告");
        var metrics=AngleEvaluator.Evaluate(measured,encoderReference);
        string Graph(Func<Pair,double> getter1,Func<Pair,double> getter2,string c1,string c2,string first,string second)
        {
            const double w=980,h=235,left=65,right=25,top=20,bottom=35;
            double lo=Math.Min(pairs.Min(getter1),pairs.Min(getter2));
            double hi=Math.Max(pairs.Max(getter1),pairs.Max(getter2));
            double padding=Math.Max((hi-lo)*.1,.002);lo-=padding;hi+=padding;
            double t0=pairs[0].T,dt=Math.Max(1e-6,pairs[^1].T-t0);
            string Poly(Func<Pair,double> f)
            {
                int stride=Math.Max(1,pairs.Count/850);
                return string.Join(" ",pairs.Where((_,i)=>i%stride==0||i==pairs.Count-1)
                  .Select(x=>F(left+(x.T-t0)/dt*(w-left-right))+","+F(h-bottom-(f(x)-lo)/(hi-lo)*(h-top-bottom))));
            }
            var sb=new StringBuilder();sb.Append($"<svg viewBox='0 0 {F(w)} {F(h)}' role='img' aria-label='时间序列'>");
            for(int i=0;i<5;i++)
            {
                double y=top+i*(h-top-bottom)/4;double v=hi-i*(hi-lo)/4;
                sb.Append($"<line x1='{F(left)}' x2='{F(w-right)}' y1='{F(y)}' y2='{F(y)}' stroke='#dbe4ef' stroke-dasharray='4 5'/>"+
                    $"<text x='5' y='{F(y+4)}' font-size='11' fill='#52667c'>{F(v)}°</text>");
            }
            sb.Append($"<polyline fill='none' stroke='{c1}' stroke-width='2' points='{Poly(getter1)}'/>"+
                      $"<polyline fill='none' stroke='{c2}' stroke-width='1.5' points='{Poly(getter2)}'/>");
            sb.Append($"<text x='{F(left)}' y='{F(h-8)}' font-size='11' fill='#54677b'>{F(t0)} s</text>"+
                $"<text x='{F(w-110)}' y='{F(h-8)}' font-size='11' fill='#54677b'>{F(pairs[^1].T)} s</text></svg>");
            return sb.ToString();
        }
        var sb2=new StringBuilder();
        sb2.Append("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"+
          "<title>动态倾角仪 SINE 对标分析报告（研究用）</title>"+
          "<style>body{font-family:'Microsoft YaHei',Arial,sans-serif;margin:35px auto;max-width:1100px;color:#17293d;background:#f8fafc}h1{margin-bottom:5px}.note{color:#8b3f17;background:#fff2db;border-left:5px solid #d48621;padding:13px;margin:14px 0}table{border-collapse:collapse;width:100%;margin:13px 0}th,td{border:1px solid #d3deeb;padding:9px;text-align:left}th{background:#e9f0f8}.card{background:#fff;border:1px solid #d6e0eb;border-radius:8px;padding:17px;margin:17px 0}svg{width:100%;height:auto}.legend span{display:inline-block;margin-right:23px}.sub{color:#607184;font-size:12px}@media print{body{margin:12mm;max-width:none}.card{break-inside:avoid}}</style></head><body>");
        sb2.Append("<h1>动态倾角仪 · SST810 运动条件对标分析</h1><p class='sub'>实测数据与参考角时间同步验证后使用；并非 SST810 厂商签发报告</p>");
        sb2.Append(timestampsCertified?
          "<div class='note'>操作员声明：时基已校验。软件无法独立证明同步误差或转台计量不确定度；本报告仍为研发分析，非出厂 QC PASS。</div>":
          "<div class='note'>未通过独立时间同步验证：统计数值仅供探索，不能作为动态测角精度或 QC PASS 的依据。</div>");
        sb2.Append("<table><tr><th>设备编号</th><td>"+WebUtility.HtmlEncode(deviceId)+"</td><th>参考数据</th><td>"+WebUtility.HtmlEncode(Path.GetFileName(refPath))+"</td></tr>"+
          $"<tr><th>计划幅值</th><td>±{F(amplitudeDeg)}°</td><th>计划频率</th><td>{F(frequencyHz)} Hz</td></tr>"+
          $"<tr><th>对齐样本</th><td>{metrics.Count}</td><th>导出时间</th><td>{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss zzz}</td></tr></table>");
        sb2.Append("<div class='card'><h2>Roll 横滚角：实测与编码器参考</h2><p class='legend'><span style='color:#1669c1'>■ 实测</span><span style='color:#e08a30'>■ 实际编码器参考</span></p>");
        sb2.Append(Graph(x=>x.MR,x=>x.RR,"#1669c1","#e08a30","测量","参考"));sb2.Append("</div>");
        sb2.Append("<div class='card'><h2>Roll 角度误差</h2>");
        sb2.Append(Graph(x=>x.ER,x=>0,"#d33d42","#91a2b0","误差","零线"));sb2.Append("</div>");
        sb2.Append("<div class='card'><h2>Pitch 俯仰角：实测与编码器参考</h2><p class='legend'><span style='color:#1669c1'>■ 实测</span><span style='color:#e08a30'>■ 实际编码器参考</span></p>");
        sb2.Append(Graph(x=>x.MP,x=>x.RP,"#1669c1","#e08a30","测量","参考"));sb2.Append("</div>");
        sb2.Append("<div class='card'><h2>Pitch 角度误差</h2>");
        sb2.Append(Graph(x=>x.EP,x=>0,"#d33d42","#91a2b0","误差","零线"));sb2.Append("</div>");
        sb2.Append($"<table><tr><th>指标</th><th>Roll</th><th>Pitch</th></tr>"+
          $"<tr><td>RMSE (°)</td><td>{F(metrics.RollRmseDeg)}</td><td>{F(metrics.PitchRmseDeg)}</td></tr>"+
          $"<tr><td>最大绝对误差 (°)</td><td>{F(metrics.RollMaxAbsDeg)}</td><td>{F(metrics.PitchMaxAbsDeg)}</td></tr>"+
          $"<tr><td>平均有符号偏差 (°)</td><td>{F(metrics.RollBiasDeg)}</td><td>{F(metrics.PitchBiasDeg)}</td></tr></table>");
        sb2.Append("<p class='sub'>测量角度误差使用 wrap180 圆周差；参考线性插值的时间容差为每侧 ≤30 ms，未自动优化时间延迟。报告不声称参考转台的计量精度，也不自动纠正内轴 0/外轴 2 到 Roll/Pitch 的几何映射。运动谱、相位延迟与旋转中心杆臂影响需要另行评价。</p>");
        sb2.Append("</body></html>");
        string filename=Path.Combine(folder,"SST810_style_research_comparison.html");
        File.WriteAllText(filename,sb2.ToString(),new UTF8Encoding(false));
        return filename;
    }
}
