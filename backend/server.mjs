// 本地分析服务：POST /analyze 接收 base64 文件，返回分析结果 JSON
// 零依赖（Node 原生 http + 内置 TextDecoder + 项目内 xlsx）
import http from 'http';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import { parseFile, fmtHMS, fmtClock } from './analyzer/parse.mjs';
import { detectNodes, calcParams } from './analyzer/efficiency.mjs';

const PORT = 3000;

function buildNodeList(d, nd){
  const sec = i => (d.dt[i]-d.dt[0])/1000;
  const mk = (f, idx, name) => ({
    f, idx, name,
    sec: idx>=0 ? Math.round(sec(idx)*10)/10 : null,
    time: idx>=0 ? fmtHMS(d.dt[idx]) : null,
    power: idx>=0 ? Math.round(d.pw[idx]*10)/10 : null,
    water: idx>=0 ? Math.round(d.W[idx]*1000)/1000 : null,
    elec: idx>=0 ? Math.round(d.el[idx]*10000)/10000 : null,
  });
  const list=[
    mk('n0', nd.n0, '运行开始'),
    mk('n1', nd.n1, '主洗进水开始（主洗开始）')
  ];
  if(nd.heatLo>=0) list.push(mk('heatLo', nd.heatLo, '加热开始'));
  if(nd.heatHi>=0) list.push(mk('heatHi', nd.heatHi, '加热结束（功率恢复）'));
  for(let k=0;k<nd.rinses.length;k++)
    list.push(mk('r'+k, nd.rinses[k], '第'+(k+1)+'次漂洗进水开始'+(k===0?'（=主洗结束）':'')));
  list.push(mk('spinOn',  nd.spinOn,  '最终脱水开始'));
  list.push(mk('spinHiE', nd.spinHiE, '最终脱水结束'));
  list.push(mk('opEnd',   nd.opEnd,   '运行结束（进入待机）'));
  return list;
}

// 结果降采样（图表用，截止 opEnd）
function downSample(d, nd){
  const stride = Math.max(1, Math.floor((nd.opEnd+1)/1400));
  const t=[], p=[], w=[], e=[];
  for(let i=0;i<=nd.opEnd;i+=stride){
    t.push(Math.round((d.dt[i]-d.dt[0])/1000));
    p.push(Math.round(d.pw[i]*10)/10);
    w.push(Math.round(d.W[i]*1000)/1000);
    e.push(Math.round(d.el[i]*10000)/10000);
  }
  return { t, p, w, e };
}

function toResult(d, nd, g){
  // 各次漂洗时长（秒）：本漂洗开始 → 下一漂洗开始 / 最终脱水开始
  g.rinseDur = nd.rinses.map((a, k) => {
    const b = (k+1 < nd.rinses.length) ? nd.rinses[k+1] : nd.spinOn;
    return Math.round((d.dt[b]-d.dt[a])/100)/10;
  });
  // 各次漂洗用电量（kWh）
  g.rinseElec = nd.rinses.map((a, k) => {
    const b = (k+1 < nd.rinses.length) ? nd.rinses[k+1] : nd.spinOn;
    return Math.round((d.el[b]-d.el[a])*10000)/10000;
  });
  return {
    n: d.n,
    fmt: d.fmt,
    usedEnc: d.usedEnc,
    filename: d.filename,
    nodes: buildNodeList(d, nd),
    startClock: fmtClock(d.dt[0]),
    endClock: fmtClock(d.dt[nd.opEnd]),
    params: g,
    series: downSample(d, nd),
    wname: d.wname,
    wType: d.wType,
    wWarn: d.wWarn,
  };
}

function handleAnalyze(body, res){
  try {
    const { filename, content } = body || {};
    if(!content) throw new Error('缺少文件内容');
    const buf = Buffer.from(content, 'base64');
    const d = parseFile(buf, filename || '');
    const nd = detectNodes(d);
    if(nd.opEnd < 0) throw new Error('未能识别运行结束节点，无法输出完整结果');
    const g = calcParams(d, nd);
    res.writeHead(200, { 'Content-Type':'application/json; charset=utf-8' });
    res.end(JSON.stringify(toResult(d, nd, g)));
  } catch(e) {
    res.writeHead(400, { 'Content-Type':'application/json; charset=utf-8' });
    res.end(JSON.stringify({ error: e.message }));
  }
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if(req.method === 'OPTIONS'){ res.writeHead(204); res.end(); return; }

  if(req.method === 'POST' && req.url === '/analyze'){
    let raw = '';
    req.on('data', c => { raw += c; });
    req.on('end', () => {
      try { handleAnalyze(JSON.parse(raw || '{}'), res); }
      catch(e){ res.writeHead(400, {'Content-Type':'application/json; charset=utf-8'}); res.end(JSON.stringify({error:'请求解析失败: '+e.message})); }
    });
    return;
  }

  // GET 静态文件（前端页面）
  if(req.method === 'GET'){
    const FRONTEND_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'frontend');
    let fp = (req.url === '/' ? '/index.html' : req.url).split('?')[0];
    try{
      const content = readFileSync(path.join(FRONTEND_DIR, fp));
      const ext = path.extname(fp).toLowerCase();
      const mime = ext==='.html' ? 'text/html; charset=utf-8' : ext==='.js' ? 'application/javascript; charset=utf-8' : ext==='.css' ? 'text/css; charset=utf-8' : 'application/octet-stream';
      res.writeHead(200, {'Content-Type': mime});
      res.end(content);
      return;
    }catch(e){ /* 落到 404 */ }
  }
  res.writeHead(404, { 'Content-Type':'text/plain; charset=utf-8' });
  res.end('Not Found');
});

server.listen(PORT, () => {
  console.log(`analysis server: http://localhost:${PORT}  (POST /analyze)`);
});
