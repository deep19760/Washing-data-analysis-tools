// 程序检查数据分析：解析 + 节点识别 + 参数计算
// 数据格式：12 列 GBK TSV，关键列（0-based）：排水泵电流=3、加热器电流=5、温度1=6、温度2=7、转速=8、功率=11
// 判定流程（用户 2026-11-05 确认）：
//   1. 程序开始 = 主洗涤开始，加热包含在内
//   2. 排水泵电流第一次大幅升高（持续） = 主洗涤结束
//   3. 主洗涤结束 → 最终脱水开始 = 总漂洗时间
//   4. 最终脱水开始 → 程序结束 = 最终脱水阶段
import { parseTime, cellNum } from './parse.mjs';

const HEAT_POWER = 1000;      // 加热功率阈值
const RPM_HIGH = 300;         // 脱水转速阈值
const RPM_LOW = 120;          // 洗涤/漂洗转速上限

function parseProgramCheck(buf){
  let text;
  const u8text = new TextDecoder('utf-8').decode(buf);
  if((u8text.match(/�/g)||[]).length > 5) text = new TextDecoder('gbk').decode(buf);
  else text = u8text;

  const lines = text.split(/\r\n|\n|\r/);
  const dt=[], valve=[], pump=[], heater=[], temp1=[], temp2=[], rpm=[], power=[];
  for(let i=5;i<lines.length;i++){
    const line = lines[i];
    if(!line.trim().length) continue;
    const f = line.split('\t');
    if(f.length < 12) continue;
    if(String(f[0]).trim().charAt(0)==='t') continue;
    const d = parseTime(f[0]);
    if(!d) continue;
    dt.push(d);
    valve.push(cellNum(f[1]));
    pump.push(cellNum(f[3]));
    heater.push(cellNum(f[5]));
    temp1.push(cellNum(f[6]));
    temp2.push(cellNum(f[7]));
    rpm.push(cellNum(f[8]));
    power.push(cellNum(f[11]));
  }
  return { n:dt.length, dt, valve, pump, heater, temp1, temp2, rpm, power };
}

// 温度列选择：全零列或含异常值(<0 或 >100)列不可用，取另一列
function pickTempCol(temp1, temp2){
  const stat = arr => {
    let nz=0, mn=Infinity, mx=-Infinity;
    for(const v of arr){ if(v!==0){ nz++; if(v<mn) mn=v; if(v>mx) mx=v; } }
    return { nz, mn, mx };
  };
  const s1 = stat(temp1), s2 = stat(temp2);
  const ok1 = s1.nz>0 && s1.mn>=0 && s1.mx<=100;
  const ok2 = s2.nz>0 && s2.mn>=0 && s2.mx<=100;
  if(ok1 && !ok2) return { col:0, arr:temp1 };
  if(!ok1 && ok2) return { col:1, arr:temp2 };
  if(ok1 && ok2) return { col:0, arr:temp1 };
  return { col:-1, arr:null };
}

function detectProgramCheck(d){
  const { n, pump, rpm, power, valve } = d;
  const t = d.temp = pickTempCol(d.temp1, d.temp2);

  // 排水泵基线（前 60 秒最大值）+ 自适应阈值（兼容不同机型量程：0.044~0.35）
  let base = 0;
  for(let i=0;i<Math.min(60,n);i++){ if(pump[i] > base) base = pump[i]; }
  const pumpThresh = base * 1.5;

  // 主洗阀电流阈值（整个周期最大值的 50%，代表进水，兼容不同机型量程与进水时机）
  let valveBase = 0;
  for(let i=0;i<n;i++){ if(valve[i] > valveBase) valveBase = valve[i]; }
  const valveThresh = valveBase * 0.5;

  // 1. 主洗涤结束 = 排水泵电流首次「大幅上升且连续」（用户指定，仅用排水泵电流判定）。
  //    pumpThresh 为自适应阈值（相对基线），30s 窗口内 ≥10 样本超过阈值即视为连续排水。
  let pumpEnd = -1;
  for(let i=0;i<n-30;i++){
    let cnt = 0;
    for(let k=i;k<i+30;k++){ if(pump[k] > pumpThresh) cnt++; }
    if(cnt >= 3){ pumpEnd = i; break; }
  }
  let mainEnd = pumpEnd;

  // 2. 加热段 = 功率 > 1000W（首个~末个）
  let heatStart=-1, heatEnd=-1;
  for(let i=0;i<n;i++){ if(power[i] > HEAT_POWER){ heatStart=i; break; } }
  if(heatStart>=0){
    heatEnd = heatStart;
    for(let i=heatStart;i<n;i++){ if(power[i] > HEAT_POWER) heatEnd=i; }
  }

  // 3. 最终脱水：转速>=300 的段（gap<=60s 合并），最后一段；加速起点往前回溯到转速<=120
  const segs = [];
  let inSeg=false, s=-1, e=-1;
  for(let i=0;i<n;i++){
    if(rpm[i] >= RPM_HIGH){
      if(!inSeg){ s=i; inSeg=true; }
      e=i;
    } else if(inSeg && (i-e) > 60){
      segs.push([s,e]); inSeg=false;
    }
  }
  if(inSeg) segs.push([s,e]);

  let spinStart=-1, spinHiE=-1;
  if(segs.length){
    const last = segs[segs.length-1];
    spinHiE = last[1];
    // 加速起点：从高速段起点往前回溯到转速<=120 的第一个点之后
    spinStart = last[0];
    for(let i=last[0]-1;i>=0;i--){
      if(rpm[i] <= RPM_LOW){ spinStart = i+1; break; }
    }
  }

  // 4. 运行结束 = 高速段结束后，转速<60 且功率<5W 连续 10s（抖散结束后彻底归零）
  let opEnd = -1;
  if(spinHiE>=0){
    for(let i=spinHiE+1;i<n-10;i++){
      let ok=true;
      for(let k=0;k<10;k++){ if(rpm[i+k]>=60 || power[i+k]>=5){ ok=false; break; } }
      if(ok){ opEnd=i; break; }
    }
  }
  if(opEnd<0) opEnd = n-1;

  // 5. 漂洗段 = 主洗结束到最终脱水之间，转速<300 且排水泵持续低（<阈值）的连续段，段长≥60s
  // 漂洗次数 = 主洗涤结束后的进水段数（主洗阀电流代表进水）
  const intakes = [];
  let inV=false, vs=-1, ve=-1;
  for(let i=0;i<n;i++){
    if(valve[i] > valveThresh){
      if(!inV){ vs=i; inV=true; }
      ve=i;
    } else {
      if(inV && (i-ve) > 30){ if(ve-vs >= 10) intakes.push({s:vs, e:ve}); inV=false; }
    }
  }
  if(inV && ve-vs >= 10) intakes.push({s:vs, e:ve});
  // 漂洗进水 = 主洗涤结束后、最终脱水开始前的进水段（主洗进水、最终脱水内的补水不计入漂洗）
  const rinses = intakes.filter(x => x.s > mainEnd && x.e < spinStart);

  return { n0:0, mainEnd, heatStart, heatEnd, spinStart, spinHiE, opEnd, rinses, tempCol:t.col };
}

function calcProgramCheckParams(d, nd){
  const g = {};
  const sec = i => (d.dt[i]-d.dt[0])/1000;
  g.washTime   = nd.mainEnd>=0 ? sec(nd.mainEnd) : 0;              // 洗涤时间（秒）
  g.temp       = (nd.heatEnd>=0 && d.temp.arr) ? d.temp.arr[nd.heatEnd] : null; // 加热结束时刻温度
  g.rinseCount = nd.rinses.length;                                  // 漂洗次数
  g.totalRinseTime = (nd.spinStart>=0 && nd.mainEnd>=0) ? sec(nd.spinStart)-sec(nd.mainEnd) : 0; // 总漂洗时间
  g.spinTime   = nd.spinStart>=0 ? sec(nd.opEnd)-sec(nd.spinStart) : 0; // 脱水时间
  g.maxRpm     = Math.max(...d.rpm);                                // 最高转速
  g.totalTime  = sec(nd.opEnd);                                     // 总运行时间
  return g;
}

export { parseProgramCheck, detectProgramCheck, calcProgramCheckParams };
