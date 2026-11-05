// 能效数据分析：节点识别 + 参数计算
// 从 app.html 原样抽取，纯函数、无 DOM 依赖
function detectNodes(d){
  const { n, pw, dt, hc } = d;

  function profile(arr){
    let pos=0, neg=0;
    const bursts=[];
    let inB=false, bs=0, last=0, bvol=0;
    for(let i=1;i<arr.length;i++){
      const dv=arr[i]-arr[i-1];
      if(dv>0.001) pos+=dv;
      if(dv<-0.001) neg-=dv;
      if(dv>0.01){
        if(!inB){ inB=true; bs=i; bvol=0; }
        bvol+=dv; last=i;
      } else if(inB && (i-last)>60){
        if(bvol>0.1) bursts.push({s:bs,e:last,v:bvol});
        inB=false;
      }
    }
    if(inB && bvol>0.1) bursts.push({s:bs,e:last,v:bvol});
    return {pos,neg,bursts};
  }
  const cand=[
    {key:'w1', arr:d.w1, name:'用水量1（列'+(d.cols.water1+1)+'）'}
  ];
  if(d.cols.water2>=0) cand.push({key:'w2', arr:d.w2, name:'用水量2（列'+(d.cols.water2+1)+'）'});
  cand.forEach(c=>{ c.pf=profile(c.arr); });
  let sel;
  const act=cand.filter(c=>c.pf.bursts.length>=1 && c.pf.pos>1);
  d.wWarn='';
  if(act.length===0){ sel=cand[0]; d.wWarn='两个用水量列均未检出有效进水脉冲，默认使用'+sel.name; }
  else if(act.length===1){ sel=act[0]; d.wWarn='已自动选择有完整周期变化的 '+sel.name+'（另一列无进水特征，已排除）'; }
  else {
    const A=act[0].pf.bursts, B=act[1].pf.bursts;
    let paired=0;
    A.forEach(a=>{ if(B.some(b=>Math.abs(b.s-a.s)<=120)) paired++; });
    if(Math.min(A.length,B.length)>=2 && paired/Math.min(A.length,B.length)>=0.5){
      sel={key:'sum', name:'双进水合计（用水量1+2）', arr:d.w1.map((v,i)=>v+d.w2[i])};
      sel.pf=profile(sel.arr);
      d.wWarn='检测到双进水（两表脉冲交错），已合并两表计量';
    } else {
      sel=act.sort((a,b)=>(b.pf.bursts.length-a.pf.bursts.length)||(b.pf.pos-a.pf.pos))[0];
      d.wWarn='已选择进水周期变化更完整的 '+sel.name+'（另一列仅开机孤立跳变或脉冲不成周期，按单进水排除）';
    }
  }
  d.W=sel.arr; d.wname=sel.name;
  d.wType = sel.pf.neg>0.5 ? 'level' : 'cumulative';
  const w=d.W;
  const sec = i => (dt[i]-dt[0])/1000;

  const dW = new Array(n).fill(0);
  for(let i=1;i<n;i++) dW[i] = w[i]-w[i-1];

  const n0 = 0;
  let n1 = -1;
  for(let i=1;i<n;i++){ if(dW[i]>0.001){ n1=i; break; } }

  const wBursts = (sel.pf.bursts||[]).filter(b=>b.v>=0.3);

  let heatLo=-1, heatHi=-1, heatCycle=false, heatSegs=[];
  if(n1>=0){
    for(let i=n1;i<n;i++){ if(pw[i]>1000){ heatLo=i; break; } }
    if(heatLo>=0){
      heatHi=heatLo;
      for(let i=heatLo;i<n;i++){ if(pw[i]>1000) heatHi=i; }
    } else if(wBursts.length){
      let bound = n;
      let gi=0, gv=-1;
      for(let k=0;k<wBursts.length-1;k++){ const g0=wBursts[k+1].s-wBursts[k].e; if(g0>gv){gv=g0;gi=k;} }
      if(gv>=1800 && gi+1<wBursts.length) bound = wBursts[gi+1].s;
      const hot=[];
      for(let i=n1;i+60<bound;i++){
        let c=0;
        for(let k=i;k<i+60 && k<bound;k++){ if(pw[k]>450) c++; }
        if(c>=18) hot.push([i,i+59]);
      }
      const m=[];
      for(const hw of hot){
        if(m.length && hw[0]-m[m.length-1][1]<=120) m[m.length-1][1]=hw[1];
        else m.push(hw.slice());
      }
      heatSegs = m.filter(hw=>hw[1]-hw[0]+1>=120);
      let lo=-1, hi=-1, on=0;
      for(let i=n1;i<bound;i++){ if(pw[i]>450){ if(lo<0) lo=i; hi=i; on++; } }
      if(heatSegs.length>=2 && lo>=0 && (hi-lo+1)>=600 && on>=300){
        let hcOk=true;
        if(d.cols.heaterCur>=0){
          let hcMx=0;
          for(let i=lo;i<=hi;i++){ if(hc[i]>hcMx) hcMx=hc[i]; }
          if(hcMx<1.0){
            hcOk=false;
            d.wWarn=(d.wWarn?d.wWarn+'；':'')+'加热器电流通道峰值仅 '+hcMx.toFixed(3)+' A（加热器未通电），高功率脉冲判为电机负载，不设加热段';
          }
        }
        if(hcOk){ heatLo=lo; heatHi=hi; heatCycle=true; }
      }
    }
  }
  let heatOn=0, heatSpan=0, heatMaxGap=0, lowCnt=0, curGap=0;
  if(heatHi>=0){
    if(heatCycle){
      heatSpan = heatHi-heatLo+1;
      heatOn = 0;
      for(let i=heatLo;i<=heatHi;i++){ if(pw[i]>450) heatOn++; }
      for(let k=0;k<heatSegs.length-1;k++){ const g=heatSegs[k+1][0]-heatSegs[k][1]-1; if(g>heatMaxGap) heatMaxGap=g; }
    } else {
      for(let k=heatLo;k<=heatHi;k++){
        if(pw[k]<=1000){ lowCnt++; curGap++; if(curGap>heatMaxGap) heatMaxGap=curGap; }
        else curGap=0;
      }
      heatSpan = heatHi-heatLo+1;
      heatOn = heatSpan-lowCnt;
    }
  }
  const fills=[];
  if(n1>=0){
    if(heatHi>=0){
      const after = wBursts.filter(b=>b.s>heatHi);
      let cut=0;
      if(after.length>1){
        let gi=0, gv=-1;
        for(let k=0;k<after.length-1;k++){ const g0=after[k+1].s-after[k].e; if(g0>gv){gv=g0;gi=k;} }
        if(gv>=1800){
          let prM=0; for(let k=0;k<=gi;k++) if(after[k].v>prM) prM=after[k].v;
          let poM=0; for(let k=gi+1;k<after.length;k++) if(after[k].v>poM) poM=after[k].v;
          if(prM < poM*0.25) cut=gi+1;
        }
      }
      for(let k=cut;k<after.length;k++) fills.push({s:after[k].s,e:after[k].e,v:after[k].v});
    } else {
      const all = wBursts.filter(b=>b.s>=n1);
      if(all.length>1){
        let gi=0, gv=-1;
        for(let k=0;k<all.length-1;k++){ const g0=all[k+1].s-all[k].e; if(g0>gv){gv=g0;gi=k;} }
        for(let k=gi+1;k<all.length;k++) fills.push({s:all[k].s,e:all[k].e,v:all[k].v});
      }
    }
  }
  if(fills.length>1){
    const merged=[];
    for(const b of fills){
      const p = merged[merged.length-1];
      if(p && (b.s-p.e)<=120 && Math.min(b.v,p.v) < 0.25*Math.max(b.v,p.v)){
        p.e=b.e; p.v+=b.v;
      } else merged.push({s:b.s,e:b.e,v:b.v});
    }
    fills.length=0;
    for(const b of merged) fills.push(b);
  }
  if(fills.length>1){
    for(let pass=0;pass<4;pass++){
      let mx=0; for(const b of fills) if(b.v>mx) mx=b.v;
      let cut=-1, cutV=1e9;
      for(let k=0;k<fills.length;k++) if(fills[k].v < mx*0.5 && fills[k].v<cutV){ cutV=fills[k].v; cut=k; }
      if(cut<0) break;
      fills.splice(cut,1);
    }
  }
  if(fills.length>2){
    for(let pass=0;pass<4;pass++){
      if(fills.length<=2) break;
      let mx=0; for(const b of fills) if(b.v>mx) mx=b.v;
      const durs=[];
      for(let k=0;k<fills.length-1;k++) durs.push(fills[k+1].s-fills[k].s);
      const sorted=durs.slice().sort((a,b)=>a-b);
      const med = sorted.length%2 ? sorted[(sorted.length-1)>>1]
                                  : (sorted[sorted.length/2-1]+sorted[sorted.length/2])/2;
      let cut=-1, cutR=0;
      for(let k=0;k<fills.length-1;k++){
        if(durs[k] > med*2 && fills[k].v < mx*0.6){
          const r=durs[k]/med;
          if(r>cutR){ cutR=r; cut=k; }
        }
      }
      if(cut<0) break;
      fills.splice(cut,1);
    }
  }
  const rinses=fills.map(f=>f.s-1);
  const r1 = fills.length ? fills[0].s-1 : -1;
  const r1end = fills.length ? fills[0].e : -1;
  const lastFillEnd = fills.length ? fills[fills.length-1].e : -1;

  let spinOn=-1;
  if(lastFillEnd>=0){
    let lastWInc=-1;
    for(let i=lastFillEnd;i<n;i++){ if(dW[i]>0.01) lastWInc=i; }
    const sFrom = lastWInc>=0 ? lastWInc : lastFillEnd;
    let firstP300=-1;
    for(let k=sFrom;k<n;k++){ if(pw[k]>300){ firstP300=k; break; } }
    let i=sFrom;
    while(i<n-45 && (firstP300<0 || i<firstP300)){
      if(pw[i]<=5){
        let qe=i; while(qe+1<n && pw[qe+1]<=5) qe++;
        const L=qe-i+1;
        if(L>=2){
          let m1=0; for(let k=qe+1;k<=Math.min(qe+12,n-1);k++) if(pw[k]>m1) m1=pw[k];
          let m2=0; for(let k=i+25;k<=Math.min(i+40,n-1);k++) if(pw[k]>m2) m2=pw[k];
          if(m1>=90 && m2>=90){ spinOn = i + (L>>1); break; }
        }
        i=qe+1;
      } else i++;
    }
    if(spinOn<0){
      let cap2=-1;
      for(let k=sFrom;k+4<n;k++){ let c=0; for(let m=0;m<5;m++) if(pw[k+m]>300) c++; if(c>=3){ cap2=k; break; } }
      const lim2 = cap2<0 ? n-45 : cap2;
      let j=sFrom;
      while(j<lim2){
        if(pw[j]<=5){
          let qe=j; while(qe+1<n && pw[qe+1]<=5) qe++;
          const L=qe-j+1;
          if(L>=5){
            let m1=0; for(let k=qe+1;k<=Math.min(qe+12,n-1);k++) if(pw[k]>m1) m1=pw[k];
            let m2=0; for(let k=j+25;k<=Math.min(j+40,n-1);k++) if(pw[k]>m2) m2=pw[k];
            if(m1>=90 && m2>=90){ spinOn = j + (L>>1); break; }
          }
          j=qe+1;
        } else j++;
      }
    }
    if(spinOn<0){
      for(let i=lastFillEnd;i<n-26;i++){
        if(pw[i]>=90 && pw[i+1]>=90 && pw[i+2]>=90){
          let cnt=0;
          for(let k=0;k<=25 && i+k<n;k++) if(pw[i+k]>=90) cnt++;
          if(cnt<20) continue;
          for(let k=i+25;k<=Math.min(i+300,n-1);k++){
            if(pw[k]>300){ spinOn=i; break; }
          }
        }
        if(spinOn>=0) break;
      }
    }
    if(spinOn<0){
      for(let i=lastFillEnd;i<n-25;i++){ if(pw[i]>80 && pw[i+25]>300){ spinOn=i; break; } }
    }
    if(spinOn<0){
      let i=lastFillEnd;
      while(i<n-8){
        if(pw[i]>20){
          let drop=-1;
          for(let k=i;k<i+180 && k+7<n;k++){
            let run=true;
            for(let m=0;m<8;m++){ if(pw[k+m]>10){ run=false; break; } }
            if(run){ drop=k; break; }
          }
          if(drop<0){ spinOn=i; break; }
          i=drop+1;
        } else i++;
      }
    }
    if(spinOn<0){
      const from = lastWInc>=0 ? lastWInc+1 : lastFillEnd+1;
      for(let i=from;i<n-60;i++){
        if(pw[i]>=30){
          let mx=0;
          for(let k=i+1;k<=i+60 && k<n;k++){ if(pw[k]>mx) mx=pw[k]; }
          if(mx>=60){ spinOn=i; break; }
        }
      }
    }
  }
  const segs=[];
  if(spinOn>=0){
    let i=spinOn;
    while(i<n){
      if(pw[i]>300){
        let s=i; while(i<n && pw[i]>300) i++;
        const e=i-1;
        if(segs.length && (s-segs[segs.length-1][1])<=120) segs[segs.length-1][1]=e;
        else segs.push([s,e]);
      } else i++;
    }
  }
  let spinHiE = segs.length ? segs[segs.length-1][1] : -1;
  if(spinHiE<0 && spinOn>=0){
    for(let th=60; spinHiE<0 && th>=20; th-=20){
      let i=spinOn, lastE=-1;
      while(i<n){
        if(pw[i]>=th){
          while(i<n && pw[i]>=th) i++;
          lastE=i-1;
        } else i++;
      }
      if(lastE>=0) spinHiE=lastE;
    }
  }
  const hiStart = -1;

  let opEnd=-1;
  if(spinHiE>=0){
    let ls=-1;
    for(let i=n-1;i>spinHiE;i--){ if(pw[i]>=12){ ls=i; break; } }
    let plat=-1;
    if(ls>=0){
      let run=0;
      for(let i=ls+1;i<n;i++){
        if(pw[i]>=3 && pw[i]<=12){ run++; if(run>=300){ plat=i; break; } }
        else run=0;
      }
    }
    if(plat>=0){
      for(let i=ls+1;i<n-20;i++){
        let ok=true;
        for(let k=0;k<20;k++){ if(pw[i+k]>=12){ ok=false; break; } }
        if(ok){ opEnd=i; break; }
      }
    }
    if(opEnd<0){
    for(let i=spinHiE+30;i<n-10;i++){
      let ok=true;
      for(let k=0;k<10;k++){ if(pw[i+k]>=5){ ok=false; break; } }
      if(!ok) continue;
      let p10=-1e9, p40=-1e9;
      for(let k=1;k<=10 && i-k>=0;k++) if(pw[i-k]>p10) p10=pw[i-k];
      for(let k=1;k<=40 && i-k>=0;k++) if(pw[i-k]>p40) p40=pw[i-k];
      if(p10<100 && p40>5){ opEnd=i; break; }
    }
    if(opEnd<0){
      let lastAct=-1;
      for(let i=n-1;i>spinHiE;i--){ if(pw[i]>=5){ lastAct=i; break; } }
      if(lastAct>=0){
        let s=lastAct;
        while(s>spinHiE && pw[s-1]>=5) s--;
        if(lastAct-s+1>30){
          for(let i=spinHiE+1;i<n-20;i++){
            let ok=true;
            for(let k=0;k<20;k++){ if(pw[i+k]>=10){ ok=false; break; } }
            if(ok){ opEnd=i; break; }
          }
        } else if(lastAct+1<n){ opEnd=lastAct+1; }
      }
    }
    }
  }
  let antiCrease=0;
  if(opEnd>=0){ for(let i=opEnd+10;i<n;i++){ if(pw[i]>7) antiCrease++; } }

  return { n0,n1,heatLo,heatHi,heatOn,heatSpan,heatMaxGap,lowCnt,heatCycle,heatSegLen:heatSegs.length,r1,r1end,rinses,fills,
           spinOn,hiStart,spinHiE,segs,opEnd,antiCrease,sec };
}

function calcParams(d, nd){
  const { dt, el } = d;
  const w = d.W;
  const g = {};
  const sec = nd.sec;
  const sumPos=(a,b)=>{ let s=0; for(let i=Math.max(a,1);i<b;i++){ const dv=w[i]-w[i-1]; if(dv>0) s+=dv; } return s; };
  g.totalSec   = sec(nd.opEnd);
  g.mainDur    = (dt[nd.r1]-dt[nd.n1])/1000;
  if(d.wType==='level'){
    g.mainWater  = sumPos(nd.n1, nd.r1);
    g.rinseW=[];
    for(let k=0;k<nd.fills.length;k++){
      const a=nd.fills[k].s, b=(k+1<nd.fills.length)?nd.fills[k+1].s:nd.spinOn;
      g.rinseW.push(sumPos(a,b));
    }
    g.totalWater = sumPos(0, nd.spinHiE+1);
  } else {
    g.mainWater  = w[nd.r1-1]-w[nd.n1-1];
    g.rinseW=[];
    for(let k=0;k<nd.fills.length;k++){
      const a=nd.fills[k].s, b=(k+1<nd.fills.length)?nd.fills[k+1].s:nd.spinOn;
      g.rinseW.push(w[b-1]-w[a-1]);
    }
    g.totalWater = w[nd.spinHiE];
  }
  g.wName=d.wname; g.wType=d.wType; g.wWarn=d.wWarn;
  g.water2End  = d.w2[nd.spinHiE];
  g.elecSpin   = el[nd.spinHiE];
  g.elecEnd    = el[nd.opEnd];
  g.heatMin    = nd.heatHi>=0 ? nd.heatOn/60 : null;
  g.preSec     = sec(nd.n1);
  g.d3         = (dt[nd.opEnd]-dt[nd.spinOn])/1000;
  g.segDur=[g.preSec, g.mainDur];
  for(let k=1;k<nd.rinses.length;k++)
    g.segDur.push((dt[nd.rinses[k]]-dt[nd.rinses[k-1]])/1000);
  if(nd.rinses.length) g.segDur.push((dt[nd.spinOn]-dt[nd.rinses[nd.rinses.length-1]])/1000);
  g.segDur.push(g.d3);
  g.eMain = el[nd.r1]-el[0];
  g.eRinseAll = el[nd.spinOn]-el[nd.r1];
  g.eSpin = el[nd.opEnd]-el[nd.spinOn];
  g.elecTotal = g.eMain + g.eRinseAll + g.eSpin;
  return g;
}

export { detectNodes, calcParams };
