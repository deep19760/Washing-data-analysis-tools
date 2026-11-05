// 解析管线：Excel(.xls/.xlsx) / 文本(.tsv/.csv) → 结构化数据 d
// 从 app.html 抽取，XLSX 改为 Node require，其余逻辑原样保留
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const XLSX = require('../../lib/xlsx.full.min.js');

const DEFAULT_COLS = { time:0, power:28, water1:20, water2:23, elec:29, heaterCur:-1 };

function parseTime(s){
  // 兼容 2026/8/28  23:43:33.000000 与 2026-8-28 23:43:33
  const m = String(s).trim().replace(/\s+/g,' ').match(
    /(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})[ T](\d{1,2}):(\d{1,2}):(\d{2})(?:\.(\d+))?/);
  if(!m) return null;
  const ms = m[7] ? Math.round(Number('0.'+m[7])*1000) : 0;
  return new Date(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +m[6], ms);
}
const pnum = s => { const v = parseFloat(String(s).trim()); return isFinite(v)?v:0; };
const pad2 = n => String(n).padStart(2,'0');
function fmtClock(d){ return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate())+' '+pad2(d.getHours())+':'+pad2(d.getMinutes())+':'+pad2(d.getSeconds()); }
function fmtHMS(d){ return pad2(d.getHours())+':'+pad2(d.getMinutes())+':'+pad2(d.getSeconds()); }

function mapColumns(headerFields){
  const cols = { ...DEFAULT_COLS };
  const found = { power:false, water1:false, water2:false, elec:false, heaterCur:false };
  let singleWater = false;
  headerFields.forEach((raw, idx) => {
    const h = String(raw==null?'':raw).toLowerCase().replace(/\s+/g,'');
    if(/用水量1|水量1|用水1|water1|water\(1\)/.test(h))   { cols.water1 = idx; found.water1 = true; }
    else if(/用水量2|水量2|用水2|water2|water\(2\)/.test(h)){ cols.water2 = idx; found.water2 = true; }
    else if(/加热器电流|heater/.test(h))   { cols.heaterCur = idx; found.heaterCur = true; }
    else if(/电量|kwh|kw\.h|energy|电能/.test(h)){ cols.elec = idx; found.elec = true; }
    else if(/功率|power/.test(h))        { cols.power = idx; found.power = true; }
    else if(!found.water1 && /^用水量|^水量|^water[\(\s（]/.test(h)){ cols.water1 = idx; found.water1 = true; singleWater = true; }
  });
  if(singleWater && !found.water2){ cols.water2 = -1; found.water2 = false; }
  return { cols, found };
}

function excelSerialToDate(v){
  return new Date(Math.round((v - 25569) * 86400 * 1000) + new Date(Date.UTC(1970,0,1)).getTime());
}
function cellToDate(v){
  if(v instanceof Date && !isNaN(v.getTime())) return v;
  if(typeof v === 'number'){
    if(v >= 1 && v <= 2958465) return excelSerialToDate(v);
    return null;
  }
  if(typeof v === 'string') return parseTime(v);
  return null;
}
function cellNum(v){
  if(typeof v === 'number') return isFinite(v)?v:0;
  return pnum(v);
}

function parseRows(rows, source){
  let headerRow = -1, headerFields = [];
  for(let i=0;i<rows.length;i++){
    const r = rows[i];
    if(r && r.some(c=>String(c==null?'':c).trim().length)){ headerRow=i; headerFields=r; break; }
  }
  const { cols, found } = mapColumns(headerFields);
  const needMax = Math.max(cols.power, cols.water1, cols.elec, cols.heaterCur>=0?cols.heaterCur:0);

  const dt=[], pw=[], w1=[], w2=[], el=[], hc=[];
  let firstDataLine=-1;
  for(let i=0;i<rows.length;i++){
    const f = rows[i];
    if(!f) continue;
    const d0 = cellToDate(f[0]);
    if(d0 && f.length > needMax){
      firstDataLine = i;
      for(let j=i;j<rows.length;j++){
        const g = rows[j];
        if(!g || !g.some(c=>String(c==null?'':c).trim().length)) continue;
        if(typeof g[0]==='string' && g[0].trim().charAt(0)==='t') continue;
        const dd = cellToDate(g[0]);
        if(!dd) continue;
        dt.push(dd);
        pw.push(cellNum(g[cols.power]));
        w1.push(cellNum(g[cols.water1]));
        w2.push(cols.water2<0 ? 0 : cellNum(g[cols.water2]));
        el.push(cellNum(g[cols.elec]));
        hc.push(cols.heaterCur>=0 ? cellNum(g[cols.heaterCur]) : 0);
      }
      if(dt.length>5){
        const avgMs = (dt[dt.length-1].getTime()-dt[0].getTime())/(dt.length-1);
        if(avgMs<750){
          const ndt=[], npw=[], nw1=[], nw2=[], nel=[], nhc=[];
          let prevSec=NaN;
          for(let k=0;k<dt.length;k++){
            const s=Math.floor(dt[k].getTime()/1000);
            if(s===prevSec) continue;
            prevSec=s;
            ndt.push(dt[k]); npw.push(pw[k]); nw1.push(w1[k]); nw2.push(w2[k]); nel.push(el[k]); nhc.push(hc[k]);
          }
          dt.length=0; pw.length=0; w1.length=0; w2.length=0; el.length=0; hc.length=0;
          dt.push(...ndt); pw.push(...npw); w1.push(...nw1); w2.push(...nw2); el.push(...nel); hc.push(...nhc);
        }
      }
      break;
    }
  }
  return { n:dt.length, dt, pw, w1, w2, el, hc, cols, found, firstDataLine, headerRow,
           headerFields: headerFields.map(h=>String(h==null?'':h)), source };
}

function parseTextRows(text){
  const lines = text.split(/\r\n|\n|\r/);
  const sample = lines.find(l=>l.trim().length) || '';
  let delim = '\t';
  if((sample.match(/\t/g)||[]).length < 5 && (sample.match(/,/g)||[]).length >= 5) delim = ',';
  return { rows: lines.filter(l=>l.trim().length).map(l=>l.split(delim)), delim };
}

function parseExcelRows(buf){
  if(typeof XLSX === 'undefined'){
    throw new Error('Excel 解析库未加载（lib/xlsx.full.min.js 缺失）。请使用完整软件包，或将文件另存为 CSV 后上传。');
  }
  const wb = XLSX.read(buf, { type:'buffer', cellDates:true });
  if(!wb.SheetNames.length) throw new Error('工作簿中没有工作表。');
  let best=null, bestName='', bestCount=0;
  wb.SheetNames.forEach(name=>{
    const ws = wb.Sheets[name];
    const rows = XLSX.utils.sheet_to_json(ws, { header:1, raw:true, defval:'', blankrows:false });
    let cnt=0; for(const r of rows){ if(r.some(c=>String(c==null?'':c).trim().length)) cnt++; }
    if(cnt > bestCount){ bestCount=cnt; best=rows; bestName=name; }
  });
  return { rows:best, sheetName:bestName, allSheets:wb.SheetNames };
}

// 统一入口：Buffer + 文件名 → 解析结果 d（自动识别 Excel/文本、GBK/UTF-8）
function parseFile(buf, filename){
  const u8 = new Uint8Array(buf, 0, Math.min(8, buf.length));
  const isXls = u8.length>=4 && u8[0]===0xD0 && u8[1]===0xCF && u8[2]===0x11 && u8[3]===0xE0;
  const isXlsx = u8.length>=4 && u8[0]===0x50 && u8[1]===0x4B && u8[2]===0x03 && u8[3]===0x04;
  let parsed;
  if(isXls || isXlsx){
    const ex = parseExcelRows(buf);
    parsed = parseRows(ex.rows, 'excel');
    parsed.sheetName = ex.sheetName;
    parsed.allSheets = ex.allSheets;
    parsed.fmt = isXls ? 'xls' : 'xlsx';
  } else {
    const u8text = new TextDecoder('utf-8').decode(buf);
    let text, usedEnc;
    if((u8text.match(/�/g)||[]).length > 5){ text = new TextDecoder('gbk').decode(buf); usedEnc = 'GBK'; }
    else { text = u8text; usedEnc = 'UTF-8'; }
    const tr = parseTextRows(text);
    parsed = parseRows(tr.rows, 'text');
    parsed.delim = tr.delim;
    parsed.usedEnc = usedEnc;
    parsed.fmt = 'text';
  }
  parsed.filename = filename;
  return parsed;
}

export { DEFAULT_COLS, parseTime, pnum, pad2, fmtClock, fmtHMS, mapColumns, cellToDate, cellNum, parseRows, parseTextRows, parseExcelRows, parseFile };
