# -*- coding: utf-8 -*-
"""
生成参数对比看板（单文件 HTML + 内嵌 ECharts）。

数据驱动：档位、核心指标、画像卡展示字段、口径说明全部来自 preset 配置，
JS 只负责按元数据渲染，不认识任何具体品类。

单文件内嵌 ECharts 是为了避免 CDN 不可达导致图表一片空白（见 troubleshooting 第 3 条）。

板块：
  一、档位 × 核心指标 热力图
  二、档位对比柱状图
  三、各档位画像卡
  四、完整参数明细表
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from lib import config as cfgmod

# 缺失值的默认文案（配置 render.missing_label 可覆盖）
DEFAULT_MISSING = "未提取"


def skill_dir():
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def tier_of(price, tiers):
    if price is None:
        return None
    for t in tiers:
        if t["lo"] <= price < t["hi"]:
            return t["name"]
    return None


def field_defs_of(cfg, names):
    """按名字取字段定义，缺失时用字段名本身做标签。"""
    by_name = {fd["name"]: fd for fd in cfg["fields"]}
    out = []
    for n in names:
        out.append(by_name.get(n, {"name": n, "label": n, "type": "text_short"}))
    return out


def build_payload(models, cfg):
    dash = cfg.get("dashboard", {})
    render = cfg.get("render", {})
    missing_label = render.get("missing_label", DEFAULT_MISSING)
    tiers = dash.get("tiers", [])
    price_field = dash.get("price_field", "价格")
    metrics = dash.get("metrics", [])
    # 画像卡展示的字段：优先用核对表的展示顺序
    card_fields = cfg.get("table", {}).get("field_order") or \
        [fd["name"] for fd in cfg["fields"]]

    rows = []
    for m in sorted(models, key=lambda x: x.get("first_seen", 0)):
        p = m.get("params", {})
        price = p.get(price_field, {}).get("value")

        # 遍历实际解析出的参数，而不是仅遍历 fields ——
        # 兜底字段（如 HDMI2.1数量、刷新率_倍频）不在 fields 里，但同样要展示
        values = {}
        for name, e in p.items():
            if not e or e.get("value") is None:
                values[name] = {"value": None, "unit": "", "display": missing_label}
                continue
            unit = e.get("unit", "")
            val = e["value"]
            display = f"{val}{unit}" if unit else str(val)
            if e.get("is_range") and e.get("value_min") is not None:
                display = f"{e['value_min']}-{val}{unit}"
            if e.get("ocr_error"):
                display = f"待确认 {display}"
            values[name] = {
                "value": val, "unit": unit, "display": display,
                "exact": e.get("exact"), "is_range": e.get("is_range"),
                "raw": e.get("raw", ""),
            }

        rows.append({
            "brand": m.get("brand") or "?",
            "model": m.get("model") or "?",
            "price": price,
            "tier": tier_of(price, tiers),
            "values": values,
            "specials": [s.get("name") for s in m.get("specials", [])],
            "notes": [n.get("note_text", "") for n in m.get("notes", [])],
            "ts": m.get("first_seen", 0),
            "verified": bool(m.get("verified")),
        })

    return {
        "meta": {
            "title": cfg.get("meta", {}).get("title", "参数对比看板"),
            "author": cfg.get("meta", {}).get("author", ""),
            "source_date": cfg.get("meta", {}).get("source_date", ""),
            "note": cfg.get("meta", {}).get("note", ""),
            "tiers": [t["name"] for t in tiers],
            "tierDesc": {t["name"]: t.get("desc", "") for t in tiers},
            "metrics": [{"key": m["field"], "label": m.get("label", m["field"])}
                        for m in metrics],
            "cardFields": [{"key": n,
                            "label": next((fd["label"] for fd in cfg["fields"]
                                           if fd["name"] == n), n)}
                           for n in card_fields],
            "priceField": price_field,
            "caveats": dash.get("caveats", []),
            # 缺失值文案与图表处理方式一并注入 JS，避免 JS 里再写字面量
            "missingLabel": missing_label,
            "missingInChart": render.get("missing_in_chart", "gap"),
        },
        "rows": rows,
    }


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
 *{margin:0;padding:0;box-sizing:border-box}
 body{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f5f6f8;
      color:#1f2329;padding:22px}
 h1{font-size:25px;margin-bottom:5px}
 .sub{color:#646a73;font-size:13px;margin-bottom:14px;line-height:1.8}
 .notice{background:#fff8e6;border-left:4px solid #ffab00;padding:11px 15px;
         border-radius:4px;font-size:13px;color:#5c4a00;line-height:1.9;margin-bottom:18px}
 .card{background:#fff;border-radius:8px;padding:18px;margin-bottom:18px;
       box-shadow:0 1px 3px rgba(0,0,0,.06)}
 .card h2{font-size:17px;margin-bottom:4px}
 .card .d{font-size:12.5px;color:#8f959e;margin-bottom:12px;line-height:1.7}
 .miss{color:#c9cdd4}
 .tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;
      background:#eef1f4;color:#4a5058;margin-left:5px}
 .tag.ok{background:#f0f9eb;color:#52c41a}
 .tag.warn{background:#fff7e6;color:#fa8c16}
 .chips{margin-top:8px}
 .chip{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;
       background:#e6f4ff;color:#0958d9;margin:2px 4px 0 0}
 .tierbar{margin-bottom:12px}
 .tb{display:inline-block;padding:5px 13px;margin:0 6px 6px 0;border-radius:15px;
     font-size:12.5px;background:#f2f3f5;color:#4a5058;cursor:pointer;user-select:none}
 .tb.on{background:#3370ff;color:#fff}
 .tier-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
 .tc{border:1px solid #e5e6eb;border-radius:7px;padding:12px;background:#fcfcfd}
 .tc h3{font-size:14px;margin-bottom:2px}
 .tc .tsub{font-size:11px;color:#8f959e;margin-bottom:8px}
 .tc table{width:100%;font-size:12px;border-collapse:collapse}
 .tc td{padding:3px 0;vertical-align:top}
 .tc td.k{color:#8f959e;width:38%}
 .tc td.v{font-variant-numeric:tabular-nums}
 .tblwrap{overflow:auto}
 table.all{border-collapse:collapse;font-size:12.5px;white-space:nowrap;width:100%}
 table.all th{background:#f7f8fa;padding:8px;text-align:left;font-weight:600;
   border-bottom:1px solid #e5e6eb;position:sticky;top:0;z-index:2}
 table.all td{padding:7px 8px;border-bottom:1px solid #f0f1f3}
 table.all tr:hover td{background:#fafbfc}
 .rng{color:#fa8c16;font-size:11px}
</style></head><body>
<h1>__TITLE__</h1>
<div class="sub">
数据源：__AUTHOR__（__DATE__）· 共 <b>__N__</b> 条<br>
__NOTE__
</div>
<div class="notice"><strong>口径说明：</strong>__CAVEATS__</div>

<div class="card"><h2>一、档位 × 核心指标</h2>
<div class="d">每格为该档位内的最优值；灰色「__MISSING__」表示画面未给出该字段，不做推测填充。</div>
<div id="c1" style="height:260px"></div></div>

<div class="card"><h2>二、各档位对比</h2>
<div class="d">不同指标口径不同，仅用于同一指标跨档位比较，不可横向混算。</div>
<div id="c2" style="height:330px"></div></div>

<div class="card"><h2>三、各档位画像</h2>
<div class="d">点档位可筛选。缺失字段显式标注，不填 0。</div>
<div class="tierbar" id="tierbar"></div>
<div id="c3"></div></div>

<div class="card"><h2>四、完整参数明细</h2>
<div class="d">全部 __N__ 条逐条列出。</div>
<div class="tblwrap"><table class="all" id="c5"></table></div></div>

<script>__ECHARTS__</script>
<script>
const D = __DATA__;
const M = D.meta;
const F = n => (n===null||n===undefined) ? '<span class="miss">'+M.missingLabel+'</span>' : n;
const val = (r,k) => (r.values[k] && r.values[k].value!==null) ? r.values[k].value : null;
const disp = (r,k) => (r.values[k] ? r.values[k].display : M.missingLabel);

// 一、热力图
const tiers = M.tiers, metrics = M.metrics;
const hm = [];
metrics.forEach((m,mi)=>{
  tiers.forEach((t,ti)=>{
    const it = D.rows.filter(r=>r.tier===t && val(r,m.key)!==null);
    hm.push([mi, ti, it.length ? Math.max(...it.map(r=>val(r,m.key))) : '-']);
  });
});
echarts.init(document.getElementById('c1')).setOption({
  tooltip:{formatter:p=>{
    const v=p.value[2];
    if(v==='-') return metrics[p.value[0]].label+'<br/>'+tiers[p.value[1]]
      +'<br/><b>该档未提取到该指标</b>';
    const k=metrics[p.value[0]].key;
    const hit=D.rows.filter(r=>r.tier===tiers[p.value[1]]&&val(r,k)===v);
    return metrics[p.value[0]].label+'<br/>'+tiers[p.value[1]]+'<br/>档内最优：<b>'+v+'</b>'
      +'<br/><span style="color:#999">机型：'+hit.map(r=>r.brand+' '+r.model).join('、')+'</span>';
  }},
  grid:{left:130,right:60,top:20,bottom:70},
  xAxis:{type:'category',data:tiers,axisLabel:{fontSize:12,interval:0,rotate:12},splitArea:{show:true}},
  yAxis:{type:'category',data:metrics.map(m=>m.label),splitArea:{show:true}},
  visualMap:{min:0,max:Math.max(...hm.filter(d=>d[2]!=='-').map(d=>d[2]),1),
    calculable:true,orient:'vertical',right:10,top:'center',
    inRange:{color:['#e8f4ff','#b3d9ff','#4096ff','#0050b3']}},
  series:[{type:'heatmap',data:hm,
    label:{show:true,formatter:p=>p.value[2]==='-'?M.missingLabel:p.value[2],fontSize:12},
    itemStyle:{borderColor:'#fff',borderWidth:2}}]
});

// 二、柱状图
echarts.init(document.getElementById('c2')).setOption({
  tooltip:{trigger:'axis'},
  legend:{top:0,data:metrics.map(m=>m.label)},
  grid:{left:70,right:30,top:45,bottom:70},
  xAxis:{type:'category',data:tiers,axisLabel:{fontSize:12,interval:0,rotate:12}},
  yAxis:{type:'value',name:'数值（口径不同，不可直接比较）'},
  series:metrics.map((m,i)=>({
    name:m.label,type:'bar',
    data:tiers.map(t=>{
      const it=D.rows.filter(r=>r.tier===t&&val(r,m.key)!==null);
      // 缺失值按配置处理：gap=留空（默认，铁律 M8），zero=补 0
      // 此前无条件填 0，会让"该档没数据"看起来像"该档真的是 0"
      return it.length?Math.max(...it.map(r=>val(r,m.key))):(M.missingInChart==='zero'?0:null);
    }),
    itemStyle:{color:['#4096ff','#52c41a','#fa8c16','#722ed1','#eb2f96'][i%5]},
    label:{show:true,position:'top',fontSize:11,
      formatter:p=>(p.value===null||p.value===undefined)?'':p.value}
  }))
});

// 三、画像卡
let curTier=null;
function renderTiers(){
  const list = curTier ? tiers.filter(t=>t===curTier) : tiers;
  document.getElementById('c3').innerHTML = list.map(t=>{
    const items = D.rows.filter(r=>r.tier===t);
    const desc = M.tierDesc[t]||'';
    const head = `<h3 style="font-size:15px;margin:4px 0 2px">${t}
      <span class="tag">${items.length} 款</span></h3>
      <div class="tsub" style="margin-bottom:10px">${desc}</div>`;
    if(!items.length) return `<div>${head}
      <div class="miss">该档位暂未提取到条目</div></div>`;
    const cards = items.slice(0,6).map(r=>{
      const chips = r.specials.length
        ? '<div class="chips">'+r.specials.map(n=>`<span class="chip">${n}</span>`).join('')+'</div>'
        : '';
      const rowsHtml = M.cardFields.map(f=>{
        const e = r.values[f.key];
        const shown = (e && e.value!==null) ? e.display : F(null);
        const extra = (e && e.is_range) ? '<span class="rng"> 区间</span>'
          : ((e && e.exact===false) ? '<span class="rng"> 档次</span>' : '');
        return `<tr><td class="k">${f.label}</td><td class="v">${shown}${extra}</td></tr>`;
      }).join('');
      return `<div class="tc">
        <h3>${r.brand} ${r.model}${r.verified?'<span class="tag ok">已核对</span>':''}</h3>
        <div class="tsub">来源 @${Math.round(r.ts)}s</div>
        <table>${rowsHtml}</table>${chips}</div>`;
    }).join('');
    const more = items.length>6
      ? `<div class="miss" style="margin-top:9px;font-size:12px">…另有 ${items.length-6} 款，见下方明细表</div>` : '';
    return `<div>${head}<div class="tier-grid">${cards}</div>${more}</div>`;
  }).join('');
}

// 四、明细表
function renderTable(){
  const cols = ['档位','品牌','型号'].concat(M.cardFields.map(f=>f.label));
  const list = curTier ? D.rows.filter(r=>r.tier===curTier) : D.rows;
  let h = '<thead><tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>';
  list.forEach(r=>{
    h += '<tr><td>'+(r.tier||'-')+'</td><td>'+r.brand+'</td><td>'+r.model+'</td>'
      + M.cardFields.map(f=>{
          const e=r.values[f.key];
          return '<td>'+((e && e.value!==null) ? e.display
            : '<span class="miss">'+M.missingLabel+'</span>')+'</td>';
        }).join('')
      + '</tr>';
  });
  document.getElementById('c5').innerHTML = h + '</tbody>';
}

const tb=document.getElementById('tierbar');
tb.innerHTML='<div class="tb on" data-t="">全部档位</div>'
  +tiers.map(t=>`<div class="tb" data-t="${t}">${t}</div>`).join('');
tb.querySelectorAll('.tb').forEach(el=>{
  el.onclick=()=>{
    tb.querySelectorAll('.tb').forEach(x=>x.classList.remove('on'));
    el.classList.add('on');
    curTier=el.dataset.t||null;
    renderTiers(); renderTable();
  };
});
renderTiers(); renderTable();
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="生成参数对比看板（单文件 HTML）")
    ap.add_argument("--preset", required=True, help="品类预设名")
    ap.add_argument("--input", required=True, help="models.json 路径")
    ap.add_argument("--output", required=True, help="输出 HTML 路径")
    args = ap.parse_args()

    cfg = cfgmod.load_config(args.preset)
    with open(args.input, encoding="utf-8") as f:
        models = json.load(f)

    payload = build_payload(models, cfg)
    meta = payload["meta"]

    # 内嵌 ECharts：CDN 不可达时图表会空白且无报错，故默认内嵌。
    # 置 render.inline_echarts=false 则改用 CDN（会打印醒目警告）
    render = cfg.get("render", {})
    inline = render.get("inline_echarts", True)
    if inline:
        echarts_path = os.path.join(skill_dir(), "assets", "echarts.min.js")
        if not os.path.exists(echarts_path):
            print(f"错误：找不到 {echarts_path}；"
                  f"可置 render.inline_echarts=false 改用 CDN", file=sys.stderr)
            sys.exit(1)
        with open(echarts_path, encoding="utf-8") as f:
            echarts_src = f.read()
        echarts_tag = f"<script>{echarts_src}</script>"
    else:
        cdn = render.get(
            "echarts_cdn_url",
            "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js")
        print("警告：inline_echarts=false，改用 CDN 加载 ECharts。"
              "CDN 不可达时图表会一片空白且不报错（见 troubleshooting 第 3 条）",
              flush=True)
        echarts_tag = f'<script src="{cdn}"></script>'

    missing_label = meta["missingLabel"]
    caveats = "".join(f"<br>{i+1}. {c}" for i, c in enumerate(meta["caveats"]))
    caveats += (f"<br>{len(meta['caveats'])+1}. 标注「{missing_label}」"
                f"表示画面未给出该字段，不做推测填充。")

    html = (HTML_TMPL
            .replace("__TITLE__", meta["title"])
            .replace("__AUTHOR__", meta["author"])
            .replace("__DATE__", meta["source_date"])
            .replace("__NOTE__", meta["note"])
            .replace("__CAVEATS__", caveats)
            .replace("__N__", str(len(payload["rows"])))
            .replace("__MISSING__", missing_label)
            .replace("<script>__ECHARTS__</script>", echarts_tag)
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False)))

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"输出: {args.output}", flush=True)
    print(f"条目数: {len(payload['rows'])}，档位数: {len(meta['tiers'])}", flush=True)
    print(f"核心指标: {[m['label'] for m in meta['metrics']]}", flush=True)
    tail = "内嵌 ECharts，无外部依赖" if inline else "CDN 加载 ECharts"
    print(f"体积: {len(html.encode('utf-8')) / 1024:.0f} KB（{tail}）", flush=True)


if __name__ == "__main__":
    main()
