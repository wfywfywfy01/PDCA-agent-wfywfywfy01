#!/usr/bin/env node
/**
 * GitHub 推送隧道代理（本地 CONNECT 代理）
 *
 * 背景：内网/国内网络下 github.com 的 DNS 常被解析到一个**不可达**的 IP
 * （例如 20.205.243.166 超时，而 140.82.112.x~116.x、20.27.177.113 可达），
 * 表现为 git push 报 "Failed to connect to github.com port 443"。
 * hosts 文件通常没有管理员权限可改，本脚本用本地代理定向到可达 IP：
 *   git -> 127.0.0.1:8899（CONNECT github.com:443）-> 可达 IP:443
 * TLS 的 SNI 仍是 github.com，证书校验正常，无需关闭 sslVerify。
 *
 * 用法：
 *   node scripts/gh_tunnel_proxy.cjs                 # 自动探测可达 IP，监听 127.0.0.1:8899
 *   node scripts/gh_tunnel_proxy.cjs --port 9000
 *   node scripts/gh_tunnel_proxy.cjs --ip 140.82.113.3
 *
 * 另开一个终端：
 *   git -c http.proxy=http://127.0.0.1:8899 push origin <branch>
 *   # 若代理长期常开，可固化（不常开时不要固化，否则 git 会连不上）：
 *   # git config --global http.https://github.com/.proxy http://127.0.0.1:8899
 *
 * 注意：gh 命令走 api.github.com（通常可达），一般**不需要**代理。
 */
const http = require('http');
const net = require('net');

const CANDIDATES = [
  '140.82.112.3', '140.82.113.3', '140.82.113.4',
  '140.82.114.3', '140.82.116.3', '20.27.177.113',
];

function parseArgs(argv) {
  const args = { port: 8899, ip: '', host: 'github.com' };
  for (let i = 2; i < argv.length; i += 1) {
    const flag = argv[i];
    if (flag === '--port') args.port = Number(argv[++i] || 8899);
    else if (flag === '--ip') args.ip = String(argv[++i] || '');
    else if (flag === '--host') args.host = String(argv[++i] || 'github.com');
  }
  return args;
}

function probe(ip, port = 443, timeout = 5000) {
  return new Promise((resolve) => {
    const socket = net.connect({ host: ip, port });
    const done = (ok) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeout);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
  });
}

async function pickIp(explicit) {
  if (explicit) {
    const ok = await probe(explicit);
    console.log((ok ? '[ok]   ' : '[warn] ') + explicit + (ok ? ' 可达' : ' 不可达（仍将使用）'));
    return explicit;
  }
  for (const ip of CANDIDATES) {
    if (await probe(ip)) {
      console.log('[ok]   选中可达 IP ' + ip);
      return ip;
    }
    console.log('[skip] ' + ip + ' 不可达');
  }
  console.error('[fail] 候选 GitHub IP 全部不可达；请检查网络（或手动指定 --ip）');
  process.exit(1);
}

async function main() {
  const args = parseArgs(process.argv);
  const ip = await pickIp(args.ip);

  const server = http.createServer((req, res) => {
    res.writeHead(501, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('仅支持 CONNECT（HTTPS 隧道）\n');
  });

  server.on('connect', (req, clientSocket, head) => {
    const [host, portRaw] = String(req.url || '').split(':');
    const port = Number(portRaw || 443);
    const target = host === args.host ? ip : host;
    const upstream = net.connect(port, target, () => {
      clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head && head.length) upstream.write(head);
      upstream.pipe(clientSocket);
      clientSocket.pipe(upstream);
    });
    const fail = () => {
      try { clientSocket.end('HTTP/1.1 502 Bad Gateway\r\n\r\n'); } catch (_) { /* ignore */ }
      try { upstream.destroy(); } catch (_) { /* ignore */ }
    };
    upstream.on('error', fail);
    clientSocket.on('error', fail);
  });

  server.listen(args.port, '127.0.0.1', () => {
    console.log('');
    console.log('隧道代理已启动: 127.0.0.1:' + args.port + '  ->  ' + args.host + ' = ' + ip);
    console.log('在另一个终端执行：');
    console.log('  git -c http.proxy=http://127.0.0.1:' + args.port + ' push origin <branch>');
    console.log('  git -c http.proxy=http://127.0.0.1:' + args.port + ' ls-remote origin');
    console.log('停止：Ctrl+C');
  });
}

main();
