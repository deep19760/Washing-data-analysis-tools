# 能效数据解析：文本(GBK/UTF-8 TSV/CSV) → 结构化数据 d
# 从 backend/analyzer/parse.mjs 逐行转化，纯标准库、零第三方依赖
import re
import math
from datetime import datetime, timedelta

DEFAULT_COLS = {'time': 0, 'power': 28, 'water1': 20, 'water2': 23, 'elec': 29, 'heaterCur': -1}


def js_round(x):
    """复刻 JS Math.round（四舍五入，0.5 向上），区别于 Python round 的银行家舍入。"""
    return math.floor(x + 0.5)


def parse_time(s):
    # 兼容 2026/8/28  23:43:33.000000 与 2026-8-28 23:43:33
    s = re.sub(r'\s+', ' ', str(s).strip())
    m = re.search(r'(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})[ T](\d{1,2}):(\d{1,2}):(\d{2})(?:\.(\d+))?', s)
    if not m:
        return None
    ms = js_round(float('0.' + m.group(7)) * 1000) if m.group(7) else 0
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    int(m.group(4)), int(m.group(5)), int(m.group(6)), ms * 1000)


def cell_num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else 0.0
    except (ValueError, TypeError):
        return 0.0


def excel_serial_to_date(v):
    ms = js_round((v - 25569) * 86400 * 1000)
    return datetime(1970, 1, 1) + timedelta(milliseconds=ms)


def cell_to_date(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 1 <= v <= 2958465:
            return excel_serial_to_date(v)
        return None
    if isinstance(v, str):
        return parse_time(v)
    return None


def map_columns(header_fields):
    cols = dict(DEFAULT_COLS)
    found = {'power': False, 'water1': False, 'water2': False, 'elec': False, 'heaterCur': False}
    single_water = False
    for idx, raw in enumerate(header_fields):
        h = re.sub(r'\s+', '', str(raw if raw is not None else '')).lower()
        if re.search(r'用水量1|水量1|用水1|water1|water\(1\)', h):
            cols['water1'] = idx
            found['water1'] = True
        elif re.search(r'用水量2|水量2|用水2|water2|water\(2\)', h):
            cols['water2'] = idx
            found['water2'] = True
        elif re.search(r'加热器电流|heater', h):
            cols['heaterCur'] = idx
            found['heaterCur'] = True
        elif re.search(r'电量|kwh|kw\.h|energy|电能', h):
            cols['elec'] = idx
            found['elec'] = True
        elif re.search(r'功率|power', h):
            cols['power'] = idx
            found['power'] = True
        elif (not found['water1']) and re.search(r'^用水量|^水量|^water[\(\s（]', h):
            cols['water1'] = idx
            found['water1'] = True
            single_water = True
    if single_water and not found['water2']:
        cols['water2'] = -1
        found['water2'] = False
    return cols, found


def _non_empty(row):
    return row is not None and any(str(c if c is not None else '').strip() for c in row)


def parse_rows(rows, source):
    header_row = -1
    header_fields = []
    for i in range(len(rows)):
        r = rows[i]
        if _non_empty(r):
            header_row = i
            header_fields = r
            break
    cols, found = map_columns(header_fields)
    heater_idx = cols['heaterCur'] if cols['heaterCur'] >= 0 else 0
    need_max = max(cols['power'], cols['water1'], cols['elec'], heater_idx)

    dt, pw, w1, w2, el, hc = [], [], [], [], [], []
    first_data_line = -1
    for i in range(len(rows)):
        f = rows[i]
        if not f:
            continue
        d0 = cell_to_date(f[0]) if len(f) > 0 else None
        if d0 and len(f) > need_max:
            first_data_line = i
            for j in range(i, len(rows)):
                g = rows[j]
                if not _non_empty(g):
                    continue
                if isinstance(g[0], str) and g[0].strip()[:1] == 't':
                    continue
                dd = cell_to_date(g[0])
                if not dd:
                    continue
                dt.append(dd)
                pw.append(cell_num(g[cols['power']]))
                w1.append(cell_num(g[cols['water1']]))
                w2.append(0.0 if cols['water2'] < 0 else cell_num(g[cols['water2']]))
                el.append(cell_num(g[cols['elec']]))
                hc.append(cell_num(g[cols['heaterCur']]) if cols['heaterCur'] >= 0 else 0.0)
            if len(dt) > 5:
                avg_ms = (dt[-1] - dt[0]).total_seconds() * 1000 / (len(dt) - 1)
                if avg_ms < 750:
                    # 复刻 JS Math.floor(dt[k].getTime()/1000) 按绝对秒去重：
                    # 绝对秒整数 = floor(相对秒 + dt[0] 的毫秒小数)
                    ndt, npw, nw1, nw2, nel, nhc = [], [], [], [], [], []
                    prev_sec = None
                    frac = dt[0].microsecond / 1e6
                    for k in range(len(dt)):
                        s = math.floor((dt[k] - dt[0]).total_seconds() + frac)
                        if s == prev_sec:
                            continue
                        prev_sec = s
                        ndt.append(dt[k])
                        npw.append(pw[k])
                        nw1.append(w1[k])
                        nw2.append(w2[k])
                        nel.append(el[k])
                        nhc.append(hc[k])
                    dt, pw, w1, w2, el, hc = ndt, npw, nw1, nw2, nel, nhc
            break

    return {
        'n': len(dt), 'dt': dt, 'pw': pw, 'w1': w1, 'w2': w2, 'el': el, 'hc': hc,
        'cols': cols, 'found': found, 'firstDataLine': first_data_line,
        'headerRow': header_row,
        'headerFields': [str(h if h is not None else '') for h in header_fields],
        'source': source,
    }


def parse_text_rows(text):
    lines = re.split(r'\r\n|\n|\r', text)
    sample = next((l for l in lines if l.strip()), '')
    delim = '\t'
    if sample.count('\t') < 5 and sample.count(',') >= 5:
        delim = ','
    rows = [l.split(delim) for l in lines if l.strip()]
    return rows, delim


def parse_file(data, filename):
    u8 = data[:8]
    is_xls = len(u8) >= 4 and u8[0] == 0xD0 and u8[1] == 0xCF and u8[2] == 0x11 and u8[3] == 0xE0
    is_xlsx = len(u8) >= 4 and u8[0] == 0x50 and u8[1] == 0x4B and u8[2] == 0x03 and u8[3] == 0x04
    if is_xls or is_xlsx:
        raise RuntimeError('检测到真正的 Excel 文件（.xls/.xlsx），当前版本未安装 openpyxl/xlrd，无法解析。请改用文本格式（GBK/UTF-8 TSV/CSV）。')
    u8text = data.decode('utf-8', errors='replace')
    if u8text.count('�') > 5:
        text = data.decode('gbk', errors='replace')
        used_enc = 'GBK'
    else:
        text = u8text
        used_enc = 'UTF-8'
    rows, delim = parse_text_rows(text)
    parsed = parse_rows(rows, 'text')
    parsed['delim'] = delim
    parsed['usedEnc'] = used_enc
    parsed['fmt'] = 'text'
    parsed['filename'] = filename
    return parsed
