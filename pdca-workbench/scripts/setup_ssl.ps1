# 生成本地 HTTPS 证书（需先安装 mkcert: choco install mkcert）
# 用法: .\scripts\setup_ssl.ps1

$certDir = Join-Path $PSScriptRoot "..\certs"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

mkcert -install
mkcert -cert-file "$certDir\cert.pem" -key-file "$certDir\key.pem" localhost 127.0.0.1 ::1

Write-Host "证书已生成: $certDir"
Write-Host "在 .env 中设置:"
Write-Host "  PDCA_SECURE_COOKIES=1"
Write-Host "Docker 使用 nginx-ssl.conf 并挂载 ./certs:/etc/nginx/certs:ro"
