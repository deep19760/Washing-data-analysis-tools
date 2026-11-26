# 本地分析服务：GET 静态前端 + POST /analyze（能效 + 程序检查）
# 纯标准库（http.server + json + base64），零第三方依赖
import os
import json
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from parser import parse_file, js_round
from efficiency import detect_nodes, calc_params
from program_check import parse_program_check, detect_program_check, calc_program_check_params

PORT = int(os.environ.get('PORT', 3000))
HOST = os.environ.get('HOST', '127.0.0.1')
MAX_BODY = 20 * 1024 * 1024

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.normpath(os.path.join(HERE, '..', 'frontend'))


def fmt_hms(dt):
    return f'{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}'


def fmt_clock(dt):
    return f'{dt.year}-{dt.month:02d}-{dt.day:02d} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}'


# ---------- 能效 ----------

def build_node_list(d, nd):
    def sec(i):
        return (d['dt'][i] - d['dt'][0]).total_seconds()

    def mk(f, idx, name):
        return {
            'f': f, 'idx': idx, 'name': name,
            'sec': js_round(sec(idx) * 10) / 10 if idx >= 0 else None,
            'time': fmt_hms(d['dt'][idx]) if idx >= 0 else None,
            'power': js_round(d['pw'][idx] * 10) / 10 if idx >= 0 else None,
            'water': js_round(d['W'][idx] * 1000) / 1000 if idx >= 0 else None,
            'elec': js_round(d['el'][idx] * 10000) / 10000 if idx >= 0 else None,
        }

    lst = [
        mk('n0', nd['n0'], '运行开始'),
        mk('n1', nd['n1'], '主洗进水开始（主洗开始）'),
    ]
    if nd['heatLo'] >= 0:
        lst.append(mk('heatLo', nd['heatLo'], '加热开始'))
    if nd['heatHi'] >= 0:
        lst.append(mk('heatHi', nd['heatHi'], '加热结束（功率恢复）'))
    for k in range(len(nd['rinses'])):
        lst.append(mk('r' + str(k), nd['rinses'][k], '第' + str(k + 1) + '次漂洗进水开始' + ('（=主洗结束）' if k == 0 else '')))
    lst.append(mk('spinOn', nd['spinOn'], '最终脱水开始'))
    lst.append(mk('spinHiE', nd['spinHiE'], '最终脱水结束'))
    lst.append(mk('opEnd', nd['opEnd'], '运行结束（进入待机）'))
    return lst


def down_sample(d, nd):
    stride = max(1, (nd['opEnd'] + 1) // 1400)
    t, p, w, e = [], [], [], []
    i = 0
    while i <= nd['opEnd']:
        t.append(js_round((d['dt'][i] - d['dt'][0]).total_seconds()))
        p.append(js_round(d['pw'][i] * 10) / 10)
        w.append(js_round(d['W'][i] * 1000) / 1000)
        e.append(js_round(d['el'][i] * 10000) / 10000)
        i += stride
    return {'t': t, 'p': p, 'w': w, 'e': e}


def to_result(d, nd, g):
    g['rinseDur'] = []
    g['rinseElec'] = []
    for k in range(len(nd['rinses'])):
        a = nd['rinses'][k]
        b = nd['rinses'][k + 1] if k + 1 < len(nd['rinses']) else nd['spinOn']
        g['rinseDur'].append(js_round((d['dt'][b] - d['dt'][a]).total_seconds() * 10) / 10)
        g['rinseElec'].append(js_round((d['el'][b] - d['el'][a]) * 10000) / 10000)
    return {
        'n': d['n'],
        'fmt': d['fmt'],
        'usedEnc': d.get('usedEnc'),
        'filename': d['filename'],
        'nodes': build_node_list(d, nd),
        'startClock': fmt_clock(d['dt'][0]),
        'endClock': fmt_clock(d['dt'][nd['opEnd']]),
        'params': g,
        'series': down_sample(d, nd),
        'wname': d['wname'],
        'wType': d['wType'],
        'wWarn': d['wWarn'],
    }


# ---------- 程序检查 ----------

def build_program_check_node_list(d, nd):
    def sec(i):
        return (d['dt'][i] - d['dt'][0]).total_seconds()

    def mk(f, idx, name):
        return {
            'f': f, 'idx': idx, 'name': name,
            'sec': js_round(sec(idx) * 10) / 10 if idx >= 0 else None,
            'time': fmt_hms(d['dt'][idx]) if idx >= 0 else None,
            'power': js_round(d['power'][idx] * 10) / 10 if idx >= 0 else None,
            'pump': js_round(d['pump'][idx] * 1000) / 1000 if idx >= 0 else None,
            'rpm': js_round(d['rpm'][idx]) if idx >= 0 else None,
            'temp': js_round(d['temp']['arr'][idx] * 10) / 10 if idx >= 0 and d['temp']['arr'] else None,
        }

    lst = [mk('start', 0, '运行开始')]
    if nd['heatStart'] >= 0:
        lst.append(mk('heatStart', nd['heatStart'], '加热开始'))
    if nd['heatEnd'] >= 0:
        lst.append(mk('heatEnd', nd['heatEnd'], '加热结束'))
    lst.append(mk('mainEnd', nd['mainEnd'], '主洗涤结束（开始排水）'))
    lst.append(mk('spinStart', nd['spinStart'], '最终脱水开始'))
    lst.append(mk('opEnd', nd['opEnd'], '运行结束'))
    return lst


def down_sample_program_check(d, nd):
    stride = max(1, (nd['opEnd'] + 1) // 1400)
    t, power, pump, valve, rpm = [], [], [], [], []
    i = 0
    while i <= nd['opEnd']:
        t.append(js_round((d['dt'][i] - d['dt'][0]).total_seconds()))
        power.append(js_round(d['power'][i] * 10) / 10)
        pump.append(js_round(d['pump'][i] * 1000) / 1000)
        valve.append(js_round(d['valve'][i] * 1000) / 1000)
        rpm.append(js_round(d['rpm'][i]))
        i += stride
    return {'t': t, 'power': power, 'pump': pump, 'valve': valve, 'rpm': rpm}


def to_program_check_result(d, nd, g, filename):
    return {
        'n': d['n'],
        'filename': filename,
        'nodes': build_program_check_node_list(d, nd),
        'startClock': fmt_clock(d['dt'][0]),
        'endClock': fmt_clock(d['dt'][nd['opEnd']]),
        'params': g,
        'series': down_sample_program_check(d, nd),
        'tempCol': nd['tempCol'],
    }


# ---------- 分发 ----------

def handle_analyze(body):
    filename = body.get('filename')
    content = body.get('content')
    test_type = body.get('testType')
    if not content:
        raise ValueError('缺少文件内容')
    buf = base64.b64decode(content)

    if test_type == 'program-check':
        d = parse_program_check(buf)
        nd = detect_program_check(d)
        if nd['opEnd'] < 0:
            raise ValueError('未能识别运行结束节点，无法输出完整结果')
        return to_program_check_result(d, nd, calc_program_check_params(d, nd), filename or '')

    d = parse_file(buf, filename or '')
    nd = detect_nodes(d)
    if nd['opEnd'] < 0:
        raise ValueError('未能识别运行结束节点。该数据可能不是「能效」数据（缺少用水量/电量列），请确认测试类型——程序检查数据请选择「程序检查」')
    return to_result(d, nd, calc_params(d, nd))


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            path = '/index.html'
        fp = os.path.normpath(os.path.join(FRONTEND_DIR, path.lstrip('/')))
        # 仅允许 frontend 目录内的文件，防目录穿越
        if not fp.startswith(FRONTEND_DIR):
            self.send_error(403)
            return
        try:
            with open(fp, 'rb') as f:
                content = f.read()
        except OSError:
            self.send_error(404)
            return
        ext = os.path.splitext(fp)[1].lower()
        mime = {
            '.html': 'text/html; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
        }.get(ext, 'application/octet-stream')
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.path != '/analyze':
            self.send_error(404)
            return
        length = int(self.headers.get('Content-Length', 0))
        if length > MAX_BODY:
            self._send_json(413, {'error': '文件过大，上限 20MB'})
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode('utf-8') or '{}')
            result = handle_analyze(body)
            self._send_json(200, result)
        except Exception as e:
            self._send_json(400, {'error': str(e)})

    def log_message(self, fmt, *args):
        pass  # 静默日志


def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f'analysis server (Python): http://{HOST}:{PORT}  (POST /analyze)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
