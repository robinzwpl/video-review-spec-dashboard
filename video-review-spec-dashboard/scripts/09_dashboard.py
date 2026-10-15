# -*- coding: utf-8 -*-
"""
生成分价位性能指标看板（单文件 HTML + ECharts，light 主题）。

三块内容 + 一个特殊技术专栏：
1. 档位 × 核心指标对比（热力图 + 分组柱状图）
2. 各价位段画像卡
3. 选购建议
4. 特殊技术特性专栏（玲珑控色区、万象分区、画质芯片等）
"""
import os
import re
import sys
import json
from collections import defaultdict


# 档位划分（依据视频实际章节卡 + 实际价格分布，不是预设值）
# 实际价格区间 2821.9 - 10649.1 元，32 台分布：
#   <3500: 6台  3500-4500: 4台  4500-6000: 8台
#   6000-8000: 7台  8000-11000: 6台  >=11000: 1台
TIERS = [
    (0, 3500, "3000元档", "第一档：能看和看着难受的分界线"),
    (3500, 4500, "3500-4500元", "第二档：独立分区 + 原生高刷"),
    (4500, 6000, "4500-6000元", "第三档：均衡之选"),
    (6000, 8000, "6000-8000元", "第四档：中高端"),
    (8000, 11000, "8000-11000元", "第五档：8000 元以上"),
    (11000, 10 ** 9, "11000元以上", "万元附近旗舰"),
]

# 色域按标准分组，不同标准不可混算
COLOR_STD_GROUPS = [
    ("% DCI-P3", "DCI-P3"),
    ("% BT.2020", "BT.2020"),
    ("% sRGB", "sRGB"),
    ("% BT.709", "BT.709"),
]


def tier_of(price):
    if price is None:
        return None
    for lo, hi, name, desc in TIERS:
        if lo <= price < hi:
            return name
    return None


def build_payload(models):
    rows = []
    for m in sorted(models, key=lambda x: x.get("first_seen", 0)):
        p = m.get("params", {})
        price = p.get("价格", {}).get("value")
        cg = p.get("色域", {})
        bright = p.get("峰值亮度", {})
        row = {
            "brand": m.get("brand") or "?",
            "model": m.get("model") or "?",
            "price": price,
            "tier": tier_of(price),
            "screen": p.get("屏幕", {}).get("value"),
            "zones": p.get("分区数", {}).get("value"),
            "zones_type": p.get("分区数", {}).get("zone_type"),
            "zones_exact": p.get("分区数", {}).get("exact"),
            "zones_raw": p.get("分区数", {}).get("raw"),
            "color_zone": p.get("控色区", {}).get("value"),
            "color_zone_raw": p.get("控色区", {}).get("raw"),
            "bright": bright.get("value"),
            "bright_min": bright.get("value_min"),
            "bright_is_range": bright.get("is_range"),
            "bright_raw": bright.get("raw"),
            "refresh": p.get("刷新率", {}).get("value"),
            "refresh_native": p.get("刷新率", {}).get("is_native"),
            "refresh_raw": p.get("刷新率", {}).get("raw"),
            "refresh_boost": p.get("刷新率_倍频", {}).get("value"),
            "color_val": cg.get("value"),
            "color_std": cg.get("unit"),
            "color_raw": cg.get("raw"),
            "color_err": cg.get("ocr_error", False),
            "mem": p.get("内存", {}).get("value"),
            "storage": p.get("存储", {}).get("value"),
            "cpu": p.get("处理器", {}).get("value"),
            "hdmi21": p.get("HDMI2.1数量", {}).get("value"),
            "hdmi20": p.get("HDMI2.0数量", {}).get("value"),
            "speaker": p.get("发声单元", {}).get("value"),
            "specials": m.get("specials", []),
            "notes": [n.get("note_text", "") for n in m.get("notes", [])],
            "ts": m.get("first_seen", 0),
            "verified": bool(m.get("verified")),
        }
        rows.append(row)
    return rows


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>75寸电视分价位性能指标看板</title>
<!--__ECHARTS_INLINE__-->
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
 background:#f5f6f8;color:#1f2329;padding:22px;line-height:1.6}
.wrap{max-width:1440px;margin:0 auto}
h1{font-size:27px;font-weight:600;margin-bottom:6px}
.sub{color:#646a73;font-size:13.5px;margin-bottom:16px}
.sub b{color:#3370ff}
.notice{background:#fff8e6;border-left:4px solid #ffab00;padding:13px 17px;
 border-radius:4px;font-size:13px;color:#5c4a00;margin-bottom:18px;line-height:1.85}
.notice b{color:#d46b08}
.card{background:#fff;border-radius:8px;padding:20px;margin-bottom:18px;
 box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card>h2{font-size:18px;font-weight:600;padding-left:10px;
 border-left:3px solid #3370ff;margin-bottom:5px}
.card>.d{color:#8f959e;font-size:12.5px;margin:6px 0 16px 13px}
.chart{width:100%;height:440px}
.chart.sm{height:360px}
.tier-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:15px}
.tc{border:1px solid #e5e6eb;border-radius:6px;padding:15px;background:#fafbfc}
.tc h3{font-size:15px;font-weight:600;margin-bottom:2px}
.tc .tsub{font-size:11.5px;color:#8f959e;margin-bottom:11px}
.tc table{width:100%;border-collapse:collapse;font-size:12.5px}
.tc td{padding:5px 0;border-bottom:1px dashed #eceef0;vertical-align:top}
.tc td.k{color:#646a73;white-space:nowrap;padding-right:8px;width:76px}
.tc td.v{text-align:right;font-weight:500}
.miss{color:#c9cdd4;font-weight:400!important}
.rng{color:#fa8c16;font-size:11px}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}
.chip{background:#eef3ff;color:#2b5fd9;padding:3px 9px;border-radius:11px;font-size:11.5px}
.chip.hl{background:#fff1e6;color:#d4380d}
.chip.ok{background:#f0f9eb;color:#237804}
.rec{display:grid;grid-template-columns:1fr1fr;gap:15px}
.rb{border-radius:6px;padding:16px}
.rb.g{background:#f0f9eb;border:1px solid #b7eb8f}
.rb.w{background:#fff1f0;border:1px solid #ffa39e}
.rb h3{font-size:15px;margin-bottom:9px}
.rb li{font-size:13px;margin:7px 0;line-height:1.65}
.tblwrap{overflow-x:auto}
table.all{border-collapse:collapse;font-size:12.5px;white-space:nowrap;width:100%}
table.all th{background:#f7f8fa;padding:9px;font-weight:600;text-align:left;
 border-bottom:1px solid #e5e6eb;position:sticky;top:0}
table.all td{padding:8px 9px;border-bottom:1px solid #f0f1f3}
table.all td.n{text-align:right;font-variant-numeric:tabular-nums}
table.all td.miss{color:#c9cdd4}
table.all tr:hover td{background:#fafbfc}
.tag{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;
 background:#eef1f4;color:#4a5058;margin-left:4px}
.tag.warn{background:#fff1e6;color:#d46b08}
.tag.ok{background:#f6ffed;color:#389e0d}
.tag.bt{background:#e6f4ff;color:#0958d9}
.tierbar{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:14px}
.tierbar .tb{background:#f0f2f5;padding:5px 12px;border-radius:15px;font-size:12.5px;
 color:#5a6069;cursor:pointer;user-select:none}
.tierbar .tb.on{background:#3370ff;color:#fff}
</style></head><body>
<div class="wrap">
<h1>75 寸电视分价位性能指标看板</h1>
<div class="sub">
数据源：科技绝对值《七大品牌 32 台 75 寸电视横评》（2026-09-23）·共 <b>__N__</b> 台机型<br>
提取方式：视频关键帧 OCR（参数卡）+ 音频转写交叉验证 · 每台标注来源帧时间戳可回溯
</div>

<div class="notice">
<b>数据口径说明（务必先读，直接影响数值可比性）</b><br>
① <b>色域按标准分列</b>：sRGB / DCI-P3 / BT.2020 / BT.709 是不同标准，<b>数值不可跨标准比较</b>；<br>
② <b>刷新率以原生 4K 口径为主</b>，倍频（如 288Hz 倍频）与 2K 模式单独标注，不与原生值混算；<br>
③ <b>亮度常为区间</b>（如 4000-5000 nits），图中取上限，完整区间见明细表；<br>
④ <b>分区类型不同算法不可直比</b>：万象分区（TCL/雷鸟）/独立背光分区 / 超级分区（创维）/无分区；<br>
⑤ 标注「未提取」表示视频参数卡未给出该字段，<b>不做推测填充</b>；「待确认」表示 OCR 识别异常需人工核对。
</div>

<div class="card">
<h2>一、档位 × 核心指标对比</h2>
<div class="d">热力图取各档位该指标的最优值（代表该档性能上限）。点击档位标签可筛选下方明细表。</div>
<div class="chart" id="c1"></div>
</div>

<div class="card">
<h2>二、分档柱状对比</h2>
<div class="d">三档核心指标横向对比，注意不同口径数值不可直接比较。</div>
<div class="chart" id="c2"></div>
</div>

<div class="card">
<h2>三、各价位段画像卡</h2>
<div class="d">逐档展开代表机型与关键指标，底部为该档特殊技术特性。</div>
<div class="tierbar" id="tierbar"></div>
<div class="tier-grid" id="c3"></div>
</div>

<div class="card">
<h2>四、特殊技术特性</h2>
<div class="d">各品牌独有的画质/背光技术，按归属品牌归类。这些是同价位段的差异化要素。</div>
<div id="c4"></div>
</div>

<div class="card">
<h2>五、选购建议</h2>
<div class="d">基于视频的价格带与指标分布，非厂商推荐。</div>
<div class="rec">
<div class="rb g"><h3>推荐关注</h3><ul id="rg"></ul></div>
<div class="rb w"><h3>需权衡 / 谨慎</h3><ul id="rw"></ul></div>
</div>
</div>

<div class="card">
<h2>六、完整参数明细</h2>
<div class="d">全部 __N__ 台机型逐条列出。缺失字段显式标注，不填 0。</div>
<div class="tblwrap"><table class="all" id="c5"></table></div>
</div>
</div>

<script>
const D = __DATA__;
const F = n => n===null||n===undefined ? '<span class="miss">未提取</span>' : n;

// ==================== 一、热力图 ====================
const metrics = [
  {k:'bright', label:'峰值亮度(nit)'},
  {k:'zones',  label:'背光分区'},
  {k:'refresh',label:'原生刷新(Hz)'},
];
const tiers = D.tiers;

const hm = [];
metrics.forEach((m,mi)=>{
  tiers.forEach((t,ti)=>{
    const items = D.rows.filter(r=>r.tier===t && r[m.k]!==null);
    const v = items.length ? Math.max(...items.map(r=>r[m.k])) : '-';
    hm.push([mi,ti,v]);
  });
});

const c1 = echarts.init(document.getElementById('c1'));
c1.setOption({
  tooltip:{ formatter:p=>{
    const v=p.value[2];
    if(v==='-') return metrics[p.value[0]].label+'<br/>'+tiers[p.value[1]]+'<br/><b>该档未提取到该指标</b>';
    // 玲珑控色区与背光分区口径不同，需分别列出机型并注明
    const hit=D.rows.filter(r=>r.tier===tiers[p.value[1]]&&r[metrics[p.value[0]].k]===v);
    const names=hit.map(r=>r.brand+' '+r.model).join('、');
    let extra='';
    if(metrics[p.value[0]].k==='zones'){
      const cz=D.rows.filter(r=>r.tier===tiers[p.value[1]]&&r.color_zone!==null);
      if(cz.length) extra='<br/><span style="color:#fa8c16">玲珑控色区（不同口径，未计入）：'
        +cz.map(r=>r.brand+' '+r.model+' '+r.color_zone+'个').join('、')+'</span>';
    }
    return metrics[p.value[0]].label+'<br/>'+tiers[p.value[1]]+'<br/>档内最优：<b>'+v+'</b>'
      +'<br/><span style="color:#999">机型：'+names+'</span>'+extra;
  }},
  grid:{left:130,right:60,top:30,bottom:70},
  xAxis:{type:'category',data:tiers,axisLabel:{fontSize:12,interval:0,rotate:12},
    splitArea:{show:true}},
  yAxis:{type:'category',data:metrics.map(m=>m.label),splitArea:{show:true}},
  visualMap:{min:0,max:Math.max(...hm.filter(d=>d[2]!=='-').map(d=>d[2]),1),
    calculable:true,orient:'vertical',right:10,top:'center',
    inRange:{color:['#e8f4ff','#b3d9ff','#4096ff','#0050b3']}},
  series:[{type:'heatmap',data:hm,
    label:{show:true,formatter:p=>p.value[2]==='-'?'未提取':p.value[2],fontSize:12},
    itemStyle:{borderColor:'#fff',borderWidth:2}}]
});

// ==================== 二、柱状图 ====================
const c2 = echarts.init(document.getElementById('c2'));
c2.setOption({
  tooltip:{trigger:'axis'},
  legend:{top:0,data:metrics.map(m=>m.label)},
  grid:{left:70,right:30,top:45,bottom:70},
  xAxis:{type:'category',data:tiers,axisLabel:{fontSize:12,interval:0,rotate:12}},
  yAxis:{type:'value',name:'数值（口径不同，不可直接比较）'},
  series:metrics.map((m,i)=>({
    name:m.label,type:'bar',
    data:tiers.map(t=>{
      const items=D.rows.filter(r=>r.tier===t&&r[m.k]!==null);
      return items.length?Math.max(...items.map(r=>r[m.k])):0;
    }),
    itemStyle:{color:['#4096ff','#52c41a','#fa8c16'][i]},
    label:{show:true,position:'top',fontSize:11,formatter:p=>p.value===0?'':p.value}
  }))
});

// ==================== 三、画像卡 ====================
let curTier = null;
function renderTiers(){
  const box=document.getElementById('c3');
  const list = curTier ? tiers.filter(t=>t===curTier) : tiers;
  box.innerHTML = list.map(t=>{
    const items=D.rows.filter(r=>r.tier===t);
    const desc=D.tierDesc[t]||'';
    if(!items.length) return `<div class="tc"><h3>${t}</h3><div class="tsub">${desc}</div>
      <div class="miss">该档位暂未提取到机型</div></div>`;
    const cards=items.slice(0,6).map(r=>{
      const sp=(r.specials||[]).map(s=>s.name);
      const chips=sp.length?'<div class="chips">'+sp.map(n=>`<span class="chip">${n}</span>`).join('')+'</div>':'';
      const brightCell = r.bright===null?F(null)
        : r.bright+(r.bright_is_range?`<span class="rng"> (${r.bright_min}-${r.bright}区间)</span>`:'');
      const zoneCell = r.zones===null ? F(null)
        : r.zones+(r.zones_exact===false?'<span class="rng"> 档次</span>':'')
          +(r.zones_type?`<span class="tag">${r.zones_type}</span>`:'');
      const cgCell = r.color_err? `<span class="tag warn">待确认</span> ${r.color_raw||''}`
        : (r.color_val===null?F(null):`${r.color_val}${r.color_std}`);
      return `<div class="tc">
        <h3>${r.brand} ${r.model}${r.verified?'<span class="tag ok">已核对</span>':''}</h3>
        <div class="tsub">来源 @${Math.round(r.ts)}s</div>
        <table>
          <tr><td class="k">价格</td><td class="v">${r.price===null?F(null):r.price+' 元'}</td></tr>
          <tr><td class="k">屏幕</td><td class="v">${r.screen||F(null)}</td></tr>
          <tr><td class="k">背光分区</td><td class="v">${zoneCell}</td></tr>
          ${r.color_zone?`<tr><td class="k">玲珑控色区</td><td class="v"><span class="tag hl">${r.color_zone} 个</span></td></tr>`:''}
          <tr><td class="k">峰值亮度</td><td class="v">${brightCell}</td></tr>
          <tr><td class="k">原生刷新</td><td class="v">${r.refresh===null?F(null):r.refresh+' Hz'}</td></tr>
          ${r.refresh_boost?`<tr><td class="k">倍频</td><td class="v"><span class="tag warn">${r.refresh_boost} Hz</span></td></tr>`:''}
          <tr><td class="k">色域</td><td class="v">${cgCell}</td></tr>
          <tr><td class="k">内存/存储</td><td class="v">${(r.mem||r.storage)?(F(r.mem)+' / '+F(r.storage))+' GB':F(null)}</td></tr>
          <tr><td class="k">处理器</td><td class="v">${r.cpu||F(null)}</td></tr>
        </table>${chips}</div>`;
    }).join('');
    const more = items.length>6?`<div class="miss" style="margin-top:9px;font-size:12px">…另有 ${items.length-6} 款，见下方明细表</div>`:'';
    return `<div><h3 style="font-size:15px;font-weight:600;margin:4px 0 2px">${t}
      <span class="tag">${items.length} 款</span></h3>
      <div class="tsub" style="font-size:11.5px;color:#8f959e;margin-bottom:10px">${desc}</div>
      <div class="tier-grid">${cards}</div>${more}</div>`;
  }).join('');
}
const tb=document.getElementById('tierbar');
tb.innerHTML='<div class="tb on" data-t="">全部档位</div>'+
  tiers.map(t=>`<div class="tb" data-t="${t}">${t}</div>`).join('');
tb.querySelectorAll('.tb').forEach(el=>{
  el.onclick=()=>{
    tb.querySelectorAll('.tb').forEach(x=>x.classList.remove('on'));
    el.classList.add('on');
    curTier=el.dataset.t||null;
    renderTiers(); renderTable();
  };
});
renderTiers();

// ==================== 四、特殊技术 ====================
const byType={};
D.rows.forEach(r=>{
  (r.specials||[]).forEach(s=>{
    const k=s.type||'其他';
    (byType[k]=byType[k]||[]).push({brand:r.brand,model:r.model,name:s.name});
  });
});
const uniq={};
Object.keys(byType).forEach(k=>{
  const seen=new Set();
  uniq[k]=byType[k].filter(x=>{
    const key=x.brand+'|'+x.name;
    if(seen.has(key))return false; seen.add(key); return true;
  });
});
document.getElementById('c4').innerHTML = Object.keys(uniq).map(k=>`
  <div style="margin-bottom:16px">
    <div style="font-size:14px;font-weight:600;margin-bottom:8px">${k}
      <span class="tag">${uniq[k].length} 个机型采用</span></div>
    <div class="chips">${uniq[k].map(x=>
      `<span class="chip ${x.brand==='海信'?'hl':(x.brand==='创维'||x.brand==='TCL'||x.brand==='雷鸟'?'ok':'')}"
       title="${x.brand} ${x.model}">${x.name}<span style="opacity:.65"> · ${x.brand}</span></span>`).join('')}
    </div>
  </div>`).join('') || '<div class="miss">未提取到特殊技术特性</div>';

// ==================== 五、选购建议 ====================
const stats=tiers.map(t=>{
  const it=D.rows.filter(r=>r.tier===t);
  const pr=it.map(r=>r.price).filter(x=>x!==null);
  const br=it.filter(r=>r.bright!==null).map(r=>r.bright);
  const zo=it.filter(r=>r.zones!==null&&r.zones_exact!==false).map(r=>r.zones);
  return {t,n:it.length,min:pr.length?Math.min(...pr):null,max:pr.length?Math.max(...pr):null,
    avgB:br.length?Math.round(br.reduce((a,b)=>a+b,0)/br.length):null,
    maxZ:zo.length?Math.max(...zo):null};
});
const find=n=>stats.find(s=>s.t.includes(n));
const f3=find('3500'),f5=find('4500'),f6=find('6000'),f8=find('8000'),f12=find('12000');
let g='';
if(f3&&f5&&f3.avgB&&f5.avgB){
  const d=Math.round((f5.avgB-f3.avgB)/f3.avgB*100);
  g+=`<li><b>3500-4500元档</b>：共 ${f3.n} 款，平均亮度约 ${f3.avgB} nit；
     相比 4500-6000 档${d>=0?`低约 ${d}%`:`高约 ${-d}%`}。
     视频定位为"能看和看着难受的分界线"，${d<40?'差异不大，日常内容够用。':'若主打HDR，差距会明显。'}</li>`;
}
if(f5){g+=`<li><b>4500-6000元档</b>：共 ${f5.n} 款${f5.avgB?`，平均亮度约 ${f5.avgB} nit`:''}。
  视频强调此档"独立分区 + 原生高刷"，是最贴合均衡之选的一档。</li>`;}
if(f6&&f8&&f6.maxZ&&f8.maxZ){
  g+=`<li><b>6000-8000元档</b>：最高分区达 ${f6.maxZ}，进入中高端区间。
     该档机型开始出现玲珑控色区等画质技术。</li>`;
}
document.getElementById('rg').innerHTML=g||'<li>数据不足</li>';
let w='';
if(f8){w+=`<li><b>8000元以上边际收益递减</b>：共 ${f8.n} 款${f8.avgB?`，平均亮度约 ${f8.avgB} nit`:''}。
  相比中高档提升主要在分区数与光控细节，主观画质改善需结合实机判断，非必选。</li>`;}
if(f12){w+=`<li><b>12000元以上需明确需求</b>：共 ${f12.n} 款${f12.min?`，价格 ${f12.min}-${f12.max}元`:''}。
  若无专业调色、游戏高刷等明确需求，旗舰档性价比通常不高。</li>`;}
w+=`<li><b>色域不可横向比数值</b>：sRGB 100% 与 DCI-P3 98% 是不同标准，
  前者甚至在视频中用于入门机（成本低），跨标准比大小会得出错误结论。</li>`;
w+=`<li><b>高刷有代价</b>：视频多次标注"144Hz限1080P输入"、"300Hz为2K模式"，
  追求高刷数值需牺牲分辨率，实用价值有限。</li>`;
document.getElementById('rw').innerHTML=w;

// ==================== 六、明细表 ====================
function renderTable(){
  const list=curTier?D.rows.filter(r=>r.tier===curTier):D.rows;
  const cols=['档位','品牌','型号','价格','屏幕','背光分区','玲珑控色区','分区类型','亮度(nit)',
    '原生刷新','倍频','色域','内存','存储','处理器','HDMI2.1','HDMI2.0','发声单元','特殊技术','来源'];
  let h='<thead><tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>';
  list.forEach(r=>{
    const cg = r.color_err? `<span class="tag warn">待确认</span>`
      : (r.color_val===null?F(null):`${r.color_val}<span class="tag">${r.color_std}</span>`);
    const zone = r.zones===null?F(null)
      : r.zones+(r.zones_exact===false?`<span class="tag warn">档次</span>`:'');
    const cells=[
      `<span class="tag">${r.tier}</span>`,
      r.brand, r.model+(r.verified?'<span class="tag ok">核对</span>':''),
      r.price===null?F(null):r.price,
      r.screen||F(null), zone,
      r.color_zone?`<span class="tag hl">${r.color_zone}</span>`:F(null),
      r.zones_type||'-',
      r.bright===null?F(null):(r.bright_is_range?`${r.bright_min}-${r.bright}`:r.bright),
      r.refresh===null?F(null):r.refresh,
      r.refresh_boost?`<span class="tag warn">${r.refresh_boost}</span>`:'-',
      cg, F(r.mem), F(r.storage), r.cpu||F(null),
      F(r.hdmi21), F(r.hdmi20), F(r.speaker),
      (r.specials||[]).map(s=>s.name).join('、')||'-',
      `@${Math.round(r.ts)}s`
    ];
    h+='<tr>'+cells.map((v,i)=>{
      const isN=[3,5,6,8,9,11,12,14,15,16].includes(i);
      const miss=(v==='<span class="miss">未提取</span>');
      return `<td class="${isN?'n':''} ${miss?'miss':''}">${v}</td>`;
    }).join('')+'</tr>';
  });
  document.getElementById('c5').innerHTML=h+'</tbody>';
}
renderTable();

window.addEventListener('resize',()=>{c1.resize();c2.resize();});
</script></body></html>
"""


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
    with open(os.path.join(out_dir, "tv_models.json"), encoding="utf-8") as f:
        models = json.load(f)

    rows = build_payload(models)
    tiers = [t[2] for t in TIERS if any(r["tier"] == t[2] for r in rows)]
    tier_desc = {t[2]: t[3] for t in TIERS}

    payload = {
        "rows": rows, "tiers": tiers, "tierDesc": tier_desc,
    }
    print(f"载入 {len(rows)} 台机型，{len(tiers)} 个档位", flush=True)

    # ---- ECharts 内嵌 ----
    # 本机实测 cdn.jsdelivr.net 不可达（curl 返回 000），若引用 CDN 则图表区空白。
    # 改为把 echarts.min.js 直接内嵌进 HTML，生成零外部依赖的单文件：
    # 双击即可打开，不需要本地服务器，也不依赖网络。
    lib_path = os.path.join(out_dir, "echarts.min.js")
    if os.path.exists(lib_path):
        with open(lib_path, encoding="utf-8") as f:
            echarts_js = f.read()
        # 去掉可能存在的 sourcemap 注释，避免换行解析问题
        echarts_js = echarts_js.split("//# sourceMappingURL=")[0]
        script_tag = "<script>%s</script>" % echarts_js
        print(f"已内嵌 ECharts: {len(echarts_js)/1024:.0f} KB", flush=True)
    else:
        script_tag = ('<script src="https://unpkg.com/echarts@5.4.3/dist/'
                      'echarts.min.js"></script>')
        print("警告：未找到 echarts.min.js，回退为 unpkg CDN 引用", flush=True)

    html = (HTML_TMPL
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
            .replace("__N__", str(len(rows)))
            .replace("<!--__ECHARTS_INLINE__-->", script_tag))

    out_path = os.path.join(out_dir, "tv_dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"输出: {out_path}  ({os.path.getsize(out_path)/1024:.1f} KB)", flush=True)
    print("该文件为完全自包含单文件，可直接双击在浏览器打开", flush=True)


if __name__ == "__main__":
    main()
