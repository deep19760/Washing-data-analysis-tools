# 能效数据分析：节点识别 + 参数计算
# 从 backend/analyzer/efficiency.mjs 逐行转化，纯标准库、零第三方依赖
import math


def detect_nodes(d):
    n = d['n']
    pw = d['pw']
    dt = d['dt']
    hc = d['hc']

    def profile(arr):
        pos = 0.0
        neg = 0.0
        bursts = []
        in_b = False
        bs = 0
        last = 0
        bvol = 0.0
        for i in range(1, len(arr)):
            dv = arr[i] - arr[i - 1]
            if dv > 0.001:
                pos += dv
            if dv < -0.001:
                neg -= dv
            if dv > 0.01:
                if not in_b:
                    in_b = True
                    bs = i
                    bvol = 0.0
                bvol += dv
                last = i
            elif in_b and (i - last) > 60:
                if bvol > 0.1:
                    bursts.append({'s': bs, 'e': last, 'v': bvol})
                in_b = False
        if in_b and bvol > 0.1:
            bursts.append({'s': bs, 'e': last, 'v': bvol})
        return {'pos': pos, 'neg': neg, 'bursts': bursts}

    cand = [{'key': 'w1', 'arr': d['w1'], 'name': '用水量1（列' + str(d['cols']['water1'] + 1) + '）'}]
    if d['cols']['water2'] >= 0:
        cand.append({'key': 'w2', 'arr': d['w2'], 'name': '用水量2（列' + str(d['cols']['water2'] + 1) + '）'})
    for c in cand:
        c['pf'] = profile(c['arr'])

    sel = None
    act = [c for c in cand if len(c['pf']['bursts']) >= 1 and c['pf']['pos'] > 1]
    d['wWarn'] = ''
    if len(act) == 0:
        sel = cand[0]
        d['wWarn'] = '两个用水量列均未检出有效进水脉冲，默认使用' + sel['name']
    elif len(act) == 1:
        sel = act[0]
        d['wWarn'] = '已自动选择有完整周期变化的 ' + sel['name'] + '（另一列无进水特征，已排除）'
    else:
        A = act[0]['pf']['bursts']
        B = act[1]['pf']['bursts']
        paired = 0
        for a in A:
            if any(abs(b['s'] - a['s']) <= 120 for b in B):
                paired += 1
        if min(len(A), len(B)) >= 2 and paired / min(len(A), len(B)) >= 0.5:
            arr = [d['w1'][i] + d['w2'][i] for i in range(len(d['w1']))]
            sel = {'key': 'sum', 'name': '双进水合计（用水量1+2）', 'arr': arr}
            sel['pf'] = profile(sel['arr'])
            d['wWarn'] = '检测到双进水（两表脉冲交错），已合并两表计量'
        else:
            sel = sorted(act, key=lambda c: (len(c['pf']['bursts']), c['pf']['pos']), reverse=True)[0]
            d['wWarn'] = '已选择进水周期变化更完整的 ' + sel['name'] + '（另一列仅开机孤立跳变或脉冲不成周期，按单进水排除）'

    d['W'] = sel['arr']
    d['wname'] = sel['name']
    d['wType'] = 'level' if sel['pf']['neg'] > 0.5 else 'cumulative'
    w = d['W']

    def sec(i):
        return (dt[i] - dt[0]).total_seconds()

    dW = [0.0] * n
    for i in range(1, n):
        dW[i] = w[i] - w[i - 1]

    n0 = 0
    n1 = -1
    for i in range(1, n):
        if dW[i] > 0.001:
            n1 = i
            break

    wBursts = [b for b in (sel['pf']['bursts'] or []) if b['v'] >= 0.3]

    heatLo = -1
    heatHi = -1
    heatCycle = False
    heatSegs = []
    if n1 >= 0:
        for i in range(n1, n):
            if pw[i] > 1000:
                heatLo = i
                break
        if heatLo >= 0:
            heatHi = heatLo
            for i in range(heatLo, n):
                if pw[i] > 1000:
                    heatHi = i
        elif len(wBursts) > 0:
            bound = n
            gi = 0
            gv = -1
            for k in range(len(wBursts) - 1):
                g0 = wBursts[k + 1]['s'] - wBursts[k]['e']
                if g0 > gv:
                    gv = g0
                    gi = k
            if gv >= 1800 and gi + 1 < len(wBursts):
                bound = wBursts[gi + 1]['s']
            hot = []
            for i in range(n1, bound - 60):
                c = 0
                for k in range(i, min(i + 60, bound)):
                    if pw[k] > 450:
                        c += 1
                if c >= 18:
                    hot.append([i, i + 59])
            m = []
            for hw in hot:
                if m and hw[0] - m[-1][1] <= 120:
                    m[-1][1] = hw[1]
                else:
                    m.append(hw[:])
            heatSegs = [hw for hw in m if hw[1] - hw[0] + 1 >= 120]
            lo = -1
            hi = -1
            on = 0
            for i in range(n1, bound):
                if pw[i] > 450:
                    if lo < 0:
                        lo = i
                    hi = i
                    on += 1
            if len(heatSegs) >= 2 and lo >= 0 and (hi - lo + 1) >= 600 and on >= 300:
                hcOk = True
                if d['cols']['heaterCur'] >= 0:
                    hcMx = 0
                    for i in range(lo, hi + 1):
                        if hc[i] > hcMx:
                            hcMx = hc[i]
                    if hcMx < 1.0:
                        hcOk = False
                        d['wWarn'] = (d['wWarn'] + '；' if d['wWarn'] else '') + '加热器电流通道峰值仅 ' + format(hcMx, '.3f') + ' A（加热器未通电），高功率脉冲判为电机负载，不设加热段'
                if hcOk:
                    heatLo = lo
                    heatHi = hi
                    heatCycle = True

    heatOn = 0
    heatSpan = 0
    heatMaxGap = 0
    lowCnt = 0
    curGap = 0
    if heatHi >= 0:
        if heatCycle:
            heatSpan = heatHi - heatLo + 1
            heatOn = 0
            for i in range(heatLo, heatHi + 1):
                if pw[i] > 450:
                    heatOn += 1
            for k in range(len(heatSegs) - 1):
                g = heatSegs[k + 1][0] - heatSegs[k][1] - 1
                if g > heatMaxGap:
                    heatMaxGap = g
        else:
            for k in range(heatLo, heatHi + 1):
                if pw[k] <= 1000:
                    lowCnt += 1
                    curGap += 1
                    if curGap > heatMaxGap:
                        heatMaxGap = curGap
                else:
                    curGap = 0
            heatSpan = heatHi - heatLo + 1
            heatOn = heatSpan - lowCnt

    fills = []
    if n1 >= 0:
        if heatHi >= 0:
            after = [b for b in wBursts if b['s'] > heatHi]
            cut = 0
            if len(after) > 1:
                gi = 0
                gv = -1
                for k in range(len(after) - 1):
                    g0 = after[k + 1]['s'] - after[k]['e']
                    if g0 > gv:
                        gv = g0
                        gi = k
                if gv >= 1800:
                    prM = 0
                    for k in range(0, gi + 1):
                        if after[k]['v'] > prM:
                            prM = after[k]['v']
                    poM = 0
                    for k in range(gi + 1, len(after)):
                        if after[k]['v'] > poM:
                            poM = after[k]['v']
                    if prM < poM * 0.25:
                        cut = gi + 1
            for k in range(cut, len(after)):
                fills.append({'s': after[k]['s'], 'e': after[k]['e'], 'v': after[k]['v']})
        else:
            all_b = [b for b in wBursts if b['s'] >= n1]
            if len(all_b) > 1:
                gi = 0
                gv = -1
                for k in range(len(all_b) - 1):
                    g0 = all_b[k + 1]['s'] - all_b[k]['e']
                    if g0 > gv:
                        gv = g0
                        gi = k
                for k in range(gi + 1, len(all_b)):
                    fills.append({'s': all_b[k]['s'], 'e': all_b[k]['e'], 'v': all_b[k]['v']})

    if len(fills) > 1:
        merged = []
        for b in fills:
            if merged and (b['s'] - merged[-1]['e']) <= 120 and min(b['v'], merged[-1]['v']) < 0.25 * max(b['v'], merged[-1]['v']):
                merged[-1]['e'] = b['e']
                merged[-1]['v'] += b['v']
            else:
                merged.append({'s': b['s'], 'e': b['e'], 'v': b['v']})
        fills = merged

    if len(fills) > 1:
        for _ in range(4):
            mx = 0
            for b in fills:
                if b['v'] > mx:
                    mx = b['v']
            cut = -1
            cutV = 1e9
            for k in range(len(fills)):
                if fills[k]['v'] < mx * 0.5 and fills[k]['v'] < cutV:
                    cutV = fills[k]['v']
                    cut = k
            if cut < 0:
                break
            fills.pop(cut)

    if len(fills) > 2:
        for _ in range(4):
            if len(fills) <= 2:
                break
            mx = 0
            for b in fills:
                if b['v'] > mx:
                    mx = b['v']
            durs = [fills[k + 1]['s'] - fills[k]['s'] for k in range(len(fills) - 1)]
            sorted_durs = sorted(durs)
            L = len(sorted_durs)
            if L % 2:
                med = sorted_durs[L // 2]
            else:
                med = (sorted_durs[L // 2 - 1] + sorted_durs[L // 2]) / 2
            cut = -1
            cutR = 0
            for k in range(len(fills) - 1):
                if durs[k] > med * 2 and fills[k]['v'] < mx * 0.6:
                    r = durs[k] / med
                    if r > cutR:
                        cutR = r
                        cut = k
            if cut < 0:
                break
            fills.pop(cut)

    rinses = [f['s'] - 1 for f in fills]
    r1 = fills[0]['s'] - 1 if fills else -1
    r1end = fills[0]['e'] if fills else -1
    lastFillEnd = fills[-1]['e'] if fills else -1

    spinOn = -1
    if lastFillEnd >= 0:
        lastWInc = -1
        for i in range(lastFillEnd, n):
            if dW[i] > 0.01:
                lastWInc = i
        sFrom = lastWInc if lastWInc >= 0 else lastFillEnd
        firstP300 = -1
        for k in range(sFrom, n):
            if pw[k] > 300:
                firstP300 = k
                break
        i = sFrom
        while i < n - 45 and (firstP300 < 0 or i < firstP300):
            if pw[i] <= 5:
                qe = i
                while qe + 1 < n and pw[qe + 1] <= 5:
                    qe += 1
                L = qe - i + 1
                if L >= 2:
                    m1 = 0
                    for k in range(qe + 1, min(qe + 12, n - 1) + 1):
                        if pw[k] > m1:
                            m1 = pw[k]
                    m2 = 0
                    for k in range(i + 25, min(i + 40, n - 1) + 1):
                        if pw[k] > m2:
                            m2 = pw[k]
                    if m1 >= 90 and m2 >= 90:
                        spinOn = i + (L // 2)
                        break
                i = qe + 1
            else:
                i += 1
        if spinOn < 0:
            cap2 = -1
            for k in range(sFrom, n - 4):
                c = 0
                for m in range(5):
                    if pw[k + m] > 300:
                        c += 1
                if c >= 3:
                    cap2 = k
                    break
            lim2 = cap2 if cap2 >= 0 else n - 45
            j = sFrom
            while j < lim2:
                if pw[j] <= 5:
                    qe = j
                    while qe + 1 < n and pw[qe + 1] <= 5:
                        qe += 1
                    L = qe - j + 1
                    if L >= 5:
                        m1 = 0
                        for k in range(qe + 1, min(qe + 12, n - 1) + 1):
                            if pw[k] > m1:
                                m1 = pw[k]
                        m2 = 0
                        for k in range(j + 25, min(j + 40, n - 1) + 1):
                            if pw[k] > m2:
                                m2 = pw[k]
                        if m1 >= 90 and m2 >= 90:
                            spinOn = j + (L // 2)
                            break
                    j = qe + 1
                else:
                    j += 1
        if spinOn < 0:
            for i in range(lastFillEnd, n - 26):
                if pw[i] >= 90 and pw[i + 1] >= 90 and pw[i + 2] >= 90:
                    cnt = 0
                    for k in range(0, min(26, n - i)):
                        if pw[i + k] >= 90:
                            cnt += 1
                    if cnt < 20:
                        continue
                    for k in range(i + 25, min(i + 300, n - 1) + 1):
                        if pw[k] > 300:
                            spinOn = i
                            break
                if spinOn >= 0:
                    break
        if spinOn < 0:
            for i in range(lastFillEnd, n - 25):
                if pw[i] > 80 and pw[i + 25] > 300:
                    spinOn = i
                    break
        if spinOn < 0:
            i = lastFillEnd
            while i < n - 8:
                if pw[i] > 20:
                    drop = -1
                    for k in range(i, min(i + 180, n - 7)):
                        run = True
                        for m in range(8):
                            if pw[k + m] > 10:
                                run = False
                                break
                        if run:
                            drop = k
                            break
                    if drop < 0:
                        spinOn = i
                        break
                    i = drop + 1
                else:
                    i += 1
        if spinOn < 0:
            frm = lastWInc + 1 if lastWInc >= 0 else lastFillEnd + 1
            for i in range(frm, n - 60):
                if pw[i] >= 30:
                    mx = 0
                    for k in range(i + 1, min(i + 60, n - 1) + 1):
                        if pw[k] > mx:
                            mx = pw[k]
                    if mx >= 60:
                        spinOn = i
                        break

    segs = []
    if spinOn >= 0:
        i = spinOn
        while i < n:
            if pw[i] > 300:
                s = i
                while i < n and pw[i] > 300:
                    i += 1
                e = i - 1
                if segs and (s - segs[-1][1]) <= 120:
                    segs[-1][1] = e
                else:
                    segs.append([s, e])
            else:
                i += 1

    spinHiE = segs[-1][1] if segs else -1
    if spinHiE < 0 and spinOn >= 0:
        th = 60
        while spinHiE < 0 and th >= 20:
            i = spinOn
            lastE = -1
            while i < n:
                if pw[i] >= th:
                    while i < n and pw[i] >= th:
                        i += 1
                    lastE = i - 1
                else:
                    i += 1
            if lastE >= 0:
                spinHiE = lastE
            th -= 20

    hiStart = -1

    opEnd = -1
    if spinHiE >= 0:
        ls = -1
        for i in range(n - 1, spinHiE, -1):
            if pw[i] >= 12:
                ls = i
                break
        plat = -1
        if ls >= 0:
            run = 0
            for i in range(ls + 1, n):
                if 3 <= pw[i] <= 12:
                    run += 1
                    if run >= 300:
                        plat = i
                        break
                else:
                    run = 0
        if plat >= 0:
            for i in range(ls + 1, n - 20):
                ok = True
                for k in range(20):
                    if pw[i + k] >= 12:
                        ok = False
                        break
                if ok:
                    opEnd = i
                    break
        if opEnd < 0:
            for i in range(spinHiE + 30, n - 10):
                ok = True
                for k in range(10):
                    if pw[i + k] >= 5:
                        ok = False
                        break
                if not ok:
                    continue
                p10 = -1e9
                p40 = -1e9
                for k in range(1, 11):
                    if i - k >= 0 and pw[i - k] > p10:
                        p10 = pw[i - k]
                for k in range(1, 41):
                    if i - k >= 0 and pw[i - k] > p40:
                        p40 = pw[i - k]
                if p10 < 100 and p40 > 5:
                    opEnd = i
                    break
            if opEnd < 0:
                lastAct = -1
                for i in range(n - 1, spinHiE, -1):
                    if pw[i] >= 5:
                        lastAct = i
                        break
                if lastAct >= 0:
                    s = lastAct
                    while s > spinHiE and pw[s - 1] >= 5:
                        s -= 1
                    if lastAct - s + 1 > 30:
                        for i in range(spinHiE + 1, n - 20):
                            ok = True
                            for k in range(20):
                                if pw[i + k] >= 10:
                                    ok = False
                                    break
                            if ok:
                                opEnd = i
                                break
                    elif lastAct + 1 < n:
                        opEnd = lastAct + 1

    antiCrease = 0
    if opEnd >= 0:
        for i in range(opEnd + 10, n):
            if pw[i] > 7:
                antiCrease += 1

    return {
        'n0': n0, 'n1': n1, 'heatLo': heatLo, 'heatHi': heatHi,
        'heatOn': heatOn, 'heatSpan': heatSpan, 'heatMaxGap': heatMaxGap,
        'lowCnt': lowCnt, 'heatCycle': heatCycle, 'heatSegLen': len(heatSegs),
        'r1': r1, 'r1end': r1end, 'rinses': rinses, 'fills': fills,
        'spinOn': spinOn, 'hiStart': hiStart, 'spinHiE': spinHiE, 'segs': segs,
        'opEnd': opEnd, 'antiCrease': antiCrease, 'sec': sec,
    }


def calc_params(d, nd):
    dt = d['dt']
    el = d['el']
    w = d['W']
    sec = nd['sec']

    def sum_pos(a, b):
        s = 0.0
        for i in range(max(a, 1), b):
            dv = w[i] - w[i - 1]
            if dv > 0:
                s += dv
        return s

    g = {}
    g['totalSec'] = sec(nd['opEnd'])
    g['mainDur'] = (dt[nd['r1']] - dt[nd['n1']]).total_seconds()
    if d['wType'] == 'level':
        g['mainWater'] = sum_pos(nd['n1'], nd['r1'])
        g['rinseW'] = []
        for k in range(len(nd['fills'])):
            a = nd['fills'][k]['s']
            b = nd['fills'][k + 1]['s'] if k + 1 < len(nd['fills']) else nd['spinOn']
            g['rinseW'].append(sum_pos(a, b))
        g['totalWater'] = sum_pos(0, nd['spinHiE'] + 1)
    else:
        g['mainWater'] = w[nd['r1'] - 1] - w[nd['n1'] - 1]
        g['rinseW'] = []
        for k in range(len(nd['fills'])):
            a = nd['fills'][k]['s']
            b = nd['fills'][k + 1]['s'] if k + 1 < len(nd['fills']) else nd['spinOn']
            g['rinseW'].append(w[b - 1] - w[a - 1])
        g['totalWater'] = w[nd['spinHiE']]
    g['wName'] = d['wname']
    g['wType'] = d['wType']
    g['wWarn'] = d['wWarn']
    g['water2End'] = d['w2'][nd['spinHiE']]
    g['elecSpin'] = el[nd['spinHiE']]
    g['elecEnd'] = el[nd['opEnd']]
    g['heatMin'] = nd['heatOn'] / 60 if nd['heatHi'] >= 0 else None
    g['preSec'] = sec(nd['n1'])
    g['d3'] = (dt[nd['opEnd']] - dt[nd['spinOn']]).total_seconds()
    g['segDur'] = [g['preSec'], g['mainDur']]
    for k in range(1, len(nd['rinses'])):
        g['segDur'].append((dt[nd['rinses'][k]] - dt[nd['rinses'][k - 1]]).total_seconds())
    if len(nd['rinses']):
        g['segDur'].append((dt[nd['spinOn']] - dt[nd['rinses'][-1]]).total_seconds())
    g['segDur'].append(g['d3'])
    g['eMain'] = el[nd['r1']] - el[0]
    g['eRinseAll'] = el[nd['spinOn']] - el[nd['r1']]
    g['eSpin'] = el[nd['opEnd']] - el[nd['spinOn']]
    g['elecTotal'] = g['eMain'] + g['eRinseAll'] + g['eSpin']
    return g
