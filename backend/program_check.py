# 程序检查数据分析：解析 + 节点识别 + 参数计算
# 从 backend/analyzer/program-check.mjs 逐行转化，纯标准库、零第三方依赖
# 数据格式：12 列 GBK TSV，关键列（0-based）：主洗阀电流=1、排水泵电流=3、加热器电流=5、温度1=6、温度2=7、转速=8、功率=11
# 判定流程（用户 2026-11-05 确认）：
#   1. 程序开始 = 主洗涤开始，加热包含在内
#   2. 排水泵电流第一次大幅升高（持续） = 主洗涤结束
#   3. 主洗涤结束 → 最终脱水开始 = 总漂洗时间
#   4. 最终脱水开始 → 程序结束 = 最终脱水阶段
import re
from parser import parse_time, cell_num

HEAT_POWER = 1000      # 加热功率阈值
RPM_HIGH = 300         # 脱水转速阈值
RPM_LOW = 120          # 洗涤/漂洗转速上限


def parse_program_check(data):
    text = data.decode('utf-8', errors='replace')
    if text.count('�') > 5:
        text = data.decode('gbk', errors='replace')
    lines = re.split(r'\r\n|\n|\r', text)
    dt, valve, pump, heater, temp1, temp2, rpm, power = [], [], [], [], [], [], [], []
    for i in range(5, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        f = line.split('\t')
        if len(f) < 12:
            continue
        if str(f[0]).strip()[:1] == 't':
            continue
        dd = parse_time(f[0])
        if not dd:
            continue
        dt.append(dd)
        valve.append(cell_num(f[1]))
        pump.append(cell_num(f[3]))
        heater.append(cell_num(f[5]))
        temp1.append(cell_num(f[6]))
        temp2.append(cell_num(f[7]))
        rpm.append(cell_num(f[8]))
        power.append(cell_num(f[11]))
    return {'n': len(dt), 'dt': dt, 'valve': valve, 'pump': pump, 'heater': heater,
            'temp1': temp1, 'temp2': temp2, 'rpm': rpm, 'power': power}


def pick_temp_col(temp1, temp2):
    # 温度列选择：全零列或含异常值(<0 或 >100)列不可用，取另一列
    def stat(arr):
        nz = 0
        mn = float('inf')
        mx = float('-inf')
        for v in arr:
            if v != 0:
                nz += 1
                if v < mn:
                    mn = v
                if v > mx:
                    mx = v
        return {'nz': nz, 'mn': mn, 'mx': mx}

    s1 = stat(temp1)
    s2 = stat(temp2)
    ok1 = s1['nz'] > 0 and s1['mn'] >= 0 and s1['mx'] <= 100
    ok2 = s2['nz'] > 0 and s2['mn'] >= 0 and s2['mx'] <= 100
    if ok1 and not ok2:
        return {'col': 0, 'arr': temp1}
    if not ok1 and ok2:
        return {'col': 1, 'arr': temp2}
    if ok1 and ok2:
        return {'col': 0, 'arr': temp1}
    return {'col': -1, 'arr': None}


def detect_program_check(d):
    n = d['n']
    pump = d['pump']
    rpm = d['rpm']
    power = d['power']
    valve = d['valve']
    t = d['temp'] = pick_temp_col(d['temp1'], d['temp2'])

    # 排水泵基线（前 60 秒最大值）+ 自适应阈值（兼容不同机型量程：0.044~0.35）
    base = 0
    for i in range(min(60, n)):
        if pump[i] > base:
            base = pump[i]
    pump_thresh = base * 1.5

    # 主洗阀电流阈值（整个周期最大值的 50%，代表进水，兼容不同机型量程与进水时机）
    valve_base = 0
    for i in range(n):
        if valve[i] > valve_base:
            valve_base = valve[i]
    valve_thresh = valve_base * 0.5

    # 1. 主洗涤结束 = 排水泵电流首次「大幅上升且连续」（用户指定，仅用排水泵电流判定）。
    #    pumpThresh 为自适应阈值（相对基线），30s 窗口内 ≥3 样本超过阈值即视为连续排水。
    pump_end = -1
    for i in range(n - 30):
        cnt = 0
        for k in range(i, i + 30):
            if pump[k] > pump_thresh:
                cnt += 1
        if cnt >= 3:
            pump_end = i
            break
    main_end = pump_end

    # 2. 加热段 = 功率 > 1000W（首个~末个）
    heat_start = -1
    heat_end = -1
    for i in range(n):
        if power[i] > HEAT_POWER:
            heat_start = i
            break
    if heat_start >= 0:
        heat_end = heat_start
        for i in range(heat_start, n):
            if power[i] > HEAT_POWER:
                heat_end = i

    # 3. 最终脱水：转速>=300 的段（gap<=60s 合并），最后一段；加速起点往前回溯到转速<=120
    segs = []
    in_seg = False
    s = -1
    e = -1
    for i in range(n):
        if rpm[i] >= RPM_HIGH:
            if not in_seg:
                s = i
                in_seg = True
            e = i
        elif in_seg and (i - e) > 60:
            segs.append([s, e])
            in_seg = False
    if in_seg:
        segs.append([s, e])

    spin_start = -1
    spin_hi_e = -1
    if segs:
        last = segs[-1]
        spin_hi_e = last[1]
        spin_start = last[0]
        for i in range(last[0] - 1, -1, -1):
            if rpm[i] <= RPM_LOW:
                spin_start = i + 1
                break

    # 4. 运行结束 = 高速段结束后，转速<60 且功率<5W 连续 10s（抖散结束后彻底归零）
    op_end = -1
    if spin_hi_e >= 0:
        for i in range(spin_hi_e + 1, n - 10):
            ok = True
            for k in range(10):
                if rpm[i + k] >= 60 or power[i + k] >= 5:
                    ok = False
                    break
            if ok:
                op_end = i
                break
    if op_end < 0:
        op_end = n - 1

    # 5. 漂洗段：主洗结束到最终脱水之间的进水段（主洗阀电流代表进水）
    intakes = []
    in_v = False
    vs = -1
    ve = -1
    for i in range(n):
        if valve[i] > valve_thresh:
            if not in_v:
                vs = i
                in_v = True
            ve = i
        else:
            if in_v and (i - ve) > 30:
                if ve - vs >= 10:
                    intakes.append({'s': vs, 'e': ve})
                in_v = False
    if in_v and ve - vs >= 10:
        intakes.append({'s': vs, 'e': ve})
    # 漂洗进水 = 主洗涤结束后、最终脱水开始前的进水段（主洗进水、最终脱水内的补水不计入漂洗）
    rinses = [x for x in intakes if x['s'] > main_end and x['e'] < spin_start]

    return {'n0': 0, 'mainEnd': main_end, 'heatStart': heat_start, 'heatEnd': heat_end,
            'spinStart': spin_start, 'spinHiE': spin_hi_e, 'opEnd': op_end,
            'rinses': rinses, 'tempCol': t['col']}


def calc_program_check_params(d, nd):
    def sec(i):
        return (d['dt'][i] - d['dt'][0]).total_seconds()

    g = {}
    g['washTime'] = sec(nd['mainEnd']) if nd['mainEnd'] >= 0 else 0              # 洗涤时间（秒）
    g['temp'] = d['temp']['arr'][nd['heatEnd']] if (nd['heatEnd'] >= 0 and d['temp']['arr']) else None  # 加热结束时刻温度
    g['rinseCount'] = len(nd['rinses'])                                          # 漂洗次数
    g['totalRinseTime'] = (sec(nd['spinStart']) - sec(nd['mainEnd'])) if (nd['spinStart'] >= 0 and nd['mainEnd'] >= 0) else 0  # 总漂洗时间
    g['spinTime'] = (sec(nd['opEnd']) - sec(nd['spinStart'])) if nd['spinStart'] >= 0 else 0  # 脱水时间
    g['maxRpm'] = max(d['rpm'])                                                  # 最高转速
    g['totalTime'] = sec(nd['opEnd'])                                            # 总运行时间
    return g
